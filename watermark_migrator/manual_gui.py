"""
Minimal manual editor - exactly 3 actions:
  1. Выбрать файл (photo or video, from your computer)
  2. Добавить знак (drops in the one fixed overlay image - drag it and
     resize it with the corner handle onto the watermark by hand)
  3. Готово (burns it in and sends the result to TARGET_CHANNEL)

Login to Telegram (phone/code/2FA password) happens through dialog boxes in
this window, not the console.

Usage:
    python -m watermark_migrator.manual_gui
"""
import asyncio
import os
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, simpledialog

from PIL import Image, ImageTk

from .config import Config, load_config
from .ffmpeg_utils import _run, encode_with_fallback, get_duration, get_video_dimensions
from .telegram_io import make_client, upload_message

PREVIEW_MAX_W = 960
PREVIEW_MAX_H = 600
HANDLE_SIZE = 14

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}

# ---- look & feel ----
BG = "#1e1f29"
PANEL = "#262838"
ACCENT = "#5b8cff"
ACCENT_GREEN = "#3ecf8e"
TEXT = "#eaeaf0"
MUTED = "#9497a8"
FONT = ("Segoe UI", 11)
FONT_BOLD = ("Segoe UI", 12, "bold")
FONT_TITLE = ("Segoe UI", 16, "bold")


def _styled_button(parent, text, command, bg=ACCENT, fg="#0c0d12", state="normal"):
    return tk.Button(
        parent, text=text, command=command, state=state,
        bg=bg, fg=fg, activebackground=bg, activeforeground=fg,
        font=FONT_BOLD, relief="flat", bd=0, padx=16, pady=8,
        cursor="hand2", highlightthickness=0,
    )


class _GuiInput(simpledialog.Dialog):
    """A simpledialog styled to match the app, used for phone/code/password
    and the target channel prompt."""

    def __init__(self, parent, title, prompt, hide=False, default=""):
        self.prompt = prompt
        self.hide = hide
        self.default = default
        self.result_value = None
        super().__init__(parent, title=title)

    def body(self, master):
        master.configure(bg=PANEL)
        tk.Label(master, text=self.prompt, bg=PANEL, fg=TEXT, font=FONT).pack(padx=16, pady=(12, 6))
        self.entry = tk.Entry(
            master, show="*" if self.hide else "", font=FONT, width=30,
            bg="#12131a", fg=TEXT, insertbackground=TEXT, relief="flat",
        )
        if self.default:
            self.entry.insert(0, self.default)
            self.entry.select_range(0, "end")
        self.entry.pack(padx=16, pady=(0, 12), ipady=6)
        return self.entry

    def buttonbox(self):
        box = tk.Frame(self, bg=PANEL)
        _styled_button(box, "OK", self.ok, bg=ACCENT).pack(side="left", padx=8, pady=8)
        _styled_button(box, "Отмена", self.cancel, bg="#3a3c4d", fg=TEXT).pack(side="left", padx=8, pady=8)
        self.bind("<Return>", lambda e: self.ok())
        box.pack()

    def apply(self):
        self.result_value = self.entry.get().strip()


class SimpleOverlayApp:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop_thread, daemon=True).start()
        self.client = None

        self.file_path = None
        self.is_video = False
        self.scale = 1.0
        self.overlay_pil = Image.open(cfg.overlay_image).convert("RGBA")
        self.overlay_box = [20, 20, 160, 80]  # x, y, w, h in canvas pixels
        self._drag = {"mode": None, "x": 0, "y": 0}
        self.busy = False

        self.root = tk.Tk()
        self.root.title("Наложение знака")
        self.root.configure(bg=BG)

        tk.Label(
            self.root, text="Наложение знака", bg=BG, fg=TEXT, font=FONT_TITLE
        ).pack(anchor="w", padx=16, pady=(14, 2))

        self.status_var = tk.StringVar(value="Подключение к Telegram...")
        tk.Label(
            self.root, textvariable=self.status_var, anchor="w",
            bg=BG, fg=MUTED, font=FONT,
        ).pack(fill="x", padx=16, pady=(0, 8))

        canvas_frame = tk.Frame(self.root, bg=PANEL, highlightbackground="#3a3c4d", highlightthickness=1)
        canvas_frame.pack(padx=16, pady=4)
        self.canvas = tk.Canvas(
            canvas_frame, width=PREVIEW_MAX_W, height=PREVIEW_MAX_H, bg="#111219",
            highlightthickness=0,
        )
        self.canvas.pack(padx=2, pady=2)

        btns = tk.Frame(self.root, bg=BG)
        btns.pack(pady=14)
        self.choose_btn = _styled_button(btns, "📂  Выбрать файл", self.on_choose, bg="#3a3c4d", fg=TEXT, state="disabled")
        self.choose_btn.pack(side="left", padx=6)
        self.mark_btn = _styled_button(btns, "➕  Добавить знак", self.on_add_mark, bg=ACCENT, state="disabled")
        self.mark_btn.pack(side="left", padx=6)
        self.done_btn = _styled_button(btns, "✅  Готово (отправить)", self.on_done, bg=ACCENT_GREEN, state="disabled")
        self.done_btn.pack(side="left", padx=6)

        tk.Label(
            self.root, text="Тащите знак мышкой за середину. Тащите за нижний-правый уголок, чтобы изменить размер.",
            bg=BG, fg=MUTED, font=FONT,
        ).pack(pady=(0, 14))

        self.bg_photo = None
        self.overlay_photo = None
        self.overlay_id = None
        self.handle_id = None

        self._run_async(self._connect())
        self.root.mainloop()

    # ---------------- asyncio plumbing ----------------
    def _loop_thread(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _run_async(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def _set_status(self, text: str):
        self.root.after(0, lambda: self.status_var.set(text))

    def _set_busy(self, busy: bool):
        self.busy = busy

        def _apply():
            state = "disabled" if busy else "normal"
            self.choose_btn.config(state=state)
            self.mark_btn.config(state=state if self.file_path else "disabled")
            self.done_btn.config(state=state if self.overlay_id else "disabled")

        self.root.after(0, _apply)

    # ---------------- GUI-based Telegram login ----------------
    def _ask(self, title: str, prompt: str, hide: bool = False, default: str = "") -> str:
        """Called from the background asyncio thread; blocks it (not the UI)
        until the user answers a dialog shown on the main thread."""
        box = {}
        event = threading.Event()

        def show():
            dlg = _GuiInput(self.root, title, prompt, hide=hide, default=default)
            box["value"] = dlg.result_value or ""
            event.set()

        self.root.after(0, show)
        event.wait()
        return box["value"]

    async def _connect(self):
        tgt = self._ask(
            "Канал-приёмник",
            "Куда отправлять готовые файлы (@username или ссылка):",
            default=self.cfg.target_channel,
        )
        if not tgt:
            self._set_status("Канал-приёмник не указан - закройте окно и запустите заново.")
            return
        self.cfg.target_channel = tgt

        self.client = make_client(self.cfg)
        await self.client.start(
            phone=lambda: self._ask("Вход в Telegram", "Номер телефона (с +7...):"),
            code_callback=lambda: self._ask("Вход в Telegram", "Код из Telegram:"),
            password=lambda: self._ask("Вход в Telegram", "Облачный пароль (2FA), если есть:", hide=True),
        )
        self._set_status("Готово. Выберите файл.")
        self.root.after(0, lambda: self.choose_btn.config(state="normal"))

    # ---------------- 1. choose file ----------------
    def on_choose(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(
            title="Выберите фото или видео",
            filetypes=[
                ("Видео и фото", "*.mp4 *.mov *.mkv *.avi *.webm *.jpg *.jpeg *.png *.bmp *.webp"),
                ("Все файлы", "*.*"),
            ],
        )
        if not path:
            return
        self.file_path = path
        self.is_video = os.path.splitext(path)[1].lower() in VIDEO_EXTS
        self.overlay_id = None
        self.handle_id = None
        self._set_status("Загружаю превью...")
        self._set_busy(True)
        self._run_async(self._load_preview())

    async def _load_preview(self):
        try:
            if self.is_video:
                duration = await get_duration(self.cfg, self.file_path)
                frame_path = os.path.join(tempfile.gettempdir(), "wm_preview.jpg")
                await _run([
                    self.cfg.ffmpeg_bin, "-y", "-ss", f"{duration / 2:.2f}",
                    "-i", self.file_path, "-frames:v", "1", "-q:v", "2", frame_path,
                ])
                preview_path = frame_path
            else:
                preview_path = self.file_path
        except Exception as e:
            self._set_status(f"Ошибка чтения файла: {e}")
            self._set_busy(False)
            return
        self.root.after(0, lambda: self._show_preview(preview_path))

    def _show_preview(self, preview_path: str):
        img = Image.open(preview_path)
        scale = min(PREVIEW_MAX_W / img.width, PREVIEW_MAX_H / img.height, 1.0)
        self.scale = scale
        disp = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))))
        self.bg_photo = ImageTk.PhotoImage(disp)
        self.canvas.delete("all")
        self.canvas.config(width=disp.width, height=disp.height)
        self.canvas.create_image(0, 0, anchor="nw", image=self.bg_photo)
        self._set_status("Файл загружен. Нажмите 'Добавить знак'.")
        self._set_busy(False)
        self.root.after(0, lambda: self.mark_btn.config(state="normal"))

    # ---------------- 2. add mark (drag + resize handle) ----------------
    def on_add_mark(self):
        if self.busy or not self.file_path:
            return
        self.overlay_box = [20, 20, 160, 80]
        self._redraw_overlay()
        self._set_status("Разместите знак: тащите за середину (двигать) или за уголок (размер), затем 'Готово'.")
        self.done_btn.config(state="normal")

    def _redraw_overlay(self):
        x, y, w, h = self.overlay_box
        w, h = max(HANDLE_SIZE * 2, int(w)), max(HANDLE_SIZE * 2, int(h))
        self.overlay_box[2], self.overlay_box[3] = w, h
        resized = self.overlay_pil.resize((w, h))
        self.overlay_photo = ImageTk.PhotoImage(resized)

        if self.overlay_id:
            self.canvas.delete(self.overlay_id)
        if self.handle_id:
            self.canvas.delete(self.handle_id)

        self.overlay_id = self.canvas.create_image(int(x), int(y), anchor="nw", image=self.overlay_photo)
        hx, hy = x + w - HANDLE_SIZE, y + h - HANDLE_SIZE
        self.handle_id = self.canvas.create_rectangle(
            hx, hy, hx + HANDLE_SIZE, hy + HANDLE_SIZE,
            fill=ACCENT, outline="white",
        )

        self.canvas.tag_bind(self.overlay_id, "<ButtonPress-1>", self._on_move_press)
        self.canvas.tag_bind(self.overlay_id, "<B1-Motion>", self._on_move_drag)
        self.canvas.tag_bind(self.handle_id, "<ButtonPress-1>", self._on_resize_press)
        self.canvas.tag_bind(self.handle_id, "<B1-Motion>", self._on_resize_drag)

    def _on_move_press(self, event):
        self._drag = {"mode": "move", "x": event.x, "y": event.y}

    def _on_move_drag(self, event):
        dx, dy = event.x - self._drag["x"], event.y - self._drag["y"]
        self.overlay_box[0] += dx
        self.overlay_box[1] += dy
        self._drag["x"], self._drag["y"] = event.x, event.y
        self._redraw_overlay()

    def _on_resize_press(self, event):
        self._drag = {"mode": "resize", "x": event.x, "y": event.y}

    def _on_resize_drag(self, event):
        dx, dy = event.x - self._drag["x"], event.y - self._drag["y"]
        self.overlay_box[2] = max(HANDLE_SIZE * 2, self.overlay_box[2] + dx)
        self.overlay_box[3] = max(HANDLE_SIZE * 2, self.overlay_box[3] + dy)
        self._drag["x"], self._drag["y"] = event.x, event.y
        self._redraw_overlay()

    # ---------------- 3. done ----------------
    def on_done(self):
        if self.busy or not self.file_path or self.overlay_id is None:
            return
        x, y, w, h = self.overlay_box
        bbox = (
            int(x / self.scale), int(y / self.scale),
            int(w / self.scale), int(h / self.scale),
        )
        self._set_busy(True)
        self._set_status("Накладываю и отправляю...")
        self._run_async(self._process_and_send(bbox))

    async def _process_and_send(self, bbox: tuple[int, int, int, int]):
        ext = ".mp4" if self.is_video else (os.path.splitext(self.file_path)[1] or ".png")
        out_path = os.path.join(tempfile.gettempdir(), f"wm_output{ext}")
        try:
            if self.is_video:
                await self._burn_video(self.file_path, out_path, bbox)
            else:
                self._burn_image(self.file_path, out_path, bbox)
            await upload_message(self.client, self.cfg.target_channel, out_path, "")
        except Exception as e:
            self._set_status(f"Ошибка: {e}")
            self._set_busy(False)
            return
        self._set_status("Отправлено! Выберите следующий файл.")
        self.file_path = None
        self.overlay_id = None
        self.root.after(0, lambda: self.canvas.delete("all"))
        self._set_busy(False)

    async def _burn_video(self, input_path: str, output_path: str, bbox: tuple[int, int, int, int]) -> None:
        x, y, w, h = bbox
        frame_w, frame_h = await get_video_dimensions(self.cfg, input_path)
        x = max(0, min(x, frame_w - 1))
        y = max(0, min(y, frame_h - 1))
        w = max(2, min(w, frame_w - x))
        h = max(2, min(h, frame_h - y))
        graph = (
            f"[1:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=0x00000000[badge];"
            f"[0:v][badge]overlay={x}:{y}[masked]"
        )
        await encode_with_fallback(
            self.cfg, ["-i", input_path, "-i", self.cfg.overlay_image], graph, output_path
        )

    def _burn_image(self, input_path: str, output_path: str, bbox: tuple[int, int, int, int]) -> None:
        x, y, w, h = bbox
        base = Image.open(input_path).convert("RGBA")
        w = max(1, min(w, base.width - x))
        h = max(1, min(h, base.height - y))
        sticker = self.overlay_pil.resize((w, h))
        base.paste(sticker, (x, y), sticker)
        base.convert("RGB").save(output_path)


def main():
    cfg = load_config()
    if not cfg.overlay_image:
        raise SystemExit(
            "OVERLAY_IMAGE не задан в .env - укажите путь к PNG со знаком, "
            "который будете накладывать."
        )
    SimpleOverlayApp(cfg)


if __name__ == "__main__":
    main()
