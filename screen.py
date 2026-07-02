import tkinter as tk
import customtkinter as ctk
import math
import time
from ui.theme import *
from core import database as db
from modules.sender import logic as sender
from modules.editor import logic as editor


class DashboardScreen(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master, fg_color=BG)
        self._particles = []
        self._anim_id = None
        self._build()
        self._start_animation()

    def _build(self):
        ctk.CTkLabel(self, text="🗺️  Карта действий",
                     font=ctk.CTkFont("Segoe UI", 20, "bold"),
                     text_color=TEXT).pack(anchor="w", padx=32, pady=(24, 4))
        ctk.CTkLabel(self, text="Визуализация процессов в реальном времени",
                     font=ctk.CTkFont("Segoe UI", 12), text_color=MUTED).pack(anchor="w", padx=32)

        # Canvas for animation
        self.canvas = tk.Canvas(self, bg="#0A0D14", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=32, pady=16)

        # Status bar
        self.status_frame = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        self.status_frame.pack(fill="x", padx=32, pady=(0, 20))
        self._build_status()

    def _build_status(self):
        for w in self.status_frame.winfo_children():
            w.destroy()
        row = ctk.CTkFrame(self.status_frame, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=12)

        sender_status = sender.get_status()
        editor_status = editor.get_status()

        items = [
            ("📡 TG Sender", "Активен" if sender_status["is_running"] else "Стоит",
             SUCCESS if sender_status["is_running"] else MUTED,
             f"Циклов: {sender_status['cycle_count']}"),
            ("✏️ Editor", "Активен" if editor_status["is_running"] else "Стоит",
             SUCCESS if editor_status["is_running"] else MUTED,
             editor_status.get("current_task", "—")),
        ]

        for title, status, color, detail in items:
            card = ctk.CTkFrame(row, fg_color=CARD2, corner_radius=8)
            card.pack(side="left", padx=6, fill="x", expand=True)
            ctk.CTkLabel(card, text=title, font=ctk.CTkFont("Segoe UI", 12, "bold"),
                         text_color=TEXT).pack(anchor="w", padx=12, pady=(8, 0))
            ctk.CTkLabel(card, text=status, font=ctk.CTkFont("Segoe UI", 11),
                         text_color=color).pack(anchor="w", padx=12)
            ctk.CTkLabel(card, text=detail, font=ctk.CTkFont("Segoe UI", 10),
                         text_color=MUTED).pack(anchor="w", padx=12, pady=(0, 8))

    # Node definitions: (x%, y%, label, color, key)
    NODES = [
        (0.5,  0.12, "OmniGram", ACCENT,  "core"),
        (0.20, 0.42, "Channel\nEditor", "#7C3AED", "editor"),
        (0.50, 0.42, "TG Sender", ACCENT,  "sender"),
        (0.80, 0.42, "Auto\nManager", MUTED,   "manager"),
        (0.15, 0.75, "Аккаунты", "#7C3AED", "acc_editor"),
        (0.38, 0.75, "Посты", "#7C3AED", "posts"),
        (0.50, 0.75, "Рассылка", ACCENT,  "sending"),
        (0.65, 0.75, "Чат пул", ACCENT,  "chatpool"),
        (0.80, 0.75, "Резерв\nакков", MUTED,   "reserve"),
    ]

    EDGES = [
        ("core", "editor"),
        ("core", "sender"),
        ("core", "manager"),
        ("editor", "acc_editor"),
        ("editor", "posts"),
        ("sender", "sending"),
        ("sender", "chatpool"),
        ("manager", "reserve"),
    ]

    def _start_animation(self):
        self.canvas.bind("<Configure>", lambda e: self._redraw())
        self._tick()

    def _tick(self):
        self._redraw()
        self._anim_id = self.after(50, self._tick)

    def _redraw(self):
        c = self.canvas
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 10 or h < 10:
            return

        # Compute node positions
        positions = {}
        for nx, ny, label, color, key in self.NODES:
            positions[key] = (int(nx * w), int(ny * h))

        # Active nodes based on running state
        sender_running = sender.get_status()["is_running"]
        editor_running = editor.get_status()["is_running"]
        active_keys = {"core"}
        if sender_running:
            active_keys.update({"sender", "sending", "chatpool"})
        if editor_running:
            active_keys.update({"editor", "acc_editor", "posts"})

        t = time.time()

        # Draw edges
        for src, dst in self.EDGES:
            x1, y1 = positions[src]
            x2, y2 = positions[dst]
            is_active = src in active_keys and dst in active_keys
            color = "#1E3A5F" if is_active else "#1E3A5F"
            c.create_line(x1, y1, x2, y2, fill=color, width=2 if is_active else 1)

            # Animated particle on active edges
            if is_active:
                progress = (t * 0.6) % 1.0
                px = x1 + (x2 - x1) * progress
                py = y1 + (y2 - y1) * progress
                c.create_oval(px-4, py-4, px+4, py+4, fill=ACCENT, outline="")
                # Glow
                c.create_oval(px-8, py-8, px+8, py+8,
                              fill="", outline="#1E3A5F", width=2)

        # Draw nodes
        for nx, ny, label, color, key in self.NODES:
            x, y = positions[key]
            is_active = key in active_keys
            r = 34 if is_active else 28

            # Pulse ring for active nodes
            if is_active:
                pulse = 0.5 + 0.5 * math.sin(t * 3 + hash(key) % 10)
                pr = r + 8 + int(pulse * 6)
                c.create_oval(x-pr, y-pr, x+pr, y+pr,
                              fill="", outline="#1E3A5F", width=2)

            # Node circle
            c.create_oval(x-r, y-r, x+r, y+r,
                          fill=color + ("FF" if is_active else "33"),
                          outline=color, width=2)

            # Label
            lines = label.split("\n")
            for i, line in enumerate(lines):
                offset = (i - (len(lines)-1)/2) * 13
                c.create_text(x, y + r + 14 + offset, text=line,
                              fill=TEXT if is_active else MUTED,
                              font=("Segoe UI", 9, "bold" if is_active else "normal"))

        # Recent actions log overlay
        actions = db.get_recent_actions(5)
        if actions:
            c.create_rectangle(8, h-120, 320, h-8,
                               fill="#1E3A5F", outline="#1F2937", width=1)
            c.create_text(16, h-108, text="📋 Последние действия",
                          fill=MUTED, font=("Segoe UI", 9, "bold"), anchor="w")
            for i, act in enumerate(actions):
                dot = "🟢" if act["status"] == "done" else ("🔴" if act["status"] == "error" else "🟡")
                text = f"{dot} [{act['module']}] {act['action']}"
                c.create_text(16, h-90 + i*18, text=text[:48],
                              fill=TEXT if act["status"] == "running" else MUTED,
                              font=("Segoe UI", 9), anchor="w")

    def destroy(self):
        if self._anim_id:
            self.after_cancel(self._anim_id)
        super().destroy()
