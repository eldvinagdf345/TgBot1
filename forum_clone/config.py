import os

try:
    from dotenv import load_dotenv
    # Всегда ищем .env рядом с этим файлом, а не рядом с текущей рабочей
    # директорией - иначе поиск ломается, если запускать `python -m
    # forum_clone.clone` из папки на уровень выше (что и требуется для -m).
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass


def _get(name, default=None, required=False):
    value = os.environ.get(name, default)
    if required and not value:
        raise SystemExit(
            f"Не задана переменная окружения {name}. "
            f"Скопируйте .env.example в .env и заполните её."
        )
    return value


API_ID = int(_get("API_ID", required=True))
API_HASH = _get("API_HASH", required=True)
SESSION_NAME = _get("SESSION_NAME", "clone_session")

SOURCE_CHAT = _get("SOURCE_CHAT", required=True)
TARGET_CHAT = _get("TARGET_CHAT", "") or None
TARGET_TITLE = _get("TARGET_TITLE", "") or None

DOWNLOAD_DIR = _get("DOWNLOAD_DIR", "./downloads")
STATE_FILE = _get("STATE_FILE", "./state.json")

DELAY_SECONDS = float(_get("DELAY_SECONDS", "1.5"))

# Название темы-навигации: создаётся и заполняется последней, ссылки на темы
# источника внутри неё переписываются на ссылки клона. Сравнение по названию,
# без учёта регистра/пробелов по краям.
NAV_TOPIC_TITLE = _get("NAV_TOPIC_TITLE", "НАВИГАЦИЯ КАНАЛА")
