import os
import requests

# Используем зеркало
base_url = "https://hf-mirror.com/Salesforce/blip-image-captioning-large/resolve/main"
files = [
    "config.json",
    "pytorch_model.bin",
    "preprocessor_config.json",
    "tokenizer_config.json",
    "vocab.txt",
    "special_tokens_map.json"
]
os.makedirs("blip-local", exist_ok=True)

for filename in files:
    url = f"{base_url}/{filename}"
    print(f"Скачиваю {filename}...")
    response = requests.get(url, stream=True)
    response.raise_for_status()
    with open(f"blip-local/{filename}", "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    print(f"  Готово")

print("Все файлы сохранены в ./blip-local")
