from __future__ import annotations

import tkinter as tk
from tkinter import ttk

BG = "#0d1117"
FG = "#c9d1d9"
FIELD = "#161b22"
BUTTON = "#21262d"
ACCENT = "#58a6ff"
SELECTION = "#1f6feb"
OK = "#57ab5a"
WARN = "#e3b341"
WARN_BG = "#2d1d00"
FONT = ("monospace", 10)


def apply(root: tk.Tk) -> None:
    root.configure(bg=BG)
    style = ttk.Style(root)
    style.theme_use("default")
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=FG)
    style.configure("TButton", background=BUTTON, foreground=ACCENT, borderwidth=1)
    style.configure("TLabelframe", background=BG, foreground=FG)
    style.configure("TLabelframe.Label", background=BG, foreground=FG)
    style.configure("TEntry", fieldbackground=FIELD, foreground=FG, insertcolor=FG)
    style.configure("TCombobox", fieldbackground=FIELD, background=BUTTON, foreground=FG, arrowcolor=FG, insertcolor=FG)
    style.configure("Treeview", background=FIELD, fieldbackground=FIELD, foreground=FG, font=FONT, rowheight=22)
    style.configure("Treeview.Heading", background=BUTTON, foreground=FG, font=FONT, padding=(5, 2))
    style.map("Treeview", background=[("selected", SELECTION)], foreground=[("selected", "#ffffff")])
    style.map("TCombobox",
              fieldbackground=[("readonly", FIELD)], foreground=[("readonly", FG)],
              selectbackground=[("readonly", FIELD)], selectforeground=[("readonly", FG)])


def table(parent: tk.Widget, columns: dict[str, int], height: int) -> ttk.Treeview:
    """Treeview with the given column titles and widths."""
    tree = ttk.Treeview(parent, columns=list(columns), show="headings", height=height, selectmode="browse")
    for title, width in columns.items():
        tree.heading(title, text=title, anchor=tk.W)
        tree.column(title, width=width, minwidth=60, anchor=tk.W)
    return tree
