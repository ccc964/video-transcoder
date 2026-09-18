# -*- coding: utf-8 -*-
"""圆角扁平控件（纯 tkinter，不引入 sv_ttk / ttkthemes 之类的依赖）。

ttk 原生不支持圆角，所以这里用 Canvas 自己画：
- ``RoundCard``      圆角卡片容器
- ``RoundButton``    圆角按钮（保留 ttk 常用 API：state()/config()/cget()）
- ``RoundMenubutton`` 圆角下拉按钮
- ``install_indicators`` 用自绘图片替换 clam 的勾选/单选指示器
  （clam 默认画的是一个粗体「✗」，小尺寸下很像"错误"，必须换）
"""
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

# ------------------------------------------------------------------ 配色
C_BG = "#eff1f5"
C_CARD = "#ffffff"
C_CARD_ALT = "#f7f9fc"
C_BORDER = "#dde1e8"
C_TEXT = "#1f2328"
C_MUTED = "#6b7280"
C_ACCENT = "#2f6fed"
C_ACCENT_D = "#2158c9"
C_ACCENT_SOFT = "#e8effd"
C_OK = "#14804a"
C_ERR = "#c0392b"
C_WARN = "#a15c00"
C_SEL = "#d6e4ff"
C_DISABLED_BG = "#f1f3f7"
C_DISABLED_FG = "#a8adb6"

FONT = "Microsoft YaHei UI"

_font_cache = {}

# 全局缩放（高 DPI 适配）。app 启动时调一次 set_scale()，
# 各控件不传 scale 就用这个默认值，省得每个调用点都写一遍。
_SCALE = 1.0


def set_scale(v):
    global _SCALE
    _SCALE = float(v or 1.0)


def _scale_of(explicit=None):
    return float(explicit) if explicit else _SCALE


def get_font(size=9, weight="normal", master=None):
    """按「Tk 解释器 + 字号 + 字重」缓存字体。

    必须带上解释器：tkfont.Font 绑定在某个 Tk 实例上，窗口销毁后旧对象就失效，
    再被新窗口复用会抛 "can't invoke font command: application has been destroyed"。
    """
    key = (str(getattr(master, "tk", master)), size, weight)
    f = _font_cache.get(key)
    if f is None:
        f = tkfont.Font(root=master, family=FONT, size=size, weight=weight)
        _font_cache[key] = f
    return f


# ------------------------------------------------------------------ 圆角绘制
def round_points(x1, y1, x2, y2, r):
    """给 create_polygon(smooth=True) 用的圆角矩形顶点串。"""
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    return [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
            x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
            x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]


def round_rect(cv, x1, y1, x2, y2, r, **kw):
    kw.setdefault("smooth", True)
    return cv.create_polygon(round_points(x1, y1, x2, y2, r), **kw)


# ------------------------------------------------------------------ 圆角卡片
class RoundCard(tk.Canvas):
    """圆角白卡片。内容放进 ``card.inner``（一个普通 Frame）。"""

    def __init__(self, master, pad=9, radius=10, bg=C_CARD, border=C_BORDER,
                 outer_bg=C_BG, scale=None):
        s = _scale_of(scale)
        px = lambda v: int(round(v * s))
        pad, radius = px(pad), px(radius)
        super().__init__(master, bg=outer_bg, highlightthickness=0, bd=0,
                         takefocus=0)
        self._pad = pad
        self._radius = max(0, radius)
        self._bg = bg
        self._border = border
        self._rect = round_rect(self, 0, 0, 1, 1, self._radius,
                                fill=bg, outline=border, width=1)
        self.inner = tk.Frame(self, bg=bg)
        self._win = self.create_window(pad, pad, window=self.inner, anchor="nw")
        self._lock = False
        self.bind("<Configure>", self._fit)
        self.inner.bind("<Configure>", self._want)

    def _fit(self, _=None):
        if self._lock:
            return
        self._lock = True
        try:
            w = max(2, self.winfo_width())
            h = max(2, self.winfo_height())
            self.coords(self._rect, *round_points(0.5, 0.5, w - 0.5, h - 0.5,
                                                  self._radius))
            self.itemconfigure(self._win, width=max(1, w - 2 * self._pad),
                               height=max(1, h - 2 * self._pad))
        finally:
            self._lock = False

    def _want(self, _=None):
        """把内容的自然尺寸申报给画布，让 pack/grid 知道该留多大。"""
        if self._lock:
            return
        self._lock = True
        try:
            self.configure(width=self.inner.winfo_reqwidth() + 2 * self._pad,
                           height=self.inner.winfo_reqheight() + 2 * self._pad)
        finally:
            self._lock = False


# ------------------------------------------------------------------ 圆角按钮
_KINDS = {
    # kind: (底色, 文字色, 边框色, 悬停底, 按下底)
    "accent": (C_ACCENT, "#ffffff", C_ACCENT, C_ACCENT_D, C_ACCENT_D),
    "default": (C_CARD, C_TEXT, C_BORDER, C_ACCENT_SOFT, "#dbe7ff"),
    "ghost": (C_CARD_ALT, C_TEXT, C_BORDER, C_ACCENT_SOFT, "#dbe7ff"),
    "chip": (C_ACCENT_SOFT, C_ACCENT_D, "#c7d8fb", "#dbe7ff", "#cfdffd"),
    # 页签：选中=白底主色字，未选中=透明底灰字
    "tab_on": (C_CARD, C_ACCENT, C_BORDER, C_CARD, C_CARD),
    "tab_off": (C_BG, C_MUTED, C_BG, "#e7ebf2", "#dee4ee"),
}


class RoundButton(tk.Canvas):
    """圆角按钮。

    故意保留 ttk 的常用接口（``state()`` / ``config()`` / ``cget()``），
    这样调用方从 ttk.Button 换过来不用改逻辑。
    """

    def __init__(self, master, text="", command=None, kind="default",
                 padx=13, pady=6, radius=8, size=9, weight="normal",
                 bg=None, width=None, **kw):
        s = _scale_of(kw.pop("scale", None))
        px = lambda v: int(round(v * s))
        if bg is None:
            try:
                bg = master.cget("bg")
            except Exception:
                bg = C_CARD
        self._bg = bg
        self._kind = kind
        self._command = command
        self._text = text
        self._padx = px(padx)
        self._pady = px(pady)
        self._radius = px(radius)
        self._font = get_font(size, weight, master)
        self._disabled = False
        self._hover = False
        self._pressed = False
        self.menu = None                     # RoundMenubutton 用
        self._caret = kw.pop("caret", False)

        w = px(width) if width else self._natural_w(text)
        f = self._font.metrics("linespace") + 2 * self._pady
        super().__init__(master, width=w, height=f, bg=bg,
                         highlightthickness=0, bd=0, takefocus=0)
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self._draw()

    # ---------- 绘制 ----------
    def _natural_w(self, text):
        return self._font.measure(text) + 2 * self._padx + (14 if self._caret else 0)

    def _colors(self):
        base, fg, bd, hover, press = _KINDS.get(self._kind, _KINDS["default"])
        if self._disabled:
            return C_DISABLED_BG, C_DISABLED_FG, C_BORDER, C_DISABLED_BG, C_DISABLED_BG
        if self._pressed:
            return press, fg, base, hover, press
        if self._hover:
            return hover, fg, base, hover, press
        return base, fg, bd, hover, press

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 1:
            w = int(self.cget("width")) or 40
        if h <= 1:
            h = int(self.cget("height")) or 24
        fill, fg, bd, _, _ = self._colors()
        round_rect(self, 0.5, 0.5, w - 0.5, h - 0.5, self._radius,
                   fill=fill, outline=bd, width=1)
        cx = w / 2
        if self._caret:
            cx = w / 2 - 7
        self.create_text(cx, h / 2, text=self._text, fill=fg, font=self._font)
        if self._caret:
            ax, ay = w - 15, h / 2 - 2
            self.create_polygon(ax - 4, ay, ax + 4, ay, ax, ay + 5,
                                fill=fg if not self._disabled else C_DISABLED_FG,
                                outline="")

    # ---------- 事件 ----------
    def _on_enter(self, _=None):
        self._hover = True
        self.configure(cursor="hand2" if not self._disabled else "")
        self._draw()

    def _on_leave(self, _=None):
        self._hover = self._pressed = False
        self._draw()

    def _on_press(self, _=None):
        if self._disabled:
            return
        self._pressed = True
        self._draw()

    def _on_release(self, e=None):
        was = self._pressed
        self._pressed = False
        self._draw()
        if was and not self._disabled:
            self.invoke()

    def invoke(self):
        if not self._disabled and self._command:
            self._command()

    # ---------- ttk 兼容接口 ----------
    def state(self, spec=None):
        if spec is None:
            return ("disabled",) if self._disabled else ()
        for item in spec:
            if str(item).startswith("!"):
                if str(item)[1:] == "disabled":
                    self._disabled = False
            elif str(item) == "disabled":
                self._disabled = True
        self._draw()
        return ("disabled",) if self._disabled else ()

    def configure(self, **kw):
        redraw = False
        if "state" in kw:
            st = kw.pop("state")
            self._disabled = (str(st) == "disabled")
            redraw = True
        if "text" in kw:
            self._text = kw.pop("text")
            if not kw.get("width"):
                self.configure(width=self._natural_w(self._text))
            redraw = True
        if "command" in kw:
            self._command = kw.pop("command")
        if "kind" in kw:
            self._kind = kw.pop("kind")
            redraw = True
        if kw:
            super().configure(**kw)
        if redraw:
            self._draw()

    config = configure

    def cget(self, key):
        if key == "text":
            return self._text
        if key == "state":
            return "disabled" if self._disabled else "normal"
        if key == "kind":
            return self._kind
        return super().cget(key)

    # 让 btn["menu"] = m 这种写法可用
    def __setitem__(self, key, value):
        if key == "menu":
            self.menu = value
            self._caret = True
            self._draw()
        else:
            super().__setitem__(key, value)

    def __getitem__(self, key):
        if key == "menu":
            return self.menu
        return super().__getitem__(key)


class RoundMenubutton(RoundButton):
    """看起来像按钮、点开是下拉菜单。"""

    def __init__(self, master, text="", kind="default", **kw):
        kw["caret"] = True
        super().__init__(master, text=text, kind=kind, **kw)
        self.bind("<ButtonRelease-1>", self._popup)

    def _popup(self, _=None):
        if self._disabled or self.menu is None:
            return
        self.menu.post(self.winfo_rootx(),
                       self.winfo_rooty() + self.winfo_height() + 2)
        self.menu.grab_release()


# ------------------------------------------------------------------ 圆角输入框
class RoundEntry(tk.Canvas):
    """圆角输入槽：外面自绘圆角，里面塞一个无边框 ttk.Entry。"""

    def __init__(self, master, textvariable=None, bg=None, radius=8,
                 height=None, radius_pad=7, **kw):
        s = _scale_of(kw.pop("scale", None))
        px = lambda v: int(round(v * s))
        if bg is None:
            try:
                bg = master.cget("bg")
            except Exception:
                bg = C_CARD
        self._bg = bg
        self._s = s
        self._radius = px(radius)
        self._pad = px(radius_pad)
        self._focus = False
        h = px(height if height else 32)
        super().__init__(master, bg=bg, height=h,
                         highlightthickness=0, bd=0, takefocus=0)
        # 必须先 super().__init__，否则 self.tk 还不存在，里面建不了子控件
        self.entry = ttk.Entry(self, textvariable=textvariable, **kw)
        self._rect = round_rect(self, 0, 0, 1, 1, self._radius,
                                fill=C_CARD, outline=C_BORDER, width=1)
        self._win = self.create_window(self._pad, 2, window=self.entry, anchor="nw")
        self.bind("<Configure>", self._fit)
        self.entry.bind("<FocusIn>", lambda e: self._set_focus(True))
        self.entry.bind("<FocusOut>", lambda e: self._set_focus(False))

    def _set_focus(self, on):
        self._focus = on
        self.itemconfigure(self._rect, outline=C_ACCENT if on else C_BORDER)

    def _fit(self, _=None):
        px = lambda v: int(round(v * self._s))
        w, h = max(2, self.winfo_width()), max(2, self.winfo_height())
        self.coords(self._rect, *round_points(0.5, 0.5, w - 0.5, h - 0.5,
                                              self._radius))
        self.itemconfigure(self._win, width=max(1, w - 2 * self._pad),
                           height=max(1, h - px(4)))

    # 转发常用方法，调用方当普通 Entry 用即可
    def get(self):
        return self.entry.get()

    def set(self, v):
        return self.entry.set(v) if hasattr(self.entry, "set") else None

    def focus_set(self):
        self.entry.focus_set()


# ------------------------------------------------------------------ 圆角页签
class TabBar(tk.Frame):
    """胶囊式圆角页签，API 对齐 ttk.Notebook 的常用子集。

    ttk.Notebook 的页签是直角、样式改不动，所以自己用圆角按钮拼一条。
    页面控件请挂在 ``tabbar.body`` 下（Tk 不能换父容器，所以得由调用方建对）。
    """

    def __init__(self, master, scale=None, bg=C_BG, gap=6):
        s = _scale_of(scale)
        px = lambda v: int(round(v * s))
        super().__init__(master, bg=bg)
        self.scale = s
        self._bg = bg
        self._gap = px(gap)
        self._strip = tk.Frame(self, bg=bg)
        self._strip.pack(fill="x")
        self.body = tk.Frame(self, bg=bg)
        self.body.pack(fill="both", expand=True)
        self._pages = []
        self._cur = -1

    def add(self, child, text=""):
        idx = len(self._pages)
        btn = RoundButton(self._strip, text=text, kind="tab_off", scale=self.scale,
                          padx=18, pady=6, radius=9, size=10, weight="bold",
                          command=lambda i=idx: self.select(i))
        btn.pack(side="left", padx=(0, self._gap))
        self._pages.append([btn, child])
        if self._cur < 0:
            self.select(0)
        return child

    def select(self, idx=None):
        if idx is None:
            return self._cur
        try:
            idx = int(idx)
        except Exception:
            return self._cur
        if not 0 <= idx < len(self._pages):
            return self._cur
        for i, (btn, page) in enumerate(self._pages):
            if i == idx:
                btn.configure(kind="tab_on")
                if not page.winfo_ismapped():
                    page.pack(fill="both", expand=True)
            else:
                btn.configure(kind="tab_off")
                page.pack_forget()
        self._cur = idx
        return idx

    def tabs(self):
        return tuple(str(p) for _, p in self._pages)

    def index(self, child):
        for i, (_, page) in enumerate(self._pages):
            if str(page) == str(child):
                return i
        return -1


# ------------------------------------------------------------------ 圆角滑块
class RoundSlider(tk.Canvas):
    """圆角滑块（ttk.Scale 的轨道很细、滑块很小，跟圆角风格不搭）。"""

    def __init__(self, master, variable=None, from_=16, to=32, command=None,
                 bg=None, height=26, knob=9, thickness=5, scale=None):
        s = _scale_of(scale)
        px = lambda v: int(round(v * s))
        if bg is None:
            try:
                bg = master.cget("bg")
            except Exception:
                bg = C_CARD
        self._bg = bg
        self._h = px(height)
        self._knob = px(knob)
        self._th = px(thickness)
        self._var = variable
        self._from, self._to = from_, to
        self._cmd = command
        self._disabled = False
        self._active = False
        super().__init__(master, bg=bg, height=self._h,
                         highlightthickness=0, bd=0, takefocus=0)
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Enter>", lambda e: self._draw())
        self.bind("<Leave>", lambda e: self._draw())
        if variable is not None:
            variable.trace_add("write", lambda *_: self._draw())
        self._draw()

    def _value(self):
        try:
            return int(self._var.get())
        except Exception:
            return self._from

    def _geom(self):
        w = max(self._knob * 2 + 4, self.winfo_width())
        pad = self._knob / 2
        return pad, w - pad, self._h / 2

    def _draw(self):
        self.delete("all")
        if not self._var:
            return
        try:
            if not self.winfo_ismapped() and self.winfo_width() <= 1:
                return
        except Exception:
            pass
        x0, x1, cy = self._geom()
        span = max(1, self._to - self._from)
        frac = min(1.0, max(0.0, (self._value() - self._from) / span))
        kx = x0 + frac * (x1 - x0)
        t = self._th / 2
        round_rect(self, x0, cy - t, x1, cy + t, t, fill="#e3e8f0", outline="")
        if kx > x0 + 0.5:
            round_rect(self, x0, cy - t, kx, cy + t, t, fill=C_ACCENT, outline="")
        ring = C_DISABLED_FG if self._disabled else C_ACCENT
        r = self._knob / 2
        self.create_oval(kx - r, cy - r, kx + r, cy + r, fill="#ffffff",
                         outline=ring, width=max(2, int(round(2 * (self._knob / 18)))))

    def _pos_to_value(self, x):
        x0, x1, _ = self._geom()
        frac = 0.0 if x1 <= x0 else (x - x0) / (x1 - x0)
        frac = min(1.0, max(0.0, frac))
        return round(self._from + frac * (self._to - self._from))

    def _press(self, e):
        if self._disabled:
            return
        self._active = True
        self._apply(e.x)

    def _drag(self, e):
        if self._disabled or not self._active:
            return
        self._apply(e.x)

    def _release(self, _=None):
        self._active = False

    def _apply(self, x):
        v = self._pos_to_value(x)
        if v != self._value():
            self._var.set(v)
            if self._cmd:
                self._cmd(str(v))
        self._draw()

    # ttk 风格接口
    def configure(self, **kw):
        if "state" in kw:
            self._disabled = (str(kw.pop("state")) == "disabled")
            self._draw()
        if kw:
            super().configure(**kw)

    config = configure

    def cget(self, key):
        if key == "state":
            return "disabled" if self._disabled else "normal"
        return super().cget(key)


# ------------------------------------------------------------------ 勾选指示器
_ICON_REF = {}          # 必须持有引用，否则 PhotoImage 会被 GC 掉
_CARD_BG_FOR_ICON = C_CARD


# 纯 tkinter 绘制指示器图标（不依赖 PIL —— 引入 PIL 会让打包体积涨 7.6MB）
def _sdf_rrect(x, y, w, h, r):
    """圆角矩形有符号距离场：<0 在内部。"""
    qx = abs(x - w / 2.0) - (w / 2.0 - r)
    qy = abs(y - h / 2.0) - (h / 2.0 - r)
    ax, ay = max(qx, 0.0), max(qy, 0.0)
    return (ax * ax + ay * ay) ** 0.5 + min(max(qx, qy), 0.0) - r


def _sdf_seg(x, y, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    l2 = dx * dx + dy * dy
    t = 0.0 if not l2 else max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / l2))
    px, py = x1 + t * dx, y1 + t * dy
    return ((x - px) ** 2 + (y - py) ** 2) ** 0.5


def _hex2rgb(c):
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _make_icon(master, n, shape, fill, outline, tick=None, bg=C_CARD,
               border=2.0, tick_w=2.4, dot=False):
    """画一个 n×n 指示器图标。

    用 3×3 超采样 + 覆盖率混色实现抗锯齿（PIL 那套的等价替代，但零依赖）。
    背景不透明：直接把卡片底色填在圆角外，贴到卡片上视觉上就是圆的。
    """
    img = tk.PhotoImage(master=master, width=n, height=n)
    F = 3
    S = float(n * F)
    r = S / 2.0 - 1.0 if shape == "circle" else max(2.0, S * 0.24)
    bw = max(1.0, border * (S / n) * 0.5)
    tw = tick_w * (S / n)
    bgc, fc, oc = _hex2rgb(bg), _hex2rgb(fill), _hex2rgb(outline)
    tc = _hex2rgb(tick) if tick else None
    # 勾的两段线（相对尺寸，和系统勾选图标一致）
    p1 = (0.24 * S, 0.52 * S)
    p2 = (0.44 * S, 0.72 * S)
    p3 = (0.78 * S, 0.30 * S)
    dr = 0.30 * S / 2.0
    cc = (S / 2.0, S / 2.0)
    rows = []
    for py in range(n):
        row = []
        for pxi in range(n):
            acc = [0.0, 0.0, 0.0]
            for sy in range(F):
                for sx in range(F):
                    x = (pxi * F + sx + 0.5)
                    y = (py * F + sy + 0.5)
                    if shape == "circle":
                        d = ((x - cc[0]) ** 2 + (y - cc[1]) ** 2) ** 0.5 - (S / 2.0 - bw / 2.0)
                    else:
                        d = _sdf_rrect(x, y, S, S, r)
                    if dot and ((x - cc[0]) ** 2 + (y - cc[1]) ** 2) ** 0.5 <= dr:
                        col = oc
                    elif tc is not None and tick:
                        dmin = min(_sdf_seg(x, y, *p1, *p2), _sdf_seg(x, y, *p2, *p3))
                        if dmin <= tw / 2.0:
                            col = tc
                        elif abs(d) <= bw / 2.0:
                            col = oc
                        elif d < 0:
                            col = fc
                        else:
                            col = bgc
                    elif abs(d) <= bw / 2.0:
                        col = oc
                    elif d < 0:
                        col = fc
                    else:
                        col = bgc
                    acc[0] += col[0]
                    acc[1] += col[1]
                    acc[2] += col[2]
            k = float(F * F)
            row.append("#%02x%02x%02x" % (int(acc[0] / k + 0.5),
                                          int(acc[1] / k + 0.5),
                                          int(acc[2] / k + 0.5)))
        rows.append("{" + " ".join(row) + "}")
    img.put(" ".join(rows))
    return img


def make_indicators(scale=1.0, master=None):
    """生成勾选框/单选钮的指示器图片（纯 tkinter，无第三方依赖）。"""
    if master is None:
        return None
    s = max(1.0, float(scale))
    n = max(14, int(round(15 * s)))
    src = _CARD_BG_FOR_ICON
    out = {}
    for key, fill, outline, tick in (
            ("check_off", "#ffffff", "#c6ccd8", None),
            ("check_on", C_ACCENT, C_ACCENT, "#ffffff"),
            ("check_off_dis", C_DISABLED_BG, "#e2e6ec", None),
            ("check_on_dis", "#b9c6df", "#b9c6df", "#ffffff")):
        out[key] = _make_icon(master, n, "square", fill, outline, tick=tick, bg=src)
    for key, fill, outline, dot in (
            ("radio_off", "#ffffff", "#c6ccd8", False),
            ("radio_on", "#ffffff", C_ACCENT, True),
            ("radio_off_dis", C_DISABLED_BG, "#e2e6ec", False),
            ("radio_on_dis", "#ffffff", "#b9c6df", True)):
        out[key] = _make_icon(master, n, "circle", fill, outline, bg=src, dot=dot)
    return out


def install_indicators(style, scale=1.0, master=None, prefix="Round",
                       style_names=("TCheckbutton", "TRadiobutton")):
    """把 ttk 的勾选/单选指示器换成自绘圆角图片。

    直接把布局装到 **默认样式名**（TCheckbutton / TRadiobutton）上，
    这样所有 `ttk.Checkbutton(...)` 调用处都不用改。

    返回 True 表示替换成功；False 表示调用方应继续用 clam 默认样式。
    """
    icons = make_indicators(scale, master)
    if not icons:
        return False
    _ICON_REF.clear()
    _ICON_REF.update(icons)
    ck_style, rd_style = style_names
    try:
        style.element_create(f"{prefix}.Checkbutton.indicator", "image",
                             icons["check_off"],
                             ("selected", icons["check_on"]),
                             ("disabled", icons["check_off_dis"]),
                             ("disabled", "selected", icons["check_on_dis"]),
                             sticky="w")
        style.element_create(f"{prefix}.Radiobutton.indicator", "image",
                             icons["radio_off"],
                             ("selected", icons["radio_on"]),
                             ("disabled", icons["radio_off_dis"]),
                             ("disabled", "selected", icons["radio_on_dis"]),
                             sticky="w")
        style.layout(ck_style, [
            ("Checkbutton.padding", {"sticky": "nswe", "children": [
                (f"{prefix}.Checkbutton.indicator", {"side": "left", "sticky": ""}),
                ("Checkbutton.focus", {"side": "left", "sticky": "w", "children": [
                    ("Checkbutton.label", {"sticky": "nswe"})]})]})])
        style.layout(rd_style, [
            ("Radiobutton.padding", {"sticky": "nswe", "children": [
                (f"{prefix}.Radiobutton.indicator", {"side": "left", "sticky": ""}),
                ("Radiobutton.focus", {"side": "left", "sticky": "w", "children": [
                    ("Radiobutton.label", {"sticky": "nswe"})]})]})])
        return True
    except Exception:
        return False
