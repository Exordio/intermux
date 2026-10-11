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
    # The drop-down list of a combobox is a plain Tk listbox, styled through the option database.
    root.option_add("*TCombobox*Listbox.background", FIELD)
    root.option_add("*TCombobox*Listbox.foreground", FG)
    root.option_add("*TCombobox*Listbox.selectBackground", SELECTION)
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
    root.option_add("*TCombobox*Listbox.font", FONT)
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


def table(parent: tk.Widget, columns: dict[str, int], height: int,
          tree_column: tuple[str, int] | None = None) -> ttk.Treeview:
    """Treeview with the given column titles and widths, optionally with a hierarchy column first."""
    tree = ttk.Treeview(parent, columns=list(columns), height=height, selectmode="browse",
                        show="tree headings" if tree_column else "headings")
    if tree_column:
        tree.heading("#0", text=tree_column[0], anchor=tk.W)
        tree.column("#0", width=tree_column[1], minwidth=60, anchor=tk.W)
    for title, width in columns.items():
        tree.heading(title, text=title, anchor=tk.W)
        tree.column(title, width=width, minwidth=60, anchor=tk.W)
    return tree
