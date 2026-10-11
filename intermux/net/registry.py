"""What each namespace serves. Kept in /run, so it disappears on reboot together with the namespaces."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

STATE_DIR = "/run/intermux"


@dataclass
class App:
    path: str
    separate_profile: bool = False


@dataclass
class Entry:
    namespace: str
    interface: str
    subnet: str
    route: str
    dns: list[str]
    dns_auto: bool
    apps: list[App] = field(default_factory=list)
    limit_down: float | None = None
    limit_up: float | None = None
    """Mbit/s, None for no limit."""


def load(namespace: str) -> Entry | None:
    try:
        with open(_path(namespace)) as f:
            data = json.load(f)
        data["apps"] = [App(app) if isinstance(app, str) else App(**app) for app in data.get("apps", [])]
        return Entry(**data)
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


def add_app(namespace: str, app: App) -> None:
    entry = load(namespace)
    if entry:
        entry.apps = [known for known in entry.apps if known.path != app.path] + [app]
        save(entry)


def remove_app(namespace: str, path: str) -> None:
    entry = load(namespace)
    if entry:
        entry.apps = [app for app in entry.apps if app.path != path]
        save(entry)


def _path(namespace: str) -> str:
    return os.path.join(STATE_DIR, f"{namespace}.json")
