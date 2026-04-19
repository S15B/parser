import time
import pytest
import requests
import responses
from unittest.mock import patch
from pytest_httpserver import HTTPServer


from crawler.async_crawler import AsyncCrawler


@pytest.fixture
def temp_data_dir(tmp_path):
    """Создаёт временную директорию для выходных данных тестов."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return data_dir


@pytest.fixture
def start_urls_file(tmp_path):
    """Создаёт временный файл start_urls.txt с тестовым URL."""
    urls_file = tmp_path / "start_urls.txt"
    urls_file.write_text("http://example.com\n", encoding="utf-8")
    return urls_file


@pytest.fixture
def crawler(start_urls_file, temp_data_dir):
    """Возвращает экземпляр AsyncCrawler с настроенными путями."""
    crawler = AsyncCrawler(
        urls_file=str(start_urls_file),
        output_dir=str(temp_data_dir),
        max_pages=5,
        workers=2,
        delay=0.0,
        use_parser=False
    )
    return crawler


@responses.activate
def test_handle_404_not_found(crawler, start_urls_file):
    """Проверяет, что краулер не падает при получении 404 и не добавляет страницу в скачанные."""
    responses.add(
        responses.GET,
        "http://example.com",
        status=404,
        body="Not Found"
    )

    crawler.crawl()

    assert crawler.stats['downloaded'] == 0
    assert crawler.stats['errors'] == 1
    assert len(crawler.visited) == 1
    assert len(crawler.results) == 0\


@responses.activate
def test_handle_500_server_error(crawler, start_urls_file):
    """Проверяет обработку ошибки 500 Internal Server Error."""
    responses.add(
        responses.GET,
        "http://example.com",
        status=500,
        body="Internal Server Error"
    )

    crawler.crawl()

    assert crawler.stats['downloaded'] == 0
    assert crawler.stats['errors'] == 1
    assert len(crawler.results) == 0


@responses.activate
def test_handle_timeout(crawler, start_urls_file):
    """Проверяет, что при превышении таймаута запрос считается ошибкой."""
    def raise_timeout(request):
        raise requests.Timeout("Connection timed out")

    responses.add_callback(
        responses.GET,
        "http://example.com",
        callback=raise_timeout
    )

    crawler.crawl()

    assert crawler.stats['downloaded'] == 0
    assert crawler.stats['errors'] == 1


@responses.activate
def test_handle_connection_error(crawler, start_urls_file):
    """Проверяет обработку ConnectionError (например, DNS не найден)."""
    def raise_connection_error(request):
        raise requests.ConnectionError("Failed to resolve")

    responses.add_callback(
        responses.GET,
        "http://example.com",
        callback=raise_connection_error
    )

    crawler.crawl()

    assert crawler.stats['errors'] == 1
    assert crawler.stats['downloaded'] == 0


@responses.activate
def test_ignore_external_links(crawler, start_urls_file):
    """
    Проверяет, что ссылки на внешние домены не добавляются в очередь.
    Страница содержит ссылку на external.com, краулер не должен по ней идти.
    """
    html_content = """
    <html>
        <a href="http://external.com/page">External Link</a>
        <a href="/internal">Internal Link</a>
    </html>
    """
    responses.add(
        responses.GET,
        "http://example.com",
        body=html_content,
        status=200,
        content_type="text/html"
    )

    crawler.max_pages = 1
    crawler.crawl()

    assert len(crawler.visited) == 1
    assert "http://example.com" in crawler.visited
    assert not any("external.com" in url for url in crawler.queue)


@responses.activate
def test_cycle_detection(crawler, start_urls_file):
    """
    Проверяет, что краулер не зацикливается на страницах,
    которые ссылаются друг на друга (цикл).
    """
    html_a = '<a href="/b">Go to B</a>'
    html_b = '<a href="/a">Go to A</a>'

    responses.add(responses.GET, "http://example.com", body=html_a, status=200)
    responses.add(responses.GET, "http://example.com/b", body=html_b, status=200)

    crawler.max_pages = 5
    crawler.crawl()

    assert len(crawler.visited) == 3
    assert "http://example.com" in crawler.visited
    assert "http://example.com/b" in crawler.visited
    assert len(crawler.queue) == 0


@responses.activate
def test_malformed_html(crawler, start_urls_file):
    """
    Проверяет, что краулер не падает при парсинге битого HTML.
    """
    bad_html = "<html><body><a href='/page2'>>>Unclosed tags and weird stuff"
    responses.add(responses.GET, "http://example.com", body=bad_html, status=200)

    crawler.crawl()

    assert crawler.stats['downloaded'] == 1
    assert len(crawler.visited) == 2


@responses.activate
def test_no_images_on_page(crawler, start_urls_file):
    """
    Проверяет, что краулер корректно обрабатывает страницы без изображений
    (не пытается вызвать парсер или не падает, если парсер отключён).
    """
    html_no_img = "<html><body>No images here</body></html>"
    responses.add(responses.GET, "http://example.com", body=html_no_img, status=200)

    crawler.use_parser = True
    with patch('crawler.async_crawler.parse_html_file') as mock_parser:
        crawler.crawl()
        mock_parser.assert_called_once()
        mock_parser.return_value = []   # нет изображений

    assert crawler.stats['images_found'] == 0
    assert crawler.stats['downloaded'] == 1


@responses.activate
def test_parser_error_handling(crawler, start_urls_file):
    """
    Проверяет, что при возникновении исключения в парсере
    краулер продолжает работу и не прерывает обход.
    """
    html = "<html><img src='image.jpg'></html>"
    responses.add(responses.GET, "http://example.com", body=html, status=200)

    crawler.use_parser = True
    with patch('crawler.async_crawler.parse_html_file', side_effect=Exception("Parser crashed")):
        crawler.crawl()

    assert crawler.stats['downloaded'] == 1
    assert crawler.stats['errors'] == 0
    assert crawler.stats['images_found'] == 0


def test_delay_between_requests(httpserver: HTTPServer, tmp_path, start_urls_file):
    """
    Проверяет, что краулер соблюдает задержку между запросами к одному домену.
    Используем локальный сервер, чтобы контролировать время ответа.
    """
    httpserver.expect_request("/page2").respond_with_data("Page 2", content_type="text/html")

    start_url = httpserver.url_for("/page1")
    start_urls_file.write_text(start_url + "\n", encoding="utf-8")

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    crawler = AsyncCrawler(
        urls_file=str(start_urls_file),
        output_dir=str(data_dir),
        max_pages=2,
        workers=1,
        delay=0.3,
        use_parser=False
    )
    httpserver.expect_request("/page1").respond_with_data(
        '<a href="/page2">Next</a>', content_type="text/html"
    )

    start_time = time.time()
    crawler.crawl()
    elapsed = time.time() - start_time

    assert elapsed >= 0.3
    assert crawler.stats['downloaded'] == 2


def test_redirect_handling(httpserver: HTTPServer, tmp_path, start_urls_file):
    """
    Проверяет, что краулер корректно обрабатывает редиректы (301/302).
    """
    # Настроим редирект с /start на /final
    httpserver.expect_request("/start").respond_with_data(
        "", status=302, headers={"Location": "/final"}
    )
    httpserver.expect_request("/final").respond_with_data(
        "<html>Final page</html>", content_type="text/html"
    )

    start_url = httpserver.url_for("/start")
    start_urls_file.write_text(start_url + "\n", encoding="utf-8")

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    crawler = AsyncCrawler(
        urls_file=str(start_urls_file),
        output_dir=str(data_dir),
        max_pages=1,
        workers=1,
        delay=0,
        use_parser=False
    )

    crawler.crawl()

    assert crawler.stats['downloaded'] == 1
    assert start_url in crawler.visited


def test_empty_start_urls_file(tmp_path):
    """Если файл start_urls.txt пуст, краулер не должен ничего делать."""
    empty_file = tmp_path / "empty.txt"
    empty_file.write_text("", encoding="utf-8")

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    crawler = AsyncCrawler(
        urls_file=str(empty_file),
        output_dir=str(data_dir),
        max_pages=10
    )

    crawler.crawl()
    assert crawler.stats['start_urls'] == 0
    assert crawler.stats['downloaded'] == 0


def test_invalid_url_scheme(crawler, start_urls_file):
    """
    Проверяет, что краулер не падает при URL с неподдерживаемой схемой.
    В конструкторе _load_urls добавляет https://, поэтому ftp:// станет https://ftp://...
    Но при попытке запроса requests вызовет ошибку.
    """
    start_urls_file.write_text("ftp://example.com\n", encoding="utf-8")
    crawler.start_urls = crawler._load_urls()
    crawler.queue = crawler.start_urls.copy()

    with patch('requests.get', side_effect=requests.exceptions.InvalidSchema):
        crawler.crawl()

    assert crawler.stats['errors'] >= 1
    assert crawler.stats['downloaded'] == 0
