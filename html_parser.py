"""
HTML парсер с нуля — поддержка локальных файлов, URL и Data URL.
"""

import os
import sys
import shutil
import base64
import urllib.request


class HtmlParser:
    """
    Собственный HTML парсер.
    Работает через посимвольный разбор строки.
    """
    
    def __init__(self, html: str):
        self.html = html
        self.pos = 0
        self.length = len(html)
        self.elements = []
    
    def parse(self):
        """Проходит по HTML и извлекает теги и текст."""
        current_text = ""
        
        while self.pos < self.length:
            char = self.html[self.pos]
            
            if char == "<":
                # Сохраняем накопленный текст
                self._save_text(current_text)
                current_text = ""
                
                # Парсим тег
                tag_info = self._parse_tag()
                
                if tag_info:
                    tag_name = tag_info["name"].lower()
                    
                    # Тег <img>
                    if tag_name == "img":
                        src = self._get_attribute(tag_info["attributes"], "src")
                        alt = self._get_attribute(tag_info["attributes"], "alt")
                        
                        if src:
                            self.elements.append({
                                "type": "image",
                                "src": src,
                                "alt": alt,
                            })
                    
                    # Пропускаем script и style
                    elif tag_name in ("script", "style"):
                        self._skip_until_closing_tag(tag_name)
            else:
                current_text += char
                self.pos += 1
        
        self._save_text(current_text)
        return self.elements
    
    def _parse_tag(self):
        """Парсит HTML тег."""
        self.pos += 1  # пропускаем '<'
        
        if self.pos >= self.length:
            return None
        
        # Комментарий
        if self.html[self.pos:self.pos + 3] == "!--":
            self._skip_comment()
            return None
        
        # DOCTYPE и подобное
        if self.html[self.pos] == "!":
            self._skip_until(">")
            return None
        
        # Закрывающий тег
        is_closing = False
        if self.html[self.pos] == "/":
            is_closing = True
            self.pos += 1
        
        # Имя тега
        tag_name = ""
        while self.pos < self.length:
            char = self.html[self.pos]
            if char.isalnum():
                tag_name += char
                self.pos += 1
            else:
                break
        
        if not tag_name:
            self._skip_until(">")
            return None
        
        # Атрибуты
        attributes = ""
        while self.pos < self.length:
            char = self.html[self.pos]
            self.pos += 1
            if char == ">":
                break
            attributes += char
        
        return {
            "name": tag_name,
            "is_closing": is_closing,
            "attributes": attributes.strip(),
        }
    
    def _get_attribute(self, attrs_str: str, attr_name: str) -> str:
        """Извлекает значение атрибута."""
        if not attrs_str:
            return ""
        
        attr_lower = attr_name.lower()
        attrs_lower = attrs_str.lower()
        
        # Ищем атрибут
        pos = attrs_lower.find(attr_lower + "=")
        if pos == -1:
            return ""
        
        pos = attrs_str.find("=", pos) + 1
        
        # Пропускаем пробелы
        while pos < len(attrs_str) and attrs_str[pos] == " ":
            pos += 1
        
        if pos >= len(attrs_str):
            return ""
        
        # Определяем кавычки
        quote = attrs_str[pos]
        
        if quote in ('"', "'"):
            pos += 1
            value = ""
            while pos < len(attrs_str) and attrs_str[pos] != quote:
                value += attrs_str[pos]
                pos += 1
            return value
        else:
            value = ""
            while pos < len(attrs_str) and attrs_str[pos] not in (" ", ">", "\t", "\n"):
                value += attrs_str[pos]
                pos += 1
            return value
    
    def _skip_comment(self):
        """Пропускает <!-- ... -->"""
        end = self.html.find("-->", self.pos)
        self.pos = end + 3 if end != -1 else self.length
    
    def _skip_until(self, char: str):
        """Пропускает до указанного символа."""
        while self.pos < self.length:
            if self.html[self.pos] == char:
                self.pos += 1
                break
            self.pos += 1
    
    def _skip_until_closing_tag(self, tag_name: str):
        """Пропускает до </tag_name>"""
        closing = f"</{tag_name}>".lower()
        while self.pos < self.length:
            if self.html[self.pos:self.pos + len(closing)].lower() == closing:
                self.pos += len(closing)
                return
            self.pos += 1
    
    def _save_text(self, text: str):
        """Сохраняет текст."""
        cleaned = " ".join(text.split()).strip()
        if cleaned:
            self.elements.append({"type": "text", "content": cleaned})
            

def save_image(src: str, output_dir: str, counter: int, base_path: str) -> dict:
    """
    Сохраняет картинку из любого источника.
    
    Поддерживает:
    - Локальные файлы: images/photo.png
    - URL: https://example.com/photo.png
    - Data URL: data:image/png;base64,...
    
    Возвращает словарь с информацией или None при ошибке
    """
    
    # ===== ТИП 1: Data URL =====
    if src.startswith("data:"):
        return save_data_url(src, output_dir, counter)
    
    # ===== ТИП 2: URL (http/https) =====
    if src.startswith(("http://", "https://")):
        return download_url(src, output_dir, counter)
    
    # ===== ТИП 3: Локальный файл =====
    return copy_local_file(src, output_dir, counter, base_path)


def save_data_url(data_url: str, output_dir: str, counter: int) -> dict:
    """
    Декодирует и сохраняет картинку из Data URL.
    
    Формат: data:image/png;base64,iVBORw0KGgo...
    """
    try:
        # Разделяем заголовок и данные
        header, encoded_data = data_url.split(",", 1)
        
        # Определяем расширение по заголовку
        if "png" in header:
            ext = ".png"
        elif "jpeg" in header or "jpg" in header:
            ext = ".jpg"
        elif "gif" in header:
            ext = ".gif"
        elif "webp" in header:
            ext = ".webp"
        elif "svg" in header:
            ext = ".svg"
        else:
            ext = ".png"
        
        # Декодируем base64 в байты
        image_bytes = base64.b64decode(encoded_data)
        
        # Сохраняем
        image_name = f"image_{counter}{ext}"
        save_path = os.path.join(output_dir, image_name)
        
        with open(save_path, "wb") as f:
            f.write(image_bytes)
        
        print(f"  [DATA URL] Декодировано и сохранено: {image_name} ({len(image_bytes)} байт)")
        
        return {
            "image_name": image_name,
            "image_path": os.path.abspath(save_path),
            "source_type": "data_url",
        }
        
    except Exception as e:
        print(f"  [ОШИБКА] Не удалось декодировать data URL: {e}")
        return None


def download_url(url: str, output_dir: str, counter: int) -> dict:
    """
    Скачивает картинку по URL.
    """
    try:
        # Определяем имя файла из URL        
        path_part = url.split("?")[0]  # убираем параметры
        original_name = path_part.split("/")[-1]
        
        # Определяем расширение
        _, ext = os.path.splitext(original_name)
        if not ext or len(ext) > 5:
            ext = ".jpg"
        
        image_name = f"image_{counter}{ext}"
        save_path = os.path.join(output_dir, image_name)
        
        # Скачиваем
        print(f"  [СКАЧИВАНИЕ] {url[:60]}...")
        
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        request = urllib.request.Request(url, headers=headers)
        
        with urllib.request.urlopen(request, timeout=30) as response:
            image_bytes = response.read()
        
        with open(save_path, "wb") as f:
            f.write(image_bytes)
        
        print(f"  [OK] Скачано: {image_name} ({len(image_bytes)} байт)")
        
        return {
            "image_name": image_name,
            "image_path": os.path.abspath(save_path),
            "source_type": "url",
        }
        
    except Exception as e:
        print(f"  [ОШИБКА] Не удалось скачать {url[:50]}: {e}")
        return None


def copy_local_file(src: str, output_dir: str, counter: int, base_path: str) -> dict:
    """
    Копирует локальный файл картинки.
    """
    # Собираем полный путь
    source_path = os.path.join(base_path, src)
    source_path = os.path.normpath(source_path)
    
    if not os.path.exists(source_path):
        print(f"  [НЕ НАЙДЕН] {source_path}")
        return None
    
    # Определяем расширение
    _, ext = os.path.splitext(src)
    if not ext:
        ext = ".png"
    
    image_name = f"image_{counter}{ext}"
    save_path = os.path.join(output_dir, image_name)
    
    # Копируем
    shutil.copy2(source_path, save_path)
    print(f"  [OK] Скопировано: {src} -> {image_name}")
    
    return {
        "image_name": image_name,
        "image_path": os.path.abspath(save_path),
        "source_type": "local",
    }


def find_text_before(elements, index):
    """Ищет текст ПЕРЕД элементом."""
    for i in range(index - 1, -1, -1):
        if elements[i]["type"] == "text":
            return elements[i]["content"]
    return ""


def find_text_after(elements, index):
    """Ищет текст ПОСЛЕ элемента."""
    for i in range(index + 1, len(elements)):
        if elements[i]["type"] == "text":
            return elements[i]["content"]
    return ""


def parse_html_file(html_path, output_dir="output"):
    """Парсит HTML и извлекает картинки с текстом."""
    
    print(f"\n{'='*60}")
    print(f"  HTML ПАРСЕР")
    print(f"{'='*60}")
    print(f"\nФайл: {html_path}")
    
    if not os.path.exists(html_path):
        print("ОШИБКА: Файл не найден!")
        return []
    
    os.makedirs(output_dir, exist_ok=True)
    
    # Читаем файл
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    
    print(f"Размер: {len(html_content)} символов")
    print(f"\n--- Парсинг ---\n")
    
    # Парсим
    parser = HtmlParser(html_content)
    elements = parser.parse()
    
    # Статистика
    images = [e for e in elements if e["type"] == "image"]
    print(f"\nНайдено картинок: {len(images)}")
    
    if not images:
        print("Картинки не найдены!")
        return []
    
    # Классифицируем картинки
    local_count = sum(1 for e in images if not e["src"].startswith(("http", "data:")))
    url_count = sum(1 for e in images if e["src"].startswith(("http://", "https://")))
    data_count = sum(1 for e in images if e["src"].startswith("data:"))
    
    print(f"  - локальных файлов: {local_count}")
    print(f"  - URL (http/https): {url_count}")
    print(f"  - Data URL (base64): {data_count}")
    
    base_path = os.path.dirname(os.path.abspath(html_path))
    
    # Обрабатываем картинки
    print(f"\n--- Сохранение картинок ---\n")
    
    results = []
    counter = 0
    
    for i, elem in enumerate(elements):
        if elem["type"] != "image":
            continue
        
        counter += 1
        src = elem["src"]
        alt = elem["alt"]
        
        # Сохраняем картинку (любого типа)
        saved = save_image(src, output_dir, counter, base_path)
        
        if saved:
            text_before = find_text_before(elements, i)
            text_after = find_text_after(elements, i)
            
            results.append({
                "image_name": saved["image_name"],
                "image_path": saved["image_path"],
                "original_src": src[:100],  # обрезаем длинные data url
                "source_type": saved["source_type"],
                "alt": alt,
                "text_before": text_before,
                "text_after": text_after,
            })
    
    return results


def print_results(results):
    """Выводит результаты."""
    print(f"\n{'='*60}")
    print(f"  РЕЗУЛЬТАТ: {len(results)} картинок")
    print(f"{'='*60}\n")
    
    if not results:
        return
    
    for i, r in enumerate(results, 1):
        print(f"[{i}] 📷 {r['image_name']}  ({r['source_type']})")
        print(f"    Alt:         {r['alt'] or '(пусто)'}")
        print(f"    Текст ДО:    {r['text_before'][:60] or '(пусто)'}")
        print(f"    Текст ПОСЛЕ: {r['text_after'][:60] or '(пусто)'}")
        print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python html_parser.py <файл.html>")
        sys.exit(0)
    
    html_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "output"
    
    results = parse_html_file(html_path, output_dir)
    print_results(results)
    
    if results:
        print(f"📁 Картинки сохранены: {output_dir}/")


