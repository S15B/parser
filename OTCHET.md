# ОТЧЕТ О ТЕСТИРОВАНИИ ПРОЕКТА "HTML ПАРСЕР"

## ТЕСТОВЫЙ ПЛАН

Объект тестирования: HTML парсер 
Цель: Проверка извлечения изображений из HTML, поддержка локальных файлов, URL, Data URL, а также расширенных возможностей парсера

**Что проверяли:**
- Проверить базовую функциональность парсинга HTML и извлечения тегов <img>
- Протестировать сохранение изображений из разных источников
- Проверить обработку ошибок и граничных случаев
- Обеспечить покрытие новых функций (srcset, CSS, lazy loading, мета-теги)
- Подтвердить стабильность работы на реальных данных


## ПРОЕКТИРОВАНИЕ ТЕСТ-КЕЙСОВ

Разработано **14 тест-кейсов**, покрывающих основную функциональность:

 **Парсер** 
test_parse_text_only - Парсинг обычного текста 
test_parse_single_tag - Парсинг параграфа 
test_parse_img_tag - Извлечение изображения с alt 
test_parse_img_without_alt - Изображение без alt 
test_skip_script - Пропуск script тегов 
test_skip_comments - Пропуск комментариев 
 **Сохранение** 
test_save_data_url_png - Сохранение PNG из Data URL 
test_save_data_url_invalid - Некорректный Data URL 
test_copy_local_file - Копирование локального файла 
 test_copy_local_file_not_found - Обработка отсутствующего файла 
 **Граничные случаи** 
test_empty_html - Пустой HTML 
test_unclosed_tag - Незакрытый тег 
test_unicode_text - Unicode символы 
test_attributes_with_spaces - Пробелы вокруг знака = 


Разработано **18 тест-кейсов**, покрывающих расширенную функциональность:

**Новые способы вставки**
test_srcset_parsing - Парсинг srcset (выбор лучшей картинки)
test_srcset_with_x_descriptors - srcset с 1x, 2x дескрипторами
test_background_css_in_style_attr - Картинка в style="background: url()"
test_style_block_with_urls - Картинки внутри тега <style>
test_svg_image_tag - SVG <image xlink:href>
test_video_poster - <video poster>
test_lazy_loading_attributes - Lazy loading (data-src, data-lazy)
test_input_type_image - <input type="image">
test_link_preload_image - <link rel="preload" as="image">
test_meta_og_image - Open Graph мета-теги (og:image, twitter:image)

**Фильтрация иконок**
test_filter_favicon - favicon.ico не сохраняется
test_filter_small_icons - Маленькие иконки (16x16, 32x32) не сохраняются
test_keep_normal_small_images - Маленькие фото (не иконки) сохраняются

**Декодирование**
test_html_entities - Декодирование HTML-сущностей ( , «)
test_numeric_entities - Числовые сущности (', ")

**Дедупликация**
test_duplicate_urls - Одинаковые URL не дублируются
test_url_normalization - URL с параметрами считаются дубликатами

**Unicode**
test_unicode_text - Текст с Unicode символами (дополнительно)


---

## РАЗРАБОТКА ЮНИТ-ТЕСТОВ

На основе разработанных тест-кейсов были созданы автоматизированные юнит-тесты.

Для удобства поддержки и запуска тесты были организованы в следующую структуру:

tests/
├── __init__.py                    # Маркер пакета Python
├── test_parser.py                  # Тесты для базового парсера (7 тестов)
├── test_image_saving.py            # Тесты для сохранения изображений (4 теста)
├── test_edge_cases.py              # Тесты для граничных случаев (4 теста)
└── test_advanced_features.py       # Тесты для расширенной функциональности (18 тестов)

Для запуска всех тестов создан файл run_tests.py

Все разработанные юнит-тесты полностью покрывают тест-кейсы, описанные в разделе 2. Каждый тест-кейс реализован в виде отдельного тестового метода, что обеспечивает прослеживаемость между требованиями и кодом тестов.


## СТАТИСТИКА ТЕСТИРОВАНИЯ
Всего тестов: 32
Успешно пройдено: 32
Упало: 0


## НАЙДЕННЫЕ ОШИБКИ И БАГИ
В ходе выполнения теста test_attributes_with_spaces выявлена ошибка в работе парсера. Тест проверял ситуацию, когда в атрибутах тега <img> присутствуют пробелы вокруг знака равенства (например, src = "test.jpg" вместо src="test.jpg").

Статус: Закрыт 



