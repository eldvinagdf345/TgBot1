import json
import os

ACCOUNTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "accounts.json")


def load_accounts():
    if not os.path.exists(ACCOUNTS_PATH):
        return []
    with open(ACCOUNTS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_accounts(accounts):
    with open(ACCOUNTS_PATH, "w", encoding="utf-8") as f:
        json.dump(accounts, f, ensure_ascii=False, indent=2)


def add_account(session_name, label):
    accounts = load_accounts()
    accounts.append({"session_name": session_name, "label": label})
    save_accounts(accounts)


def remove_account(session_name):
    save_accounts([a for a in load_accounts() if a["session_name"] != session_name])


def next_session_name():
    existing = {a["session_name"] for a in load_accounts()}
    i = 2
    while f"clone_worker_{i}" in existing:
        i += 1
    return f"clone_worker_{i}"
