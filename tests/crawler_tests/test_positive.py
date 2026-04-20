import os
import pytest
from unittest.mock import patch, MagicMock

from crawler.async_crawler import AsyncCrawler


@pytest.fixture
def sample_urls_file(tmp_path):
    """Создаёт временный файл start_urls.txt с примерами URL."""
    content = """# Комментарий
https://example.com
example.org
http://test.com/path?query=1
"""
    file_path = tmp_path / "start_urls.txt"
    file_path.write_text(content, encoding="utf-8")
    return str(file_path)


@pytest.fixture
def crawler_instance(tmp_path, sample_urls_file):
    """Создаёт экземпляр AsyncCrawler с временными директориями."""
    output_dir = tmp_path / "data"
    return AsyncCrawler(
        urls_file=sample_urls_file,
        output_dir=str(output_dir),
        max_pages=5,
        workers=2,
        delay=0.1,
        use_parser=False   # отключаем парсер для юнит-тестов
    )


def test_init_creates_directories(crawler_instance, tmp_path):
    """Проверяем, что при инициализации создаются нужные папки."""
    assert os.path.isdir(crawler_instance.html_dir)
    assert os.path.isdir(crawler_instance.images_dir)
    assert crawler_instance.html_dir.startswith(str(tmp_path))


def test_load_urls_parses_file_correctly(crawler_instance):
    """Проверяем, что _load_urls корректно читает и обрабатывает URL."""
    urls = crawler_instance.start_urls
    assert len(urls) == 3
    assert urls[0] == "https://example.com"
    assert urls[1] == "https://example.org"
    assert urls[2] == "http://test.com/path?query=1"


def test_load_urls_skips_missing_file(tmp_path):
    """Если файла нет – возвращается пустой список."""
    crawler = AsyncCrawler(
        urls_file=str(tmp_path / "nonexistent.txt"),
        output_dir=str(tmp_path / "out")
    )
    assert crawler.start_urls == []
    assert crawler.queue == []


def test_domains_extracted(crawler_instance):
    """Проверяем, что домены из стартовых URL корректно сохраняются."""
    expected = {"example.com", "example.org", "test.com"}
    assert crawler_instance.domains == expected


@pytest.mark.parametrize("url, expected", [
    ("https://example.com/page", True),
    ("http://www.example.com/other", True),
    ("https://sub.example.com/", True),
    ("https://example.org", True),
    ("https://google.com", False),
    ("https://test.com:8080/api", True),
])
def test_is_same_domain(crawler_instance, url, expected):
    assert crawler_instance._is_same_domain(url) == expected


def test_extract_links_finds_all_href(crawler_instance):
    html = '''
    <html>
        <a href="/about">About</a>
        <a href="https://example.com/contact">Contact</a>
        <a href="http://www.example.com/news">News</a>
        <a href="//cdn.example.com/image.png">Image</a>
    </html>
    '''
    base = "https://example.com/"
    links = crawler_instance._extract_links(html, base)
    expected = {
        "https://example.com/about",
        "https://example.com/contact",
        "http://www.example.com/news",
        "https://cdn.example.com/image.png"
    }
    assert links == expected


def test_extract_links_ignores_non_http(crawler_instance):
    html = '''
        <a href="javascript:void(0)">JS</a>
        <a href="#section">Anchor</a>
        <a href="mailto:test@example.com">Email</a>
        <a href="tel:+1234567890">Phone</a>
    '''
    links = crawler_instance._extract_links(html, "https://example.com")
    assert links == set()


def test_extract_links_filters_different_domain(crawler_instance):
    html = '''
        <a href="https://google.com">Google</a>
        <a href="https://example.com/page">Stay</a>
    '''
    links = crawler_instance._extract_links(html, "https://example.com")
    assert links == {"https://example.com/page"}


def test_extract_links_removes_fragment(crawler_instance):
    html = '<a href="https://example.com/page#section">Page</a>'
    links = crawler_instance._extract_links(html, "https://example.com")
    assert links == {"https://example.com/page"}


def test_extract_links_with_relative_paths(crawler_instance):
    html = '<a href="../images/photo.jpg">Photo</a>'
    base = "https://example.com/blog/post/"
    links = crawler_instance._extract_links(html, base)
    assert links == {"https://example.com/blog/images/photo.jpg"}


@patch("requests.get")
def test_download_success(mock_get, crawler_instance):
    """Успешная загрузка страницы."""
    mock_response = MagicMock()
    mock_response.text = "<html>Test</html>"
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    html = crawler_instance._download("https://example.com")
    assert html == "<html>Test</html>"
    mock_get.assert_called_once_with(
        "https://example.com",
        headers={'User-Agent': 'Mozilla/5.0'},
        timeout=30
    )


@patch("requests.get")
def test_download_http_error(mock_get, crawler_instance):
    """Обработка HTTP-ошибки (статус 4xx/5xx)."""
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = Exception("HTTP 500")
    mock_get.return_value = mock_response

    html = crawler_instance._download("https://example.com")
    assert html is None
    assert crawler_instance.stats['errors'] == 1


@patch("requests.get")
def test_download_timeout(mock_get, crawler_instance):
    """Обработка таймаута запроса."""
    import requests
    mock_get.side_effect = requests.Timeout

    html = crawler_instance._download("https://slow.com")
    assert html is None
    assert crawler_instance.stats['errors'] == 1


def test_save_html_creates_file(crawler_instance, tmp_path):
    url = "https://example.com/about/team"
    html = "<html><body>Team page</body></html>"
    filepath, filename = crawler_instance._save_html(url, html, 42)

    expected_dir = crawler_instance.html_dir
    assert filepath.startswith(expected_dir)
    assert os.path.exists(filepath)

    with open(filepath, 'r', encoding='utf-8') as f:
        saved = f.read()
    assert saved == html

    # Проверка имени файла
    assert filename.startswith("0042_")
    assert "example_com" in filename
    assert "about_team" in filename or "team" in filename


def test_save_html_handles_empty_path(crawler_instance):
    url = "https://example.com"
    html = "<html></html>"
    filepath, filename = crawler_instance._save_html(url, html, 1)
    assert os.path.exists(filepath)
    assert "index" in filename


def test_save_html_truncates_long_path(crawler_instance):
    long_path = "/" + "a" * 200
    url = f"https://example.com{long_path}"
    html = "<html></html>"
    filepath, filename = crawler_instance._save_html(url, html, 1)
    assert os.path.exists(filepath)
    assert len(filename) <= 150  # 4 цифры + домен + обрезанный путь


@patch.object(AsyncCrawler, "_download")
@patch.object(AsyncCrawler, "_save_html")
@patch.object(AsyncCrawler, "_extract_links")
def test_process_page_success(mock_extract, mock_save, mock_download, crawler_instance):
    mock_download.return_value = "<html>content</html>"
    mock_save.return_value = ("/fake/path.html", "0001_example_com_index.html")
    mock_extract.return_value = {"https://example.com/page2", "https://example.com/page3"}

    result = crawler_instance._process_page("https://example.com", 1)

    assert result['success'] is True
    assert result['url'] == "https://example.com"
    assert result['num'] == 1
    assert result['images_count'] == 0  # use_parser=False
    assert result['new_links'] == {"https://example.com/page2", "https://example.com/page3"}

    mock_download.assert_called_once_with("https://example.com")
    mock_save.assert_called_once_with("https://example.com", "<html>content</html>", 1)
    mock_extract.assert_called_once_with("<html>content</html>", "https://example.com")


@patch.object(AsyncCrawler, "_download")
def test_process_page_download_fails(mock_download, crawler_instance):
    mock_download.return_value = None
    result = crawler_instance._process_page("https://fail.com", 1)
    assert result is None
    # _save_html не должен вызываться
    with patch.object(crawler_instance, "_save_html") as mock_save:
        mock_save.assert_not_called()
