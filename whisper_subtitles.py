import sys
from pathlib import Path
import shutil
import logging
from tqdm import tqdm

# Задержка для просмотра вывода при запуске через двойной клик
if sys.platform == "win32":
    input("Нажмите Enter, чтобы начать...")

# Диагностика интерпретатора Python
print(f"[*] Используемый Python: {sys.executable}")
print(f"[*] Версия Python: {sys.version}")

# Проверка зависимостей
try:
    import whisper
    print("[*] Библиотека openai-whisper успешно импортирована")
except ImportError as e:
    print(f"[!] Ошибка импорта openai-whisper: {e}")
    print("Установите библиотеку в текущей среде:")
    print("pip install -U openai-whisper")
    if sys.platform == "win32":
        input("\nНажмите Enter для выхода...")
    sys.exit(1)

try:
    import torch
    print("[*] Библиотека torch успешно импортирована")
except ImportError as e:
    print(f"[!] Ошибка импорта torch: {e}")
    print("Установите библиотеку в текущей среде:")
    print("pip install -U torch")
    if sys.platform == "win32":
        input("\nНажмите Enter для выхода...")
    sys.exit(1)

# Проверка ffmpeg
if not shutil.which("ffmpeg"):
    print("[!] Ошибка: ffmpeg не найден. Установите ffmpeg и добавьте его в PATH.")
    print("Скачайте с https://ffmpeg.org/download.html")
    if sys.platform == "win32":
        input("\nНажмите Enter для выхода...")
    sys.exit(1)

# --- Конфигурация ---
OUTPUT_DIR_NAME = "transcribed_texts"
SUPPORTED_EXTENSIONS = {
    ".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac",
    ".mp4", ".mov", ".avi", ".mkv", ".webm", ".mpeg", ".mpg"
}
MAX_FILE_SIZE_MB = 1024  # Максимальный размер файла в МБ
SUPPORTED_MODELS = [
    {"name": "tiny", "description": "Самая легкая модель, низкая точность, подходит для слабых ПК"},
    {"name": "base", "description": "Легкая модель, хороший баланс скорости и точности"},
    {"name": "small", "description": "Средняя модель, лучше точность, требует больше ресурсов"},
    {"name": "medium", "description": "Тяжелая модель, высокая точность, медленная на CPU"},
    {"name": "large", "description": "Очень тяжелая модель, высокая точность, для мощных ПК"},
    {"name": "large-v2", "description": "Улучшенная версия large, еще выше точность"},
    {"name": "large-v3",
        "description": "Новейшая модель, максимальная точность, очень ресурсоемкая"}
]

# --- Настройка логирования ---
logging.basicConfig(
    filename="transcription.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    encoding='utf-8'  # Добавляем явное указание кодировки UTF-8
)


def check_model_availability(model_name):
    """Проверяет, существует ли модель в локальном кэше, не загружая её"""
    cache_dir = Path.home() / ".cache" / "whisper"  # Стандартная папка кэша Whisper
    # Возможные файлы модели
    model_files = [f"{model_name}.pt", f"{model_name}.en.pt"]
    for file in model_files:
        if (cache_dir / file).exists():
            return True
    return False


def select_model():
    """Показывает список моделей и позволяет выбрать одну"""
    print("\n--- Доступные модели Whisper ---")
    available_models = []
    for i, model in enumerate(SUPPORTED_MODELS, 1):
        is_available = check_model_availability(model["name"])
        status = "Установлена" if is_available else "Не установлена (будет загружена при выборе)"
        print(f"{i}. {model['name']} - {status}")
        print(f"   Описание: {model['description']}")
        available_models.append(model["name"])

    while True:
        try:
            choice = input("\nВыберите модель (введите номер 1-7): ")
            choice = int(choice)
            if 1 <= choice <= len(SUPPORTED_MODELS):
                return SUPPORTED_MODELS[choice - 1]["name"]
            else:
                print(f"[!] Введите номер от 1 до {len(SUPPORTED_MODELS)}.")
        except ValueError:
            print("[!] Введите корректный номер.")


def create_srt(words, output_filepath):
    """Создает файл субтитров в формате .srt с временными метками на уровне слов"""
    with open(output_filepath, "w", encoding="utf-8") as f:
        for i, word in enumerate(words, 1):
            start_time = word.get("start", 0)
            # Добавляем 0.5 сек, если end отсутствует
            end_time = word.get("end", start_time + 0.5)
            text = word["word"].strip()
            # Форматируем время в формате SRT (чч:мм:сс,миллисекунды)
            start_srt = f"{int(start_time//3600):02d}:{int((start_time % 3600)//60):02d}:{int(start_time % 60):02d},{int((start_time % 1)*1000):03d}"
            end_srt = f"{int(end_time//3600):02d}:{int((end_time % 3600)//60):02d}:{int(end_time % 60):02d},{int((end_time % 1)*1000):03d}"
            f.write(f"{i}\n{start_srt} --> {end_srt}\n{text}\n\n")


def transcribe_files_in_folder(model_name):
    # Определяем директорию скрипта
    try:
        script_path = Path(__file__).resolve()
        script_dir = script_path.parent
    except NameError:
        script_dir = Path.cwd()
        logging.warning("Using current working directory as script directory")

    output_dir = script_dir / OUTPUT_DIR_NAME
    print(f"[*] Директория скрипта: {script_dir}")
    print(f"[*] Папка для результатов: {output_dir}")
    logging.info(
        f"Script directory: {script_dir}, Output directory: {output_dir}")

    # Создаем папку для результатов
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        print(f"[*] Папка '{OUTPUT_DIR_NAME}' готова.")
    except OSError as e:
        print(f"[!] Ошибка создания папки {output_dir}: {e}")
        logging.error(f"Failed to create output directory: {e}")
        return

    # Определяем устройство (GPU или CPU)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[*] Используемое устройство: {device}")
    if device == "cpu":
        print("[!] Внимание: Транскрипция на CPU будет медленнее.")
        if model_name in ["medium", "large", "large-v2", "large-v3"]:
            print(
                f"[!] Модель '{model_name}' может быть очень медленной на CPU.")
    logging.info(f"Using device: {device}")

    # Загружаем модель Whisper
    print(f"[*] Загрузка модели Whisper '{model_name}'...")
    try:
        model = whisper.load_model(model_name, device=device)
        print("[*] Модель успешно загружена.")
        logging.info(f"Model {model_name} loaded successfully")
    except Exception as e:
        print(f"[!] Ошибка загрузки модели: {e}")
        print(
            f"Убедитесь, что модель '{model_name}' поддерживается и есть доступ к интернету для загрузки.")
        logging.error(f"Failed to load model: {e}")
        return

    # Ищем файлы для обработки
    files_to_process = []
    print("\n[*] Поиск поддерживаемых аудио/видео файлов...")
    for item in script_dir.iterdir():
        if item.is_file() and item.suffix.lower() in SUPPORTED_EXTENSIONS:
            file_size_mb = item.stat().st_size / (1024 * 1024)
            if file_size_mb > MAX_FILE_SIZE_MB:
                print(
                    f"  [!] Файл {item.name} слишком большой ({file_size_mb:.2f} МБ). Пропуск.")
                logging.warning(
                    f"Skipped {item.name}: File too large ({file_size_mb:.2f} MB)")
                continue
            files_to_process.append(item)
            print(f"  [+] Найден: {item.name}")

    if not files_to_process:
        print("\n[!] Не найдено поддерживаемых файлов.")
        logging.info("No supported files found")
        return

    print(
        f"\n[*] Начинается транскрипция {len(files_to_process)} файла(ов)...")
    success_count = 0
    fail_count = 0

    # Обрабатываем файлы
    for input_filepath in tqdm(files_to_process, desc="Транскрипция файлов"):
        output_filename = input_filepath.stem + ".txt"
        srt_filename = input_filepath.stem + ".srt"
        output_filepath = output_dir / output_filename
        srt_filepath = output_dir / srt_filename
        print(f"\n--- Обработка: {input_filepath.name} ---")
        logging.info(f"Processing file: {input_filepath.name}")

        try:
            # Транскрипция с временными метками слов
            result = model.transcribe(
                str(input_filepath), verbose=False, word_timestamps=True, language="ru")
            transcribed_text = result["text"]

            # Сохраняем текст
            with open(output_filepath, "w", encoding="utf-8") as f:
                f.write(transcribed_text)
            print(
                f"  [*] Транскрипция сохранена в: {output_dir.name}/{output_filename}")

            # Собираем слова с временными метками
            words = []
            for segment in result["segments"]:
                words.extend(segment.get("words", []))
            if words:
                create_srt(words, srt_filepath)
                print(
                    f"  [*] Субтитры сохранены в: {output_dir.name}/{srt_filename}")
            else:
                print(
                    f"  [!] Не удалось получить временные метки слов для {input_filepath.name}")

            logging.info(
                f"Transcription and SRT saved for {input_filepath.name}")
            success_count += 1

        except Exception as e:
            print(f"  [!] Ошибка транскрипции {input_filepath.name}: {e}")
            logging.error(
                f"Transcription failed for {input_filepath.name}: {e}")
            try:
                with open(output_filepath, "w", encoding="utf-8") as f:
                    f.write(f"Ошибка транскрипции: {e}")
                print(
                    f"  [*] Сообщение об ошибке записано в: {output_dir.name}/{output_filename}")
            except Exception as write_err:
                print(f"  [!] Не удалось записать ошибку: {write_err}")
                logging.error(
                    f"Failed to write error message for {input_filepath.name}: {write_err}")
            fail_count += 1

    print("\n-------------------------------------")
    print(
        f"Завершена обработка. Успешно: {success_count}, С ошибками: {fail_count}")
    print(f"Результаты сохранены в папке: {output_dir.name}")
    logging.info(
        f"Completed. Successful: {success_count}, Failed: {fail_count}")


if __name__ == "__main__":
    print("--- Whisper Subtitles Generator ---")
    print("Запуск генерации субтитров для аудио/видео файлов...")
    print("Для слабых компьютеров используйте 'tiny' или 'base'.")

    # Выбор модели пользователем
    selected_model = select_model()
    transcribe_files_in_folder(selected_model)

    if sys.platform == "win32":
        input("\nНажмите Enter для выхода...")
