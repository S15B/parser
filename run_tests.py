import unittest
import sys
import os

if __name__ == "__main__":
    print("=" * 60)
    
    loader = unittest.TestLoader()
    
    test_modules = [
        "tests.test_parser",
        "tests.test_image_saving",
        "tests.test_edge_cases",
        "tests.test_advanced_features"
    ]
    
    suite = unittest.TestSuite()
    
    for module_name in test_modules:
        try:
            module = __import__(module_name, fromlist=['*'])
            suite.addTests(loader.loadTestsFromModule(module))
            print(f"✓ Загружен модуль: {module_name}")
        except Exception as e:
            print(f"✗ Ошибка загрузки {module_name}: {e}")
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print("\n" + "=" * 60)
    print("ИТОГОВАЯ СТАТИСТИКА")
    print("=" * 60)
    print(f"Всего тестов: {result.testsRun}")
    print(f"Успешно: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Упало: {len(result.failures)}")
    print(f"Ошибок: {len(result.errors)}")