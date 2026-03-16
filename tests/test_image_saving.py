import unittest
import sys
import os
import tempfile
import shutil

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from html_parser import save_data_url, copy_local_file

class TestImageSaving(unittest.TestCase):
    """Тестирование сохранения картинок"""
    
    def setUp(self):
        """Эта функция выполняется перед КАЖДЫМ тестом"""
        self.test_dir = tempfile.mkdtemp()
        self.output_dir = os.path.join(self.test_dir, "output")
        os.makedirs(self.output_dir, exist_ok=True)
        print(f"Создана временная папка: {self.test_dir}")
    
    def tearDown(self):
        """Эта функция выполняется после КАЖДОГО теста"""
        shutil.rmtree(self.test_dir)
        print(f"Удалена временная папка")
    
    def test_save_data_url_png(self):
        """Тест 7: Сохранение PNG из Data URL"""
        data_url = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        
        result = save_data_url(data_url, self.output_dir, 1)
        
        self.assertIsNotNone(result)  # Результат не должен быть None
        self.assertEqual(result["image_name"], "image_1.png")
        self.assertTrue(os.path.exists(result["image_path"]))  # Файл должен существовать
        #self.assertEqual(result["source_type"], "data_url")
        
        print(f"✓ test_save_data_url_png пройден, файл: {result['image_name']}")
    
    def test_save_data_url_invalid(self):
        """Тест 8: Некорректный Data URL"""
        data_url = "data:image/png;base64,ЭТО_НЕ_BASE64!!!!"
        
        result = save_data_url(data_url, self.output_dir, 1)
        
        self.assertIsNone(result)  # Должен вернуть None
        print("✓ test_save_data_url_invalid пройден")
    
    def test_copy_local_file(self):
        """Тест 9: Копирование локального файла"""
        test_file = os.path.join(self.test_dir, "test.jpg")
        with open(test_file, "w") as f:
            f.write("Это тестовое содержимое картинки")
        
        result = copy_local_file("test.jpg", self.output_dir, 1, self.test_dir)
        
        self.assertIsNotNone(result)
        self.assertEqual(result["image_name"], "image_1.jpg")
        self.assertTrue(os.path.exists(result["image_path"]))
        
        with open(result["image_path"], "r") as f:
            content = f.read()
        self.assertEqual(content, "Это тестовое содержимое картинки")
        
        print(f"✓ test_copy_local_file пройден, файл скопирован")
    
    def test_copy_local_file_not_found(self):
        """Тест 10: Копирование несуществующего файла"""
        result = copy_local_file("nofile.jpg", self.output_dir, 1, self.test_dir)
        
        self.assertIsNone(result)
        print("✓ test_copy_local_file_not_found пройден")

if __name__ == "__main__":
    unittest.main()