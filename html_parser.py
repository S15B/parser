"""
HTML парсер с нуля — финальная версия.
Поддержка локальных файлов, URL, Data URL.
С дедупликацией и поддержкой base_url.

Использование:
    python html_parser.py <файл.html> [папка_вывода] [base_url]

Примеры:
    python html_parser.py page.html
    python html_parser.py spbu.html output/
    python html_parser.py spbu.html output/ https://spbu.ru
"""

import os
import sys
import shutil
import base64
import urllib.request
import json
import re


def decode_html_entities(text: str) -> str:
    """
    Декодирует HTML-сущности в тексте.
    
    Примеры:
        &amp;  -> &
        &#39;  -> '
        &laquo; -> «
    """
    if not text:
        return text
    
    # Словарь основных HTML-сущностей
    entities = {
        "&amp;": "&",
        "&lt;": "<",
        "&gt;": ">",
        "&quot;": '"',
        "&apos;": "'",
        "&#39;": "'",
        "&#34;": '"',
        "&nbsp;": " ",
        "&laquo;": "«",
        "&raquo;": "»",
        "&mdash;": "—",
        "&ndash;": "–",
    }
    
    # Заменяем именованные сущности
    for entity, char in entities.items():
        text = text.replace(entity, char)
    
    # Заменяем числовые сущности типа &#123;
    def replace_numeric(match):
        try:
            return chr(int(match.group(1)))
        except:
            return match.group(0)
    
    text = re.sub(r'&#(\d+);', replace_numeric, text)
    
    return text


def normalize_image_url(src: str) -> str:
    """
    Нормализует URL картинки для проверки дубликатов.
    
    Проблема: на сайтах типа СПбГУ одна картинка генерируется
    в нескольких размерах:
        /styles/card_2x1_420/public/banner.jpg?itok=abc
        /styles/card_2x1_900/public/banner.jpg?itok=xyz
        /styles/card_2x1_1200/public/banner.jpg?itok=123
    
    Это одна и та же картинка! Нужно оставить только одну.
    
    Решение: убираем размеры и параметры, оставляем только имя файла.
    """
    if not src:
        return ""
    
    # Приводим к нижнему регистру и убираем кавычки
    src = src.strip("'\"").lower()
    
    # Убираем параметры после ?
    src = src.split("?")[0]
    
    # Убираем префикс размеров Drupal: /styles/card_2x1_1200/public/
    # Это специфика CMS Drupal, которую использует СПбГУ
    src = re.sub(r'/styles/[^/]+/public/', '/', src)
    
    # Оставляем только имя файла
    src = os.path.basename(src)
    
    return src


def read_html_file(file_path: str) -> str:
    """
    Читает HTML файл с автоопределением кодировки.
    
    Пробует несколько кодировок по очереди:
    - utf-8 (современный стандарт)
    - cp1251 (русская Windows)
    - cp1252 (западноевропейская Windows)
    - latin-1 (всегда работает, но может быть неправильным)
    """
    encodings = ["utf-8", "cp1251", "cp1252", "latin-1"]
    
    for encoding in encodings:
        try:
            with open(file_path, "r", encoding=encoding) as f:
                content = f.read()
            print(f"Кодировка: {encoding}")
            return content
        except UnicodeDecodeError:
            continue
    
    # Если ничего не подошло — читаем с заменой ошибок
    print("Кодировка: utf-8 (с заменой ошибок)")
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


class HtmlParser:
    """
    Собственный HTML парсер, написанный с нуля.
    
    Работает через посимвольный разбор строки.
    Не использует внешние библиотеки для парсинга.
    
    Находит:
    - Теги <img src="...">
    - background-image: url(...) в атрибуте style
    - Элементы с role="img" и aria-label
    
    Также извлекает текст для определения контекста картинок.
    """
    
    def __init__(self, html: str):
        """
        Инициализация парсера.
        
        Аргументы:
            html — строка с HTML-кодом
        """
        self.html = html
        self.pos = 0  # текущая позиция в строке
        self.length = len(html)
        self.elements = []  # найденные элементы (картинки и текст)
        self.found_images = set()  # для дедупликации картинок
    
    def parse(self):
        """
        Основной метод парсинга.
        
        Проходит по HTML посимвольно:
        - Если встретил '<' — парсит тег
        - Иначе — накапливает текст
        
        Возвращает список элементов:
        [
            {"type": "text", "content": "..."},
            {"type": "image", "src": "...", "alt": "...", "source_type": "img"},
            ...
        ]
        """
        current_text = ""
        
        while self.pos < self.length:
            char = self.html[self.pos]
            
            if char == "<":
                # Встретили начало тега — сохраняем накопленный текст
                self._save_text(current_text)
                current_text = ""
                
                # Парсим тег
                self._parse_tag()
            else:
                # Обычный символ — добавляем к тексту
                current_text += char
                self.pos += 1
        
        # Сохраняем оставшийся текст
        self._save_text(current_text)
        
        return self.elements
    
    def _add_image(self, src: str, alt: str, source_type: str):
        """
        Добавляет картинку в список с проверкой на дубликаты.
        
        Аргументы:
            src — путь или URL картинки
            alt — альтернативный текст (описание)
            source_type — откуда найдена: "img", "background", "role_img_background"
        """
        if not src:
            return
        
        # Нормализуем URL для проверки дубликата
        unique_id = normalize_image_url(src)
        
        # Пропускаем если уже есть такая картинка
        if unique_id in self.found_images:
            return
        
        self.found_images.add(unique_id)
        
        self.elements.append({
            "type": "image",
            "src": src,
            "alt": alt or "",
            "source_type": source_type,
        })
    
    def _parse_tag(self):
        """
        Парсит HTML тег начиная с текущей позиции.
        
        Обрабатывает:
        - Комментарии <!-- ... -->
        - DOCTYPE и подобные декларации
        - Открывающие и закрывающие теги
        - Теги <img>
        - Элементы с background-image в style
        - Теги <script> и <style> (пропускает их содержимое)
        """
        self.pos += 1  # пропускаем '<'
        
        if self.pos >= self.length:
            return
        
        # Проверяем комментарий <!-- ... -->
        if self.html[self.pos:self.pos + 3] == "!--":
            self._skip_comment()
            return
        
        # Проверяем DOCTYPE и подобное
        if self.html[self.pos] == "!":
            self._skip_until(">")
            return
        
        # Проверяем закрывающий тег </...>
        is_closing = False
        if self.html[self.pos] == "/":
            is_closing = True
            self.pos += 1
        
        # Читаем имя тега
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
            return
        
        # Читаем атрибуты (всё до >)
        attributes = ""
        while self.pos < self.length:
            char = self.html[self.pos]
            self.pos += 1
            if char == ">":
                break
            attributes += char
        
        attributes = attributes.strip()
        tag_name_lower = tag_name.lower()
        
        # Закрывающие теги не обрабатываем
        if is_closing:
            return
        
        # === Обрабатываем теги с картинками ===
        
        # 1. Тег <img src="...">
        if tag_name_lower == "img":
            src = self._get_attribute(attributes, "src")
            alt = self._get_attribute(attributes, "alt")
            if src:
                self._add_image(src, decode_html_entities(alt), "img")
            return
        
        # 2. Элемент с background-image в style
        # Пример: <div style="background-image: url('photo.jpg')">
        style = self._get_attribute(attributes, "style")
        if style and "url(" in style.lower():
            urls = self._extract_background_images(style)
            
            # Берём описание из aria-label или alt
            aria_label = self._get_attribute(attributes, "aria-label") or ""
            alt_attr = self._get_attribute(attributes, "alt") or ""
            role = self._get_attribute(attributes, "role") or ""
            
            for url in urls:
                # Определяем тип источника
                if role.lower() == "img":
                    source_type = "role_img_background"
                else:
                    source_type = "background"
                
                self._add_image(url, decode_html_entities(aria_label or alt_attr), source_type)
        
        # 3. Пропускаем содержимое script и style
        if tag_name_lower in ("script", "style"):
            self._skip_until_closing_tag(tag_name)
    
    def _extract_background_images(self, style_attr: str) -> list:
        """
        Извлекает все url() из атрибута style.
        
        Примеры входных данных:
            "background-image: url('photo.jpg')"
            "background: url(image.png) no-repeat"
            "background-image: url('img1.jpg'), url('img2.jpg')"
        
        Возвращает список URL: ['photo.jpg'], ['image.png'], ['img1.jpg', 'img2.jpg']
        """
        urls = []
        pos = 0
        style_lower = style_attr.lower()
        
        while True:
            # Ищем url(
            start = style_lower.find("url(", pos)
            if start == -1:
                break
            
            start += 4  # пропускаем "url("
            
            # Пропускаем пробелы
            while start < len(style_attr) and style_attr[start] in " \t":
                start += 1
            
            # Определяем тип кавычек
            quote_char = None
            if start < len(style_attr) and style_attr[start] in "'\"":
                quote_char = style_attr[start]
                start += 1
            
            # Ищем конец URL
            end = start
            while end < len(style_attr):
                char = style_attr[end]
                if quote_char:
                    if char == quote_char:
                        break
                else:
                    if char in ")\"' \t":
                        break
                end += 1
            
            # Извлекаем URL
            if end > start:
                url = style_attr[start:end]
                url = decode_html_entities(url)
                url = url.strip("'\"")
                if url:
                    urls.append(url)
            
            pos = end + 1
        
        return urls
    
    def _get_attribute(self, attrs_str: str, attr_name: str) -> str:
        """
        Извлекает значение атрибута из строки атрибутов.
        
        Поддерживает:
        - Атрибуты в двойных кавычках: src="value"
        - Атрибуты в одинарных кавычках: src='value'
        - Атрибуты без кавычек: src=value
        - Пробелы вокруг знака =: src = "value"
        
        Аргументы:
            attrs_str — строка со всеми атрибутами тега
            attr_name — имя искомого атрибута
        
        Возвращает значение атрибута или пустую строку
        """
        if not attrs_str:
            return ""
        
        attr_lower = attr_name.lower()
        attrs_lower = attrs_str.lower()
        
        # Ищем позицию атрибута
        pos = 0
        while True:
            pos = attrs_lower.find(attr_lower, pos)
            if pos == -1:
                return ""
            
            # Проверяем, что это начало слова (не часть другого атрибута)
            # Например, "data-src" не должен матчиться при поиске "src"
            if pos > 0 and (attrs_lower[pos - 1].isalnum() or attrs_lower[pos - 1] == "-"):
                pos += 1
                continue
            
            # Проверяем, что после имени идёт = или пробел
            end_of_name = pos + len(attr_lower)
            if end_of_name < len(attrs_str):
                next_char = attrs_str[end_of_name]
                if next_char.isalnum() or next_char == "-":
                    pos += 1
                    continue
            
            break
        
        # Пропускаем имя атрибута
        pos += len(attr_lower)
        
        # Пропускаем пробелы ПЕРЕД знаком =
        while pos < len(attrs_str) and attrs_str[pos] in " \t\n\r":
            pos += 1
        
        # Проверяем наличие знака =
        if pos >= len(attrs_str) or attrs_str[pos] != "=":
            return ""
        
        pos += 1  # пропускаем =
        
        # Пропускаем пробелы ПОСЛЕ знака =
        while pos < len(attrs_str) and attrs_str[pos] in " \t\n\r":
            pos += 1
        
        if pos >= len(attrs_str):
            return ""
        
        # Определяем тип кавычек
        quote = attrs_str[pos]
        
        if quote in ('"', "'"):
            # Значение в кавычках
            pos += 1
            value = ""
            while pos < len(attrs_str) and attrs_str[pos] != quote:
                value += attrs_str[pos]
                pos += 1
            return value
        else:
            # Значение без кавычек — до пробела или конца
            value = ""
            while pos < len(attrs_str) and attrs_str[pos] not in (" ", ">", "\t", "\n", "\r", "/"):
                value += attrs_str[pos]
                pos += 1
            return value
    
    def _skip_comment(self):
        """Пропускает HTML комментарий <!-- ... -->"""
        end = self.html.find("-->", self.pos)
        self.pos = end + 3 if end != -1 else self.length
    
    def _skip_until(self, char: str):
        """Пропускает символы до указанного символа (включительно)."""
        while self.pos < self.length:
            if self.html[self.pos] == char:
                self.pos += 1
                break
            self.pos += 1
    
    def _skip_until_closing_tag(self, tag_name: str):
        """
        Пропускает содержимое до закрывающего тега.
        Используется для <script> и <style>.
        """
        closing = f"</{tag_name}>".lower()
        while self.pos < self.length:
            if self.html[self.pos:self.pos + len(closing)].lower() == closing:
                self.pos += len(closing)
                return
            self.pos += 1
    
    def _save_text(self, text: str):
        """
        Сохраняет текстовый блок.
        
        Нормализует пробелы и пропускает пустые блоки.
        """
        # Убираем лишние пробелы и переносы строк
        cleaned = " ".join(text.split()).strip()
        
        if cleaned:
            self.elements.append({
                "type": "text",
                "content": decode_html_entities(cleaned)
            })


def save_image(src: str, output_dir: str, counter: int, base_path: str, base_url: str = "") -> dict:
    """
    Универсальная функция сохранения картинки.
    
    Поддерживает:
    - Data URL (base64): data:image/png;base64,...
    - URL (http/https): https://example.com/photo.jpg
    - Пути от корня сайта: /images/photo.jpg (с base_url)
    - Локальные файлы: ./images/photo.jpg
    
    Аргументы:
        src — путь или URL картинки
        output_dir — папка для сохранения
        counter — счётчик для имени файла
        base_path — папка где лежит HTML файл
        base_url — базовый URL сайта (для путей от корня)
    
    Возвращает словарь с информацией или None при ошибке
    """
    # Декодируем HTML-сущности
    src = decode_html_entities(src)
    
    # Убираем лишние кавычки
    src = src.strip("'\"")
    
    # ТИП 1: Data URL (картинка в base64)
    if src.startswith("data:"):
        return save_data_url(src, output_dir, counter)
    
    # ТИП 2: URL (http/https)
    if src.startswith(("http://", "https://", "//")):
        if src.startswith("//"):
            src = "https:" + src
        return download_url(src, output_dir, counter)
    
    # ТИП 3: Путь от корня сайта (/images/photo.jpg)
    if src.startswith("/") and not src.startswith("./"):
        if base_url:
            # Собираем полный URL
            full_url = base_url.rstrip("/") + src
            return download_url(full_url, output_dir, counter)
        else:
            # Без base_url не можем скачать
            return None
    
    # ТИП 4: Локальный файл (./images/photo.jpg или images/photo.jpg)
    return copy_local_file(src, output_dir, counter, base_path)


def save_data_url(data_url: str, output_dir: str, counter: int) -> dict:
    """
    Декодирует и сохраняет картинку из Data URL.
    
    Формат Data URL: data:image/png;base64,iVBORw0KGgo...
                     │    │         │      │
                     │    │         │      └── данные в base64
                     │    │         └── кодировка
                     │    └── тип изображения
                     └── схема
    """
    try:
        # Разделяем заголовок и данные по запятой
        header, encoded_data = data_url.split(",", 1)
        
        # Определяем расширение по типу изображения
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
        
        # Сохраняем файл
        image_name = f"image_{counter}{ext}"
        save_path = os.path.join(output_dir, image_name)
        
        with open(save_path, "wb") as f:
            f.write(image_bytes)
        
        print(f"  [DATA URL] -> {image_name} ({len(image_bytes)} байт)")
        
        return {
            "image_name": image_name,
            "image_path": os.path.abspath(save_path),
        }
        
    except Exception as e:
        print(f"  [ОШИБКА] Data URL: {e}")
        return None


def download_url(url: str, output_dir: str, counter: int) -> dict:
    """
    Скачивает картинку по URL.
    
    Использует urllib.request (стандартная библиотека).
    Добавляет User-Agent чтобы сервер не блокировал запрос.
    """
    try:
        # Убираем параметры для определения расширения
        path_part = url.split("?")[0]
        original_name = path_part.split("/")[-1]
        
        # Определяем расширение
        _, ext = os.path.splitext(original_name)
        if not ext or len(ext) > 5:
            ext = ".jpg"  # по умолчанию
        
        image_name = f"image_{counter}{ext}"
        save_path = os.path.join(output_dir, image_name)
        
        print(f"  [СКАЧИВАНИЕ] {url[:60]}...")
        
        # Создаём запрос с User-Agent
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        request = urllib.request.Request(url, headers=headers)
        
        # Скачиваем
        with urllib.request.urlopen(request, timeout=30) as response:
            image_bytes = response.read()
        
        # Сохраняем
        with open(save_path, "wb") as f:
            f.write(image_bytes)
        
        print(f"  [OK] -> {image_name} ({len(image_bytes)} байт)")
        
        return {
            "image_name": image_name,
            "image_path": os.path.abspath(save_path),
        }
        
    except Exception as e:
        print(f"  [ОШИБКА] {url[:50]}: {e}")
        return None


def copy_local_file(src: str, output_dir: str, counter: int, base_path: str) -> dict:
    """
    Копирует локальный файл картинки.
    
    Аргументы:
        src — относительный путь к файлу
        output_dir — папка для сохранения
        counter — счётчик для имени файла
        base_path — папка где лежит HTML файл
    """
    # Убираем параметры из пути (например ?v=123)
    clean_src = src.split("?")[0]
    
    # Собираем полный путь
    source_path = os.path.join(base_path, clean_src)
    source_path = os.path.normpath(source_path)
    
    # Проверяем существование файла
    if not os.path.exists(source_path):
        return None
    
    # Определяем расширение
    _, ext = os.path.splitext(clean_src)
    if not ext:
        ext = ".png"
    
    image_name = f"image_{counter}{ext}"
    save_path = os.path.join(output_dir, image_name)
    
    # Копируем файл
    shutil.copy2(source_path, save_path)
    
    size = os.path.getsize(save_path)
    print(f"  [OK] {src} -> {image_name} ({size} байт)")
    
    return {
        "image_name": image_name,
        "image_path": os.path.abspath(save_path),
    }


def find_text_before(elements, index):
    """
    Ищет ближайший текстовый блок ПЕРЕД указанным элементом.
    
    Идёт от текущей позиции вверх до начала списка.
    Возвращает первый найденный текст или пустую строку.
    """
    for i in range(index - 1, -1, -1):
        if elements[i]["type"] == "text":
            return elements[i]["content"]
    return ""


def find_text_after(elements, index):
    """
    Ищет ближайший текстовый блок ПОСЛЕ указанного элемента.
    
    Идёт от текущей позиции вниз до конца списка.
    Возвращает первый найденный текст или пустую строку.
    """
    for i in range(index + 1, len(elements)):
        if elements[i]["type"] == "text":
            return elements[i]["content"]
    return ""


def save_results_to_json(results, output_dir):
    """
    Сохраняет результаты парсинга в JSON файл.
    
    Формат JSON:
    [
        {
            "id": 1,
            "image_name": "image_1.jpg",
            "image_path": "/path/to/image_1.jpg",
            "original_src": "https://example.com/photo.jpg",
            "source_type": "img",
            "alt": "Описание картинки",
            "text_before": "Текст перед картинкой",
            "text_after": "Текст после картинки",
            "context": "Текст перед | Описание | Текст после"
        },
        ...
    ]
    """
    path = os.path.join(output_dir, "results.json")
    
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    return path


def parse_html_file(html_path, output_dir="output", base_url=""):
    """
    Главная функция — парсит HTML файл и извлекает картинки.
    
    Аргументы:
        html_path — путь к HTML файлу
        output_dir — папка для сохранения картинок и JSON
        base_url — базовый URL сайта (для путей от корня, например /images/photo.jpg)
    
    Возвращает список словарей с информацией о картинках.
    """
    print(f"\n{'='*60}")
    print(f"  HTML ПАРСЕР")
    print(f"{'='*60}")
    print(f"\nФайл: {html_path}")
    if base_url:
        print(f"Base URL: {base_url}")
    
    # Проверяем существование файла
    if not os.path.exists(html_path):
        print("ОШИБКА: Файл не найден!")
        return []
    
    # Создаём папку для результатов
    os.makedirs(output_dir, exist_ok=True)
    
    # Читаем HTML файл
    html_content = read_html_file(html_path)
    
    print(f"Размер: {len(html_content)} символов")
    print(f"\n--- Парсинг ---\n")
    
    # Парсим HTML
    parser = HtmlParser(html_content)
    elements = parser.parse()
    
    # Считаем картинки
    images = [e for e in elements if e["type"] == "image"]
    print(f"\nНайдено уникальных картинок: {len(images)}")
    
    if not images:
        print("Картинки не найдены!")
        return []
    
    # Определяем базовый путь для локальных файлов
    base_path = os.path.dirname(os.path.abspath(html_path))
    
    print(f"\n--- Сохранение картинок ---\n")
    
    results = []
    counter = 0
    
    # Обрабатываем каждую картинку
    for i, elem in enumerate(elements):
        if elem["type"] != "image":
            continue
        
        counter += 1
        src = elem["src"]
        alt = elem.get("alt", "")
        source_type = elem.get("source_type", "unknown")
        
        # Сохраняем картинку
        saved = save_image(src, output_dir, counter, base_path, base_url)
        
        if saved:
            # Ищем контекст (текст рядом)
            text_before = find_text_before(elements, i)
            text_after = find_text_after(elements, i)
            
            # Добавляем в результаты
            results.append({
                "id": counter,
                "image_name": saved["image_name"],
                "image_path": saved["image_path"],
                "original_src": src[:200],  # обрезаем очень длинные URL
                "source_type": source_type,
                "alt": alt,
                "text_before": text_before,
                "text_after": text_after,
                "context": " | ".join(filter(None, [text_before, alt, text_after])),
            })
    
    # Сохраняем в JSON
    if results:
        json_path = save_results_to_json(results, output_dir)
        print(f"\n📄 JSON: {json_path}")
    
    return results


def print_results(results):
    """Выводит результаты в консоль."""
    print(f"\n{'='*60}")
    print(f"  РЕЗУЛЬТАТ: {len(results)} уникальных картинок")
    print(f"{'='*60}\n")
    
    if not results:
        return
    
    for r in results:
        print(f"[{r['id']}] 📷 {r['image_name']}  ({r['source_type']})")
        alt_display = r['alt'][:50] if r['alt'] else '(пусто)'
        before_display = r['text_before'][:60] if r['text_before'] else '(пусто)'
        after_display = r['text_after'][:60] if r['text_after'] else '(пусто)'
        print(f"    Alt:         {alt_display}")
        print(f"    Текст ДО:    {before_display}")
        print(f"    Текст ПОСЛЕ: {after_display}")
        print()


if __name__ == "__main__":
    # Проверяем аргументы командной строки
    if len(sys.argv) < 2:
        print("HTML парсер — извлекает картинки и текст рядом с ними")
        print()
        print("Использование:")
        print("  python html_parser.py <файл.html> [папка_вывода] [base_url]")
        print()
        print("Примеры:")
        print("  python html_parser.py page.html")
        print("  python html_parser.py spbu.html output/")
        print("  python html_parser.py spbu.html output/ https://spbu.ru")
        print()
        print("base_url нужен для скачивания картинок с путями типа /images/photo.jpg")
        sys.exit(0)
    
    # Читаем аргументы
    html_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "output"
    base_url = sys.argv[3] if len(sys.argv) > 3 else ""
    
    # Запускаем парсер
    results = parse_html_file(html_path, output_dir, base_url)
    
    # Выводим результаты
    print_results(results)
    
    if results:
        print(f"📁 Картинки сохранены: {output_dir}/")