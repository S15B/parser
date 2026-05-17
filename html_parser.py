import os
import sys
import shutil
import base64
import urllib.request
import json
import re
import logging

logger = logging.getLogger(__name__)


def decode_html_entities(text: str) -> str:
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
    if not src:
        return ""
    src = src.strip("'\"").lower()
    src = src.split("?")[0]
    src = re.sub(r'/styles/[^/]+/public/', '/', src)
    return src

def is_image_url(url: str) -> bool:
    if not url:
        return False
    url_lower = url.lower().strip("'\"")
    if url_lower.startswith("data:image"):
        return True
    extensions = (
        '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.avif', '.tiff'
    )
    path = url_lower.split("?")[0].split("#")[0]
    return path.endswith(extensions)


def is_icon(src: str, tag_attrs: dict = None) -> bool:
    """
    Определяет, является ли изображение иконкой/служебным элементом.
    В приоритете – атрибуты HTML-тега, затем резервная проверка URL.
    """
    if not src:
        return False

    if tag_attrs:
        w = tag_attrs.get('width')
        h = tag_attrs.get('height')
        if w and h:
            try:
                w_val = int(w)
                h_val = int(h)
                if w_val <= 48 and h_val <= 48:
                    return True
            except ValueError:
                pass

        css_classes = (tag_attrs.get('class', '') + ' ' + tag_attrs.get('id', '')).lower()
        if any(word in css_classes for word in
               ['icon', 'logo', 'avatar', 'sprite', 'emoji', 'favicon', 'ui-']):
            return True

        role = tag_attrs.get('role', '').lower()
        if role in ('presentation', 'none'):
            return True

    return False


def read_html_file(file_path: str) -> str:
    for encoding in ["utf-8", "cp1251", "cp1252", "latin-1"]:
        try:
            with open(file_path, "r", encoding=encoding) as f:
                content = f.read()
            logger.debug(f"Кодировка: {encoding}")
            return content
        except UnicodeDecodeError:
            continue
    logger.debug("Кодировка: utf-8 (с заменой ошибок)")
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


IMAGE_ATTRS = [
    "src", "srcset", "data", "poster", "xlink:href", "background",
    "data-src", "data-lazy", "data-original", "data-image",
    "data-bg", "data-poster", "data-background",
]

ALT_ATTRS = ["alt", "aria-label", "title"]

BLOCK_TAGS = {
    'p', 'div', 'section', 'article', 'header', 'footer', 'main', 'aside',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'blockquote', 'figcaption',
    'caption', 'td', 'th', 'form', 'nav', 'details', 'summary', 'pre',
    'address', 'fieldset'
}

HEADING_TAGS = {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}


class HtmlParser:
    def __init__(self, html: str):
        self.html = html
        self.pos = 0
        self.length = len(html)
        # Древовидная структура
        self.root = {'tag': 'root', 'children': [], 'elements': [], 'text': ''}
        self.current_block = self.root
        self.stack = [self.root]       # стек узлов
        self.in_heading = False
        self.heading_tag = None
        self.found_images = set()

    def parse(self):
        current_text = ""
        while self.pos < self.length:
            char = self.html[self.pos]
            if char == "<":
                if current_text:
                    self._add_text(current_text)
                    current_text = ""
                self._parse_tag()
            else:
                current_text += char
                self.pos += 1
        if current_text:
            self._add_text(current_text)

        # Извлечение изображений из CSS-блоков (style)
        self._parse_style_blocks()

        # Рекурсивно вычисляем полный текст всех блоков
        self._compute_texts(self.root)
        return self.root

    def _add_text(self, text: str):
        cleaned = " ".join(text.split()).strip()
        if not cleaned:
            return
        decoded = decode_html_entities(cleaned)
        if self.in_heading:
            self.current_block['elements'].append({
                'type': 'heading',
                'content': decoded,
                'tag': self.heading_tag
            })
        else:
            self.current_block['elements'].append({
                'type': 'text',
                'content': decoded
            })

    def _add_image(self, src: str, alt: str, source_type: str, tag_attrs: dict = None):
        if not src:
            return
        if is_icon(src, tag_attrs):
            logger.debug(f"ICON BLOCKED: {src[:100]}")
            return
        unique_id = normalize_image_url(src)
        if not unique_id or unique_id in self.found_images:
            return
        self.found_images.add(unique_id)
        self.current_block['elements'].append({
            'type': 'image',
            'src': src,
            'alt': alt or '',
            'source_type': source_type
        })

    def _start_block(self, tag: str):
        new_block = {'tag': tag, 'children': [], 'elements': [], 'text': ''}
        self.current_block['children'].append(new_block)
        self.stack.append(new_block)
        self.current_block = new_block

    def _end_block(self, tag: str):
        if len(self.stack) > 1 and self.stack[-1]['tag'] == tag:
            self.stack.pop()
            self.current_block = self.stack[-1]

    def _parse_tag(self):
        self.pos += 1
        if self.pos >= self.length:
            return
        if self.html[self.pos:self.pos+3] == "!--":
            self._skip_comment()
            return
        if self.html[self.pos] == "!":
            self._skip_until(">")
            return

        is_closing = False
        if self.html[self.pos] == "/":
            is_closing = True
            self.pos += 1

        tag_name = ""
        while self.pos < self.length and self.html[self.pos].isalnum():
            tag_name += self.html[self.pos]
            self.pos += 1
        if not tag_name:
            self._skip_until(">")
            return

        attributes = ""
        while self.pos < self.length:
            char = self.html[self.pos]
            self.pos += 1
            if char == ">":
                break
            attributes += char

        tag_lower = tag_name.lower()

        # Парсинг атрибутов в словарь
        attr_dict = {}
        for m in re.finditer(r'([\w-]+)\s*=\s*("[^"]*"|\'[^\']*\'|\S+)', attributes):
            key = m.group(1).lower()
            val = m.group(2).strip('"\'')
            attr_dict[key] = val

        if is_closing:
            if tag_lower in HEADING_TAGS:
                self.in_heading = False
                self.heading_tag = None
            if tag_lower in BLOCK_TAGS:
                self._end_block(tag_lower)
            return

        # Открывающий тег
        alt = ""
        for alt_attr in ALT_ATTRS:
            val = attr_dict.get(alt_attr, '')
            if val:
                alt = decode_html_entities(val)
                break

        # Поиск изображений в атрибутах
        for attr in IMAGE_ATTRS:
            value = attr_dict.get(attr, '')
            if not value:
                continue
            if attr == "srcset":
                self._parse_srcset(value, f"{tag_lower}_srcset")
                continue
            if is_image_url(value):
                self._add_image(value, alt, f"{tag_lower}_{attr}", attr_dict)

        # link, meta, image
        if tag_lower == "link":
            rel = attr_dict.get('rel', '').lower()
            href = attr_dict.get('href', '')
            if href and is_image_url(href):
                if "icon" in rel or "apple-touch" in rel:
                    pass
                elif "stylesheet" in rel or "font" in rel:
                    pass
                elif "preload" in rel:
                    as_attr = attr_dict.get('as', '').lower()
                    if as_attr == "image":
                        self._add_image(href, alt, "link_preload", attr_dict)
        elif tag_lower == "meta":
            prop = attr_dict.get('property', '').lower()
            name = attr_dict.get('name', '').lower()
            content = attr_dict.get('content', '')
            if content and is_image_url(content):
                if "image" in prop or "image" in name:
                    self._add_image(content, alt, "meta_image", attr_dict)
        elif tag_lower == "image":
            href = attr_dict.get('href', '') or attr_dict.get('xlink:href', '')
            if href and is_image_url(href):
                self._add_image(href, alt, "svg_image", attr_dict)

        # style="..."
        style = attr_dict.get('style', '')
        if style and "url(" in style.lower():
            urls = self._extract_urls_from_css(style)
            role = attr_dict.get('role', '').lower()
            for url in urls:
                s_type = f"{tag_lower}_background"
                if role == "img":
                    s_type = f"{tag_lower}_role_img"
                self._add_image(url, alt, s_type, attr_dict)

        # Начало блока или заголовка
        if tag_lower in HEADING_TAGS:
            self.in_heading = True
            self.heading_tag = tag_lower
        if tag_lower in BLOCK_TAGS:
            self._start_block(tag_lower)

        # script/style – пропустить содержимое
        if tag_lower in ("script", "style"):
            self._skip_until_closing_tag(tag_name)

    def _parse_srcset(self, srcset: str, source_type: str):
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
        """Извлекает url(...) из <style>...</style> и добавляет изображения в корень."""
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
                if is_image_url(url) and not is_icon(url):
                    # Добавляем в корневой блок (без конкретного тега)
                    self.root['elements'].append({
                        'type': 'image',
                        'src': url,
                        'alt': '',
                        'source_type': 'css_style_block'
                    })
            pos = end + 8

    def _extract_urls_from_css(self, css: str) -> list:
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

    def _compute_texts(self, block):
        """Рекурсивно вычисляет полный текст блока (включая дочерние)."""
        parts = []
        for elem in block['elements']:
            if elem['type'] in ('text', 'heading'):
                parts.append(elem['content'])
        for child in block['children']:
            self._compute_texts(child)
            if child['text']:
                parts.append(child['text'])
        block['text'] = ' '.join(parts)

    def _get_attribute(self, attrs_str: str, attr_name: str) -> str:
        # Этот метод больше не используется в основном коде, оставлен для совместимости
        # при необходимости можно удалить.
        pass

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


# ─── Функции сохранения изображений ────────────────────────
def save_image(src: str, output_dir: str, counter: int, base_path: str = None, base_url: str = "", referer: str = None) -> dict:
    src = decode_html_entities(src).strip("'\"")
    if src.startswith("data:"):
        return save_data_url(src, output_dir, counter)
    if src.startswith(("http://", "https://", "//")):
        if src.startswith("//"):
            src = "https:" + src
        return download_url(src, output_dir, counter, referer=referer)
    if src.startswith("/") and not src.startswith("./"):
        if base_url:
            return download_url(base_url.rstrip("/") + src, output_dir, counter, referer=referer)
        return None
    if base_path:
        return copy_local_file(src, output_dir, counter, base_path)
    return None


def save_data_url(data_url: str, output_dir: str, counter: int) -> dict:
    try:
        header, encoded_data = data_url.split(",", 1)
        ext_map = {"png": ".png", "jpeg": ".jpg", "jpg": ".jpg",
                   "gif": ".gif", "webp": ".webp"}
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
        logger.debug(f"  [DATA URL] -> {image_name} ({len(image_bytes)} байт)")
        return {"image_name": image_name, "image_path": os.path.abspath(save_path)}
    except Exception as e:
        logger.warning(f"  [ОШИБКА] Data URL: {e}")
        return None


def download_url(url: str, output_dir: str, counter: int, referer: str = None) -> dict:
    try:
        original_name = url.split("?")[0].split("/")[-1]
        _, ext = os.path.splitext(original_name)
        if not ext or len(ext) > 5:
            ext = ".jpg"
        image_name = f"image_{counter}{ext}"
        save_path = os.path.join(output_dir, image_name)
        logger.debug(f"  [СКАЧИВАНИЕ] {url[:60]}...")
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        if referer:
            headers["Referer"] = referer
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=30) as response:
            image_bytes = response.read()
        with open(save_path, "wb") as f:
            f.write(image_bytes)
        logger.debug(f"  [OK] -> {image_name} ({len(image_bytes)} байт)")
        return {"image_name": image_name, "image_path": os.path.abspath(save_path)}
    except Exception as e:
        logger.warning(f"  [ОШИБКА] {url[:50]}: {e}")
        return None


def copy_local_file(src: str, output_dir: str, counter: int, base_path: str) -> dict:
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
    logger.debug(f"  [OK] {src} -> {image_name} ({size} байт)")
    return {"image_name": image_name, "image_path": os.path.abspath(save_path)}


def save_results_to_json(results, output_dir):
    path = os.path.join(output_dir, "results.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    return path


# ─── Сбор контекста по дереву ──────────────────────────────
def collect_context_from_tree(node, page_url, output_dir, results, counter, last_heading=""):
    """
    Рекурсивно обходит дерево блоков, извлекает изображения с контекстом.
    Возвращает (counter, last_heading).
    """
    # Если узел — заголовок, обновляем last_heading
    if node['tag'] in HEADING_TAGS and node['elements']:
        for elem in node['elements']:
            if elem['type'] == 'heading':
                last_heading = elem['content']
                break

    # Проход по элементам текущего узла
    for i, elem in enumerate(node['elements']):
        if elem['type'] == 'image':
            # Ищем текст перед изображением (соседний элемент)
            text_before = ""
            for j in range(i - 1, -1, -1):
                if node['elements'][j]['type'] == 'text':
                    text_before = node['elements'][j]['content']
                    break
            text_after = ""
            for j in range(i + 1, len(node['elements'])):
                if node['elements'][j]['type'] == 'text':
                    text_after = node['elements'][j]['content']
                    break

            # block_text — весь текст текущего блока (уже вычислен рекурсивно)
            block_text = node.get('text', '')

            counter += 1
            saved = save_image(elem['src'], output_dir, counter, base_url=page_url, referer=page_url)
            if saved:
                results.append({
                    "id": counter,
                    "image_name": saved["image_name"],
                    "image_path": saved["image_path"],
                    "original_src": elem['src'][:200],
                    "source_type": elem.get('source_type', 'unknown'),
                    "alt": elem.get('alt', ''),
                    "text_before": text_before,
                    "text_after": text_after,
                    "block_text": block_text,
                    "heading": last_heading,
                    "page_url": page_url,
                })

    # Рекурсивный обход дочерних блоков
    for child in node['children']:
        counter, last_heading = collect_context_from_tree(
            child, page_url, output_dir, results, counter, last_heading
        )
    return counter, last_heading


def parse_html_content(html_content: str, output_dir: str, base_url: str = "") -> list:
    logger.info("=" * 60)
    logger.info("  HTML ПАРСЕР (древовидный контекст)")
    logger.info("=" * 60)
    if base_url:
        logger.info(f"Base URL: {base_url}")

    os.makedirs(output_dir, exist_ok=True)
    parser = HtmlParser(html_content)
    root = parser.parse()

    results = []
    # counter начнётся с 1
    collect_context_from_tree(root, base_url, output_dir, results, 0, "")

    # Пересчитываем id и добавляем общий context
    for idx, r in enumerate(results, start=1):
        r['id'] = idx
        parts = [r['heading'], r['text_before'], r['block_text'], r['alt'], r['text_after']]
        r['context'] = " | ".join(filter(None, parts))

    if results:
        json_path = save_results_to_json(results, output_dir)
        logger.info(f"📄 JSON: {json_path}")

    return results


# Для CLI-совместимости
def parse_html_file(html_path, output_dir="output", base_url=""):
    html_content = read_html_file(html_path)
    return parse_html_content(html_content, output_dir, base_url)


def print_results(results):
    logger.info(f"\n{'='*60}")
    logger.info(f"  РЕЗУЛЬТАТ: {len(results)} уникальных картинок")
    logger.info(f"{'='*60}\n")
    for r in results:
        logger.info(f"[{r['id']}] 📷 {r['image_name']}  ({r['source_type']})")
        logger.info(f"    Alt:         {r['alt'][:50] if r['alt'] else '(пусто)'}")
        logger.info(f"    Heading:     {r['heading'][:50] if r['heading'] else '(нет)'}")
        logger.info(f"    Блок ДО:     {r['text_before'][:60] if r['text_before'] else '(пусто)'}")
        logger.info(f"    Блок ПОСЛЕ:  {r['text_after'][:60] if r['text_after'] else '(пусто)'}")
        logger.info(f"    Block text:  {r['block_text'][:80] if r['block_text'] else '(пусто)'}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    if len(sys.argv) < 2:
        print("Использование:")
        print("  python html_parser.py <файл.html> [папка] [base_url]")
        sys.exit(0)
    html_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "output"
    base_url = sys.argv[3] if len(sys.argv) > 3 else ""
    results = parse_html_file(html_path, output_dir, base_url)
    print_results(results)
    if results:
        logger.info(f" Картинки: {output_dir}/")
