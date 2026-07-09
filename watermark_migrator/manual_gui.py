"""
Manual placement mode: you drag/resize the overlay sticker over a preview
frame of each video yourself, click "Готово", and the program burns it in
at exactly that spot for the whole video and uploads the result to
TARGET_CHANNEL - then automatically loads the next unprocessed video.

Usage:
    python -m watermark_migrator.manual_gui
"""
import asyncio
import os
import shutil
import threading
import tkinter as tk

from PIL import Image, ImageTk

from .config import Config, load_config, prompt_for_channels
from .db import StateDB
from .ffmpeg_utils import _run, clean_watermark, get_duration, get_video_dimensions
from .pipeline import ProcessResult, publish_one
from .telegram_io import download_media, iter_source_messages, make_client
from .text_rules import load_brand_terms

PREVIEW_MAX_W = 960
PREVIEW_MAX_H = 600


class ManualOverlayApp:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.brand_terms = load_brand_terms(cfg.brand_terms_path)
        self.db = StateDB(cfg.db_path)

        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop_thread, daemon=True).start()

        self.client = None
        self.messages: list = []
        self.msg_pos = 0
        self.busy = False

        self.video_path = None
        self.scale = 1.0
        self.overlay_pil = None
        self.overlay_box = [20, 20, 160, 80]  # x, y, w, h in *canvas* pixels
        self._drag = {"x": 0, "y": 0}

        self.root = tk.Tk()
        self.root.title("Ручное наложение стикера")

        self.status_var = tk.StringVar(value="Подключение к Telegram...")
        tk.Label(self.root, textvariable=self.status_var, anchor="w").pack(fill="x", padx=8, pady=4)

        self.canvas = tk.Canvas(self.root, width=PREVIEW_MAX_W, height=PREVIEW_MAX_H, bg="#222")
        self.canvas.pack(padx=8, pady=4)
        self.canvas.bind("<MouseWheel>", self._on_wheel)       # Windows/macOS
        self.canvas.bind("<Button-4>", lambda e: self._resize(1.1))   # Linux scroll up
        self.canvas.bind("<Button-5>", lambda e: self._resize(0.9))   # Linux scroll down

        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=8)
        self.done_btn = tk.Button(
            btn_frame, text="✅ Готово (наложить и отправить)", command=self.on_done
        )
        self.done_btn.pack(side="left", padx=4)
        self.skip_btn = tk.Button(btn_frame, text="⏭ Пропустить", command=self.on_skip)
        self.skip_btn.pack(side="left", padx=4)
        tk.Label(
            self.root,
            text="Тащите стикер мышкой, крутите колёсико чтобы изменить размер.",
        ).pack(pady=(0, 6))

        self.bg_image_id = None
        self.bg_photo = None
        self.overlay_id = None
        self.overlay_photo = None

        self._run_async(self._startup())
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
        state = "disabled" if busy else "normal"
        self.root.after(0, lambda: (self.done_btn.config(state=state), self.skip_btn.config(state=state)))

    # ---------------- startup / queue ----------------
    async def _startup(self):
        self.client = make_client(self.cfg)
        await self.client.start()
        self._set_status("Загружаю список видео из канала-источника...")
        self.messages = [
            m async for m in iter_source_messages(self.client, self.cfg.source_channel)
            if m.video is not None
        ]
        self.root.after(0, self._advance)

    def _advance(self):
        while self.msg_pos < len(self.messages) and self.db.is_done(self.messages[self.msg_pos].id):
            self.msg_pos += 1
        if self.msg_pos >= len(self.messages):
            self.status_var.set("Готово - необработанных видео больше нет.")
            return
        self._set_busy(True)
        self._set_status(f"Скачиваю видео {self.msg_pos + 1}/{len(self.messages)}...")
        self._run_async(self._load_current())

    async def _load_current(self):
        msg = self.messages[self.msg_pos]
        job_dir = os.path.join(self.cfg.work_dir, str(msg.id))
        os.makedirs(job_dir, exist_ok=True)
        raw_path = os.path.join(job_dir, "raw.mp4")
        try:
            await download_media(self.client, msg, raw_path)
            duration = await get_duration(self.cfg, raw_path)
            frame_path = os.path.join(job_dir, "preview.jpg")
            await _run([
                self.cfg.ffmpeg_bin, "-y", "-ss", f"{duration / 2:.2f}", "-i", raw_path,
                "-frames:v", "1", "-q:v", "2", frame_path,
            ])
            self.video_path = raw_path
        except Exception as e:
            self._set_status(f"Ошибка загрузки: {e}")
            self._set_busy(False)
            return
        self.root.after(0, lambda: self._show_preview(frame_path))

    # ---------------- preview / overlay ----------------
    def _show_preview(self, frame_path: str):
        img = Image.open(frame_path)
        scale = min(PREVIEW_MAX_W / img.width, PREVIEW_MAX_H / img.height, 1.0)
        self.scale = scale
        disp = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))))
        self.bg_photo = ImageTk.PhotoImage(disp)
        self.canvas.delete("all")
        self.canvas.config(width=disp.width, height=disp.height)
        self.bg_image_id = self.canvas.create_image(0, 0, anchor="nw", image=self.bg_photo)

        self.overlay_pil = Image.open(self.cfg.overlay_image).convert("RGBA")
        if self.overlay_box[2] <= 0:
            self.overlay_box = [20, 20, 160, 80]
        self._redraw_overlay()
        self._set_status(
            f"Видео {self.msg_pos + 1}/{len(self.messages)} - разместите стикер и нажмите Готово"
        )
        self._set_busy(False)

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
        cx = self.overlay_box[0] + self.overlay_box[2] / 2
        cy = self.overlay_box[1] + self.overlay_box[3] / 2
        self.overlay_box[2] *= factor
        self.overlay_box[3] *= factor
        self.overlay_box[0] = cx - self.overlay_box[2] / 2
        self.overlay_box[1] = cy - self.overlay_box[3] / 2
        self._redraw_overlay()

    # ---------------- actions ----------------
    def on_skip(self):
        if self.busy:
            return
        msg = self.messages[self.msg_pos]
        shutil.rmtree(os.path.join(self.cfg.work_dir, str(msg.id)), ignore_errors=True)
        self.msg_pos += 1
        self._advance()

    def on_done(self):
        if self.busy:
            return
        x, y, w, h = self.overlay_box
        real_bbox = (
            int(x / self.scale), int(y / self.scale),
            int(w / self.scale), int(h / self.scale),
        )
        self._set_busy(True)
        self._set_status("Накладываю и заливаю в канал...")
        self._run_async(self._process_and_upload(real_bbox))

    async def _process_and_upload(self, bbox: tuple[int, int, int, int]):
        msg = self.messages[self.msg_pos]
        job_dir = os.path.join(self.cfg.work_dir, str(msg.id))
        clean_path = os.path.join(job_dir, "clean.mp4")
        try:
            await clean_watermark(self.cfg, self.video_path, clean_path, bbox)
            os.remove(self.video_path)
            result = ProcessResult(skip=False, media_path=clean_path, transcoded=True, is_video=True)
            await publish_one(self.cfg, self.client, self.db, self.brand_terms, msg, result)
        except Exception as e:
            self.db.upsert_status(msg.id, "error", error=str(e))
            self._set_status(f"Ошибка: {e}")
            self._set_busy(False)
            return
        self.msg_pos += 1
        self.root.after(0, self._advance)


def main():
    cfg = load_config()
    prompt_for_channels(cfg)
    if not cfg.overlay_image:
        raise SystemExit(
            "OVERLAY_IMAGE не задан в .env - укажите путь к PNG со стикером, "
            "который будете накладывать."
        )
    ManualOverlayApp(cfg)


if __name__ == "__main__":
    main()
