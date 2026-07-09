"""
Minimal manual editor - exactly 3 actions:
  1. Выбрать файл (photo or video, from your computer)
  2. Добавить знак (drops in the one fixed overlay image - drag/resize it
     onto the watermark by hand)
  3. Готово (burns it in and sends the result to TARGET_CHANNEL)

Usage:
    python -m watermark_migrator.manual_gui
"""
import asyncio
import os
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog

from PIL import Image, ImageTk

from .config import Config, load_config
from .ffmpeg_utils import _run, get_duration, get_video_dimensions
from .telegram_io import make_client, upload_message

PREVIEW_MAX_W = 960
PREVIEW_MAX_H = 600

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}


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
        self._drag = {"x": 0, "y": 0}
        self.busy = False

        self.root = tk.Tk()
        self.root.title("Наложение знака")

        self.status_var = tk.StringVar(value="Подключение к Telegram...")
        tk.Label(self.root, textvariable=self.status_var, anchor="w").pack(fill="x", padx=8, pady=4)

        self.canvas = tk.Canvas(self.root, width=PREVIEW_MAX_W, height=PREVIEW_MAX_H, bg="#222")
        self.canvas.pack(padx=8, pady=4)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-4>", lambda e: self._resize(1.1))
        self.canvas.bind("<Button-5>", lambda e: self._resize(0.9))

        btns = tk.Frame(self.root)
        btns.pack(pady=8)
        self.choose_btn = tk.Button(btns, text="📂 Выбрать файл", command=self.on_choose, state="disabled")
        self.choose_btn.pack(side="left", padx=4)
        self.mark_btn = tk.Button(btns, text="➕ Добавить знак", command=self.on_add_mark, state="disabled")
        self.mark_btn.pack(side="left", padx=4)
        self.done_btn = tk.Button(btns, text="✅ Готово (отправить)", command=self.on_done, state="disabled")
        self.done_btn.pack(side="left", padx=4)

        tk.Label(
            self.root, text="После 'Добавить знак': тащите мышкой, колёсико - размер."
        ).pack(pady=(0, 6))

        self.bg_photo = None
        self.overlay_photo = None
        self.overlay_id = None

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

    async def _connect(self):
        self.client = make_client(self.cfg)
        await self.client.start()
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

    # ---------------- 2. add mark ----------------
    def on_add_mark(self):
        if self.busy or not self.file_path:
            return
        self.overlay_box = [20, 20, 160, 80]
        self._redraw_overlay()
        self._set_status("Перетащите знак на место, колёсико меняет размер, затем 'Готово'.")
        self.done_btn.config(state="normal")

    def _redraw_overlay(self):
        x, y, w, h = self.overlay_box
        w, h = max(8, int(w)), max(8, int(h))
        resized = self.overlay_pil.resize((w, h))
        self.overlay_photo = ImageTk.PhotoImage(resized)
        if self.overlay_id:
            self.canvas.delete(self.overlay_id)
        self.overlay_id = self.canvas.create_image(int(x), int(y), anchor="nw", image=self.overlay_photo)
        self.canvas.tag_bind(self.overlay_id, "<ButtonPress-1>", self._on_press)
        self.canvas.tag_bind(self.overlay_id, "<B1-Motion>", self._on_drag)

    def _on_press(self, event):
        self._drag = {"x": event.x, "y": event.y}

    def _on_drag(self, event):
        dx, dy = event.x - self._drag["x"], event.y - self._drag["y"]
        self.overlay_box[0] += dx
        self.overlay_box[1] += dy
        self._drag = {"x": event.x, "y": event.y}
        self._redraw_overlay()

    def _on_wheel(self, event):
        self._resize(1.1 if event.delta > 0 else 0.9)

    def _resize(self, factor: float):
        if self.overlay_id is None:
            return
        cx = self.overlay_box[0] + self.overlay_box[2] / 2
        cy = self.overlay_box[1] + self.overlay_box[3] / 2
        self.overlay_box[2] *= factor
        self.overlay_box[3] *= factor
        self.overlay_box[0] = cx - self.overlay_box[2] / 2
        self.overlay_box[1] = cy - self.overlay_box[3] / 2
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
            f"[0:v][badge]overlay={x}:{y}[outv]"
        )
        cmd = [
            self.cfg.ffmpeg_bin, "-y",
            "-i", input_path, "-i", self.cfg.overlay_image,
            "-filter_complex", graph, "-map", "[outv]", "-map", "0:a?",
        ]
        if self.cfg.use_gpu:
            cmd += [
                "-c:v", "h264_nvenc", "-preset", self.cfg.nvenc_preset,
                "-rc", "vbr", "-cq", str(self.cfg.nvenc_cq),
            ]
        else:
            cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]
        cmd += ["-c:a", "copy", output_path]

        code, _, err = await _run(cmd)
        if code != 0:
            raise RuntimeError(err.decode(errors="ignore")[-2000:])

    def _burn_image(self, input_path: str, output_path: str, bbox: tuple[int, int, int, int]) -> None:
        x, y, w, h = bbox
        base = Image.open(input_path).convert("RGBA")
        w = max(1, min(w, base.width - x))
        h = max(1, min(h, base.height - y))
        sticker = self.overlay_pil.resize((w, h))
        base.paste(sticker, (x, y), sticker)
        base.convert("RGB").save(output_path)


def _prompt_target_channel(cfg: Config) -> None:
    tgt = input(f"Канал-приёмник [{cfg.target_channel or 'не задан'}]: ").strip()
    if tgt:
        cfg.target_channel = tgt
    if not cfg.target_channel:
        raise SystemExit("Канал-приёмник не указан.")


def main():
    cfg = load_config()
    _prompt_target_channel(cfg)
    if not cfg.overlay_image:
        raise SystemExit(
            "OVERLAY_IMAGE не задан в .env - укажите путь к PNG со знаком, "
            "который будете накладывать."
        )
    SimpleOverlayApp(cfg)


if __name__ == "__main__":
    main()
