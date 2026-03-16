import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from html_parser import HtmlParser

class TestEdgeCases(unittest.TestCase):
    """Тестирование необычных ситуаций"""
    
    def test_empty_html(self):
        """Тест 11: Пустой HTML"""
        parser = HtmlParser("")
        elements = parser.parse()
        
        self.assertEqual(len(elements), 0)
        print("✓ test_empty_html пройден")
    
    def test_unclosed_tag(self):
        """Тест 12: Незакрытый тег"""
        html = '<p>Текст <img src="test.jpg">'
        
        parser = HtmlParser(html)
        elements = parser.parse()
        
        texts = [e for e in elements if e["type"] == "text"]
        images = [e for e in elements if e["type"] == "image"]
        
        self.assertEqual(len(texts), 1)
        self.assertEqual(len(images), 1)
        print("✓ test_unclosed_tag пройден")
    
    def test_unicode_text(self):
        """Тест 13: Текст с Unicode символами"""
        html = '<p>Hello world!</p><img src="test.jpg" alt="Тест">'
        
        parser = HtmlParser(html)
        elements = parser.parse()
        
        texts = [e for e in elements if e["type"] == "text"]
        images = [e for e in elements if e["type"] == "image"]
        
        self.assertEqual(len(texts), 1)
        self.assertEqual(len(images), 1)
        self.assertIn("Hello", texts[0]["content"])
        self.assertEqual(images[0]["alt"], "Тест")
        
        print("✓ test_unicode_text пройден")
    
    def test_attributes_with_spaces(self):
        """Тест 14: Атрибуты с пробелами"""
        html = '<img src = "test.jpg" alt = "Картинка с пробелами">'
        
        parser = HtmlParser(html)
        elements = parser.parse()
        
        self.assertEqual(len(elements), 1)
        self.assertEqual(elements[0]["src"], "test.jpg")
        self.assertEqual(elements[0]["alt"], "Картинка с пробелами")
        
        print("✓ test_attributes_with_spaces пройден")

if __name__ == "__main__":
    unittest.main()