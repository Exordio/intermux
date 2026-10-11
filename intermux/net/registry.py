"""What each namespace serves. Kept in /run, so it disappears on reboot together with the namespaces."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

STATE_DIR = "/run/intermux"


@dataclass
class Entry:
    namespace: str
    interface: str
    subnet: str
    route: str
    dns: list[str]
    dns_auto: bool
    apps: list[str] = field(default_factory=list)


def load(namespace: str) -> Entry | None:
    try:
        with open(_path(namespace)) as f:
            return Entry(**json.load(f))
    except (OSError, ValueError, TypeError):
        return None


def save(entry: Entry) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(_path(entry.namespace), "w") as f:
        json.dump(asdict(entry), f, indent=2)


def remove(namespace: str) -> None:
    try:
        os.remove(_path(namespace))
    except FileNotFoundError:
        pass


def add_app(namespace: str, app: str) -> None:
    entry = load(namespace)
    if entry and app not in entry.apps:
        entry.apps.append(app)
        save(entry)


def _path(namespace: str) -> str:
    return os.path.join(STATE_DIR, f"{namespace}.json")
