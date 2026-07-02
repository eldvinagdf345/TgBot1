import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import customtkinter as ctk
from ui.theme import *
from ui.home import HomeScreen
from core import database as db

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class OmniGram(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("OmniGram")
        self.geometry("1200x760")
        self.minsize(960, 640)
        self.configure(fg_color=BG)
        db.init_db()

        self._history = []
        self._build_topbar()
        self._content = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self._content.pack(fill="both", expand=True)
        self._show("home")

    def _build_topbar(self):
        bar = ctk.CTkFrame(self, fg_color=CARD, corner_radius=0, height=48)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        ctk.CTkLabel(bar, text="⬡  OmniGram",
                     font=ctk.CTkFont("Segoe UI", 15, "bold"),
                     text_color=ACCENT).pack(side="left", padx=20)

        # Nav buttons
        nav = ctk.CTkFrame(bar, fg_color="transparent")
        nav.pack(side="left", padx=20)
        nav_items = [("🏠 Главная", "home"), ("✏️ Editor", "editor"),
                     ("📡 Sender", "sender"), ("🗺️ Карта", "dashboard")]
        for label, key in nav_items:
            ctk.CTkButton(nav, text=label, height=30, width=100, corner_radius=6,
                          fg_color="transparent", hover_color=CARD2,
                          text_color=MUTED, font=ctk.CTkFont("Segoe UI", 11),
                          command=lambda k=key: self._show(k)).pack(side="left", padx=2)

        # Back button
        ctk.CTkButton(bar, text="← Назад", height=30, width=80, corner_radius=6,
                      fg_color="transparent", hover_color=CARD2,
                      text_color=MUTED, font=ctk.CTkFont("Segoe UI", 11),
                      command=self._go_back).pack(side="right", padx=16)

    def _show(self, key):
        if self._history and self._history[-1] == key:
            return
        self._history.append(key)
        for w in self._content.winfo_children():
            w.destroy()

        screens = {
            "home": lambda: HomeScreen(self._content, self._show),
            "editor": lambda: __import__(
                "modules.editor.screen", fromlist=["EditorScreen"]).EditorScreen(self._content),
            "sender": lambda: __import__(
                "modules.sender.screen", fromlist=["SenderScreen"]).SenderScreen(self._content),
            "dashboard": lambda: __import__(
                "modules.dashboard.screen", fromlist=["DashboardScreen"]).DashboardScreen(self._content),
        }
        if key in screens:
            screens[key]().pack(fill="both", expand=True)

    def _go_back(self):
        if len(self._history) > 1:
            self._history.pop()
            prev = self._history.pop()
            self._show(prev)


def main():
    app = OmniGram()
    app.mainloop()


if __name__ == "__main__":
    main()
