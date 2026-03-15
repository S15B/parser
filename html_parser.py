"""
HTML парсер с нуля — обобщённая версия.
С фильтром иконок и полным покрытием способов вставки картинок.
"""

import os
import sys
import shutil
import base64
import urllib.request
import json
import re


def decode_html_entities(text: str) -> str:
    """Декодирует HTML-сущности."""
    if not text:
        return text
    
    entities = {
        "&amp;": "&", "&lt;": "<", "&gt;": ">",
        "&quot;": '"', "&apos;": "'", "&#39;": "'",
        "&#34;": '"', "&nbsp;": " ", "&laquo;": "«",
        "&raquo;": "»", "&mdash;": "—", "&ndash;": "–",
    }
    
    for entity, char in entities.items():
        text = text.replace(entity, char)
    
    def replace_numeric(match):
        try:
            return chr(int(match.group(1)))
        except:
            return match.group(0)
    
    return re.sub(r'&#(\d+);', replace_numeric, text)


def normalize_image_url(src: str) -> str:
    """Нормализует URL для дедупликации."""
    if not src:
        return ""
    src = src.strip("'\"").lower()
    src = src.split("?")[0]
    src = re.sub(r'/styles/[^/]+/public/', '/', src)
    src = os.path.basename(src)
    return src


def is_image_url(url: str) -> bool:
    """Проверяет является ли строка ссылкой на картинку."""
    if not url:
        return False
    
    url_lower = url.lower().strip("'\"")
    
    if url_lower.startswith("data:image"):
        return True
    
    extensions = (
        '.jpg', '.jpeg', '.png', '.gif', '.webp',
        '.svg', '.ico', '.bmp', '.avif', '.tiff'
    )
    path = url_lower.split("?")[0].split("#")[0]
    return path.endswith(extensions)


def is_icon(src: str) -> bool:
    """
    Проверяет, является ли картинка иконкой (favicon, apple-touch и т.п.)
    Такие картинки обычно не нужны пользователю.
    """
    if not src:
        return False
    
    src_lower = src.lower()
    
    # Типичные имена иконок
    icon_patterns = [
        "favicon",
        "apple-touch-icon",
        "mstile-",
        "android-chrome",
        "safari-pinned",
        "browserconfig",
        "site.webmanifest",
    ]
    
    for pattern in icon_patterns:
        if pattern in src_lower:
            return True
    
    # Типичные размеры иконок в имени файла: 16x16, 32x32 и т.д.
    if re.search(r'\d+x\d+', src_lower):
        # Маленькие размеры — скорее всего иконка
        match = re.search(r'(\d+)x(\d+)', src_lower)
        if match:
            w, h = int(match.group(1)), int(match.group(2))
            if w <= 192 and h <= 192:
                # Но проверяем что это не обычная маленькая картинка
                basename = os.path.basename(src_lower)
                if "icon" in basename or "touch" in basename or "tile" in basename:
                    return True
    
    # Расширение .ico — всегда иконка
    if src_lower.split("?")[0].endswith(".ico"):
        return True
    
    return False


def read_html_file(file_path: str) -> str:
    """Читает HTML с автоопределением кодировки."""
    for encoding in ["utf-8", "cp1251", "cp1252", "latin-1"]:
        try:
            with open(file_path, "r", encoding=encoding) as f:
                content = f.read()
            print(f"Кодировка: {encoding}")
            return content
        except UnicodeDecodeError:
            continue
    
    print("Кодировка: utf-8 (с заменой ошибок)")
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


# Атрибуты которые могут содержать URL картинки
IMAGE_ATTRS = [
    "src",           # <img src>, <embed src>, <input src>
    "srcset",        # <img srcset>, <source srcset>
    "data",          # <object data>
    "poster",        # <video poster>
    "xlink:href",    # <svg image xlink:href>
    "background",    # <body background> (устаревший HTML)
    "data-src",      # lazy loading
    "data-lazy",     # lazy loading
    "data-original", # lazy loading
    "data-image",    # lazy loading
    "data-bg",       # lazy loading background
    "data-poster",   # lazy loading poster
    "data-background", # lazy loading background
]

# Атрибуты из которых берём описание картинки
ALT_ATTRS = ["alt", "aria-label", "title"]

# Теги в которых href/content — НЕ картинка, а служебная ссылка
# В этих тегах мы проверяем href/content отдельно с фильтром
SPECIAL_HREF_TAGS = {"link", "meta", "a"}


class HtmlParser:
    """
    Обобщённый HTML парсер.
    Для каждого тега проверяем все атрибуты из IMAGE_ATTRS.
    """
    
    def __init__(self, html: str):
        self.html = html
        self.pos = 0
        self.length = len(html)
        self.elements = []
        self.found_images = set()
    
    def parse(self):
        """Основной метод парсинга."""
        current_text = ""
        
        while self.pos < self.length:
            char = self.html[self.pos]
            
            if char == "<":
                self._save_text(current_text)
                current_text = ""
                self._parse_tag()
            else:
                current_text += char
                self.pos += 1
        
        self._save_text(current_text)
        
        # Дополнительно ищем в CSS блоках <style>
        self._parse_style_blocks()
        
        return self.elements
    
    def _add_image(self, src: str, alt: str, source_type: str):
        """Добавляет картинку с проверкой на дубликаты и фильтром иконок."""
        if not src:
            return
        
        # Фильтруем иконки
        if is_icon(src):
            return
        
        # Проверяем дубликат
        unique_id = normalize_image_url(src)
        if not unique_id or unique_id in self.found_images:
            return
        
        self.found_images.add(unique_id)
        
        self.elements.append({
            "type": "image",
            "src": src,
            "alt": alt or "",
            "source_type": source_type,
        })
    
    def _parse_tag(self):
        """Парсит один тег."""
        self.pos += 1
        
        if self.pos >= self.length:
            return
        
        # Комментарий
        if self.html[self.pos:self.pos + 3] == "!--":
            self._skip_comment()
            return
        
        # DOCTYPE
        if self.html[self.pos] == "!":
            self._skip_until(">")
            return
        
        # Закрывающий тег
        is_closing = False
        if self.html[self.pos] == "/":
            is_closing = True
            self.pos += 1
        
        # Имя тега
        tag_name = ""
        while self.pos < self.length and self.html[self.pos].isalnum():
            tag_name += self.html[self.pos]
            self.pos += 1
        
        if not tag_name:
            self._skip_until(">")
            return
        
        # Атрибуты
        attributes = ""
        while self.pos < self.length:
            char = self.html[self.pos]
            self.pos += 1
            if char == ">":
                break
            attributes += char
        
        attributes = attributes.strip()
        tag_lower = tag_name.lower()
        
        if is_closing:
            return
        
        # === УНИВЕРСАЛЬНАЯ ОБРАБОТКА ===
        
        # 1. Получаем описание (alt, aria-label, title)
        alt = ""
        for alt_attr in ALT_ATTRS:
            val = self._get_attribute(attributes, alt_attr)
            if val:
                alt = decode_html_entities(val)
                break
        
        # 2. Проверяем IMAGE_ATTRS (общие для всех тегов)
        for attr in IMAGE_ATTRS:
            value = self._get_attribute(attributes, attr)
            if not value:
                continue
            
            # srcset — несколько URL, берём лучший
            if attr == "srcset":
                self._parse_srcset(value, f"{tag_lower}_srcset")
                continue
            
            # Проверяем что это картинка
            if is_image_url(value):
                self._add_image(value, alt, f"{tag_lower}_{attr}")
        
        # 3. Отдельная обработка href и content
        #    (в <link> и <meta> они часто НЕ картинки)
        if tag_lower == "link":
            # Пропускаем иконки: <link rel="icon" href="...">
            rel = self._get_attribute(attributes, "rel").lower()
            href = self._get_attribute(attributes, "href")
            
            if href and is_image_url(href):
                # Пропускаем иконки
                if "icon" in rel or "apple-touch" in rel:
                    pass  # фильтр is_icon() тоже поймает, но лучше перестраховаться
                # Пропускаем стили и шрифты
                elif "stylesheet" in rel or "font" in rel:
                    pass
                # preload изображений — это нужная картинка
                elif "preload" in rel:
                    as_attr = self._get_attribute(attributes, "as")
                    if as_attr.lower() == "image":
                        self._add_image(href, alt, "link_preload")
        
        elif tag_lower == "meta":
            # og:image, twitter:image — это нужные картинки
            prop = self._get_attribute(attributes, "property").lower()
            name = self._get_attribute(attributes, "name").lower()
            content = self._get_attribute(attributes, "content")
            
            if content and is_image_url(content):
                if "image" in prop or "image" in name:
                    self._add_image(content, alt, "meta_image")
        
        elif tag_lower == "image":
            # SVG <image href="..."> или <image xlink:href="...">
            href = self._get_attribute(attributes, "href")
            if not href:
                href = self._get_attribute(attributes, "xlink:href")
            if href and is_image_url(href):
                self._add_image(href, alt, "svg_image")
        
        # 4. Проверяем style на url()
        style = self._get_attribute(attributes, "style")
        if style and "url(" in style.lower():
            urls = self._extract_urls_from_css(style)
            role = self._get_attribute(attributes, "role")
            
            for url in urls:
                s_type = f"{tag_lower}_background"
                if role and role.lower() == "img":
                    s_type = f"{tag_lower}_role_img"
                self._add_image(url, alt, s_type)
        
        # 5. Пропускаем содержимое script и style
        if tag_lower in ("script", "style"):
            self._skip_until_closing_tag(tag_name)
    
    def _parse_srcset(self, srcset: str, source_type: str):
        """Парсит srcset, берёт картинку с наибольшим размером."""
        parts = srcset.split(",")
        
        candidates = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            tokens = part.split()
            if not tokens:
                continue
            
            url = tokens[0].strip()
            size = 0
            if len(tokens) > 1:
                descriptor = tokens[1].lower()
                try:
                    if descriptor.endswith("w"):
                        size = int(descriptor[:-1])
                    elif descriptor.endswith("x"):
                        size = int(float(descriptor[:-1]) * 100)
                except:
                    size = 0
            candidates.append((url, size))
        
        if candidates:
            best = max(candidates, key=lambda x: x[1])
            self._add_image(best[0], "", source_type)
    
    def _parse_style_blocks(self):
        """Ищет url() внутри блоков <style>."""
        pos = 0
        html_lower = self.html.lower()
        
        while True:
            start = html_lower.find("<style", pos)
            if start == -1:
                break
            
            start_end = self.html.find(">", start)
            if start_end == -1:
                break
            
            end = html_lower.find("</style>", start_end)
            if end == -1:
                break
            
            css = self.html[start_end + 1:end]
            for url in self._extract_urls_from_css(css):
                if is_image_url(url):
                    self._add_image(url, "", "css_style_block")
            
            pos = end + 8
    
    def _extract_urls_from_css(self, css: str) -> list:
        """Извлекает все url() из CSS."""
        urls = []
        pos = 0
        css_lower = css.lower()
        
        while True:
            start = css_lower.find("url(", pos)
            if start == -1:
                break
            
            start += 4
            
            while start < len(css) and css[start] in " \t\n\r":
                start += 1
            
            quote_char = None
            if start < len(css) and css[start] in "'\"":
                quote_char = css[start]
                start += 1
            
            end = start
            while end < len(css):
                char = css[end]
                if quote_char:
                    if char == quote_char:
                        break
                else:
                    if char in ")\"' \t\n\r":
                        break
                end += 1
            
            if end > start:
                url = css[start:end]
                url = decode_html_entities(url).strip("'\"")
                if url and not url.startswith("data:text"):
                    urls.append(url)
            
            pos = end + 1
        
        return urls
    
    def _get_attribute(self, attrs_str: str, attr_name: str) -> str:
        """Извлекает значение атрибута."""
        if not attrs_str:
            return ""
        
        attr_lower = attr_name.lower()
        attrs_lower = attrs_str.lower()
        
        pos = 0
        while True:
            pos = attrs_lower.find(attr_lower, pos)
            if pos == -1:
                return ""
            
            if pos > 0 and (attrs_lower[pos - 1].isalnum() or attrs_lower[pos - 1] in "-_"):
                pos += 1
                continue
            
            end_of_name = pos + len(attr_lower)
            if end_of_name < len(attrs_str):
                next_char = attrs_str[end_of_name]
                if next_char.isalnum() or next_char in "-_":
                    pos += 1
                    continue
            break
        
        pos += len(attr_lower)
        
        while pos < len(attrs_str) and attrs_str[pos] in " \t\n\r":
            pos += 1
        
        if pos >= len(attrs_str) or attrs_str[pos] != "=":
            return ""
        
        pos += 1
        
        while pos < len(attrs_str) and attrs_str[pos] in " \t\n\r":
            pos += 1
        
        if pos >= len(attrs_str):
            return ""
        
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
            while pos < len(attrs_str) and attrs_str[pos] not in (" ", ">", "\t", "\n", "\r", "/"):
                value += attrs_str[pos]
                pos += 1
            return value
    
    def _skip_comment(self):
        end = self.html.find("-->", self.pos)
        self.pos = end + 3 if end != -1 else self.length
    
    def _skip_until(self, char: str):
        while self.pos < self.length:
            if self.html[self.pos] == char:
                self.pos += 1
                break
            self.pos += 1
    
    def _skip_until_closing_tag(self, tag_name: str):
        closing = f"</{tag_name}>".lower()
        while self.pos < self.length:
            if self.html[self.pos:self.pos + len(closing)].lower() == closing:
                self.pos += len(closing)
                return
            self.pos += 1
    
    def _save_text(self, text: str):
        cleaned = " ".join(text.split()).strip()
        if cleaned:
            self.elements.append({
                "type": "text",
                "content": decode_html_entities(cleaned),
            })


def save_image(src: str, output_dir: str, counter: int, base_path: str, base_url: str = "") -> dict:
    """Сохраняет картинку из любого источника."""
    src = decode_html_entities(src).strip("'\"")
    
    if src.startswith("data:"):
        return save_data_url(src, output_dir, counter)
    
    if src.startswith(("http://", "https://", "//")):
        if src.startswith("//"):
            src = "https:" + src
        return download_url(src, output_dir, counter)
    
    if src.startswith("/") and not src.startswith("./"):
        if base_url:
            return download_url(base_url.rstrip("/") + src, output_dir, counter)
        return None
    
    return copy_local_file(src, output_dir, counter, base_path)


def save_data_url(data_url: str, output_dir: str, counter: int) -> dict:
    """Декодирует Data URL."""
    try:
        header, encoded_data = data_url.split(",", 1)
        
        ext_map = {"png": ".png", "jpeg": ".jpg", "jpg": ".jpg",
                   "gif": ".gif", "webp": ".webp", "svg": ".svg"}
        ext = ".png"
        for key, val in ext_map.items():
            if key in header:
                ext = val
                break
        
        image_bytes = base64.b64decode(encoded_data)
        image_name = f"image_{counter}{ext}"
        save_path = os.path.join(output_dir, image_name)
        
        with open(save_path, "wb") as f:
            f.write(image_bytes)
        
        print(f"  [DATA URL] -> {image_name} ({len(image_bytes)} байт)")
        return {"image_name": image_name, "image_path": os.path.abspath(save_path)}
    except Exception as e:
        print(f"  [ОШИБКА] Data URL: {e}")
        return None


def download_url(url: str, output_dir: str, counter: int) -> dict:
    """Скачивает картинку по URL."""
    try:
        original_name = url.split("?")[0].split("/")[-1]
        _, ext = os.path.splitext(original_name)
        if not ext or len(ext) > 5:
            ext = ".jpg"
        
        image_name = f"image_{counter}{ext}"
        save_path = os.path.join(output_dir, image_name)
        
        print(f"  [СКАЧИВАНИЕ] {url[:60]}...")
        
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        
        with urllib.request.urlopen(request, timeout=30) as response:
            image_bytes = response.read()
        
        with open(save_path, "wb") as f:
            f.write(image_bytes)
        
        print(f"  [OK] -> {image_name} ({len(image_bytes)} байт)")
        return {"image_name": image_name, "image_path": os.path.abspath(save_path)}
    except Exception as e:
        print(f"  [ОШИБКА] {url[:50]}: {e}")
        return None


def copy_local_file(src: str, output_dir: str, counter: int, base_path: str) -> dict:
    """Копирует локальный файл."""
    clean_src = src.split("?")[0]
    source_path = os.path.normpath(os.path.join(base_path, clean_src))
    
    if not os.path.exists(source_path):
        return None
    
    _, ext = os.path.splitext(clean_src)
    if not ext:
        ext = ".png"
    
    image_name = f"image_{counter}{ext}"
    save_path = os.path.join(output_dir, image_name)
    
    shutil.copy2(source_path, save_path)
    size = os.path.getsize(save_path)
    print(f"  [OK] {src} -> {image_name} ({size} байт)")
    
    return {"image_name": image_name, "image_path": os.path.abspath(save_path)}


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


def save_results_to_json(results, output_dir):
    """Сохраняет результаты в JSON."""
    path = os.path.join(output_dir, "results.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    return path


def parse_html_file(html_path, output_dir="output", base_url=""):
    """Парсит HTML и извлекает картинки."""
    print(f"\n{'='*60}")
    print(f"  HTML ПАРСЕР")
    print(f"{'='*60}")
    print(f"\nФайл: {html_path}")
    if base_url:
        print(f"Base URL: {base_url}")
    
    if not os.path.exists(html_path):
        print("ОШИБКА: Файл не найден!")
        return []
    
    os.makedirs(output_dir, exist_ok=True)
    html_content = read_html_file(html_path)
    
    print(f"Размер: {len(html_content)} символов")
    print(f"\n--- Парсинг ---\n")
    
    parser = HtmlParser(html_content)
    elements = parser.parse()
    
    images = [e for e in elements if e["type"] == "image"]
    print(f"\nНайдено уникальных картинок: {len(images)}")
    
    if not images:
        print("Картинки не найдены!")
        return []
    
    by_type = {}
    for e in images:
        by_type[e["source_type"]] = by_type.get(e["source_type"], 0) + 1
    
    print("\nПо источникам:")
    for t, count in sorted(by_type.items(), key=lambda x: -x[1]):
        print(f"  - {t}: {count}")
    
    base_path = os.path.dirname(os.path.abspath(html_path))
    
    print(f"\n--- Сохранение ---\n")
    
    results = []
    counter = 0
    
    for i, elem in enumerate(elements):
        if elem["type"] != "image":
            continue
        
        counter += 1
        saved = save_image(elem["src"], output_dir, counter, base_path, base_url)
        
        if saved:
            results.append({
                "id": counter,
                "image_name": saved["image_name"],
                "image_path": saved["image_path"],
                "original_src": elem["src"][:200],
                "source_type": elem.get("source_type", "unknown"),
                "alt": elem.get("alt", ""),
                "text_before": find_text_before(elements, i),
                "text_after": find_text_after(elements, i),
                "context": " | ".join(filter(None, [
                    find_text_before(elements, i),
                    elem.get("alt", ""),
                    find_text_after(elements, i),
                ])),
            })
    
    if results:
        json_path = save_results_to_json(results, output_dir)
        print(f"\n📄 JSON: {json_path}")
    
    return results


def print_results(results):
    """Выводит результаты."""
    print(f"\n{'='*60}")
    print(f"  РЕЗУЛЬТАТ: {len(results)} уникальных картинок")
    print(f"{'='*60}\n")
    
    for r in results:
        print(f"[{r['id']}] 📷 {r['image_name']}  ({r['source_type']})")
        print(f"    Alt:         {r['alt'][:50] if r['alt'] else '(пусто)'}")
        print(f"    Текст ДО:    {r['text_before'][:60] if r['text_before'] else '(пусто)'}")
        print(f"    Текст ПОСЛЕ: {r['text_after'][:60] if r['text_after'] else '(пусто)'}")
        print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование:")
        print("  python html_parser.py <файл.html> [папка] [base_url]")
        print()
        print("Примеры:")
        print("  python html_parser.py page.html")
        print("  python html_parser.py spbu.html output/ https://spbu.ru")
        sys.exit(0)
    
    html_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "output"
    base_url = sys.argv[3] if len(sys.argv) > 3 else ""
    
    results = parse_html_file(html_path, output_dir, base_url)
    print_results(results)
    
    if results:
        print(f"📁 Картинки: {output_dir}/")