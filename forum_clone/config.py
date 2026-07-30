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
}


def save_to_env(name, value):
    """Writes/updates a single KEY=value line in .env (no prompting)."""
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
    os.environ[name] = str(value)


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
        save_to_env(name, raw)
        print("  (сохранено в .env, в следующий раз спрашивать не буду)\n")
        return raw


def clear_env_keys(*names):
    """Removes the given keys from .env and from the live process env -
    used by --switch-account so credentials get asked again from scratch."""
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
        lines = [l for l in lines if not any(l.strip().startswith(f"{n}=") for n in names)]
        with open(ENV_PATH, "w", encoding="utf-8") as f:
            f.writelines(lines)
    for n in names:
        os.environ.pop(n, None)


def _get(name, default=None, interactive=False, cast=str):
    value = os.environ.get(name) or default
    if value:
        return value
    if interactive:
        return prompt_and_save(name, cast=cast)
    return default


def get_api_id():
    """Asked lazily (not at import time) so --switch-account can clear the
    old value first, before anything prompts for it."""
    return int(_get("API_ID", interactive=True, cast=int))


def get_api_hash():
    return _get("API_HASH", interactive=True)


SESSION_NAME = _get("SESSION_NAME", "clone_session")

# SOURCE_CHAT нарочно не спрашивается здесь и не через консольный prompt:
# clone.py сам предложит выбрать группу из пронумерованного списка ваших
# чатов при первом запуске и запомнит выбор в .env. TARGET_CHAT/TARGET_TITLE
# по умолчанию тоже пустые - клон создаётся новой группой автоматически.
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
