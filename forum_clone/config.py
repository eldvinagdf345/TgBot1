import os

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

try:
    from dotenv import load_dotenv
    # Всегда ищем .env рядом с этим файлом, а не рядом с текущей рабочей
    # директорией - иначе поиск ломается, если запускать `python -m
    # forum_clone.clone` из папки на уровень выше (что и требуется для -m).
    load_dotenv(ENV_PATH)
except ImportError:
    pass


_PROMPTS = {
    "API_ID": "API_ID (число с https://my.telegram.org -> API development tools): ",
    "API_HASH": "API_HASH (с той же страницы my.telegram.org): ",
    "SOURCE_CHAT": "SOURCE_CHAT - @username форума, или его числовой id "
                   "(id можно узнать через --list-chats): ",
}


def _save_to_env_file(name, value):
    lines = []
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()

    for i, line in enumerate(lines):
        if line.strip().startswith(f"{name}="):
            lines[i] = f"{name}={value}\n"
            break
    else:
        lines.append(f"{name}={value}\n")

    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines)


def prompt_and_save(name, cast=str):
    """Asks for a value right in the console (no file editing needed) and
    remembers it in .env so future runs won't ask again."""
    prompt = _PROMPTS.get(name, f"{name}: ")
    while True:
        raw = input(prompt).strip()
        if not raw:
            print("  Значение не может быть пустым, попробуйте ещё раз.")
            continue
        try:
            cast(raw)
        except ValueError:
            print("  Не похоже на число, попробуйте ещё раз.")
            continue
        os.environ[name] = raw
        _save_to_env_file(name, raw)
        print("  (сохранено в .env, в следующий раз спрашивать не буду)\n")
        return raw


def _get(name, default=None, interactive=False, cast=str):
    value = os.environ.get(name) or default
    if value:
        return value
    if interactive:
        return prompt_and_save(name, cast=cast)
    return default


API_ID = int(_get("API_ID", interactive=True, cast=int))
API_HASH = _get("API_HASH", interactive=True)
SESSION_NAME = _get("SESSION_NAME", "clone_session")

# SOURCE_CHAT нарочно не спрашивается здесь: для --list-chats он ещё не
# нужен (это как раз способ его узнать). clone.py спрашивает его сам,
# только когда он действительно требуется для запуска клонирования.
SOURCE_CHAT = _get("SOURCE_CHAT", "") or None
TARGET_CHAT = _get("TARGET_CHAT", "") or None
TARGET_TITLE = _get("TARGET_TITLE", "") or None

DOWNLOAD_DIR = _get("DOWNLOAD_DIR", "./downloads")
STATE_FILE = _get("STATE_FILE", "./state.json")

DELAY_SECONDS = float(_get("DELAY_SECONDS", "1.5"))

# Название темы-навигации: создаётся и заполняется последней, ссылки на темы
# источника внутри неё переписываются на ссылки клона. Сравнение по названию,
# без учёта регистра/пробелов по краям.
NAV_TOPIC_TITLE = _get("NAV_TOPIC_TITLE", "НАВИГАЦИЯ КАНАЛА")
