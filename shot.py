# -*- coding: utf-8 -*-
"""启动界面 → 两个页签各截一张 → 退出。"""
import sys
from pathlib import Path

import tkinter as tk


def main():
    out = Path(sys.argv[1])
    import app
    try:
        from tkinterdnd2 import TkinterDnD
        root = TkinterDnD.Tk()
    except Exception:
        root = tk.Tk()
    a = app.App(root)

    def grab(name):
        from PIL import ImageGrab
        root.attributes("-topmost", True)
        root.lift()
        root.update()
        x, y = root.winfo_rootx(), root.winfo_rooty()
        w, h = root.winfo_width(), root.winfo_height()
        ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(out.with_name(f"{out.stem}_{name}{out.suffix}"))
        print("saved", name)

    def step2():
        grab("tab1")
        a.nb.select(1)
        root.after(600, step3)

    def step3():
        a.var_url.set("https://example.com/live.m3u8")
        grab("tab2")
        root.destroy()

    root.after(1800, step2)
    root.mainloop()


if __name__ == "__main__":
    main()
