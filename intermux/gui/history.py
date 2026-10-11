"""Recently started apps with the interface and DNS they were started with, kept in the user's home."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass

from intermux.system.users import User, give_to

log = logging.getLogger(__name__)

LIMIT = 20


@dataclass
class Item:
    app: str
    interface: str
    dns: str


class History:
    def __init__(self, user: User):
        self.user = user
        self.path = os.path.join(user.home, ".local", "share", "intermux", "history.json")
        self.items = self._load()

    @property
    def apps(self) -> list[str]:
        return [item.app for item in self.items]

    def find(self, app: str) -> Item | None:
        return next((item for item in self.items if item.app == app), None)

    def add(self, app: str, interface: str, dns: str) -> None:
        self.items = ([Item(app, interface, dns)] + [item for item in self.items if item.app != app])[:LIMIT]
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w") as f:
                json.dump([asdict(item) for item in self.items], f, indent=2)
            give_to(self.user, self.path)
        except OSError as exc:
            log.warning("Cannot save history to %s: %s", self.path, exc)

    def _load(self) -> list[Item]:
        try:
            with open(self.path) as f:
                return [Item(**item) for item in json.load(f)][:LIMIT]
        except (OSError, ValueError, TypeError):
            return []
