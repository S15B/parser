import unittest
import os
import tempfile
import shutil
from html_parser import parse_html_file, find_text_before, find_text_after

class TestIntegration(unittest.TestCase):
    
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.output_dir = os.path.join(self.test_dir, "output")
        self.html_file = os.path.join(self.test_dir, "test.html")
    
    def tearDown(self):
        shutil.rmtree(self.test_dir)
    
    def create_test_image(self, name, content="test"):
        """Создание тестового изображения"""
        img_path = os.path.join(self.test_dir, name)
        with open(img_path, "w") as f:
            f.write(content)
        return img_path
    
    def test_complete_pipeline_local_images(self):
        """Тест полного цикла с локальными изображениями"""
        # Создаем тестовые изображения
        self.create_test_image("logo.png", "logo content")
        self.create_test_image("photo.jpg", "photo content")
        
        html_content = '''
        <!DOCTYPE html>
        <html>
        <body>
            <h1>Заголовок страницы</h1>
            <p>Текст перед логотипом</p>
            <img src="logo.png" alt="Company Logo">
            <p>Текст между картинками</p>
            <img src="photo.jpg" alt="Vacation Photo">
            <p>Текст после фото</p>
        </body>
        </html>
        '''
        
        with open(self.html_file, "w", encoding="utf-8") as f:
            f.write(html_content)
        
        results = parse_html_file(self.html_file, self.output_dir)
        
        self.assertEqual(len(results), 2)
        
        self.assertEqual(results[0]["original_src"], "logo.png")
        self.assertEqual(results[0]["source_type"], "local")
        self.assertEqual(results[0]["alt"], "Company Logo")
        self.assertEqual(results[0]["text_before"], "Текст перед логотипом")
        self.assertEqual(results[0]["text_after"], "Текст между картинками")
        
        self.assertEqual(results[1]["original_src"], "photo.jpg")
        self.assertEqual(results[1]["source_type"], "local")
        self.assertEqual(results[1]["alt"], "Vacation Photo")
        self.assertEqual(results[1]["text_before"], "Текст между картинками")
        self.assertEqual(results[1]["text_after"], "Текст после фото")
        
        self.assertTrue(os.path.exists(os.path.join(self.output_dir, "image_1.png")))
        self.assertTrue(os.path.exists(os.path.join(self.output_dir, "image_2.jpg")))
    
    def test_complete_pipeline_mixed_sources(self):
        """Тест полного цикла с разными источниками"""
        self.create_test_image("local.png", "local content")
        
        data_url = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        
        html_content = f'''
        <!DOCTYPE html>
        <html>
        <body>
            <p>Локальная картинка:</p>
            <img src="local.png" alt="Local">
            
            <p>Data URL картинка:</p>
            <img src="{data_url}" alt="Data URL">
        </body>
        </html>
        '''
        
        with open(self.html_file, "w", encoding="utf-8") as f:
            f.write(html_content)
        
        results = parse_html_file(self.html_file, self.output_dir)
        
        self.assertEqual(len(results), 2)
        
        source_types = [r["source_type"] for r in results]
        self.assertIn("local", source_types)
        self.assertIn("data_url", source_types)
    
    def test_empty_alt_text(self):
        """Тест обработки пустого alt текста"""
        html_content = '''
        <img src="test.jpg" alt="">
        <img src="test2.jpg">
        '''
        
        with open(self.html_file, "w", encoding="utf-8") as f:
            f.write(html_content)
        
        results = parse_html_file(self.html_file, self.output_dir)
        
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["alt"], "")
        self.assertEqual(results[1]["alt"], "")
    
    def test_no_images(self):
        """Тест HTML без изображений"""
        html_content = '<p>Просто текст без картинок</p>'
        
        with open(self.html_file, "w", encoding="utf-8") as f:
            f.write(html_content)
        
        results = parse_html_file(self.html_file, self.output_dir)
        
        self.assertEqual(len(results), 0)

if __name__ == "__main__":
    unittest.main()