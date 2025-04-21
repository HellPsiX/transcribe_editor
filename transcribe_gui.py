import sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from tkinterdnd2 import TkinterDnD, DND_FILES
import logging
import shutil
import whisper
import torch
from moviepy.editor import VideoFileClip, concatenate_videoclips
from tqdm import tqdm
import re
import os
import subprocess

# --- Конфигурация ---
SRT_DIR_NAME = "transcribed_texts"
OUTPUT_DIR_NAME = "edited_videos"
SUPPORTED_EXTENSIONS = {
    ".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac",
    ".mp4", ".mov", ".avi", ".mkv", ".webm", ".mpeg", ".mpg"
}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov"}
MAX_FILE_SIZE_MB = 1024  # Максимальный размер файла в МБ
SUPPORTED_MODELS = [
    {"name": "tiny", "display": "tiny   75mb (1vram)",
     "description": "Самая легкая модель, низкая точность, подходит для слабых ПК"},
    {"name": "base", "display": "base   142mb (2vram)",
     "description": "Легкая модель, хороший баланс скорости и точности"},
    {"name": "small",
        "display": "small   465mb (4vram)", "description": "Средняя модель, лучше точность, требует больше ресурсов"},
    {"name": "medium",
        "display": "medium   1.5gb (6vram)", "description": "Тяжелая модель, высокая точность, медленная на CPU"},
    {"name": "large", "display": "large   2.9gb (10vram)",
     "description": "Очень тяжелая модель, высокая точность, для мощных ПК"},
    {"name": "large-v2",
        "display": "large-v2   2.9gb (10vram)", "description": "Улучшенная версия large, еще выше точность"},
    {"name": "large-v3",
        "display": "large-v3   2.9gb (10vram)", "description": "Новейшая модель, максимальная точность, очень ресурсоемкая"}
]

# --- Настройка логирования ---
logging.basicConfig(
    filename="transcribe_gui.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    encoding='utf-8'  # Добавляем явное указание кодировки UTF-8
)


def log_message(message, widget=None):
    """Выводит сообщение в лог и в текстовое поле GUI"""
    print(message)
    logging.info(message)
    if widget:
        widget.insert(tk.END, message + "\n")
        widget.see(tk.END)


def check_model_availability(model_name):
    """Проверяет, существует ли модель в локальном кэше"""
    cache_dir = Path.home() / ".cache" / "whisper"
    model_files = [f"{model_name}.pt", f"{model_name}.en.pt"]
    for file in model_files:
        if (cache_dir / file).exists():
            return True
    return False


def create_srt(words, output_filepath):
    """Создает .srt файл из списка слов с временными метками"""
    try:
        with open(output_filepath, "w", encoding="utf-8") as f:
            for i, word in enumerate(words, 1):
                start_time = word.get("start", 0)
                end_time = word.get("end", start_time + 0.5)
                text = word["word"].strip()
                start_srt = f"{int(start_time//3600):02d}:{int((start_time % 3600)//60):02d}:{int(start_time % 60):02d},{int((start_time % 1)*1000):03d}"
                end_srt = f"{int(end_time//3600):02d}:{int((end_time % 3600)//60):02d}:{int(end_time % 60):02d},{int((end_time % 1)*1000):03d}"
                f.write(f"{i}\n{start_srt} --> {end_srt}\n{text}\n\n")
    except Exception as e:
        logging.error(f"Ошибка создания .srt файла {output_filepath}: {e}")
        raise


def transcribe_file(input_filepath, model_name, output_dir, log_widget):
    """Транскрибирует файл и создает .srt и .txt"""
    device = "cuda" if torch.cuda.is_available() else "cpu"
    log_message(f"[*] Используемое устройство: {device}", log_widget)
    if device == "cpu" and model_name in ["medium", "large", "large-v2", "large-v3"]:
        log_message(
            f"[!] Модель '{model_name}' может быть очень медленной на CPU.", log_widget)

    log_message(f"[*] Загрузка модели Whisper '{model_name}'...", log_widget)
    try:
        model = whisper.load_model(model_name, device=device)
        log_message("[*] Модель успешно загружена.", log_widget)
    except Exception as e:
        log_message(f"[!] Ошибка загрузки модели: {e}", log_widget)
        return False

    output_filename = input_filepath.stem + ".txt"
    srt_filename = input_filepath.stem + ".srt"
    output_filepath = output_dir / output_filename
    srt_filepath = output_dir / srt_filename

    log_message(f"\n--- Обработка: {input_filepath.name} ---", log_widget)
    try:
        result = model.transcribe(
            str(input_filepath), verbose=False, word_timestamps=True, language="ru")
        transcribed_text = result["text"]

        with open(output_filepath, "w", encoding="utf-8") as f:
            f.write(transcribed_text)
        log_message(
            f"  [*] Транскрипция сохранена в: {SRT_DIR_NAME}/{output_filename}", log_widget)

        words = []
        for segment in result["segments"]:
            words.extend(segment.get("words", []))
        if words:
            create_srt(words, srt_filepath)
            log_message(
                f"  [*] Субтитры сохранены в: {SRT_DIR_NAME}/{srt_filename}", log_widget)
        else:
            log_message(
                f"  [!] Не удалось получить временные метки слов для {input_filepath.name}", log_widget)

        return True
    except Exception as e:
        log_message(
            f"  [!] Ошибка транскрипции {input_filepath.name}: {e}", log_widget)
        return False


def parse_srt(srt_filepath):
    """Парсит .srt файл и возвращает список слов с временными метками и текст без меток"""
    words = []
    text = []
    with open(srt_filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()
        i = 0
        while i < len(lines):
            if lines[i].strip().isdigit():
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
                    if word:
                        words.append(
                            {"start": start_time, "end": end_time, "word": word})
                        text.append(word)
                    i += 1
                except Exception as e:
                    logging.error(
                        f"Ошибка парсинга строки времени в {srt_filepath}: {time_line}, ошибка: {e}")
                    i += 1
                    continue
            else:
                i += 1
    return words, " ".join(text)


def parse_time(time_str):
    """Преобразует время в формате чч:мм:сс,миллисекунды в секунды"""
    time_str = time_str.strip()
    time_str = time_str.replace(",", ".")
    match = re.match(r"(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?", time_str)
    if not match:
        raise ValueError(f"Некорректный формат времени: {time_str}")
    hours, minutes, seconds, milliseconds = match.groups()
    seconds = float(seconds) + \
        (float(f"0.{milliseconds}") if milliseconds else 0)
    return int(hours) * 3600 + int(minutes) * 60 + seconds


def edit_text_gui(original_text, callback, log_widget, parent):
    """Открывает текстовый редактор для редактирования текста"""
    root = tk.Toplevel(parent)
    root.title("Редактор текста субтитров")
    root.geometry("600x400")
    text_area = scrolledtext.ScrolledText(
        root, wrap=tk.WORD, width=60, height=20)
    text_area.pack(padx=10, pady=10)
    text_area.insert(tk.END, original_text)

    def on_ok():
        edited_text = text_area.get("1.0", tk.END).strip()
        log_message("[*] Текст отредактирован, нажата кнопка ОК", log_widget)
        callback(edited_text)
        root.grab_release()
        root.destroy()

    ok_button = tk.Button(root, text="ОК", command=on_ok)
    ok_button.pack(pady=5)
    root.grab_set()  # Блокируем основное окно
    root.wait_window()  # Ждем закрытия окна


def edit_video(video_filepath, srt_filepath, output_dir, log_widget, parent):
    """Редактирует видео на основе отредактированного текста из .srt"""
    log_message("[*] Начало редактирования видео", log_widget)
    try:
        words, original_text = parse_srt(srt_filepath)
        if not words:
            log_message(
                f"[!] Не удалось извлечь слова из {srt_filepath.name}. Проверьте формат .srt файла.", log_widget)
            return False
        log_message(
            f"[*] Загружено {len(words)} слов из {srt_filepath.name}", log_widget)

        edited_text = [None]

        def set_edited_text(text):
            edited_text[0] = text
            log_message("[*] Получен отредактированный текст", log_widget)

        # Запускаем редактор
        edit_text_gui(original_text, set_edited_text, log_widget, parent)

        # Проверяем, получен ли текст
        if edited_text[0] is None:
            log_message("[!] Редактирование текста не завершено", log_widget)
            return False

        # Проверяем, не пустой ли отредактированный текст
        if not edited_text[0].strip():
            log_message(
                "[!] Отредактированный текст пуст. Оставьте хотя бы одно слово.", log_widget)
            return False

        # Сравниваем тексты
        log_message(
            "[*] Сравнение исходного и отредактированного текста", log_widget)
        try:
            kept_indices = compare_texts(original_text, edited_text[0])
            log_message(
                f"[*] Найдено {len(kept_indices)} совпадений слов", log_widget)
            filtered_words = [words[i] for i in kept_indices]
            log_message(
                f"[*] После редактирования осталось {len(filtered_words)} слов", log_widget)
        except Exception as e:
            log_message(f"[!] Ошибка сравнения текстов: {e}", log_widget)
            return False

        # Проверяем, есть ли слова после редактирования
        if not filtered_words:
            log_message(
                "[!] После редактирования не осталось слов для обработки.", log_widget)
            return False

        # Загружаем видео
        log_message(f"[*] Загрузка видео {video_filepath.name}", log_widget)
        try:
            video = VideoFileClip(str(video_filepath))
            log_message(
                f"[*] Видео {video_filepath.name} загружено, длительность: {video.duration} сек", log_widget)
        except Exception as e:
            log_message(f"[!] Ошибка загрузки видео: {e}", log_widget)
            return False

        # Создаем клипы для оставшихся слов
        clips = []
        current_time = 0
        adjusted_words = []
        log_message("[*] Создание видеофрагментов", log_widget)
        for word in filtered_words:
            start = word["start"]
            end = word["end"]
            if start >= video.duration:
                log_message(
                    f"[!] Пропущен фрагмент {word['word']} (вне длительности видео: {start} > {video.duration})", log_widget)
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
                log_message(
                    f"[!] Ошибка обработки фрагмента {word['word']} ({start}-{end}): {e}", log_widget)
                continue

        if not clips:
            log_message(
                f"[!] Не удалось создать фрагменты для видео {video_filepath.name}", log_widget)
            video.close()
            return False

        # Объединяем клипы
        log_message("[*] Объединение видеофрагментов", log_widget)
        try:
            final_clip = concatenate_videoclips(clips, method="compose")
            output_video = output_dir / f"edited_{video_filepath.name}"
            final_clip.write_videofile(
                str(output_video), codec="libx264", audio_codec="aac")
            log_message(
                f"[*] Отредактированное видео сохранено в: {OUTPUT_DIR_NAME}/edited_{video_filepath.name}", log_widget)
        except Exception as e:
            log_message(f"[!] Ошибка сохранения видео: {e}", log_widget)
            return False
        finally:
            video.close()
            for clip in clips:
                clip.close()
            if 'final_clip' in locals():
                final_clip.close()

        # Создаем новый .srt файл
        log_message("[*] Создание обновленного .srt файла", log_widget)
        try:
            output_srt = output_dir / f"edited_{srt_filepath.name}"
            create_srt(adjusted_words, output_srt)
            log_message(
                f"[*] Обновленный .srt сохранен в: {OUTPUT_DIR_NAME}/edited_{srt_filepath.name}", log_widget)
        except Exception as e:
            log_message(f"[!] Ошибка создания .srt файла: {e}", log_widget)
            return False

        return True
    except Exception as e:
        log_message(f"[!] Общая ошибка редактирования видео: {e}", log_widget)
        return False


def compare_texts(original_text, edited_text):
    """Сравнивает исходный и отредактированный текст, возвращает список оставшихся слов"""
    try:
        original_words = original_text.split()
        edited_words = edited_text.split()
        kept_indices = []
        j = 0
        for i, orig_word in enumerate(original_words):
            if j < len(edited_words) and orig_word.lower() == edited_words[j].lower():
                kept_indices.append(i)
                j += 1
        return kept_indices
    except Exception as e:
        logging.error(f"Ошибка в compare_texts: {e}")
        raise


class TranscribeGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Whisper Video Transcriber")
        self.root.geometry("800x600")

        # Определяем директорию скрипта
        self.script_dir = Path(__file__).parent

        # Переменные
        self.file_path = tk.StringVar()
        self.model_name = tk.StringVar(value="base")

        # №4: Кнопка "?" в правом верхнем углу
        top_frame = tk.Frame(root)
        top_frame.pack(fill=tk.X)
        tk.Label(top_frame, text="Whisper Video Transcriber",
                 font=("Arial", 16)).pack(side=tk.LEFT, pady=10)
        tk.Button(top_frame, text="?", command=self.open_readme).pack(
            side=tk.RIGHT, padx=5, pady=5)

        # Выбор файла
        tk.Label(root, text="Видео/аудио файл:").pack()
        self.file_entry = tk.Entry(root, textvariable=self.file_path, width=50)
        self.file_entry.pack(pady=5)
        tk.Button(root, text="Выбрать файл",
                  command=self.select_file).pack(pady=5)

        # Область для перетаскивания
        self.drop_area = tk.Label(
            root, text="Перетащите файл сюда", relief="sunken", width=50, height=5)
        self.drop_area.pack(pady=10)
        self.drop_area.drop_target_register(DND_FILES)
        self.drop_area.dnd_bind('<<Drop>>', self.drop_file)

        # №3: Выбор модели с информацией о размере и ресурсах
        tk.Label(root, text="Выберите модель Whisper:").pack()
        model_combo = ttk.Combobox(root, textvariable=self.model_name, values=[
                                   m["display"] for m in SUPPORTED_MODELS])
        model_combo.pack(pady=5)

        # Кнопки "Создать субтитры" и "Редактировать видео" (центр)
        main_button_frame = tk.Frame(root)
        main_button_frame.pack(pady=10)
        tk.Button(main_button_frame, text="Создать субтитры",
                  command=self.run_transcription).pack(side=tk.LEFT, padx=5)
        tk.Button(main_button_frame, text="Редактировать видео",
                  command=self.run_editing).pack(side=tk.LEFT, padx=5)

        # №1 и №2: Кнопки "Текст+Субтитры" и "Видео+Субтитры" (справа, вертикально)
        side_button_frame = tk.Frame(root)
        side_button_frame.pack(side=tk.RIGHT, padx=10)
        tk.Button(side_button_frame, text="Текст+Субтитры",
                  command=self.open_transcribed_texts).pack(pady=5)
        tk.Button(side_button_frame, text="Видео+Субтитры",
                  command=self.open_edited_videos).pack(pady=5)

        # Лог вывода
        tk.Label(root, text="Лог:").pack()
        self.log_area = scrolledtext.ScrolledText(
            root, wrap=tk.WORD, width=70, height=8)
        self.log_area.pack(pady=10)

        # Добавляем прогресс-бар
        self.progress_frame = tk.Frame(root)
        self.progress_frame.pack(fill=tk.X, padx=10, pady=5)
        self.progress_label = tk.Label(self.progress_frame, text="")
        self.progress_label.pack()
        self.progress_bar = ttk.Progressbar(
            self.progress_frame, length=300, mode='determinate')
        self.progress_bar.pack()

        # Проверка ffmpeg
        if not shutil.which("ffmpeg"):
            log_message(
                "[!] Ошибка: ffmpeg не найден. Установите ffmpeg и добавьте его в PATH.", self.log_area)
            messagebox.showerror(
                "Ошибка", "ffmpeg не найден. Установите ffmpeg и добавьте его в PATH.")
            sys.exit(1)

    def select_file(self):
        file_paths = filedialog.askopenfilenames(
            filetypes=[("Media files", list(SUPPORTED_EXTENSIONS))])
        if file_paths:
            # Сохраняем все пути через разделитель |
            self.file_path.set('|'.join(file_paths))
            for path in file_paths:
                log_message(
                    f"[*] Выбран файл: {Path(path).name}", self.log_area)

    def drop_file(self, event):
        file_paths = event.data
        # Разбиваем строку с путями на список
        paths = [p.strip('{}') for p in file_paths.split('} {')]

        valid_files = []
        for file_path in paths:
            try:
                path = Path(file_path)
                if path.exists() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                    valid_files.append(str(path.resolve()))
                    log_message(
                        f"[*] Добавлен файл: {path.name}", self.log_area)
            except Exception as e:
                log_message(
                    f"[!] Ошибка обработки файла {file_path}: {e}", self.log_area)

        if valid_files:
            # Сохраняем все пути через разделитель |
            self.file_path.set('|'.join(valid_files))
        else:
            log_message(
                "[!] Нет подходящих файлов для обработки.", self.log_area)

    def open_transcribed_texts(self):
        file_path = self.file_path.get()
        if not file_path:
            log_message("[!] Сначала выберите файл.", self.log_area)
            messagebox.showwarning("Предупреждение", "Сначала выберите файл.")
            return
        transcribed_dir = Path(file_path.split('|')[0]).parent / SRT_DIR_NAME
        if transcribed_dir.exists():
            if sys.platform == "win32":
                os.startfile(transcribed_dir)
            else:
                opener = "open" if sys.platform == "darwin" else "xdg-open"
                subprocess.run([opener, str(transcribed_dir)])
        else:
            log_message(f"[!] Папка {SRT_DIR_NAME} не найдена.", self.log_area)
            messagebox.showwarning(
                "Предупреждение", f"Папка {SRT_DIR_NAME} не найдена.")

    def open_edited_videos(self):
        file_path = self.file_path.get()
        if not file_path:
            log_message("[!] Сначала выберите файл.", self.log_area)
            messagebox.showwarning("Предупреждение", "Сначала выберите файл.")
            return
        edited_dir = Path(file_path.split('|')[0]).parent / OUTPUT_DIR_NAME
        if edited_dir.exists():
            if sys.platform == "win32":
                os.startfile(edited_dir)
            else:
                opener = "open" if sys.platform == "darwin" else "xdg-open"
                subprocess.run([opener, str(edited_dir)])
        else:
            log_message(
                f"[!] Папка {OUTPUT_DIR_NAME} не найдена.", self.log_area)
            messagebox.showwarning(
                "Предупреждение", f"Папка {OUTPUT_DIR_NAME} не найдена.")

    def open_readme(self):
        readme_path = self.script_dir / "README.txt"
        if readme_path.exists():
            if sys.platform == "win32":
                os.startfile(readme_path)
            else:
                opener = "open" if sys.platform == "darwin" else "xdg-open"
                subprocess.run([opener, str(readme_path)])
        else:
            log_message("[!] Файл README.txt не найден.", self.log_area)
            messagebox.showwarning(
                "Предупреждение", "Файл README.txt не найден.")

    def run_transcription(self):
        file_paths = self.file_path.get().split('|')
        if not file_paths or not file_paths[0]:
            log_message("[!] Выберите файлы для обработки.", self.log_area)
            messagebox.showwarning(
                "Предупреждение", "Выберите файлы для обработки.")
            return

        # Получаем модель
        selected_model = self.model_name.get().split()[0]
        total_files = len(file_paths)

        for i, file_path in enumerate(file_paths, 1):
            input_filepath = Path(file_path)
            if not input_filepath.exists():
                continue

            # Обновляем прогресс
            progress = (i - 1) / total_files * 100
            self.progress_bar['value'] = progress
            self.progress_label.config(
                text=f"Обработка файла {i} из {total_files}: {input_filepath.name}")
            self.root.update()

            # Проверка размера файла
            file_size_mb = input_filepath.stat().st_size / (1024 * 1024)
            if file_size_mb > MAX_FILE_SIZE_MB:
                log_message(
                    f"[!] Файл {input_filepath.name} слишком большой ({file_size_mb:.2f} МБ).", self.log_area)
                continue

            output_dir = input_filepath.parent / SRT_DIR_NAME
            output_dir.mkdir(parents=True, exist_ok=True)

            log_message(
                f"[*] Начинается транскрипция файла {input_filepath.name}...", self.log_area)
            success = transcribe_file(
                input_filepath, selected_model, output_dir, self.log_area)

            if success:
                log_message(
                    f"[*] Транскрипция файла {input_filepath.name} завершена.", self.log_area)
            else:
                log_message(
                    f"[!] Ошибка транскрипции файла {input_filepath.name}.", self.log_area)

        # Завершаем прогресс
        self.progress_bar['value'] = 100
        self.progress_label.config(text="Обработка завершена")
        self.root.update()

        messagebox.showinfo("Успех", "Обработка всех файлов завершена.")

    def run_editing(self):
        file_path = self.file_path.get()
        if not file_path or not Path(file_path).exists():
            log_message("[!] Выберите файл для обработки.", self.log_area)
            messagebox.showwarning(
                "Предупреждение", "Выберите файл для обработки.")
            return

        input_filepath = Path(file_path)
        if input_filepath.suffix.lower() not in VIDEO_EXTENSIONS:
            log_message(
                "[!] Файл должен быть видео (mp4, mkv, avi, mov).", self.log_area)
            messagebox.showwarning(
                "Предупреждение", "Файл должен быть видео (mp4, mkv, avi, mov).")
            return

        srt_filepath = input_filepath.parent / \
            SRT_DIR_NAME / f"{input_filepath.stem}.srt"
        if not srt_filepath.exists():
            log_message(
                f"[!] Файл .srt для {input_filepath.name} не найден в папке {SRT_DIR_NAME}.", self.log_area)
            messagebox.showwarning(
                "Предупреждение", f"Файл .srt для {input_filepath.name} не найден.")
            return

        output_dir = input_filepath.parent / OUTPUT_DIR_NAME
        output_dir.mkdir(parents=True, exist_ok=True)

        log_message(
            f"[*] Начинается редактирование видео {input_filepath.name}...", self.log_area)
        success = edit_video(input_filepath, srt_filepath,
                             output_dir, self.log_area, self.root)
        if success:
            log_message(f"[*] Редактирование завершено.", self.log_area)
            messagebox.showinfo(
                "Успех", f"Отредактированное видео и .srt сохранены в {OUTPUT_DIR_NAME}.")
        else:
            log_message(f"[!] Ошибка редактирования.", self.log_area)
            messagebox.showerror(
                "Ошибка", "Не удалось выполнить редактирование.")


if __name__ == "__main__":
    root = TkinterDnD.Tk()
    app = TranscribeGUI(root)
    root.mainloop()
