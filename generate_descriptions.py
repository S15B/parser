import os
import sys
import json
import shutil
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
import argparse

import torch
from PIL import Image, UnidentifiedImageError
import imagehash
from transformers import BlipProcessor, BlipForConditionalGeneration
from tqdm import tqdm

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/pipeline.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

LOGO_URL_KEYWORDS = ['logo', 'icon', 'brand', 'favicon', 'logotype']
MIN_LOGO_SIZE_PX = 150       # изображения с шириной и высотой меньше этого считаем возможным логотипом
MIN_LOGO_FILE_SIZE_KB = 5    # если размер файла меньше 5 КБ — тоже подозрение на логотип
LOGO_DESCRIPTION = "[LOGO] Веб-элемент брендинга"
ERROR_DESCRIPTION = "[ERROR] Ошибка генерации"


def is_image_file(path: Path) -> bool:
    """Проверяет, является ли файл изображением (по попытке открыть через Pillow)."""
    if not path.is_file():
        return False
    try:
        with Image.open(path) as img:
            img.verify()
        return True
    except (UnidentifiedImageError, OSError, Exception):
        return False


def is_logo_by_url(url: str) -> bool:
    """Эвристика: проверяет URL на наличие ключевых слов логотипа."""
    if not url:
        return False
    url_lower = url.lower()
    return any(keyword in url_lower for keyword in LOGO_URL_KEYWORDS)


def is_logo_by_visual(image_path: Path) -> bool:
    """
    Эвристика по размеру и площади файла.
    Возвращает True, если изображение похоже на логотип/иконку.
    """
    try:
        file_size_kb = image_path.stat().st_size / 1024
        if file_size_kb < MIN_LOGO_FILE_SIZE_KB:
            return True

        with Image.open(image_path) as img:
            width, height = img.size
            if width < MIN_LOGO_SIZE_PX or height < MIN_LOGO_SIZE_PX:
                return True
    except Exception:
        return False
    return False


def compute_phash(image_path: Path) -> Optional[str]:
    """Вычисляет перцептивный хеш (pHash) изображения."""
    try:
        with Image.open(image_path) as img:
            # Преобразуем в RGB, если необходимо (pHash требует RGB)
            if img.mode != 'RGB':
                img = img.convert('RGB')
            hash_obj = imagehash.phash(img)
            return str(hash_obj)
    except Exception as e:
        logger.warning(f"Не удалось вычислить pHash для {image_path}: {e}")
        return None


def load_image_safe(image_path: Path) -> Optional[Image.Image]:
    """Безопасная загрузка изображения с обработкой ошибок."""
    try:
        img = Image.open(image_path).convert('RGB')
        return img
    except Exception as e:
        logger.warning(f"Не удалось загрузить изображение {image_path}: {e}")
        return None


def load_progress(progress_path: Path) -> Dict:
    """Загружает существующий файл прогресса или создаёт новый."""
    if progress_path.exists():
        try:
            with open(progress_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.warning("Файл прогресса повреждён, начинаем с чистого листа.")
    return {"model": "Salesforce/blip-image-captioning-large", "completed": {}}


def save_progress_atomic(progress_path: Path, data: Dict) -> None:
    """Атомарная запись файла прогресса (через временный файл)."""
    tmp_path = progress_path.with_suffix('.tmp')
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, progress_path)  # атомарная замена в POSIX/Windows
        logger.debug(f"Прогресс сохранён: {progress_path}")
    except Exception as e:
        logger.error(f"Не удалось сохранить прогресс: {e}")
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def backup_progress(progress_path: Path, backup_dir: Path) -> None:
    """Создаёт резервную копию файла прогресса с временной меткой."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"descriptions_index_{timestamp}.json"
    shutil.copy2(progress_path, backup_dir / backup_name)
    logger.info(f"Бэкап прогресса сохранён в {backup_name}")


def collect_images(data_dir: Path) -> List[Dict]:
    """
    Обходит data_dir/extracted_images/page_*/,
    загружает results.json и собирает список всех изображений с метаданными.
    Каждый элемент — словарь с ключами из results.json + image_path_abs.
    """
    images = []
    extracted_dir = data_dir / "extracted_images"
    if not extracted_dir.exists():
        logger.error(f"Директория {extracted_dir} не найдена.")
        return images

    for page_dir in sorted(extracted_dir.glob("page_*")):
        if not page_dir.is_dir():
            continue

        results_file = page_dir / "results.json"
        if not results_file.exists():
            logger.warning(f"Файл results.json отсутствует в {page_dir}, пропускаем.")
            continue

        try:
            with open(results_file, 'r', encoding='utf-8') as f:
                page_data = json.load(f)
                if not isinstance(page_data, list):
                    logger.warning(f"results.json в {page_dir} не является списком, пропускаем.")
                    continue
        except json.JSONDecodeError:
            logger.warning(f"Не удалось прочитать results.json в {page_dir}.")
            continue

        for item in page_data:
            image_name = item.get("image_name")
            if not image_name:
                logger.debug(f"Пропущена запись без image_name в {page_dir}")
                continue
            image_path_abs = page_dir / image_name
            if not image_path_abs.is_file():
                logger.debug(f"Файл изображения не найден: {image_path_abs}")
                continue
            if not is_image_file(image_path_abs):
                logger.debug(f"Файл не является изображением: {image_path_abs}")
                continue

            item["image_path_abs"] = image_path_abs
            images.append(item)

    logger.info(f"Найдено изображений: {len(images)}")
    return images


def generate_descriptions(
    images_meta: List[Dict],
    model: BlipForConditionalGeneration,
    processor: BlipProcessor,
    device: torch.device,
    batch_size: int,
    progress: Dict,
    progress_path: Path,
    backup_dir: Path,
    backup_interval: int = 50
) -> None:
    """
    Основной цикл: фильтрация, дедупликация, генерация описаний, сохранение.
    """
    completed = progress["completed"]

    # 1. Первый проход: фильтрация логотипов и вычисление хешей
    logger.info("Первый проход: анализ изображений...")
    non_logo_groups = {}
    logo_images = []

    for meta in tqdm(images_meta, desc="Анализ изображений"):
        img_path_abs = meta["image_path_abs"]
        rel_path = str(img_path_abs.relative_to(img_path_abs.parents[2]))  # от data/extracted_images/...
        if rel_path in completed:
            logger.debug(f"Уже обработано: {rel_path}")
            continue

        # Проверка на логотип
        original_src = meta.get("original_src", "")
        if is_logo_by_url(original_src) or is_logo_by_visual(img_path_abs):
            logo_images.append(rel_path)
            completed[rel_path] = {
                "phash": None,
                "is_logo": True,
                "description": LOGO_DESCRIPTION,
                "generated_at": datetime.now().isoformat()
            }
            continue

        # Вычисляем pHash
        phash = compute_phash(img_path_abs)
        if phash is None:
            completed[rel_path] = {
                "phash": None,
                "is_logo": False,
                "description": ERROR_DESCRIPTION,
                "generated_at": datetime.now().isoformat()
            }
            continue

        non_logo_groups.setdefault(phash, []).append(rel_path)

    save_progress_atomic(progress_path, progress)

    # 2. Определяем изображения для генерации (по одному представителю на группу)
    representative_paths = []
    phash_representative = {}  # phash -> выбранный rel_path представитель
    for phash, paths in non_logo_groups.items():
        rep = None
        for p in paths:
            if p not in completed:
                rep = p
                break
        if rep is None:
            continue
        phash_representative[phash] = rep
        representative_paths.append(rep)

    if not representative_paths:
        logger.info("Все изображения уже обработаны или не требуют генерации.")
        return

    logger.info(f"Необходимо сгенерировать описания для {len(representative_paths)} уникальных изображений.")

    # 3. Батчевая генерация
    # Подготавливаем полные пути представителей
    base_dir = progress_path.parent
    rep_abs_paths = [base_dir / rel for rel in representative_paths]

    model.eval()
    processed_in_batch = 0

    for i in tqdm(range(0, len(rep_abs_paths), batch_size), desc="Генерация описаний"):
        batch_paths = rep_abs_paths[i:i+batch_size]
        batch_imgs = []
        valid_indices = []
        for j, p in enumerate(batch_paths):
            img = load_image_safe(p)
            if img is not None:
                batch_imgs.append(img)
                valid_indices.append(j)
            else:
                # Ошибка загрузки — записываем ошибку для представителя и всей группы
                rel = str(p.relative_to(base_dir))
                completed[rel] = {
                    "phash": compute_phash(p) if p.exists() else None,
                    "is_logo": False,
                    "description": ERROR_DESCRIPTION,
                    "generated_at": datetime.now().isoformat()
                }
                # копируем ошибку всем дубликатам в группе
                phash_for_err = None
                for ph, rep_rel in phash_representative.items():
                    if rep_rel == rel:
                        phash_for_err = ph
                        break
                if phash_for_err and phash_for_err in non_logo_groups:
                    for dup_path in non_logo_groups[phash_for_err]:
                        if dup_path not in completed:
                            completed[dup_path] = {
                                "phash": phash_for_err,
                                "is_logo": False,
                                "description": ERROR_DESCRIPTION,
                                "generated_at": datetime.now().isoformat()
                            }

        if not batch_imgs:
            continue

        try:
            inputs = processor(batch_imgs, return_tensors="pt", padding=True).to(device, torch.float16 if device.type == 'cuda' else torch.float32)
            with torch.no_grad():
                generated_ids = model.generate(
                    **inputs,
                    max_new_tokens=200,
                    min_length=60,
                    num_beams=4,
                    no_repeat_ngram_size=3,
                    repetition_penalty=1.2,
                    do_sample=False,
                    length_penalty=2.0,
                    early_stopping=True
                )
            captions = processor.batch_decode(generated_ids, skip_special_tokens=True)
        except Exception as e:
            logger.error(f"Ошибка генерации для батча: {e}")
            captions = [ERROR_DESCRIPTION] * len(batch_imgs)

        for idx, caption in zip(valid_indices, captions):
            rep_abs_path = batch_paths[idx]
            rep_rel = str(rep_abs_path.relative_to(base_dir))
            # Найдём хеш этого представителя
            phash = None
            for ph, r in phash_representative.items():
                if r == rep_rel:
                    phash = ph
                    break
            timestamp = datetime.now().isoformat()

            completed[rep_rel] = {
                "phash": phash,
                "is_logo": False,
                "description": caption,
                "generated_at": timestamp
            }
            # Копируем описание всем дубликатам
            if phash and phash in non_logo_groups:
                for dup_path in non_logo_groups[phash]:
                    if dup_path not in completed:
                        completed[dup_path] = {
                            "phash": phash,
                            "is_logo": False,
                            "description": caption,
                            "generated_at": timestamp
                        }

        processed_in_batch += len(valid_indices)

        save_progress_atomic(progress_path, progress)

        # Периодические бэкапы
        if processed_in_batch % backup_interval == 0:
            backup_progress(progress_path, backup_dir)

    save_progress_atomic(progress_path, progress)
    backup_progress(progress_path, backup_dir)
    logger.info("Генерация описаний завершена.")


def main():
    parser = argparse.ArgumentParser(description="Генератор описаний изображений для индексации")
    parser.add_argument('--device', type=str, default='cuda', choices=['cuda', 'cpu'],
                        help='Устройство для инференса (cuda или cpu)')
    parser.add_argument('--batch-size', type=int, default=2,
                        help='Размер батча для генерации описаний')
    parser.add_argument('--data-dir', type=str, default='data',
                        help='Путь к корневой папке данных (содержит extracted_images)')
    parser.add_argument('--backup-interval', type=int, default=50,
                        help='Интервал (в обработанных изображениях) для создания бэкапов')
    parser.add_argument('--progress-file', type=str, default='descriptions_index.json',
                        help='Имя файла прогресса (будет сохранён в data/)')
    args = parser.parse_args()

    if args.device == 'cuda' and not torch.cuda.is_available():
        logger.warning("CUDA недоступна, переключаюсь на CPU.")
        device = torch.device('cpu')
    else:
        device = torch.device(args.device)

    logger.info(f"Устройство: {device}")
    logger.info(f"Размер батча: {args.batch_size}")

    data_dir = Path(args.data_dir).resolve()
    if not data_dir.exists():
        logger.error(f"Директория данных {data_dir} не существует.")
        sys.exit(1)

    progress_path = data_dir / args.progress_file
    backup_dir = data_dir / "backups"

    logger.info("Загрузка модели BLIP-large...")
    model_name = "Salesforce/blip-image-captioning-large"
    try:
        processor = BlipProcessor.from_pretrained("./blip-local")
    except OSError as e:
        logger.info(f"Загрузка не удалась: {e}")

    model = BlipForConditionalGeneration.from_pretrained(
        "./blip-local",
        torch_dtype=torch.float16 if device.type == 'cuda' else torch.float32
    ).to(device)
    logger.info("Модель загружена.")

    progress = load_progress(progress_path)

    images = collect_images(data_dir)
    if not images:
        logger.info("Нет изображений для обработки.")
        return

    generate_descriptions(
        images_meta=images,
        model=model,
        processor=processor,
        device=device,
        batch_size=args.batch_size,
        progress=progress,
        progress_path=progress_path,
        backup_dir=backup_dir,
        backup_interval=args.backup_interval
    )

if __name__ == "__main__":
    main()
