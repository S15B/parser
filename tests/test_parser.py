import unittest
import sys
import os


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from html_parser import HtmlParser

class TestHtmlParser(unittest.TestCase):
    """Тестирование базовой функциональности парсера"""
    
    def test_parse_text_only(self):
        """Тест 1: Парсинг обычного текста без тегов"""
        html = "Простой текст без тегов"
        
        parser = HtmlParser(html)
        elements = parser.parse()
        
        self.assertEqual(len(elements), 1)
        self.assertEqual(elements[0]["type"], "text")
        self.assertEqual(elements[0]["content"], "Простой текст без тегов")
        print("✓ test_parse_text_only пройден")
    
    def test_parse_single_tag(self):
        """Тест 2: Парсинг параграфа"""
        html = "<p>Текст в параграфе</p>"
        
        parser = HtmlParser(html)
        elements = parser.parse()
        
        self.assertEqual(len(elements), 1)
        self.assertEqual(elements[0]["type"], "text")
        self.assertEqual(elements[0]["content"], "Текст в параграфе")
        print("✓ test_parse_single_tag пройден")
    
    def test_parse_img_tag(self):
        """Тест 3: Извлечение изображения"""
        html = '<img src="test.jpg" alt="Картинка">'
        
        parser = HtmlParser(html)
        elements = parser.parse()
        
        self.assertEqual(len(elements), 1)
        self.assertEqual(elements[0]["type"], "image")
        self.assertEqual(elements[0]["src"], "test.jpg")
        self.assertEqual(elements[0]["alt"], "Картинка")
        print("✓ test_parse_img_tag пройден")
    
    def test_parse_img_without_alt(self):
        """Тест 4: Изображение без alt"""
        html = '<img src="icon.png">'
        
        parser = HtmlParser(html)
        elements = parser.parse()
        
        self.assertEqual(len(elements), 1)
        self.assertEqual(elements[0]["type"], "image")
        self.assertEqual(elements[0]["src"], "icon.png")
        self.assertEqual(elements[0]["alt"], "")
        print("✓ test_parse_img_without_alt пройден")
    
    def test_skip_script(self):
        """Тест 5: Пропуск script тегов"""
        html = '''
        <script>var x = 10;</script>
        <img src="test.jpg">
        <script>alert("test");</script>
        '''
        
        parser = HtmlParser(html)
        elements = parser.parse()
        
        images = [e for e in elements if e["type"] == "image"]
        self.assertEqual(len(images), 1)
        print("✓ test_skip_script пройден")
    
    def test_skip_comments(self):
        """Тест 6: Пропуск комментариев"""
        html = '''
        <!-- Это комментарий -->
        <img src="photo.jpg">
        <!-- Еще комментарий -->
        '''
        
        parser = HtmlParser(html)
        elements = parser.parse()
        
        images = [e for e in elements if e["type"] == "image"]
        self.assertEqual(len(images), 1)
        print("✓ test_skip_comments пройден")

    def test_attributes_with_spaces(self):
        """Тест: Атрибуты с пробелами"""
        html = '<img src = "test.jpg" alt = "Картинка с пробелами">'
    
        parser = HtmlParser(html)
        elements = parser.parse()
    
        self.assertEqual(len(elements), 1)
        self.assertEqual(elements[0]["src"], "test.jpg")
        self.assertEqual(elements[0]["alt"], "Картинка с пробелами")
    
        print("✓ test_attributes_with_spaces пройден")


if __name__ == "__main__":
    unittest.main()