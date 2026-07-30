import asyncio
import concurrent.futures
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import customtkinter as ctk
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

from forum_clone import accounts as accounts_store
from forum_clone import config as cfg
from forum_clone.state import State
from forum_clone.telegram import is_forum
from forum_clone.pipeline import run_pipeline

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class InputDialog(ctk.CTkToplevel):
    """A small modal dialog with one text field, optionally masked - used
    for anything the background Telegram worker needs to ask the user."""

    def __init__(self, master, title, message, mask=False):
        super().__init__(master)
        self.title(title)
        self.geometry("440x170")
        self.resizable(False, False)
        self.transient(master)
        self.result = None

        ctk.CTkLabel(self, text=message, wraplength=400, justify="left").pack(padx=20, pady=(20, 10))
        self.entry = ctk.CTkEntry(self, width=380, show="*" if mask else "")
        self.entry.pack(padx=20, pady=(0, 14))

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(pady=(0, 10))
        ctk.CTkButton(buttons, text="OK", width=110, command=self._ok).pack(side="left", padx=6)
        ctk.CTkButton(buttons, text="Отмена", width=110, fg_color="gray40", hover_color="gray30",
                      command=self._cancel).pack(side="left", padx=6)

        self.entry.bind("<Return>", lambda e: self._ok())
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.after(50, lambda: (self.grab_set(), self.entry.focus()))

    def _ok(self):
        self.result = self.entry.get().strip()
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


class _StreamToLog:
    """Makes print() calls inside the shared pipeline/telegram modules show
    up in the GUI log box, without touching any of that code."""

    def __init__(self, app):
        self.app = app

    def write(self, text):
        if text:
            self.app.log(text)

    def flush(self):
        pass


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Forum Clone")
        self.geometry("820x680")
        self.minsize(680, 520)

        self.client = None
        self.loop = None
        self._loop_ready = threading.Event()
        self.busy = False
        self.dialog_cache = []
        self.selected_source = None
        self.current_future = None
        self.applied_delay = cfg.DELAY_SECONDS
        self.worker_rows = []

        self._build_ui()
        self._refresh_workers_panel()
        self._start_loop_thread()
        self.after(300, self.on_refresh_dialogs)

    # ---------- UI ----------

    def _build_ui(self):
        top = ctk.CTkFrame(self)
        top.pack(fill="x", padx=16, pady=(16, 8))
        self.account_label = ctk.CTkLabel(top, text="Аккаунт: подключаюсь...", anchor="w")
        self.account_label.pack(side="left", padx=8, fill="x", expand=True)
        self.switch_account_btn = ctk.CTkButton(top, text="Сменить аккаунт", width=150,
                                                 fg_color="gray40", hover_color="gray30",
                                                 command=self.on_switch_account)
        self.switch_account_btn.pack(side="right", padx=4)
        self.refresh_btn = ctk.CTkButton(top, text="Обновить список групп", width=180,
                                          command=self.on_refresh_dialogs)
        self.refresh_btn.pack(side="right", padx=4)

        src = ctk.CTkFrame(self)
        src.pack(fill="x", padx=16, pady=8)
        ctk.CTkLabel(src, text="Источник (форум, который нужно клонировать):").pack(anchor="w", padx=8, pady=(8, 0))
        self.source_var = ctk.StringVar(value="(нажмите «Обновить список групп»)")
        self.source_menu = ctk.CTkOptionMenu(src, variable=self.source_var,
                                              values=["(нажмите «Обновить список групп»)"],
                                              command=self.on_source_selected)
        self.source_menu.pack(fill="x", padx=8, pady=8)

        workers = ctk.CTkFrame(self)
        workers.pack(fill="x", padx=16, pady=8)
        wtop = ctk.CTkFrame(workers, fg_color="transparent")
        wtop.pack(fill="x")
        ctk.CTkLabel(wtop, text="Аккаунты-помощники (делят темы между собой для ускорения):",
                     anchor="w").pack(side="left", padx=8, pady=(8, 0))
        self.add_worker_btn = ctk.CTkButton(wtop, text="+ Добавить аккаунт", width=170,
                                             command=self.on_add_worker)
        self.add_worker_btn.pack(side="right", padx=8, pady=(4, 0))
        self.workers_list = ctk.CTkFrame(workers, fg_color="transparent")
        self.workers_list.pack(fill="x", padx=8, pady=(4, 8))
        self.no_workers_label = ctk.CTkLabel(self.workers_list, text="(нет — пересылает только основной аккаунт)",
                                              text_color="gray60")
        self.no_workers_label.pack(anchor="w")

        opts = ctk.CTkFrame(self)
        opts.pack(fill="x", padx=16, pady=8)
        opts.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(opts, text="Название клона:").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        self.title_entry = ctk.CTkEntry(opts)
        self.title_entry.grid(row=0, column=1, sticky="ew", padx=8, pady=8)

        ctk.CTkLabel(opts, text="Задержка между сообщениями, сек:").grid(row=1, column=0, sticky="w", padx=8, pady=8)
        delay_row = ctk.CTkFrame(opts, fg_color="transparent")
        delay_row.grid(row=1, column=1, sticky="w", padx=8, pady=8)
        self.delay_var = ctk.StringVar(value=str(cfg.DELAY_SECONDS))
        self.delay_entry = ctk.CTkEntry(delay_row, width=100, textvariable=self.delay_var)
        self.delay_entry.pack(side="left")
        self.delay_var.trace_add("write", self._on_delay_changed)
        self.confirm_delay_btn = ctk.CTkButton(delay_row, text="Подтвердить", width=110, state="disabled",
                                                command=self.on_confirm_delay)
        self.confirm_delay_btn.pack(side="left", padx=(8, 0))

        actions = ctk.CTkFrame(self)
        actions.pack(fill="x", padx=16, pady=8)
        self.topics_btn = ctk.CTkButton(actions, text="Создать только темы (тест)",
                                         command=lambda: self.on_start(topics_only=True))
        self.topics_btn.pack(side="left", padx=8, pady=8)
        self.start_btn = ctk.CTkButton(actions, text="Начать перенос",
                                        command=lambda: self.on_start(topics_only=False))
        self.start_btn.pack(side="left", padx=8, pady=8)
        self.stop_btn = ctk.CTkButton(actions, text="Остановить", state="disabled",
                                       fg_color="#B91C1C", hover_color="#7F1D1D",
                                       command=self.on_stop)
        self.stop_btn.pack(side="left", padx=8, pady=8)
        ctk.CTkButton(actions, text="Сбросить прогресс", fg_color="gray40", hover_color="gray30",
                      command=self.on_reset).pack(side="left", padx=8, pady=8)

        self.log_box = ctk.CTkTextbox(self, wrap="word", font=ctk.CTkFont("Consolas", 12))
        self.log_box.pack(fill="both", expand=True, padx=16, pady=(8, 16))
        self.log_box.configure(state="disabled")

    def log(self, text):
        def append():
            self.log_box.configure(state="normal")
            self.log_box.insert("end", text)
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        self.after(0, append)

    def set_busy(self, busy):
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.topics_btn.configure(state=state)
        self.start_btn.configure(state=state)
        self.refresh_btn.configure(state=state)
        self.switch_account_btn.configure(state=state)
        self.add_worker_btn.configure(state=state)
        for _, remove_btn in self.worker_rows:
            remove_btn.configure(state=state)
        self.stop_btn.configure(state="normal" if busy else "disabled")

    def _refresh_workers_panel(self):
        for w in self.workers_list.winfo_children():
            w.destroy()
        self.worker_rows = []

        accounts = accounts_store.load_accounts()
        if not accounts:
            self.no_workers_label = ctk.CTkLabel(self.workers_list,
                                                  text="(нет — пересылает только основной аккаунт)",
                                                  text_color="gray60")
            self.no_workers_label.pack(anchor="w")
            return

        for acc in accounts:
            row = ctk.CTkFrame(self.workers_list, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=f"• {acc['label']}", anchor="w").pack(side="left")
            remove_btn = ctk.CTkButton(row, text="Удалить", width=90, fg_color="gray40", hover_color="gray30",
                                        command=lambda sn=acc["session_name"]: self.on_remove_worker(sn))
            remove_btn.pack(side="right")
            self.worker_rows.append((acc["session_name"], remove_btn))

    def _on_delay_changed(self, *_args):
        raw = self.delay_var.get().strip().replace(",", ".")
        try:
            changed = abs(float(raw) - self.applied_delay) > 1e-9
        except ValueError:
            changed = bool(raw)
        self.confirm_delay_btn.configure(state="normal" if changed else "disabled")

    def on_confirm_delay(self):
        raw = self.delay_var.get().strip().replace(",", ".")
        try:
            value = float(raw)
            if value < 0:
                raise ValueError
        except ValueError:
            self.log("\nЗадержка должна быть числом ≥ 0, например 0.5\n")
            return
        self.applied_delay = value
        cfg.save_to_env("DELAY_SECONDS", str(value))
        self.confirm_delay_btn.configure(state="disabled")
        self.log(f"\nЗадержка между сообщениями изменена на {value} сек.\n")

    def on_stop(self):
        if self.current_future and not self.current_future.done():
            self.current_future.cancel()
            self.log("\n⏹ Останавливаю текущую операцию...\n")

    # ---------- cross-thread prompt ----------

    def ask(self, title, message, mask=False):
        """Called from the background thread; blocks it until the user
        answers the modal dialog shown on the main GUI thread."""
        result = {}
        done = threading.Event()

        def show():
            dlg = InputDialog(self, title, message, mask=mask)
            self.wait_window(dlg)
            result["value"] = dlg.result
            done.set()

        self.after(0, show)
        done.wait()
        return result.get("value")

    # ---------- background asyncio loop ----------

    def _start_loop_thread(self):
        def runner():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self._loop_ready.set()
            self.loop.run_forever()
        threading.Thread(target=runner, daemon=True).start()

    def run_async(self, coro, on_done=None, on_cancel=None):
        self._loop_ready.wait()
        old_stdout = sys.stdout
        sys.stdout = _StreamToLog(self)

        def _on_complete(fut):
            sys.stdout = old_stdout
            self.current_future = None
            try:
                fut.result()
            except (asyncio.CancelledError, concurrent.futures.CancelledError):
                if on_cancel:
                    on_cancel()
                else:
                    self.log("\n⏹ Остановлено.\n")
            except Exception as e:
                self.log(f"\n❌ Ошибка: {e}\n")
            if on_done:
                self.after(0, on_done)

        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        self.current_future = future
        future.add_done_callback(_on_complete)

    # ---------- Telegram login ----------

    async def ensure_credentials(self):
        api_id = os.environ.get("API_ID")
        if not api_id:
            api_id = await asyncio.to_thread(self.ask, "Настройка", "API_ID (число с https://my.telegram.org)")
            if not api_id or not api_id.strip().isdigit():
                raise RuntimeError("Не указан корректный API_ID")
            api_id = api_id.strip()
            cfg.save_to_env("API_ID", api_id)

        api_hash = os.environ.get("API_HASH")
        if not api_hash:
            api_hash = await asyncio.to_thread(self.ask, "Настройка", "API_HASH (с той же страницы my.telegram.org)")
            if not api_hash:
                raise RuntimeError("Не указан API_HASH")
            api_hash = api_hash.strip()
            cfg.save_to_env("API_HASH", api_hash)

        return int(api_id), api_hash

    async def ensure_login(self, client):
        await client.connect()
        if await client.is_user_authorized():
            return
        phone = await asyncio.to_thread(self.ask, "Вход в Telegram",
                                         "Номер телефона (с '+' и кодом страны):")
        if not phone:
            raise RuntimeError("Вход отменён")
        await client.send_code_request(phone)
        code = await asyncio.to_thread(self.ask, "Вход в Telegram", "Код из Telegram:")
        if not code:
            raise RuntimeError("Вход отменён")
        try:
            await client.sign_in(phone=phone, code=code)
        except SessionPasswordNeededError:
            password = await asyncio.to_thread(
                self.ask, "Вход в Telegram", "Пароль облачной 2FA:", True)
            if not password:
                raise RuntimeError("Вход отменён")
            await client.sign_in(password=password)

    async def _connect(self):
        if self.client is None:
            api_id, api_hash = await self.ensure_credentials()
            self.client = TelegramClient(cfg.SESSION_NAME, api_id, api_hash)
        await self.ensure_login(self.client)
        me = await self.client.get_me()
        name = f"{me.first_name or ''} {me.last_name or ''}".strip()
        self.after(0, lambda: self.account_label.configure(text=f"Аккаунт: {name} ({me.phone or '?'})"))
        return self.client

    # ---------- actions ----------

    async def _refresh_dialogs(self):
        client = await self._connect()
        dialogs = [d async for d in client.iter_dialogs() if d.is_group or d.is_channel]
        self.dialog_cache = dialogs
        names = [d.title for d in dialogs]
        self.after(0, lambda: self._populate_source_menu(names))

    def _populate_source_menu(self, names):
        if not names:
            self.source_menu.configure(values=["(групп не найдено)"])
            self.source_var.set("(групп не найдено)")
            return
        self.source_menu.configure(values=names)
        default_name = names[0]
        saved = cfg.SOURCE_CHAT
        if saved:
            try:
                saved_id = int(saved)
                for d in self.dialog_cache:
                    if d.entity.id == saved_id:
                        default_name = d.title
                        break
            except ValueError:
                pass
        self.source_var.set(default_name)
        self.on_source_selected(default_name)

    def on_source_selected(self, name):
        for d in self.dialog_cache:
            if d.title == name:
                self.selected_source = d.entity
                cfg.save_to_env("SOURCE_CHAT", d.entity.id)
                if not self.title_entry.get().strip():
                    self.title_entry.insert(0, d.title)
                break

    def on_refresh_dialogs(self):
        if self.busy:
            return
        self.set_busy(True)
        self.log("\nЗагружаю аккаунт и список групп...\n")
        self.run_async(self._refresh_dialogs(), on_done=lambda: self.set_busy(False))

    def on_switch_account(self):
        if self.busy:
            return
        cfg.clear_env_keys("API_ID", "API_HASH", "SOURCE_CHAT")
        for suffix in (".session", ".session-journal"):
            path = cfg.SESSION_NAME + suffix
            if os.path.exists(path):
                os.remove(path)
        self.client = None
        self.selected_source = None
        self.title_entry.delete(0, "end")
        self.account_label.configure(text="Аккаунт: не подключён")
        self.source_menu.configure(values=["(нажмите «Обновить список групп»)"])
        self.source_var.set("(нажмите «Обновить список групп»)")
        self.log("\nДанные аккаунта сброшены. Нажимаю «Обновить список групп»...\n")
        self.on_refresh_dialogs()

    def on_add_worker(self):
        if self.busy:
            return
        self.set_busy(True)
        self.log("\nДобавляю аккаунт-помощник...\n")

        async def task():
            api_id, api_hash = await self.ensure_credentials()
            session_name = accounts_store.next_session_name()
            client = TelegramClient(session_name, api_id, api_hash)
            await self.ensure_login(client)
            me = await client.get_me()
            label = f"{me.first_name or ''} ({me.phone or me.id})".strip()
            await client.disconnect()
            accounts_store.add_account(session_name, label)
            self.log(f"Аккаунт «{label}» добавлен. Если он ещё не состоит в группе-источнике - "
                      f"добавьте его туда сами, иначе он будет пропущен при переносе.\n")
            self.after(0, self._refresh_workers_panel)

        self.run_async(task(), on_done=lambda: self.set_busy(False))

    def on_remove_worker(self, session_name):
        if self.busy:
            return
        accounts_store.remove_account(session_name)
        for suffix in (".session", ".session-journal"):
            path = session_name + suffix
            if os.path.exists(path):
                os.remove(path)
        self._refresh_workers_panel()
        self.log("\nАккаунт-помощник удалён.\n")

    def on_start(self, topics_only):
        if self.busy:
            return
        if self.selected_source is None:
            self.log("\nСначала выберите источник из списка групп.\n")
            return

        title = self.title_entry.get().strip() or self.selected_source.title

        self.set_busy(True)
        self.log(f"\n=== {'Тестовый прогон (только темы)' if topics_only else 'Полный перенос'} "
                  f"(задержка {self.applied_delay} сек) ===\n")

        async def task():
            client = await self._connect()
            forum, _ = await is_forum(client, self.selected_source)
            if not forum:
                raise RuntimeError("Источник не является форумом (нет включённых тем).")
            state = State(cfg.STATE_FILE)

            worker_clients = []
            if not topics_only:
                api_id, api_hash = await self.ensure_credentials()
                for acc in accounts_store.load_accounts():
                    wc = TelegramClient(acc["session_name"], api_id, api_hash)
                    await wc.connect()
                    if await wc.is_user_authorized():
                        worker_clients.append(wc)
                    else:
                        print(f"  ! аккаунт «{acc['label']}» разлогинен, пропускаю (удалите и добавьте заново)")
                        await wc.disconnect()

            try:
                await run_pipeline(client, cfg, state, self.selected_source, title,
                                    self.applied_delay, topics_only=topics_only, workers=worker_clients)
            finally:
                for wc in worker_clients:
                    await wc.disconnect()

        def on_cancel():
            state = State(cfg.STATE_FILE)
            state.reset()
            self.log("\n⏹ Остановлено. Прогресс сброшен — следующий запуск начнётся с нуля.\n")

        self.run_async(task(), on_done=lambda: self.set_busy(False), on_cancel=on_cancel)

    def on_reset(self):
        if self.busy:
            return
        state = State(cfg.STATE_FILE)
        state.reset()
        self.log("\nПрогресс сброшен - следующий запуск пересоздаст клон с нуля.\n")


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
