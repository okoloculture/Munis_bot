"""Хранилище соответствия «категория -> сообщения целевого канала»."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

STATE_VERSION = 1
DEFAULT_STATE_PATH = Path("state.json")


@dataclass
class CategorySlot:
    """Сообщения целевого канала, отведённые под одну категорию."""

    title: str
    message_ids: list[int] = field(default_factory=list)
    content_hash: str | None = None


@dataclass
class State:
    """Состояние синхронизации."""

    slots: dict[str, CategorySlot] = field(default_factory=dict)
    nav_message_id: int | None = None
    nav_hash: str | None = None
    excel_message_id: int | None = None
    excel_hash: str | None = None
    info_message_id: int | None = None
    info_hash: str | None = None

    def to_dict(self) -> dict:
        return {
            "version": STATE_VERSION,
            "nav_message_id": self.nav_message_id,
            "nav_hash": self.nav_hash,
            "excel_message_id": self.excel_message_id,
            "excel_hash": self.excel_hash,
            "info_message_id": self.info_message_id,
            "info_hash": self.info_hash,
            "slots": {
                key: {
                    "title": slot.title,
                    "message_ids": slot.message_ids,
                    "hash": slot.content_hash,
                }
                for key, slot in self.slots.items()
            },
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "State":
        slots: dict[str, CategorySlot] = {}
        for key, entry in (raw.get("slots") or {}).items():
            if not isinstance(entry, dict):
                continue
            message_ids = [int(i) for i in entry.get("message_ids", []) if isinstance(i, int)]
            slots[key] = CategorySlot(
                title=str(entry.get("title", key)),
                message_ids=message_ids,
                content_hash=entry.get("hash"),
            )
        nav_id = raw.get("nav_message_id")
        excel_id = raw.get("excel_message_id")
        info_id = raw.get("info_message_id")
        return cls(
            slots=slots,
            nav_message_id=int(nav_id) if isinstance(nav_id, int) else None,
            nav_hash=raw.get("nav_hash"),
            excel_message_id=int(excel_id) if isinstance(excel_id, int) else None,
            excel_hash=raw.get("excel_hash"),
            info_message_id=int(info_id) if isinstance(info_id, int) else None,
            info_hash=raw.get("info_hash"),
        )


def load_state(path: Path = DEFAULT_STATE_PATH) -> State:
    """Прочитать состояние; при отсутствии или порче файла вернуть пустое."""
    if not path.exists():
        return State()
    try:
        return State.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        log.error("Файл состояния нечитаем (%s); начинаю с пустого", exc)
        return State()


def save_state(state: State, path: Path = DEFAULT_STATE_PATH) -> None:
    """Атомарная запись состояния."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
