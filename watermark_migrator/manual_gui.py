"""
Manual editor - 3 actions:
  1. Выбрать файл (photo or video, from your computer) - video gets a real
     player (play/pause + seek) so you can actually watch it, not just a
     single static frame.
  2. Добавить знак - drops in the one fixed overlay image as a selection box
     (dashed outline + a big corner handle per corner, CapCut-style). Drag
     the middle to move, drag any corner to resize - both track the cursor
     1:1, no lag, no delete/recreate per frame.
  3. Готово - locks the mark in place (no more moving/resizing), burns it
     into the whole file and sends the result to TARGET_CHANNEL, then
     clears the file so you can pick the next one.

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

import cv2
from PIL import Image, ImageTk

from .config import Config, load_config
from .ffmpeg_utils import encode_with_fallback, get_video_dimensions
from .telegram_io import make_client, upload_message

PREVIEW_MAX_W = 960
PREVIEW_MAX_H = 540
HANDLE_R = 11  # corner grab-circle radius, in canvas pixels
MIN_BOX = 30

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
        self.overlay_box = [30, 30, 220, 100]  # x, y, w, h in canvas pixels
        self._drag = {"mode": None, "corner": None, "x": 0, "y": 0}
        self.locked = False  # True once "Готово" is clicked - ignore further drags
        self.busy = False

        # video player state
        self.cap = None
        self.video_fps = 25.0
        self.video_frame_count = 1
        self.playing = False
        self._play_after_id = None
        self._suppress_seek = False

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

        # video transport (hidden until a video is loaded)
        self.transport = tk.Frame(self.root, bg=BG)
        self.play_btn = _styled_button(self.transport, "▶  Смотреть", self._toggle_play, bg="#3a3c4d", fg=TEXT)
        self.play_btn.pack(side="left", padx=(16, 8))
        self.seek_var = tk.DoubleVar(value=0)
        self.seek_scale = tk.Scale(
            self.transport, from_=0, to=1, orient="horizontal", variable=self.seek_var,
            showvalue=False, command=self._on_seek, length=PREVIEW_MAX_W - 140,
            bg=BG, fg=TEXT, troughcolor=PANEL, highlightthickness=0, bd=0,
            activebackground=ACCENT,
        )
        self.seek_scale.pack(side="left", padx=8, fill="x", expand=True)

        self.btns_frame = tk.Frame(self.root, bg=BG)
        self.btns_frame.pack(pady=14)
        self.choose_btn = _styled_button(self.btns_frame, "📂  Выбрать файл", self.on_choose, bg="#3a3c4d", fg=TEXT, state="disabled")
        self.choose_btn.pack(side="left", padx=6)
        self.mark_btn = _styled_button(self.btns_frame, "➕  Добавить знак", self.on_add_mark, bg=ACCENT, state="disabled")
        self.mark_btn.pack(side="left", padx=6)
        self.done_btn = _styled_button(self.btns_frame, "✅  Готово (отправить)", self.on_done, bg=ACCENT_GREEN, state="disabled")
        self.done_btn.pack(side="left", padx=6)

        self.hint_var = tk.StringVar(
            value="Тащите знак за середину, чтобы двигать. Тащите любой кружок по углам, чтобы менять размер."
        )
        tk.Label(self.root, textvariable=self.hint_var, bg=BG, fg=MUTED, font=FONT).pack(pady=(0, 14))

        self.bg_photo = None
        self.bg_image_id = None
        self.overlay_photo = None
        self.overlay_id = None
        self.outline_id = None
        self.handle_ids: dict[str, int] = {}

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
            self.done_btn.config(state=state if (self.overlay_id and not self.locked) else "disabled")

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
        self._stop_playback()
        if self.cap is not None:
            self.cap.release()
            self.cap = None

        self.file_path = path
        self.is_video = os.path.splitext(path)[1].lower() in VIDEO_EXTS
        self.locked = False
        self._clear_overlay_items()
        self.canvas.delete("all")
        self.bg_image_id = None

        if self.is_video:
            self._open_video(path)
        else:
            self.transport.pack_forget()
            img = Image.open(path)
            self._show_frame(img)
            self._set_status("Файл загружен. Нажмите 'Добавить знак'.")
            self.mark_btn.config(state="normal")

    # ---------------- video player ----------------
    def _open_video(self, path: str):
        self.cap = cv2.VideoCapture(path)
        self.video_fps = self.cap.get(cv2.CAP_PROP_FPS) or 25.0
        self.video_frame_count = max(1, int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1)
        self.seek_scale.config(to=self.video_frame_count - 1)
        self._suppress_seek = True
        self.seek_var.set(0)
        self._suppress_seek = False
        self.transport.pack(fill="x", padx=16, before=self.btns_frame)

        ok, frame = self.cap.read()
        if ok:
            self._show_frame(self._to_pil(frame))
        self._set_status("Видео загружено - можно посмотреть (▶) или сразу 'Добавить знак'.")
        self.mark_btn.config(state="normal")

    def _to_pil(self, bgr_frame) -> Image.Image:
        rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        return Image.fromarray(rgb)

    def _show_frame(self, img: Image.Image):
        scale = min(PREVIEW_MAX_W / img.width, PREVIEW_MAX_H / img.height, 1.0)
        self.scale = scale
        disp = img.resize(
            (max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.NEAREST
        )
        self.bg_photo = ImageTk.PhotoImage(disp)
        if self.bg_image_id is None:
            self.canvas.config(width=disp.width, height=disp.height)
            self.bg_image_id = self.canvas.create_image(0, 0, anchor="nw", image=self.bg_photo)
            self.canvas.tag_lower(self.bg_image_id)
        else:
            self.canvas.itemconfig(self.bg_image_id, image=self.bg_photo)

    def _toggle_play(self):
        if not self.cap:
            return
        if self.playing:
            self._stop_playback()
        else:
            self.playing = True
            self.play_btn.config(text="⏸  Пауза")
            self._play_tick()

    def _stop_playback(self):
        self.playing = False
        if self._play_after_id is not None:
            try:
                self.root.after_cancel(self._play_after_id)
            except Exception:
                pass
            self._play_after_id = None
        self.play_btn.config(text="▶  Смотреть")

    def _play_tick(self):
        if not self.playing or not self.cap:
            return
        ok, frame = self.cap.read()
        if not ok:
            self._stop_playback()
            return
        self._show_frame(self._to_pil(frame))
        pos = self.cap.get(cv2.CAP_PROP_POS_FRAMES)
        self._suppress_seek = True
        self.seek_var.set(pos)
        self._suppress_seek = False
        delay = max(10, int(1000 / self.video_fps))
        self._play_after_id = self.root.after(delay, self._play_tick)

    def _on_seek(self, value):
        if self._suppress_seek or not self.cap:
            return
        self._stop_playback()
        idx = int(float(value))
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = self.cap.read()
        if ok:
            self._show_frame(self._to_pil(frame))

    # ---------------- 2. add mark (drag + corner-handle resize) ----------------
    def on_add_mark(self):
        if self.busy or not self.file_path:
            return
        self.locked = False
        w = 220
        h = int(220 * self.overlay_pil.height / self.overlay_pil.width)
        self.overlay_box = [30, 30, w, h]
        self._create_overlay_items()
        self.hint_var.set("Тащите за середину = двигать. Тащите за кружок в углу = менять размер.")
        self._set_status("Разместите знак, затем нажмите 'Готово'.")
        self.done_btn.config(state="normal")

    def _clear_overlay_items(self):
        if self.overlay_id:
            self.canvas.delete(self.overlay_id)
            self.overlay_id = None
        if self.outline_id:
            self.canvas.delete(self.outline_id)
            self.outline_id = None
        for hid in self.handle_ids.values():
            self.canvas.delete(hid)
        self.handle_ids = {}

    def _create_overlay_items(self):
        """Build every canvas item for the overlay once. After this, moving
        and resizing only update coordinates/pixels on these same items -
        nothing gets deleted/recreated per mouse-motion tick, which is what
        made dragging feel laggy before."""
        self._clear_overlay_items()
        x, y, w, h = self.overlay_box

        sticker = self.overlay_pil.resize((int(w), int(h)), Image.NEAREST)
        self.overlay_photo = ImageTk.PhotoImage(sticker)
        self.overlay_id = self.canvas.create_image(int(x), int(y), anchor="nw", image=self.overlay_photo)
        self.canvas.tag_bind(self.overlay_id, "<ButtonPress-1>", self._on_move_press)
        self.canvas.tag_bind(self.overlay_id, "<B1-Motion>", self._on_move_drag)

        self.outline_id = self.canvas.create_rectangle(
            x, y, x + w, y + h, outline=ACCENT, width=2, dash=(6, 4)
        )

        corners = {"tl": (x, y), "tr": (x + w, y), "bl": (x, y + h), "br": (x + w, y + h)}
        for corner, (cx, cy) in corners.items():
            hid = self.canvas.create_oval(
                cx - HANDLE_R, cy - HANDLE_R, cx + HANDLE_R, cy + HANDLE_R,
                fill="#22d3ee", outline="white", width=2,
            )
            self.canvas.tag_bind(hid, "<ButtonPress-1>", lambda e, c=corner: self._on_resize_press(e, c))
            self.canvas.tag_bind(hid, "<B1-Motion>", self._on_resize_drag)
            self.handle_ids[corner] = hid

    def _move_geometry(self, dx: int, dy: int):
        """Cheap path for a pure drag: shift existing canvas items instead of
        regenerating the sticker image or recreating anything."""
        self.canvas.move(self.overlay_id, dx, dy)
        self.canvas.move(self.outline_id, dx, dy)
        for hid in self.handle_ids.values():
            self.canvas.move(hid, dx, dy)

    def _rebuild_geometry(self):
        """Resize path: the sticker pixels genuinely need to change size, but
        we still avoid delete/recreate - reuse the same item ids via
        itemconfig/coords so bindings and z-order stay intact."""
        x, y, w, h = self.overlay_box
        w, h = max(MIN_BOX, int(w)), max(MIN_BOX, int(h))
        self.overlay_box = [x, y, w, h]

        sticker = self.overlay_pil.resize((w, h), Image.NEAREST)
        self.overlay_photo = ImageTk.PhotoImage(sticker)
        self.canvas.coords(self.overlay_id, x, y)
        self.canvas.itemconfig(self.overlay_id, image=self.overlay_photo)

        self.canvas.coords(self.outline_id, x, y, x + w, y + h)
        corners = {"tl": (x, y), "tr": (x + w, y), "bl": (x, y + h), "br": (x + w, y + h)}
        for corner, (cx, cy) in corners.items():
            hid = self.handle_ids[corner]
            self.canvas.coords(hid, cx - HANDLE_R, cy - HANDLE_R, cx + HANDLE_R, cy + HANDLE_R)

    def _on_move_press(self, event):
        if self.locked:
            return
        self._drag = {"mode": "move", "corner": None, "x": event.x, "y": event.y}

    def _on_move_drag(self, event):
        if self.locked or self._drag["mode"] != "move":
            return
        dx, dy = event.x - self._drag["x"], event.y - self._drag["y"]
        self.overlay_box[0] += dx
        self.overlay_box[1] += dy
        self._drag["x"], self._drag["y"] = event.x, event.y
        self._move_geometry(dx, dy)

    def _on_resize_press(self, event, corner: str):
        if self.locked:
            return
        self._drag = {"mode": "resize", "corner": corner, "x": event.x, "y": event.y}

    def _on_resize_drag(self, event):
        if self.locked or self._drag["mode"] != "resize":
            return
        dx, dy = event.x - self._drag["x"], event.y - self._drag["y"]
        x, y, w, h = self.overlay_box
        corner = self._drag["corner"]
        if corner == "br":
            w += dx; h += dy
        elif corner == "bl":
            x += dx; w -= dx; h += dy
        elif corner == "tr":
            y += dy; w += dx; h -= dy
        elif corner == "tl":
            x += dx; y += dy; w -= dx; h -= dy
        self.overlay_box = [x, y, max(MIN_BOX, w), max(MIN_BOX, h)]
        self._drag["x"], self._drag["y"] = event.x, event.y
        self._rebuild_geometry()

    # ---------------- 3. done ----------------
    def on_done(self):
        if self.busy or not self.file_path or self.overlay_id is None or self.locked:
            return
        self.locked = True  # freeze the mark immediately, before any encoding starts
        self._stop_playback()
        x, y, w, h = self.overlay_box
        bbox = (
            int(x / self.scale), int(y / self.scale),
            int(w / self.scale), int(h / self.scale),
        )
        self._set_busy(True)
        self.hint_var.set("Знак зафиксирован.")
        self._set_status("Кодирую файл - для длинных видео это может занять пару минут...")
        self._run_async(self._process_and_send(bbox))

    async def _process_and_send(self, bbox: tuple[int, int, int, int]):
        ext = ".mp4" if self.is_video else (os.path.splitext(self.file_path)[1] or ".png")
        out_path = os.path.join(tempfile.gettempdir(), f"wm_output{ext}")
        try:
            if self.is_video:
                await self._burn_video(self.file_path, out_path, bbox)
            else:
                self._burn_image(self.file_path, out_path, bbox)
            self._set_status("Загружаю в Telegram...")
            await upload_message(self.client, self.cfg.target_channel, out_path, "")
        except Exception as e:
            self._set_status(f"Ошибка: {e}")
            self.locked = False
            self._set_busy(False)
            return

        self._set_status("Отправлено! Выберите следующий файл.")
        self.file_path = None
        self.overlay_id = None
        self.locked = False

        def _reset_canvas():
            # release the capture on the main thread - it was opened/used here
            if self.cap is not None:
                self.cap.release()
                self.cap = None
            self.canvas.delete("all")
            self.bg_image_id = None
            self.overlay_id = None
            self.outline_id = None
            self.handle_ids = {}
            self.transport.pack_forget()
            self.mark_btn.config(state="disabled")

        self.root.after(0, _reset_canvas)
        self._set_busy(False)

    async def _burn_video(self, input_path: str, output_path: str, bbox: tuple[int, int, int, int]) -> None:
        x, y, w, h = bbox
        frame_w, frame_h = await get_video_dimensions(self.cfg, input_path)
        x = max(0, min(x, frame_w - 1))
        y = max(0, min(y, frame_h - 1))
        w = max(2, min(w, frame_w - x))
        h = max(2, min(h, frame_h - y))
        # scale/pad need even dimensions, otherwise libswscale's rounding can
        # make the scaled output 1px larger than the pad target and ffmpeg
        # refuses with "Padded dimensions cannot be smaller than input
        # dimensions".
        w -= w % 2
        h -= h % 2
        w, h = max(2, w), max(2, h)
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
