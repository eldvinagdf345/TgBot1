import customtkinter as ctk
from ui.theme import *


class HomeScreen(ctk.CTkFrame):
    def __init__(self, master, on_open):
        super().__init__(master, fg_color=BG)
        self.on_open = on_open
        self._build()

    def _build(self):
        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=40, pady=(36, 0))

        ctk.CTkLabel(header, text="OmniGram",
                     font=ctk.CTkFont("Segoe UI", 36, "bold"),
                     text_color=ACCENT).pack(anchor="w")
        ctk.CTkLabel(header, text="Платформа автоматизации Telegram каналов",
                     font=ctk.CTkFont("Segoe UI", 14),
                     text_color=MUTED).pack(anchor="w", pady=(4, 0))

        ctk.CTkFrame(self, height=1, fg_color=CARD2).pack(fill="x", padx=40, pady=24)

        # Module cards grid
        ctk.CTkLabel(self, text="Модули",
                     font=ctk.CTkFont("Segoe UI", 13, "bold"),
                     text_color=MUTED).pack(anchor="w", padx=40, pady=(0, 12))

        grid = ctk.CTkFrame(self, fg_color="transparent")
        grid.pack(fill="both", expand=True, padx=40, pady=(0, 20))

        modules = [
            {
                "key": "editor",
                "icon": "✏️",
                "title": "Channel Editor",
                "desc": "Редактирование постов в купленных каналах. Копируй посты из любых источников.",
                "color": "#7C3AED",
                "tag": "АКТИВЕН",
            },
            {
                "key": "sender",
                "icon": "📡",
                "title": "TG Sender",
                "desc": "Автоматическая рассылка сообщений по каналам через несколько аккаунтов.",
                "color": ACCENT,
                "tag": "АКТИВЕН",
            },
            {
                "key": "dashboard",
                "icon": "🗺️",
                "title": "Карта действий",
                "desc": "Визуализация всех процессов в реальном времени. Анимированная паутинка модулей.",
                "color": "#059669",
                "tag": "LIVE",
            },
            {
                "key": "soon1",
                "icon": "🤖",
                "title": "Auto Manager",
                "desc": "Автоматическая замена заблокированных аккаунтов из резервного пула.",
                "color": MUTED,
                "tag": "СКОРО",
            },
            {
                "key": "soon2",
                "icon": "📊",
                "title": "Analytics",
                "desc": "Статистика каналов, охваты, динамика подписчиков и эффективность рассылок.",
                "color": MUTED,
                "tag": "СКОРО",
            },
            {
                "key": "soon3",
                "icon": "🛒",
                "title": "Account Store",
                "desc": "Автоматическая закупка и фарм аккаунтов для рассылки.",
                "color": MUTED,
                "tag": "СКОРО",
            },
        ]

        for i, mod in enumerate(modules):
            row = i // 3
            col = i % 3
            self._module_card(grid, mod, row, col)

        for c in range(3):
            grid.columnconfigure(c, weight=1)

    def _module_card(self, parent, mod, row, col):
        is_soon = mod["key"].startswith("soon")

        card = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=16,
                            border_width=1, border_color=CARD2)
        card.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")
        parent.rowconfigure(row, weight=1)

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=20, pady=18)

        # Top row: icon + tag
        top = ctk.CTkFrame(inner, fg_color="transparent")
        top.pack(fill="x")

        icon_frame = ctk.CTkFrame(top, fg_color=CARD2,
                                  corner_radius=10, width=44, height=44)
        icon_frame.pack(side="left")
        icon_frame.pack_propagate(False)
        ctk.CTkLabel(icon_frame, text=mod["icon"],
                     font=ctk.CTkFont("Segoe UI", 20)).pack(expand=True)

        tag_color = mod["color"] if not is_soon else CARD2
        ctk.CTkLabel(top, text=mod["tag"],
                     font=ctk.CTkFont("Segoe UI", 10, "bold"),
                     fg_color=CARD2, text_color=mod["color"],
                     corner_radius=6, padx=8, pady=3).pack(side="right", anchor="n")

        ctk.CTkLabel(inner, text=mod["title"],
                     font=ctk.CTkFont("Segoe UI", 15, "bold"),
                     text_color=TEXT if not is_soon else MUTED,
                     anchor="w").pack(fill="x", pady=(12, 4))

        ctk.CTkLabel(inner, text=mod["desc"],
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=MUTED, wraplength=220,
                     justify="left", anchor="w").pack(fill="x")

        if not is_soon:
            btn = ctk.CTkButton(inner, text="Открыть →",
                                fg_color=mod["color"], hover_color=mod["color"],
                                text_color="white", height=34, corner_radius=8,
                                font=ctk.CTkFont("Segoe UI", 12, "bold"),
                                command=lambda k=mod["key"]: self.on_open(k))
            btn.pack(fill="x", pady=(14, 0))
        else:
            ctk.CTkButton(inner, text="Скоро...",
                          fg_color=CARD2, hover_color=CARD2,
                          text_color=MUTED, height=34, corner_radius=8,
                          state="disabled").pack(fill="x", pady=(14, 0))
