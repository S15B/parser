import unittest
import sys
import os
import time
from datetime import datetime

def run_all_tests():
    """Запускает все тесты и показывает статистику"""
    
    print("=" * 60)
    print("ЗАПУСК ТЕСТОВ HTML ПАРСЕРА")
    print("=" * 60)
    print(f"Время запуска: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Находим все тесты в папке tests
    loader = unittest.TestLoader()
    suite = loader.discover('tests')
    
    # Запускаем тесты
    runner = unittest.TextTestRunner(verbosity=2)
    start_time = time.time()
    result = runner.run(suite)
    end_time = time.time()
    
    # Статистика
    print("\n" + "=" * 60)
    print("СТАТИСТИКА ТЕСТИРОВАНИЯ")
    print("=" * 60)
    print(f"Тестов запущено: {result.testsRun}")
    print(f"Успешно: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Упало: {len(result.failures)}")
    print(f"Ошибок: {len(result.errors)}")
    print(f"Время выполнения: {end_time - start_time:.2f} секунд")
    
    # Если есть упавшие тесты, показываем их
    if result.failures:
        print("\nУПАВШИЕ ТЕСТЫ:")
        for i, failure in enumerate(result.failures, 1):
            test_name = failure[0].id().split('.')[-1]
            print(f"  {i}. {test_name}")
    
    # Сохраняем результаты в файл
    with open("test_results.txt", "w") as f:
        f.write(f"Результаты тестирования {datetime.now()}\n")
        f.write(f"Всего тестов: {result.testsRun}\n")
        f.write(f"Успешно: {result.testsRun - len(result.failures) - len(result.errors)}\n")
        f.write(f"Упало: {len(result.failures)}\n")
        f.write(f"Ошибок: {len(result.errors)}\n")
    
    print(f"\nРезультаты сохранены в test_results.txt")
    
    return result

if __name__ == "__main__":
    run_all_tests()