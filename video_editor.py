import sys
from pathlib import Path
import re
import logging
import tkinter as tk
from tkinter import scrolledtext
from moviepy.editor import VideoFileClip, concatenate_videoclips

# Задержка для просмотра вывода при запуске через двойной клик
if sys.platform == "win32":
    input("Нажмите Enter, чтобы начать...")

# Проверка зависимостей
try:
    from moviepy.editor import VideoFileClip, concatenate_videoclips
    print("[*] Библиотека moviepy успешно импортирована")
except ImportError as e:
    print(f"[!] Ошибка импорта moviepy: {e}")
    print("Установите библиотеку в текущей среде:")
    print("pip install -U moviepy")
    if sys.platform == "win32":
        input("\nНажмите Enter для выхода...")
    sys.exit(1)

# --- Конфигурация ---
SRT_DIR_NAME = "transcribed_texts"
OUTPUT_DIR_NAME = "edited_videos"
SUPPORTED_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov"}

# --- Настройка логирования ---
logging.basicConfig(
    filename="video_edit.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

def parse_srt(srt_filepath):
    """Парсит .srt файл и возвращает список слов с временными метками и текст без меток"""
    words = []
    text = []
    with open(srt_filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()
        i = 0
        while i < len(lines):
            if lines[i].strip().isdigit():  # Номер субтитра
                i += 1
                if i >= len(lines):
                    break
                time_line = lines[i].strip()
                try:
                    start_str, end_str = time_line.split(" --> ")
                    start_time = parse_time(start_str)
                    end_time = parse_time(end_str)
                    i += 1
                    if i >= len(lines):
                        break
                    word = lines[i].strip()
                    if word:  # Пропускаем пустые строки
                        words.append({"start": start_time, "end": end_time, "word": word})
                        text.append(word)
                    i += 1
                except Exception as e:
                    logging.error(f"Ошибка парсинга строки времени в {srt_filepath}: {time_line}, ошибка: {e}")
                    i += 1
                    continue
            else:
                i += 1
    return words, " ".join(text)

def parse_time(time_str):
    """Преобразует время в формате чч:мм:сс,миллисекунды или чч:мм:сс:миллисекунды в секунды"""
    # Удаляем пробелы и нормализуем формат
    time_str = time_str.strip()
    # Заменяем запятую на точку для миллисекунд и убираем лишние двоеточия
    time_str = time_str.replace(",", ".")
    # Используем регулярное выражение для извлечения чч:мм:сс.миллисекунды
    match = re.match(r"(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?", time_str)
    if not match:
        raise ValueError(f"Некорректный формат времени: {time_str}")
    hours, minutes, seconds, milliseconds = match.groups()
    seconds = float(seconds) + (float(f"0.{milliseconds}") if milliseconds else 0)
    return int(hours) * 3600 + int(minutes) * 60 + seconds

def create_srt(words, output_filepath):
    """Создает .srt файл из списка слов с временными метками"""
    with open(output_filepath, "w", encoding="utf-8") as f:
        for i, word in enumerate(words, 1):
            start_time = word["start"]
            end_time = word["end"]
            text = word["word"].strip()
            start_srt = f"{int(start_time//3600):02d}:{int((start_time%3600)//60):02d}:{int(start_time%60):02d},{int((start_time%1)*1000):03d}"
            end_srt = f"{int(end_time//3600):02d}:{int((end_time%3600)//60):02d}:{int(end_time%60):02d},{int((end_time%1)*1000):03d}"
            f.write(f"{i}\n{start_srt} --> {end_srt}\n{text}\n\n")

def edit_text_gui(original_text, callback):
    """Открывает текстовый редактор для редактирования текста"""
    root = tk.Tk()
    root.title("Редактор текста субтитров")
    root.geometry("600x400")

    text_area = scrolledtext.ScrolledText(root, wrap=tk.WORD, width=60, height=20)
    text_area.pack(padx=10, pady=10)
    text_area.insert(tk.END, original_text)

    def on_ok():
        edited_text = text_area.get("1.0", tk.END).strip()
        callback(edited_text)
        root.destroy()

    ok_button = tk.Button(root, text="ОК", command=on_ok)
    ok_button.pack(pady=5)

    root.mainloop()

def compare_texts(original_text, edited_text):
    """Сравнивает исходный и отредактированный текст, возвращает список оставшихся слов"""
    original_words = original_text.split()
    edited_words = edited_text.split()
    kept_indices = []
    j = 0
    for i, orig_word in enumerate(original_words):
        if j < len(edited_words) and orig_word.lower() == edited_words[j].lower():
            kept_indices.append(i)
            j += 1
    return kept_indices

def edit_video(video_filepath, srt_filepath):
    # Определяем директорию скрипта
    try:
        script_path = Path(__file__).resolve()
        script_dir = script_path.parent
    except NameError:
        script_dir = Path.cwd()
        logging.warning("Using current working directory as script directory")

    output_dir = script_dir / OUTPUT_DIR_NAME
    output_dir.mkdir(parents=True, exist_ok=True)

    # Читаем .srt файл
    words, original_text = parse_srt(srt_filepath)
    if not words:
        print(f"[!] Не удалось извлечь слова из {srt_filepath.name}. Проверьте формат .srt файла.")
        logging.error(f"No words extracted from {srt_filepath.name}")
        return
    print(f"[*] Загружено {len(words)} слов из {srt_filepath.name}")

    # Открываем текстовый редактор
    edited_text = [None]
    def set_edited_text(text):
        edited_text[0] = text

    edit_text_gui(original_text, set_edited_text)
    while edited_text[0] is None:
        pass  # Ждем, пока пользователь нажмет ОК

    # Сравниваем исходный и отредактированный текст
    kept_indices = compare_texts(original_text, edited_text[0])
    filtered_words = [words[i] for i in kept_indices]
    print(f"[*] После редактирования осталось {len(filtered_words)} слов")

    # Загружаем видео
    try:
        video = VideoFileClip(str(video_filepath))
        print(f"[*] Видео {video_filepath.name} загружено")
    except Exception as e:
        print(f"[!] Ошибка загрузки видео: {e}")
        logging.error(f"Failed to load video {video_filepath.name}: {e}")
        return

    # Создаем клипы для оставшихся слов
    clips = []
    current_time = 0
    adjusted_words = []
    for word in filtered_words:
        start = word["start"]
        end = word["end"]
        if start >= video.duration:
            continue
        end = min(end, video.duration)
        try:
            clips.append(video.subclip(start, end))
            adjusted_words.append({
                "start": current_time,
                "end": current_time + (end - start),
                "word": word["word"]
            })
            current_time += end - start
        except Exception as e:
            print(f"[!] Ошибка обработки фрагмента {word['word']} ({start}-{end}): {e}")
            logging.error(f"Failed to process clip for {word['word']} ({start}-{end}): {e}")
            continue

    if not clips:
        print(f"[!] Не удалось создать фрагменты для видео {video_filepath.name}")
        logging.error(f"No clips created for {video_filepath.name}")
        video.close()
        return

    # Объединяем клипы
    try:
        final_clip = concatenate_videoclips(clips, method="compose")
        output_video = output_dir / f"edited_{video_filepath.name}"
        final_clip.write_videofile(str(output_video), codec="libx264", audio_codec="aac")
        print(f"[*] Отредактированное видео сохранено в: {output_dir.name}/edited_{video_filepath.name}")
    except Exception as e:
        print(f"[!] Ошибка сохранения видео: {e}")
        logging.error(f"Failed to save edited video: {e}")
        return
    finally:
        video.close()
        for clip in clips:
            clip.close()
        if 'final_clip' in locals():
            final_clip.close()

    # Создаем новый .srt файл
    output_srt = output_dir / f"edited_{srt_filepath.name}"
    create_srt(adjusted_words, output_srt)
    print(f"[*] Обновленный .srt сохранен в: {output_dir.name}/edited_{srt_filepath.name}")
    logging.info(f"Edited video and SRT saved for {video_filepath.name}")

if __name__ == "__main__":
    print("--- Video Editor Based on SRT ---")
    print("Редактирование видео на основе субтитров...")

    # Определяем директорию
    script_dir = Path.cwd()
    srt_dir = script_dir / SRT_DIR_NAME
    video_files = [f for f in script_dir.iterdir() if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS]

    if not video_files:
        print("[!] Видеофайлы не найдены в текущей папке.")
        if sys.platform == "win32":
            input("\nНажмите Enter для выхода...")
        sys.exit(1)

    processed = False
    for video_file in video_files:
        srt_file = srt_dir / f"{video_file.stem}.srt"
        if srt_file.exists():
            print(f"\n[*] Обработка видео: {video_file.name} с субтитрами: {srt_file.name}")
            edit_video(video_file, srt_file)
            processed = True
        else:
            print(f"[!] Файл .srt для {video_file.name} не найден в папке {SRT_DIR_NAME}.")

    if not processed:
        print("[!] Не найдено пар видео и .srt файлов для обработки.")
    
    if sys.platform == "win32":
        input("\nНажмите Enter для выхода...")