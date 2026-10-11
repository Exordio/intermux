import tkinter as tk
from tkinter import ttk

BG = "#0d1117"
FG = "#c9d1d9"
FIELD = "#161b22"
BUTTON = "#21262d"
ACCENT = "#58a6ff"
BORDER = "#30363d"
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
    style.configure("TEntry", fieldbackground=FIELD, foreground=FG)
    style.configure("TCombobox", fieldbackground=FIELD, background=BUTTON, foreground=FG, arrowcolor=FG)
    style.map("TCombobox",
              fieldbackground=[("readonly", FIELD)], foreground=[("readonly", FG)],
              selectbackground=[("readonly", FIELD)], selectforeground=[("readonly", FG)])


def listbox(parent: tk.Widget) -> tk.Listbox:
    return tk.Listbox(
        parent, bg=FIELD, fg=FG, font=FONT, relief=tk.FLAT, borderwidth=1,
        highlightthickness=1, highlightbackground=BORDER,
        selectbackground=SELECTION, selectforeground="#ffffff",
    )
