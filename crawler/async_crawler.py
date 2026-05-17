import os
import sys
import time
import re
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from urllib.parse import urljoin, urlparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from html_parser import parse_html_content
    PARSER_AVAILABLE = True
except ImportError:
    PARSER_AVAILABLE = False

logger = logging.getLogger(__name__)

EXCLUDED_EXTENSIONS = {
    '.css', '.js', '.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg',
    '.ico', '.bmp', '.tiff', '.avif',
    '.woff', '.woff2', '.ttf', '.eot', '.otf',
    '.pdf', '.zip', '.rar', '.gz', '.tar', '.mp4', '.mp3', '.avi', '.mov',
    '.xml', '.json', '.rss', '.atom'
}


class AsyncCrawler:
    def __init__(self, urls_file="start_urls.txt", output_dir="../data",
                 max_pages=100, workers=10, delay=0.5, use_parser=True,
                 verbose=False, resume=False):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.urls_file = os.path.join(base_dir, urls_file)
        self.output_dir = os.path.join(base_dir, output_dir)
        self.max_pages = max_pages
        self.workers = workers
        self.delay = delay
        self.use_parser = use_parser and PARSER_AVAILABLE
        self.verbose = verbose

        if self.verbose:
            logger.setLevel(logging.DEBUG)
        else:
            logger.setLevel(logging.WARNING)

        if not PARSER_AVAILABLE:
            logger.warning("⚠️ Парсер не найден")

        self.html_dir = os.path.join(self.output_dir, "crawled_html")
        self.images_dir = os.path.join(self.output_dir, "extracted_images")
        os.makedirs(self.html_dir, exist_ok=True)
        os.makedirs(self.images_dir, exist_ok=True)

        self.queue = []
        self.visited = set()
        self.lock = Lock()

        self.state_file = os.path.join(self.output_dir, "crawler_state.json")

        if resume and os.path.exists(self.state_file):
            self._load_state()
        else:
            self.start_urls = self._load_urls()
            self.queue = self.start_urls.copy()
            self.domains = set()
            for url in self.start_urls:
                domain = urlparse(url).netloc
                domain = re.sub(r'^www\.', '', domain)
                self.domains.add(domain)
            self.visited = set()
            self.stats = {
                'start_urls': len(self.start_urls),
                'domains': list(self.domains),
                'downloaded': 0,
                'images_found': 0,
                'errors': 0,
                'start_time': None,
                'end_time': None
            }

        self.last_request_time = {}
        self.results = []

        if self.verbose:
            logger.info("=" * 60)
            logger.info("  АСИНХРОННЫЙ КРОУЛЕР")
            logger.info("=" * 60)
            logger.info(f"Очередь: {len(self.queue)} URL")
            logger.info(f"Максимум страниц: {max_pages}")
            logger.info(f"Потоков: {workers}")

    def _load_urls(self):
        urls = []
        if not os.path.exists(self.urls_file):
            logger.warning(f"⚠️ Файл {self.urls_file} не найден!")
            return []
        with open(self.urls_file, 'r', encoding='utf-8') as f:
            for line in f:
                url = line.strip()
                if not url or url.startswith('#'):
                    continue
                if not url.startswith(('http://', 'https://')):
                    url = 'https://' + url
                if self._is_page_url(url):
                    urls.append(url)
                else:
                    logger.debug(f"Пропущен статический URL: {url}")
        logger.debug(f"✅ Загружено URL: {len(urls)}")
        return urls

    def _is_page_url(self, url: str) -> bool:
        parsed = urlparse(url)
        path = parsed.path.lower()
        if '.' not in os.path.basename(path):
            return True
        for ext in EXCLUDED_EXTENSIONS:
            if path.endswith(ext):
                return False
        return True

    def _is_same_domain(self, url):
        parsed = urlparse(url)
        domain = re.sub(r'^www\.', '', parsed.netloc)
        for allowed in self.domains:
            if allowed in domain or domain in allowed:
                return True
        return False

    def _wait_for_delay(self, domain):
        with self.lock:
            last = self.last_request_time.get(domain, 0)
            elapsed = time.time() - last
            if elapsed < self.delay:
                time.sleep(self.delay - elapsed)
            self.last_request_time[domain] = time.time()

    def _download(self, url):
        try:
            import requests
            domain = urlparse(url).netloc
            self._wait_for_delay(domain)
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            return response.text
        except Exception as e:
            with self.lock:
                self.stats['errors'] += 1
            logger.warning(f"Ошибка загрузки {url}: {e}")
            return None

    def _extract_links(self, html, url):
        links = set()
        pattern = r'href\s*=\s*["\']([^"\']+)["\']'
        for match in re.finditer(pattern, html):
            link = match.group(1)
            if link.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
                continue
            full = urljoin(url, link)
            if not full.startswith(('http://', 'https://')):
                continue
            full = full.split('#')[0]
            if self._is_same_domain(full) and self._is_page_url(full):
                links.add(full)
        return links

    def _process_page(self, url, num):
        logger.info(f"[{num}] {url[:70]}...")
        html = self._download(url)
        if not html:
            return None

        page_images_dir = os.path.join(self.images_dir, f"page_{num}")
        images_count = 0

        if self.use_parser:
            try:
                parser_logger = logging.getLogger('html_parser')
                parser_logger.setLevel(logging.DEBUG if self.verbose else logging.WARNING)
                results = parse_html_content(html, page_images_dir, base_url=url)
                images_count = len(results) if results else 0
                with self.lock:
                    self.stats['images_found'] += images_count
            except Exception as e:
                logger.error(f"Ошибка парсера: {e}")

        if images_count == 0:
            try:
                os.rmdir(page_images_dir)
            except OSError:
                pass

        new_links = self._extract_links(html, url)
        logger.debug(f"[{num}] Найдено ссылок: {len(new_links)}")

        return {
            'url': url,
            'num': num,
            'new_links': new_links,
            'images_count': images_count,
            'success': True
        }

    def _save_state(self):
        state = {
            'queue': list(self.queue),
            'visited': list(self.visited),
            'domains': list(self.domains),
            'stats': self.stats,
        }
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2, default=str)
        logger.debug(f"Состояние сохранено: {len(self.queue)} в очереди, {len(self.visited)} посещено")

    def _load_state(self):
        with open(self.state_file, 'r', encoding='utf-8') as f:
            state = json.load(f)
        self.queue = state['queue']
        self.visited = set(state['visited'])
        self.domains = set(state['domains'])
        self.stats = state['stats']
        logger.info(f"Возобновлено: очередь {len(self.queue)}, посещено {len(self.visited)}")

    def crawl(self):
        if not self.queue:
            logger.warning("Нет ссылок для обхода!")
            return

        if len(self.visited) >= self.max_pages:
            logger.info(f"Достигнут лимит страниц ({self.max_pages}), обход остановлен.")
            self._print_stats()
            self._export_urls()
            self._export_stats()
            return

        if self.verbose:
            logger.info("\n--- ПАРАЛЛЕЛЬНЫЙ ОБХОД ---\n")
        self.stats['start_time'] = datetime.now()

        page_counter = len(self.visited)  # продолжим нумерацию, если восстанавливаемся
        last_saved = 0

        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            futures = {}

            while self.queue and page_counter < self.max_pages:
                url = self.queue.pop(0)
                if url in self.visited:
                    continue
                page_counter += 1
                self.visited.add(url)
                futures[executor.submit(self._process_page, url, page_counter)] = url

            while futures:
                for future in as_completed(futures):
                    result = future.result()
                    if result and result.get('success'):
                        with self.lock:
                            self.stats['downloaded'] += 1
                            # Сохраняем состояние каждые 10 страниц
                            if self.stats['downloaded'] - last_saved >= 10:
                                self._save_state()
                                last_saved = self.stats['downloaded']

                        added = 0
                        for link in result.get('new_links', []):
                            with self.lock:
                                if link not in self.visited and link not in self.queue and self._is_page_url(link):
                                    self.queue.append(link)
                                    added += 1

                        if self.verbose:
                            logger.info(f"[{result['num']}] ➕ Добавлено: {added}, в очереди: {len(self.queue)}")

                        self.results.append(result)

                    del futures[future]

                    while self.queue and len(futures) < self.workers and page_counter < self.max_pages:
                        new_url = self.queue.pop(0)
                        if new_url not in self.visited:
                            page_counter += 1
                            self.visited.add(new_url)
                            futures[executor.submit(self._process_page, new_url, page_counter)] = new_url

                    if not futures:
                        break
                    break

        self.stats['end_time'] = datetime.now()
        self._save_state()  # финальное сохранение
        if self.verbose:
            self._print_stats()
        self._export_urls()
        self._export_stats()

    def _print_stats(self):
        duration = (self.stats['end_time'] - self.stats['start_time']).total_seconds()
        logger.info("\n" + "=" * 60)
        logger.info("  СТАТИСТИКА")
        logger.info("=" * 60)
        logger.info(f"Скачано страниц: {self.stats['downloaded']}")
        logger.info(f"Найдено изображений: {self.stats['images_found']}")
        logger.info(f"Ошибок: {self.stats['errors']}")
        logger.info(f"Время: {duration:.1f} сек")

    def _export_urls(self):
        urls_file = os.path.join(self.output_dir, "all_found_urls.txt")
        with open(urls_file, 'w', encoding='utf-8') as f:
            f.write("# Все найденные URL\n")
            f.write(f"# Всего: {len(self.visited)}\n\n")
            for url in sorted(self.visited):
                f.write(f"{url}\n")
        logger.info(f"📄 Список URL: {urls_file}")

    def _export_stats(self):
        stats_file = os.path.join(self.output_dir, "crawl_stats.json")
        with open(stats_file, 'w') as f:
            json.dump(self.stats, f, indent=2, default=str)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%H:%M:%S'
    )

    import argparse
    parser = argparse.ArgumentParser(description='Асинхронный веб-кроулер с сохранением состояния')
    parser.add_argument('--max-pages', type=int, default=1, help='Максимальное число страниц')
    parser.add_argument('--workers', type=int, default=2, help='Количество потоков')
    parser.add_argument('--resume', action='store_true', help='Продолжить с последнего сохранения')
    parser.add_argument('--verbose', action='store_true', help='Подробный вывод')
    args = parser.parse_args()

    crawler = AsyncCrawler(
        urls_file="start_urls.txt",
        output_dir="../data",
        max_pages=args.max_pages,
        workers=args.workers,
        delay=0.5,
        use_parser=True,
        verbose=args.verbose,
        resume=args.resume
    )
    crawler.crawl()