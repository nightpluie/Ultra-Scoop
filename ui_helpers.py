"""ULTRA SCOOP — UI 輔助元件：右鍵選單、快捷鍵綁定、深色文字框。"""

import tkinter as tk
from tkinter.scrolledtext import ScrolledText

import customtkinter as ctk

from app_theme import BG_PANEL, BG_INPUT, TEXT_PRI, ACCENT_BLUE, FT, FT_SM


def _add_copy_menu(widget):
    menu = tk.Menu(widget, tearoff=0,
                   bg=BG_PANEL, fg=TEXT_PRI,
                   activebackground=ACCENT_BLUE, activeforeground=TEXT_PRI,
                   font=FT_SM, bd=0)
    menu.add_command(label="複製",     command=lambda: widget.event_generate("<<Copy>>"))
    menu.add_command(label="貼上",     command=lambda: widget.event_generate("<<Paste>>"))
    menu.add_command(label="剪下",     command=lambda: widget.event_generate("<<Cut>>"))
    menu.add_separator()
    menu.add_command(label="全部選取", command=lambda: _select_all(widget))
    def _popup(e):
        try: menu.tk_popup(e.x_root, e.y_root)
        finally: menu.grab_release()
    widget.bind("<Button-2>",         _popup)
    widget.bind("<Control-Button-1>", _popup)
    # 注意：必須真的回傳字串 "break" 才能阻斷 Tk class 綁定，
    # 否則 <<Paste>> 等會被處理兩次（widget 一次 + class 一次）
    widget.bind("<Command-a>", lambda e: (_select_all(widget), "break")[1])
    widget.bind("<Command-c>", lambda e: (widget.event_generate("<<Copy>>"),  "break")[1])
    widget.bind("<Command-x>", lambda e: (widget.event_generate("<<Cut>>"),   "break")[1])
    widget.bind("<Command-v>", lambda e: (widget.event_generate("<<Paste>>"), "break")[1])


def _select_all(widget):
    widget.tag_add(tk.SEL, "1.0", tk.END)
    widget.mark_set(tk.INSERT, "1.0")
    widget.see(tk.INSERT)
    return "break"


def _add_entry_menu(e: ctk.CTkEntry):
    """為 CTkEntry 加入右鍵選單與 Cmd 快捷鍵（複製/貼上/剪下/全選）。"""
    inner = e._entry  # CTkEntry 內部的 tk.Entry

    menu = tk.Menu(inner, tearoff=0,
                   bg=BG_PANEL, fg=TEXT_PRI,
                   activebackground=ACCENT_BLUE, activeforeground=TEXT_PRI,
                   font=FT_SM, bd=0)
    menu.add_command(label="複製", command=lambda: inner.event_generate("<<Copy>>"))
    menu.add_command(label="貼上", command=lambda: inner.event_generate("<<Paste>>"))
    menu.add_command(label="剪下", command=lambda: inner.event_generate("<<Cut>>"))
    menu.add_separator()
    menu.add_command(label="全選", command=lambda: inner.select_range(0, tk.END))

    def _popup(ev):
        try: menu.tk_popup(ev.x_root, ev.y_root)
        finally: menu.grab_release()

    inner.bind("<Button-2>",         _popup)
    inner.bind("<Control-Button-1>", _popup)
    # 同上：回傳字串 "break" 阻斷 class 綁定，避免雙重貼上
    inner.bind("<Command-a>", lambda ev: (inner.select_range(0, tk.END), "break")[1])
    inner.bind("<Command-c>", lambda ev: (inner.event_generate("<<Copy>>"),  "break")[1])
    inner.bind("<Command-x>", lambda ev: (inner.event_generate("<<Cut>>"),   "break")[1])
    inner.bind("<Command-v>", lambda ev: (inner.event_generate("<<Paste>>"), "break")[1])


def _dark_text(parent, height=8, font=FT, **kwargs):
    """Create a dark-themed ScrolledText widget."""
    text = ScrolledText(
        parent, wrap="word", font=font, height=height,
        bg=BG_INPUT, fg=TEXT_PRI,
        insertbackground=TEXT_PRI,
        selectbackground="#2A4A6A", selectforeground=TEXT_PRI,
        relief="flat", bd=0, padx=8, pady=6,
        **kwargs)
    return text
