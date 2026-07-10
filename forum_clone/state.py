import json
import os
import threading


class State:
    """Persists clone progress to disk so a run can be safely resumed
    after a crash, a flood-wait, or a manual re-run for new content."""

    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self.data = self._load()

    def _load(self):
        if os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"target_chat_id": None, "topics": {}}

    def save(self):
        with self._lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)

    @property
    def target_chat_id(self):
        return self.data.get("target_chat_id")

    @target_chat_id.setter
    def target_chat_id(self, value):
        self.data["target_chat_id"] = value
        self.save()

    def get_topic(self, source_topic_id):
        return self.data["topics"].get(str(source_topic_id))

    def set_topic_mapping(self, source_topic_id, target_topic_id):
        entry = self.data["topics"].setdefault(str(source_topic_id), {})
        entry["target_topic_id"] = target_topic_id
        entry.setdefault("last_msg_id", 0)
        self.save()

    def set_last_msg_id(self, source_topic_id, msg_id):
        entry = self.data["topics"].setdefault(str(source_topic_id), {})
        entry["last_msg_id"] = msg_id
        self.save()

    def reset(self):
        self.data = {"target_chat_id": None, "topics": {}}
        self.save()
