from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk

from intermux.binding import OnRunning
from intermux.gui import theme


def ask_on_running(root: tk.Tk, app: str, pids: list[int]) -> OnRunning:
    window = tk.Toplevel(root)
    window.title("Application is running")
    window.configure(bg=theme.BG)
    window.transient(root)
    window.grab_set()

    choice = OnRunning.CANCEL

    def pick(value: OnRunning) -> None:
        nonlocal choice
        choice = value
        window.destroy()

    ttk.Label(
        window, wraplength=380, justify=tk.LEFT,
        text=f"{os.path.basename(app)} is already running ({len(pids)} process(es)).\n\nWhat should be done?",
    ).pack(padx=20, pady=(18, 10))
    for text, value in (
        ("Close and reopen on the selected network", OnRunning.RESTART),
        ("Open a new instance (separate profile)", OnRunning.SEPARATE),
        ("Cancel", OnRunning.CANCEL),
    ):
        ttk.Button(window, text=text, width=40, command=lambda v=value: pick(v)).pack(padx=20, pady=4)

    root.wait_window(window)
    return choice
