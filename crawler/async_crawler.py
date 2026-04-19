import os
import sys
import time
import re
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from urllib.parse import urljoin, urlparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from html_parser import parse_html_file
    PARSER_AVAILABLE = True
except ImportError:
    PARSER_AVAILABLE = False
    print("⚠️ Парсер не найден")


class AsyncCrawler:
    def __init__(self, urls_file="start_urls.txt", output_dir="../data", 
                 max_pages=100, workers=10, delay=0.5, use_parser=True, verbose=False):
        
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.urls_file = os.path.join(base_dir, urls_file)
        self.output_dir = os.path.join(base_dir, output_dir)
        self.max_pages = max_pages
        self.workers = workers
        self.delay = delay
        self.use_parser = use_parser and PARSER_AVAILABLE
        
        self.html_dir = os.path.join(self.output_dir, "crawled_html")
        self.images_dir = os.path.join(self.output_dir, "extracted_images")
        os.makedirs(self.html_dir, exist_ok=True)
        os.makedirs(self.images_dir, exist_ok=True)
        
        self.queue = []
        self.visited = set()
        self.lock = Lock()
        
        self.start_urls = self._load_urls()
        self.queue = self.start_urls.copy()
        
        self.domains = set()
        for url in self.start_urls:
            domain = urlparse(url).netloc
            domain = re.sub(r'^www\.', '', domain)
            self.domains.add(domain)
        
        self.last_request_time = {}
        
        self.stats = {
            'start_urls': len(self.start_urls),
            'domains': list(self.domains),
            'downloaded': 0,
            'images_found': 0,
            'errors': 0,
            'start_time': None,
            'end_time': None
        }
        
        self.results = []

        self.verbose = verbose
        if self.verbose:
            print("=" * 60)
            print("  АСИНХРОННЫЙ КРОУЛЕР")
            print("=" * 60)
            print(f"Стартовых ссылок: {len(self.start_urls)}")
            print(f"Максимум страниц: {max_pages}")
            print(f"Потоков: {workers}")
    
    def _load_urls(self):
        urls = []
        if not os.path.exists(self.urls_file):
            print(f"⚠️ Файл {self.urls_file} не найден!")
            return []
        
        with open(self.urls_file, 'r', encoding='utf-8') as f:
            for line in f:
                url = line.strip()
                if not url or url.startswith('#'):
                    continue
                if not url.startswith(('http://', 'https://')):
                    url = 'https://' + url
                urls.append(url)
        
        print(f"✅ Загружено URL: {len(urls)}")
        return urls
    
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
            if self._is_same_domain(full):
                links.add(full)
        return links
    
    def _save_html(self, url, html, num):
        parsed = urlparse(url)
        domain = parsed.netloc.replace('.', '_')
        path = parsed.path.replace('/', '_') if parsed.path else 'index'
        if not path or path == '_':
            path = 'index'
        if len(path) > 100:
            path = path[:100]
        filename = f"{num:04d}_{domain}_{path}.html"
        filepath = os.path.join(self.html_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html)
        return filepath, filename
    
    def _process_page(self, url, num):
        print(f"[{num}] {url[:70]}...")
        html = self._download(url)
        if not html:
            return None
        
        filepath, filename = self._save_html(url, html, num)
        print(f"[{num}] {filename}")
        
        images_count = 0
        if self.use_parser:
            try:
                page_images_dir = os.path.join(self.images_dir, f"page_{num}")
                results = parse_html_file(filepath, page_images_dir, base_url=url)
                images_count = len(results) if results else 0
                with self.lock:
                    self.stats['images_found'] += images_count
            except Exception as e:
                print(f"  Ошибка парсера: {e}")
        
        new_links = self._extract_links(html, url)
        print(f"[{num}] Найдено ссылок: {len(new_links)}")
        
        return {
            'url': url, 
            'num': num, 
            'new_links': new_links, 
            'images_count': images_count,
            'success': True
        }
    
    def crawl(self):
        if not self.queue:
            print("Нет ссылок!")
            return

        if self.verbose:
            print("\n--- ПАРАЛЛЕЛЬНЫЙ ОБХОД ---\n")
        self.stats['start_time'] = datetime.now()
        
        page_counter = 0
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
                        
                        added = 0
                        for link in result.get('new_links', []):
                            with self.lock:
                                if link not in self.visited and link not in self.queue:
                                    self.queue.append(link)
                                    added += 1

                        if self.verbose:
                            print(f"[{result['num']}] ➕ Добавлено: {added}, в очереди: {len(self.queue)}")
                        
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
        if self.verbose:
            self._print_stats()
        self._export_urls()
    
    def _print_stats(self):
        duration = (self.stats['end_time'] - self.stats['start_time']).total_seconds()
        print("\n" + "=" * 60)
        print("  СТАТИСТИКА")
        print("=" * 60)
        print(f"Скачано страниц: {self.stats['downloaded']}")
        print(f"Найдено изображений: {self.stats['images_found']}")
        print(f"Ошибок: {self.stats['errors']}")
        print(f"Время: {duration:.1f} сек")
        print(f"\n📁 HTML: {self.html_dir}/")
        print(f"📁 Изображения: {self.images_dir}/")
    
    def _export_urls(self):
        urls_file = os.path.join(self.output_dir, "all_found_urls.txt")
        with open(urls_file, 'w', encoding='utf-8') as f:
            f.write("# Все найденные URL\n")
            f.write(f"# Всего: {len(self.visited)}\n\n")
            for url in sorted(self.visited):
                f.write(f"{url}\n")
        print(f"📄 Список URL: {urls_file}")



if __name__ == "__main__":
    import sys
    
    max_pages = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    
    crawler = AsyncCrawler(
        urls_file="start_urls.txt",
        output_dir="../data",
        max_pages=max_pages,
        workers=workers,
        delay=0.5,
        use_parser=True
    )
    crawler.crawl()