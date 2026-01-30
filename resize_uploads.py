#!/usr/bin/env python3
"""
Скрипт для изменения размера уже загруженных изображений в папке uploads/.
Приводит все изображения к оптимальному размеру для карточки товара (макс. 800px по длинной стороне).
Запуск: python resize_uploads.py
"""
import os
import sys
from PIL import Image

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
IMAGE_MAX_SIZE = 800
IMAGE_JPEG_QUALITY = 85
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


def resize_image_to_optimal(file_path: str) -> bool:
    """Уменьшает изображение до оптимального размера. Возвращает True, если файл изменён."""
    try:
        with Image.open(file_path) as img:
            img.load()
            w, h = img.size
            if w <= IMAGE_MAX_SIZE and h <= IMAGE_MAX_SIZE:
                return False
            if w > h:
                new_w = IMAGE_MAX_SIZE
                new_h = int(h * IMAGE_MAX_SIZE / w)
            else:
                new_h = IMAGE_MAX_SIZE
                new_w = int(w * IMAGE_MAX_SIZE / h)
            resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            ext = os.path.splitext(file_path)[1].lower()
            if ext in (".jpg", ".jpeg"):
                if resized.mode != "RGB":
                    resized = resized.convert("RGB")
                resized.save(file_path, "JPEG", quality=IMAGE_JPEG_QUALITY, optimize=True)
            elif ext == ".png":
                resized.save(file_path, "PNG", optimize=True)
            else:
                if resized.mode != "RGB":
                    resized = resized.convert("RGB")
                resized.save(file_path, "JPEG", quality=IMAGE_JPEG_QUALITY, optimize=True)
            return True
    except Exception as e:
        print(f"  Ошибка: {e}", file=sys.stderr)
        return False


def main():
    if not os.path.isdir(UPLOAD_DIR):
        print(f"Папка {UPLOAD_DIR} не найдена.", file=sys.stderr)
        sys.exit(1)

    count = 0
    resized = 0
    for name in os.listdir(UPLOAD_DIR):
        ext = os.path.splitext(name)[1].lower()
        if ext not in IMAGE_EXTENSIONS:
            continue
        path = os.path.join(UPLOAD_DIR, name)
        if not os.path.isfile(path):
            continue
        count += 1
        print(f"Обработка: {name} ...", end=" ")
        if resize_image_to_optimal(path):
            resized += 1
            print("уменьшено")
        else:
            print("без изменений")

    print(f"\nГотово. Обработано: {count}, изменён размер: {resized}")


if __name__ == "__main__":
    main()
