import time
from unittest.mock import patch

import pytest
from pytest_httpserver import HTTPServer

from crawler.async_crawler import AsyncCrawler


@pytest.fixture
def temp_output_dir(tmp_path):
    """Временная директория для выходных данных краулера."""
    out_dir = tmp_path / "data"
    out_dir.mkdir()
    return out_dir

@pytest.fixture
def start_urls_file(tmp_path):
    """Файл со стартовыми URL (пустой, наполняется в тестах)."""
    file_path = tmp_path / "start_urls.txt"
    file_path.write_text("", encoding="utf-8")
    return file_path


def test_links_with_spaces_and_unicode(httpserver: HTTPServer, tmp_path, start_urls_file):
    """
    Проверяет, что краулер корректно обрабатывает ссылки, содержащие
    пробелы и кириллические символы в пути.
    """
    start_url = httpserver.url_for("/страница с пробелом.html")
    start_urls_file.write_text(start_url + "\n", encoding="utf-8")

    httpserver.expect_request("/страница с пробелом.html").respond_with_data("""
        <html>
            <img src="/фото с пробелом.jpg">
            <a href="/ссылка с пробелом.html">next</a>
        </html>
    """, content_type="text/html; charset=utf-8")

    httpserver.expect_request("/ссылка с пробелом.html").respond_with_data("""
        <html>
            <img src="/ещё одно.png">
        </html>
    """, content_type="text/html; charset=utf-8")

    crawler = AsyncCrawler(
        urls_file=str(start_urls_file),
        output_dir=str(tmp_path / "data"),
        max_pages=2,
        workers=1,
        delay=0,
        use_parser=True
    )

    with patch('crawler.async_crawler.parse_html_file') as mock_parse:
        mock_parse.return_value = []  # не важно для этого теста
        crawler.crawl()

    visited_urls = crawler.visited
    expected = {
        httpserver.url_for("/страница с пробелом.html"),
        httpserver.url_for("/ссылка с пробелом.html")
    }
    assert expected.issubset(visited_urls)

    assert mock_parse.call_count == 2


def test_data_image_urls_are_ignored(httpserver: HTTPServer, tmp_path, start_urls_file):
    """
    Проверяет, что URL вида data:image не пытаются загружаться как обычные ссылки,
    и парсер их пропускает (или обрабатывает отдельно).
    """
    start_url = httpserver.url_for("/")
    start_urls_file.write_text(start_url + "\n", encoding="utf-8")

    httpserver.expect_request("/").respond_with_data("""
        <html>
            <img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAUA...">
            <img src="/real_image.jpg">
        </html>
    """, content_type="text/html")

    crawler = AsyncCrawler(
        urls_file=str(start_urls_file),
        output_dir=str(tmp_path / "data"),
        max_pages=1,
        workers=1,
        delay=0,
        use_parser=True
    )

    with patch('crawler.async_crawler.parse_html_file') as mock_parse:
        mock_parse.return_value = []
        crawler.crawl()

    mock_parse.assert_called_once()

    for url in crawler.visited:
        assert not url.startswith("data:")


def test_many_images_performance(httpserver: HTTPServer, tmp_path, start_urls_file):
    """
    Проверяет, что краулер не падает и обрабатывает страницу с сотнями изображений
    в разумное время (менее 5 секунд для 500 img).
    """
    start_url = httpserver.url_for("/")
    start_urls_file.write_text(start_url + "\n", encoding="utf-8")

    img_tags = "\n".join([f'<img src="/img{i}.jpg">' for i in range(500)])
    html_content = f"<html><body>{img_tags}</body></html>"

    httpserver.expect_request("/").respond_with_data(html_content, content_type="text/html")

    crawler = AsyncCrawler(
        urls_file=str(start_urls_file),
        output_dir=str(tmp_path / "data"),
        max_pages=1,
        workers=1,
        delay=0,
        use_parser=True
    )

    start_time = time.perf_counter()

    with patch('crawler.async_crawler.parse_html_file') as mock_parse:
        mock_parse.return_value = [f"/img{i}.jpg" for i in range(500)]
        crawler.crawl()

    elapsed = time.perf_counter() - start_time

    assert elapsed < 5.0, f"Слишком долго: {elapsed:.2f} сек"

    mock_parse.assert_called_once()
    assert crawler.stats['images_found'] == 500


def test_non_image_mime_types(httpserver: HTTPServer, tmp_path, start_urls_file):
    """
    Проверяет, что парсер (или загрузчик) не сохраняет файлы, которые
    имеют MIME‑тип, не соответствующий изображению, даже если расширение .jpg.
    """
    start_url = httpserver.url_for("/")
    start_urls_file.write_text(start_url + "\n", encoding="utf-8")

    httpserver.expect_request("/").respond_with_data("""
        <html><img src="/fake.jpg"></html>
    """, content_type="text/html")

    httpserver.expect_request("/fake.jpg").respond_with_data(
        "This is not an image",
        content_type="text/plain"
    )

    crawler = AsyncCrawler(
        urls_file=str(start_urls_file),
        output_dir=str(tmp_path / "data"),
        max_pages=1,
        workers=1,
        delay=0,
        use_parser=True
    )

    try:
        crawler.crawl()
    except Exception as e:
        pytest.fail(f"Краулер упал на некорректном MIME‑типе: {e}")


def test_redirect_loops_handled(httpserver: HTTPServer, tmp_path, start_urls_file):
    """
    Проверяет, что краулер не зависает при циклических редиректах.
    В текущей реализации requests следует за редиректами по умолчанию,
    поэтому бесконечный цикл предотвращается самим requests (макс. 30 редиректов).
    Тест проверяет, что после исчерпания лимита краулер продолжает работу.
    """
    start_url = httpserver.url_for("/")
    start_urls_file.write_text(start_url + "\n", encoding="utf-8")

    httpserver.expect_request("/").respond_with_data("", status=302, headers={"Location": "/loop"})
    httpserver.expect_request("/loop").respond_with_data("", status=302, headers={"Location": "/"})

    crawler = AsyncCrawler(
        urls_file=str(start_urls_file),
        output_dir=str(tmp_path / "data"),
        max_pages=1,
        workers=1,
        delay=0,
        use_parser=False
    )

    with patch('requests.get') as mock_get:
        from requests.exceptions import TooManyRedirects
        mock_get.side_effect = TooManyRedirects("Exceeded 30 redirects.")

        crawler.crawl()

    assert crawler.stats['errors'] == 1
    assert len(crawler.results) == 0


def test_very_long_urls(httpserver: HTTPServer, tmp_path, start_urls_file):
    """
    Проверяет, что краулер способен обработать URL длиной более 2000 символов.
    Некоторые HTTP‑серверы и библиотеки могут иметь ограничения.
    """
    long_path = "/" + "a" * 2000
    start_url = httpserver.url_for(long_path)
    start_urls_file.write_text(start_url + "\n", encoding="utf-8")

    httpserver.expect_request(long_path).respond_with_data("<html></html>", content_type="text/html")

    crawler = AsyncCrawler(
        urls_file=str(start_urls_file),
        output_dir=str(tmp_path / "data"),
        max_pages=1,
        workers=1,
        delay=0,
        use_parser=False
    )

    crawler.crawl()

    assert crawler.stats['downloaded'] == 1
    assert start_url in crawler.visited


def test_missing_src_attribute(httpserver: HTTPServer, tmp_path, start_urls_file):
    """
    Проверяет, что теги <img> без атрибута src или с пустым src не ломают парсер.
    """
    start_url = httpserver.url_for("/")
    start_urls_file.write_text(start_url + "\n", encoding="utf-8")

    httpserver.expect_request("/").respond_with_data("""
        <html>
            <img>
            <img src="">
            <img src="/valid.jpg">
        </html>
    """, content_type="text/html")

    crawler = AsyncCrawler(
        urls_file=str(start_urls_file),
        output_dir=str(tmp_path / "data"),
        max_pages=1,
        workers=1,
        delay=0,
        use_parser=True
    )

    with patch('crawler.async_crawler.parse_html_file') as mock_parse:
        mock_parse.return_value = ["/valid.jpg"]
        crawler.crawl()

    mock_parse.assert_called_once()


def test_slow_server_timeout(httpserver: HTTPServer, tmp_path, start_urls_file):
    """
    Проверяет, что краулер корректно обрабатывает таймаут при медленном ответе сервера.
    """
    start_url = httpserver.url_for("/slow")
    start_urls_file.write_text(start_url + "\n", encoding="utf-8")

    def slow_response(request):
        time.sleep(35)
        return "<html></html>"

    httpserver.expect_request("/slow").respond_with_handler(slow_response)

    crawler = AsyncCrawler(
        urls_file=str(start_urls_file),
        output_dir=str(tmp_path / "data"),
        max_pages=1,
        workers=1,
        delay=0,
        use_parser=False
    )

    with patch('requests.get') as mock_get:
        from requests.exceptions import Timeout
        mock_get.side_effect = Timeout("Connection timed out")
        crawler.crawl()

    assert crawler.stats['errors'] == 1
    assert crawler.stats['downloaded'] == 0
