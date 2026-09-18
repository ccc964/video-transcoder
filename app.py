# -*- coding: utf-8 -*-
"""视频转码 - 图形界面（tkinter + ttk）：转码 + 直播源录制。"""
import queue
import re
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

try:
    from ctypes import windll
    windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

import core

MODE_LABELS = [
    ("copy", "无损转封装（不重编码，最快，画质零损失）"),
    ("h264", "H.264 重编码（兼容性最好，体积小）"),
    ("h265", "H.265 重编码（体积最小，速度稍慢）"),
]

# ------------------------------------------------------------------ 配色
# 配色与圆角控件都在 ui.py 里，这里直接复用，避免两处维护
import ui
from ui import (C_ACCENT, C_ACCENT_D, C_ACCENT_SOFT, C_BG, C_BORDER, C_CARD,
                C_CARD_ALT, C_DISABLED_BG, C_DISABLED_FG, C_ERR, C_MUTED,
                C_OK, C_SEL, C_TEXT, C_WARN, FONT)


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("视频转码 · ffmpeg")
        self.files = []
        self.q = queue.Queue()
        self.worker = None
        self.stop_event = threading.Event()
        self.rec_worker = None
        self.stop_event_rec = threading.Event()
        self.rec_start = 0.0
        self.probe_worker = None
        self._probe_room = None          # 最近一次解析结果（供「复制推流地址」用）
        self.dl_worker = None
        self.stop_event_dl = threading.Event()
        self.cfg = core.load_config(core.app_dir())
        # 曾解析过的主播（快捷入口）；构建界面时要用，所以先读出来
        self.history = [h for h in (self.cfg.get("history") or []) if isinstance(h, dict)]
        self._probe_input = ""
        self._probe_pending = None
        self.nvenc_h264 = False
        self.nvenc_h265 = False
        try:
            self.scale = root.winfo_fpixels("1i") / 72.0
        except Exception:
            self.scale = 1.0

        self.var_ffmpeg = tk.StringVar()
        self.var_outdir = tk.StringVar()
        self.var_mode = tk.StringVar(value="copy")
        self.var_format = tk.StringVar(value="mp4")
        self.var_cq = tk.IntVar(value=23)
        self.var_overwrite = tk.BooleanVar(value=False)

        self._build_ui()
        self._restore_cfg()
        self._enable_dnd()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(80, self._poll)
        self.root.after(60, self._detect_ffmpeg_bg)
        self._auto_size()

    # ---------- UI ----------

    def _auto_size(self):
        self.root.update_idletasks()
        # ttk.Notebook 只申报「当前页」的需求尺寸，而两个页签高度不一样。
        # 必须挨个切一遍取最大值，否则按矮的那页定窗口，切到高的那页就会
        # 凭空冒出滚动条（切页只发生在窗口显示前，不会有闪烁）。
        cur = self.nb.select()
        need = self.root.winfo_reqheight()
        try:
            for i in range(len(self.nb.tabs())):
                self.nb.select(i)
                self.root.update_idletasks()
                need = max(need, self.root.winfo_reqheight())
        finally:
            self.nb.select(cur)
            self.root.update_idletasks()
        s = self.scale
        need_w = max(self.root.winfo_reqwidth(), int(1000 * s))
        need_h = max(need, int(750 * s))
        w = min(need_w + 24, self.root.winfo_screenwidth() - 60)
        h = min(need_h + 24, self.root.winfo_screenheight() - 110)
        self.root.geometry(f"{w}x{h}")

    def _setup_style(self):
        """统一字体与控件外观（clam 主题 + 手工调色，零额外依赖）。"""
        s = self.scale
        px = lambda v: int(v * s)
        ui.set_scale(self.scale)      # 圆角控件默认按这个缩放
        st = ttk.Style(self.root)
        try:
            st.theme_use("clam")          # clam 最容易改色，vista 主题改不动
        except Exception:
            pass

        # ---- 容器 ----
        st.configure("TFrame", background=C_BG)
        st.configure("Tab.TFrame", background=C_BG)
        st.configure("Card.TFrame", background=C_CARD)
        st.configure("CardAlt.TFrame", background=C_CARD_ALT)

        # ---- 文字 ----
        st.configure("TLabel", background=C_BG, foreground=C_TEXT, font=(FONT, 9))
        st.configure("Card.TLabel", background=C_CARD, foreground=C_TEXT,
                     font=(FONT, 9))
        st.configure("CardTitle.TLabel", background=C_CARD, foreground=C_TEXT,
                     font=(FONT, 10, "bold"))
        st.configure("CardHint.TLabel", background=C_CARD, foreground=C_MUTED,
                     font=(FONT, 8))
        st.configure("Hint.TLabel", background=C_BG, foreground=C_MUTED,
                     font=(FONT, 8))
        st.configure("Brand.TLabel", background=C_CARD, foreground=C_TEXT,
                     font=(FONT, 14, "bold"))
        st.configure("BrandSub.TLabel", background=C_CARD, foreground=C_MUTED,
                     font=(FONT, 8))

        # ---- 按钮 ----
        # 按钮已全部换成 ui.RoundButton（Canvas 自绘圆角），ttk 的 TButton /
        # Accent.TButton / Ghost.TButton / Chip.TButton / TMenubutton 样式不再需要。

        # ---- 输入 ----
        st.configure("TEntry", font=(FONT, 9), padding=(px(6), px(4)),
                     fieldbackground=C_CARD, background=C_CARD,
                     foreground=C_TEXT, bordercolor=C_BORDER, relief="flat",
                     insertcolor=C_TEXT)
        st.map("TEntry", bordercolor=[("focus", C_ACCENT)],
               lightcolor=[("focus", C_ACCENT)], darkcolor=[("focus", C_ACCENT)])

        st.configure("TCombobox", font=(FONT, 9), padding=(px(6), px(3)),
                     fieldbackground=C_CARD, background=C_CARD,
                     foreground=C_TEXT, bordercolor=C_BORDER, relief="flat",
                     arrowcolor=C_MUTED)
        st.map("TCombobox",
               fieldbackground=[("readonly", C_CARD), ("disabled", C_CARD_ALT)],
               bordercolor=[("focus", C_ACCENT), ("hover", C_ACCENT)])
        # 下拉列表是原生 Tk listbox，只能走 option 数据库
        self.root.option_add("*TCombobox*Listbox.background", C_CARD)
        self.root.option_add("*TCombobox*Listbox.foreground", C_TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", C_ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
        self.root.option_add("*TCombobox*Listbox.font", (FONT, 9))
        self.root.option_add("*TCombobox*Listbox.borderWidth", 0)

        # ---- 勾选 / 单选 ----
        # clam 默认把「已勾选」画成一个粗体「✗」，小尺寸下很扎眼。这里用自绘的
        # 圆角指示器图片替换（主色底 + 白勾）；PIL 不可用时自动退回默认样式。
        if not ui.install_indicators(st, self.scale, master=self.root):
            st.map("TCheckbutton",
                   indicatorbackground=[("selected", C_ACCENT),
                                        ("!selected", C_CARD)],
                   indicatorforeground=[("selected", "#ffffff"),
                                        ("!selected", C_MUTED)])
        st.configure("TCheckbutton", background=C_CARD, foreground=C_TEXT,
                     font=(FONT, 9), focuscolor=C_CARD, relief="flat",
                     padding=(0, px(2)))
        st.map("TCheckbutton", background=[("active", C_CARD)])
        st.configure("TRadiobutton", background=C_CARD, foreground=C_TEXT,
                     font=(FONT, 9), focuscolor=C_CARD, relief="flat",
                     padding=(0, px(2)))
        st.map("TRadiobutton", background=[("active", C_CARD)])

        # ---- 表格 ----
        st.configure("Treeview", font=(FONT, 9), rowheight=px(24),
                     background=C_CARD, fieldbackground=C_CARD,
                     foreground=C_TEXT, bordercolor=C_BORDER, relief="flat")
        st.map("Treeview", background=[("selected", C_SEL)],
               foreground=[("selected", C_TEXT)])
        st.configure("Treeview.Heading", font=(FONT, 9, "bold"),
                     background=C_CARD_ALT, foreground=C_MUTED,
                     bordercolor=C_BORDER, relief="flat", padding=(px(6), px(5)))
        st.map("Treeview.Heading", background=[("active", "#eaeef5")])

        # ---- 滑块 / 进度 ----
        st.configure("TScale", background=C_CARD, troughcolor="#e6eaf1",
                     bordercolor=C_BORDER, lightcolor=C_ACCENT,
                     darkcolor=C_ACCENT)
        st.configure("Horizontal.TScale", background=C_CARD,
                     troughcolor="#e6eaf1", bordercolor=C_BORDER)
        st.configure("TProgressbar", background=C_ACCENT, troughcolor="#e6eaf1",
                     bordercolor=C_BORDER, lightcolor=C_ACCENT,
                     darkcolor=C_ACCENT, thickness=px(12))
        st.configure("TScrollbar", background=C_CARD_ALT, troughcolor=C_BG,
                     bordercolor=C_BG, arrowcolor=C_MUTED, relief="flat")
        st.map("TScrollbar", background=[("active", "#d3d9e3")])

        st.configure("TSpinbox", font=(FONT, 9), padding=(px(4), px(2)),
                     fieldbackground=C_CARD, background=C_CARD,
                     foreground=C_TEXT, bordercolor=C_BORDER, arrowcolor=C_MUTED,
                     relief="flat")

        # ---- 分隔线 ----
        st.configure("Sep.TFrame", background=C_BORDER)

    # ---------- 布局小工具 ----------

    def _card(self, parent, pad=None):
        """一张圆角白卡片；内容放进返回值的 .inner。"""
        s = self.scale
        pad = pad if pad is not None else int(8 * s)
        return ui.RoundCard(parent, pad=pad, radius=int(12 * s), scale=s)

    def _section(self, parent, text, hint=""):
        """卡片内的小标题行，返回 (行容器, 内容容器)。"""
        s = self.scale
        px = lambda v: int(v * s)
        row = tk.Frame(parent, bg=C_CARD)
        row.pack(fill="x")
        ttk.Label(row, text=text, style="CardTitle.TLabel").pack(side="left")
        if hint:
            ttk.Label(row, text=hint, style="CardHint.TLabel").pack(
                side="left", padx=(px(8), 0))
        return row

    def _hline(self, parent, top=0, bottom=0):
        s = self.scale
        px = lambda v: int(v * s)
        f = tk.Frame(parent, bg=C_BORDER, height=1)
        f.pack(fill="x", pady=(px(top), px(bottom)))
        return f

    def _scrollable(self, parent, min_h=300):
        """把页签内容放进可滚动容器。

        为什么需要：窗口高度受屏幕限制（winfo_screenheight-110）。在
        1080p@150%、1440p@200% 这类「大字体」设置下，可用高度只有 700 逻辑像素
        左右，几排设置卡加上日志放不下，末尾的「开始录制」按钮会被裁掉且点不到。
        这里让内容自己去滚动，窗口再矮也不会丢控件。

        min_h 只是向窗口申报的最小高度，窗口够大时画布会自动撑开显示全部内容。
        """
        s = self.scale
        px = lambda v: int(v * s)
        wrap = ttk.Frame(parent, style="Tab.TFrame")
        wrap.pack(fill="both", expand=True)

        canvas = tk.Canvas(wrap, bg=C_BG, highlightthickness=0, bd=0,
                           height=px(min_h), yscrollincrement=px(20))
        canvas._vt_scroll = True        # 标记，方便测试定位（tab 里也有别的 Canvas）
        vs = ttk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = ttk.Frame(canvas, style="Tab.TFrame")
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        lock = {"busy": False}

        def sync(_=None):
            if lock["busy"]:
                return
            lock["busy"] = True
            try:
                # 用 reqheight（内容自然高度）而不是 bbox，避免「设高→bbox 变化→
                # 再设高」的自激循环
                natural = inner.winfo_reqheight()
                # 把内容高度申报给布局：这样窗口会按「最高的那个页签」自动定尺寸，
                # 空间够时就不会凭空冒出滚动条（上限防止超长内容把窗口撑爆）
                want_req = min(natural, px(900))
                if int(canvas.cget("height") or 0) != want_req:
                    canvas.configure(height=want_req)
                cw, ch = canvas.winfo_width(), canvas.winfo_height()
                want_h = max(natural, ch)
                if canvas.itemcget(win, "width") != str(cw):
                    canvas.itemconfigure(win, width=cw)
                if canvas.itemcget(win, "height") != str(want_h):
                    canvas.itemconfigure(win, height=want_h)
                canvas.configure(scrollregion=(0, 0, cw, want_h))
            finally:
                lock["busy"] = False

        inner.bind("<Configure>", sync)
        canvas.bind("<Configure>", sync)

        def wheel(e):
            # 只在真正超出时才滚，避免吃掉本该给子控件（如文件列表）的滚轮
            if inner.winfo_reqheight() > canvas.winfo_height():
                canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")

        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", wheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        return inner

    def _build_ui(self):
        s = self.scale
        px = lambda v: int(v * s)
        self.root.configure(bg=C_BG)
        self._setup_style()

        # ==================== 顶部：标题 + ffmpeg ====================
        head = self._card(self.root)
        head.pack(fill="x", padx=px(12), pady=(px(10), px(8)))
        h = head.inner

        titlerow = tk.Frame(h, bg=C_CARD)
        titlerow.pack(fill="x")
        ttk.Label(titlerow, text="视频转码", style="Brand.TLabel").pack(side="left")
        ttk.Label(titlerow, text="ffmpeg 批量转码 / 直播录制",
                  style="BrandSub.TLabel").pack(side="left", padx=(px(10), 0),
                                               pady=(px(4), 0))

        self._hline(h, top=8, bottom=8)

        ffrow = tk.Frame(h, bg=C_CARD)
        ffrow.pack(fill="x")
        ttk.Label(ffrow, text="ffmpeg", style="Card.TLabel").pack(side="left")
        ui.RoundEntry(ffrow, textvariable=self.var_ffmpeg).pack(
            side="left", fill="x", expand=True, padx=(px(8), px(8)))
        ui.RoundButton(ffrow, text="浏览…", kind="ghost",
                   command=self._pick_ffmpeg).pack(side="left", padx=px(2))
        ui.RoundButton(ffrow, text="自动检测", kind="ghost",
                   command=self._detect_ffmpeg_bg).pack(side="left", padx=px(2))
        self.btn_ff = ui.RoundButton(ffrow, text="一键下载 ffmpeg", kind="accent",
                                 command=self._install_ffmpeg_bg)
        self.btn_ff.pack(side="left", padx=px(2))
        self.lbl_ff = ttk.Label(ffrow, text="检测中…", style="CardHint.TLabel")
        self.lbl_ff.pack(side="left", padx=(px(10), 0))

        # ==================== 页签 ====================
        # 注意：这里只创建、不 pack —— pack 顺序决定「窗口不够高时谁先让位」，
        # 要先 pack 底部的日志卡，再让页签去占剩余空间（见下方）。
        self.nb = ui.TabBar(self.root)
        tab1 = ttk.Frame(self.nb.body, style="Tab.TFrame")
        self.nb.add(tab1, text="  视频转码  ")
        tab2 = ttk.Frame(self.nb.body, style="Tab.TFrame")
        self.nb.add(tab2, text="  直播录制  ")

        # ---------------- 页签 1：转码 ----------------
        mid = self._scrollable(tab1)
        mid.columnconfigure(0, weight=3)
        mid.columnconfigure(1, weight=2)
        mid.rowconfigure(0, weight=1)

        left = self._card(mid)
        left.grid(row=0, column=0, sticky="nsew", padx=(px(10), px(6)), pady=px(8))
        lf = left.inner
        self._section(lf, "文件列表", "支持把视频直接拖进窗口")
        treewrap = tk.Frame(lf, bg=C_CARD)
        treewrap.pack(fill="both", expand=True, pady=(px(8), 0))
        treewrap.rowconfigure(0, weight=1)
        treewrap.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(treewrap, columns=("file", "size"),
                                 show="headings", height=9)
        self.tree.heading("file", text="文件")
        self.tree.heading("size", text="大小")
        self.tree.column("file", width=px(380))
        self.tree.column("size", width=px(80), anchor="e")
        self.tree.grid(row=0, column=0, sticky="nsew")
        ys = ttk.Scrollbar(treewrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ys.set)
        ys.grid(row=0, column=1, sticky="ns", padx=(px(4), 0))

        btns = tk.Frame(lf, bg=C_CARD)
        btns.pack(fill="x", pady=(px(10), 0))
        ui.RoundButton(btns, text="添加文件", command=self._add_files).pack(side="left")
        ui.RoundButton(btns, text="添加文件夹", command=self._add_folder).pack(
            side="left", padx=px(6))
        ui.RoundButton(btns, text="移除选中", kind="ghost",
                   command=self._remove_sel).pack(side="left")
        ui.RoundButton(btns, text="清空", kind="ghost",
                   command=self._clear_all).pack(side="left", padx=px(6))

        right = self._card(mid)
        right.grid(row=0, column=1, sticky="nsew", padx=(px(6), px(10)), pady=px(8))
        rf = right.inner

        self._section(rf, "转码模式")
        self.mode_btns = []
        for val, txt in MODE_LABELS:
            rb = ttk.Radiobutton(rf, text=txt, value=val, variable=self.var_mode,
                                 command=self._mode_changed)
            rb.pack(anchor="w", pady=(px(6), 0))
            self.mode_btns.append(rb)

        self._hline(rf, top=12, bottom=0)

        self._section(rf, "质量", "CQ/CRF，越小越清晰")
        qrow = tk.Frame(rf, bg=C_CARD)
        qrow.pack(fill="x", pady=(px(8), 0))
        self.scl_cq = ui.RoundSlider(qrow, variable=self.var_cq, from_=16, to=32,
                                     command=self._cq_changed)
        self.scl_cq.pack(side="left", fill="x", expand=True)
        self.lbl_cq = ttk.Label(qrow, text="23", style="Card.TLabel", width=4,
                                anchor="e")
        self.lbl_cq.pack(side="left", padx=(px(8), 0))

        self._hline(rf, top=12, bottom=0)

        self._section(rf, "输出")
        fmtrow = tk.Frame(rf, bg=C_CARD)
        fmtrow.pack(fill="x", pady=(px(8), 0))
        ttk.Label(fmtrow, text="格式", style="Card.TLabel").pack(side="left")
        self.cmb_fmt = ttk.Combobox(fmtrow, textvariable=self.var_format,
                                    values=["mp4", "mkv", "mov"], state="readonly",
                                    width=8)
        self.cmb_fmt.pack(side="left", padx=(px(8), 0))

        drows = tk.Frame(rf, bg=C_CARD)
        drows.pack(fill="x", pady=(px(8), 0))
        ttk.Label(drows, text="目录", style="Card.TLabel").pack(side="left")
        ui.RoundEntry(drows, textvariable=self.var_outdir).pack(
            side="left", fill="x", expand=True, padx=(px(8), px(4)))
        ui.RoundButton(drows, text="…", width=34, kind="ghost",
                   command=self._pick_outdir).pack(side="left")
        ttk.Label(rf, text="留空 = 与源文件同目录", style="CardHint.TLabel").pack(
            anchor="w", pady=(px(4), 0))

        ttk.Checkbutton(rf, text="覆盖已存在的输出文件（否则自动改名 _1/_2）",
                        variable=self.var_overwrite).pack(anchor="w", pady=(px(12), 0))

        # ---------------- 页签 2：直播录制 ----------------
        self._build_record_tab(tab2)

        # ==================== 底部：日志 ====================
        # 先 pack 底部，保证窗口再矮也不会把日志挤没（由中间的页签先让位）
        bottom = self._card(self.root)
        bottom.pack(side="bottom", fill="x", padx=px(12), pady=(px(6), px(8)))
        bf = bottom.inner
        row_b = tk.Frame(bf, bg=C_CARD)
        row_b.pack(fill="x")
        self.btn_start = ui.RoundButton(row_b, text="开始转换", kind="accent",
                                    command=self._start)
        self.btn_start.pack(side="left")
        self.btn_stop = ui.RoundButton(row_b, text="停止", kind="ghost",
                                   command=self._stop, state="disabled")
        self.btn_stop.pack(side="left", padx=px(8))
        self.lbl_state = ttk.Label(row_b, text="就绪", style="Card.TLabel")
        self.lbl_state.pack(side="left", padx=px(14))
        self.pbar = ttk.Progressbar(row_b, maximum=100, length=px(240))
        self.pbar.pack(side="right")

        logwrap = tk.Frame(bf, bg=C_BORDER, highlightthickness=0)
        logwrap.pack(fill="x", pady=(px(8), 0))
        self.txt = tk.Text(logwrap, height=5, state="disabled", wrap="none",
                           font=(FONT, 9), bg=C_CARD_ALT, fg=C_TEXT,
                           relief="flat", bd=0, padx=px(8), pady=px(6),
                           insertbackground=C_TEXT, selectbackground=C_SEL,
                           highlightthickness=1, highlightbackground=C_BORDER,
                           highlightcolor=C_BORDER)
        self.txt.pack(fill="x")
        # 日志按内容着色
        self.txt.tag_configure("ok", foreground=C_OK)
        self.txt.tag_configure("err", foreground=C_ERR)
        self.txt.tag_configure("warn", foreground=C_WARN)
        self.txt.tag_configure("muted", foreground=C_MUTED)
        self.txt.tag_configure("accent", foreground=C_ACCENT)

        # 页签最后 pack：窗口不够高时优先压缩页签，日志始终可见
        self.nb.pack(fill="both", expand=True, padx=px(12), pady=0)


    def _enable_dnd(self):
        try:
            from tkinterdnd2 import DND_FILES
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind("<<Drop>>", self._on_drop)
        except Exception:
            pass

    @staticmethod
    def _parse_dnd(data):
        out = []
        for m in re.findall(r"\{([^{}]+)\}|([^\s{}]+)", data):
            out.append(m[0] or m[1])
        return out

    def _on_drop(self, event):
        self._ingest([Path(p) for p in self._parse_dnd(event.data)])

    # ---------- 文件列表 ----------

    def _ingest(self, paths):
        added = 0
        for p in paths:
            if p.is_dir():
                for f in sorted(p.rglob("*")):
                    if f.is_file() and f.suffix.lower() in core.VIDEO_EXTS:
                        added += self._add_one(f)
            elif p.is_file() and p.suffix.lower() in core.VIDEO_EXTS:
                added += self._add_one(p)
        if added:
            self._log(f"已添加 {added} 个文件")

    def _add_one(self, p):
        if any(str(p) == str(x) for x in self.files):
            return 0
        self.files.append(p)
        try:
            size = f"{p.stat().st_size / 1048576:.1f} MB"
        except Exception:
            size = "?"
        self.tree.insert("", "end", values=(str(p), size))
        return 1

    def _add_files(self):
        ps = filedialog.askopenfilenames(title="选择视频文件")
        self._ingest([Path(p) for p in ps])

    def _add_folder(self):
        d = filedialog.askdirectory(title="选择文件夹（含子目录）")
        if d:
            self._ingest([Path(d)])

    def _remove_sel(self):
        sel = self.tree.selection()
        for iid in sel:
            vals = self.tree.item(iid, "values")
            self.files = [f for f in self.files if str(f) != vals[0]]
            self.tree.delete(iid)

    def _clear_all(self):
        self.files.clear()
        self.tree.delete(*self.tree.get_children())

    # ---------- 直播录制 ----------

    def _menu(self, parent):
        """统一样式的下拉菜单。"""
        return tk.Menu(parent, tearoff=0, font=(FONT, 9), bg=C_CARD, fg=C_TEXT,
                       activebackground=C_ACCENT, activeforeground="#ffffff",
                       bd=0, relief="flat", activeborderwidth=0)

    def _build_record_tab(self, parent):
        s = self.scale
        px = lambda v: int(v * s)
        r = self._scrollable(parent)

        # ============ 卡片 1：直播源 ============
        c1 = self._card(r)
        c1.pack(fill="x", padx=px(10), pady=(px(9), px(6)))
        f1 = c1.inner
        self._section(f1, "直播源", "抖音直播间链接 / 房间号 / 分享短链 / 主页链接，"
                                    "或 m3u8 / flv / mp4 直链 / rtmp")

        self.var_url = tk.StringVar()
        urow = tk.Frame(f1, bg=C_CARD)
        urow.pack(fill="x", pady=(px(8), 0))
        ui.RoundEntry(urow, textvariable=self.var_url).pack(fill="x")

        row_p = tk.Frame(f1, bg=C_CARD)
        row_p.pack(fill="x", pady=(px(8), 0))
        self.btn_probe = ui.RoundButton(row_p, text="解析画质", kind="accent",
                                    command=self._probe_rec_source)
        self.btn_probe.pack(side="left")

        # ---- 一键复制推流地址（转播用）----
        self.btn_copy = ui.RoundMenubutton(row_p, text="复制推流地址")
        menu = self._menu(self.btn_copy)
        menu.add_command(label="复制 FLV 地址（当前画质）",
                         command=lambda: self._copy_stream("flv"))
        menu.add_command(label="复制 HLS(m3u8) 地址（当前画质）",
                         command=lambda: self._copy_stream("hls"))
        menu.add_separator()
        menu.add_command(label="复制该画质 FLV + HLS（两行）",
                         command=lambda: self._copy_stream("both"))
        menu.add_command(label="复制全部画质（FLV）",
                         command=lambda: self._copy_stream("flv", all_qualities=True))
        menu.add_command(label="复制全部画质（HLS）",
                         command=lambda: self._copy_stream("hls", all_qualities=True))
        self.btn_copy["menu"] = menu
        self.btn_copy.pack(side="left", padx=px(6))
        self.btn_copy.state(["disabled"])

        tk.Frame(row_p, bg=C_BORDER, width=1, height=px(22)).pack(
            side="left", padx=px(10))
        ttk.Label(row_p, text="画质", style="Card.TLabel").pack(side="left")
        self.var_quality = tk.StringVar(value=core.AUTO_QUALITY)
        self.cmb_quality = ttk.Combobox(row_p, textvariable=self.var_quality,
                                        values=list(core.RECORD_QUALITIES),
                                        state="readonly", width=14)
        self.cmb_quality.pack(side="left", padx=(px(6), 0))
        self.lbl_probe = ttk.Label(row_p, text="", style="CardHint.TLabel")
        self.lbl_probe.pack(side="left", padx=px(12))

        self.var_url.trace_add("write", lambda *_: self._invalidate_probe())

        # ============ 卡片 2：常看主播（解析历史快捷入口）============
        c2 = self._card(r)
        c2.pack(fill="x", padx=px(10), pady=(0, px(6)))
        f2 = c2.inner
        hrow = tk.Frame(f2, bg=C_CARD)
        hrow.pack(fill="x")
        ttk.Label(hrow, text="常看主播", style="CardTitle.TLabel").pack(side="left")
        ttk.Label(hrow, text="点一下自动填入并重新解析（推流地址有时效，必须重新解析）",
                  style="CardHint.TLabel").pack(side="left", padx=(px(8), 0))
        self.btn_hist_more = ui.RoundMenubutton(hrow, text="全部记录")
        hm = self._menu(self.btn_hist_more)
        self.btn_hist_more["menu"] = hm
        self.btn_hist_more.pack(side="right")

        self.hist_frame = tk.Frame(f2, bg=C_CARD)
        self.hist_frame.pack(fill="x", pady=(px(8), 0))
        self.hist_cols = 4
        self._refresh_history_ui()

        # ============ 卡片 3：保存与选项 ============
        c3 = self._card(r)
        c3.pack(fill="x", padx=px(10), pady=(0, px(6)))
        f3 = c3.inner
        self._section(f3, "录制设置")

        drow = tk.Frame(f3, bg=C_CARD)
        drow.pack(fill="x", pady=(px(8), 0))
        ttk.Label(drow, text="保存到", style="Card.TLabel").pack(side="left")
        self.var_rec_dst = tk.StringVar()
        ui.RoundEntry(drow, textvariable=self.var_rec_dst).pack(
            side="left", fill="x", expand=True, padx=(px(8), px(4)))
        ui.RoundButton(drow, text="…", width=34, kind="ghost",
                   command=self._pick_rec_dst).pack(side="left")

        # 提示和「最长录制」并成一行，省纵向空间
        orow = tk.Frame(f3, bg=C_CARD)
        orow.pack(fill="x", pady=(px(6), 0))
        ttk.Label(orow, text="留空 = 按「主播名_日期_时间.mp4」自动命名",
                  style="CardHint.TLabel").pack(side="left")
        # 注意 side="right" 是「后 pack 的靠左」，所以右起第一个要先 pack
        ttk.Label(orow, text="分钟（0 = 不限）", style="CardHint.TLabel").pack(
            side="right")
        self.var_rec_limit = tk.IntVar(value=0)
        ttk.Spinbox(orow, from_=0, to=1440, textvariable=self.var_rec_limit,
                    width=5).pack(side="right", padx=(0, px(6)))
        ttk.Label(orow, text="最长录制", style="Card.TLabel").pack(
            side="right", padx=(0, px(6)))

        # 选项排成两列，省纵向空间
        opt = tk.Frame(f3, bg=C_CARD)
        opt.pack(fill="x", pady=(px(10), 0))
        self.var_rec_reconnect = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt, text="HTTP 直链断流自动重连",
                        variable=self.var_rec_reconnect).grid(row=0, column=0, sticky="w")
        self.var_rec_wait = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt, text="未开播时自动等待开录（每 30 秒重试）",
                        variable=self.var_rec_wait).grid(row=0, column=1, sticky="w",
                                                         padx=(px(18), 0))
        self.var_rec_mp4 = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt, text="停止后自动无损转成 mp4",
                        variable=self.var_rec_mp4).grid(row=1, column=0, sticky="w",
                                                        pady=(px(6), 0))
        self.var_rec_keep = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt, text="保留 ts 中间文件",
                        variable=self.var_rec_keep).grid(row=1, column=1, sticky="w",
                                                         padx=(px(18), 0),
                                                         pady=(px(6), 0))

        trow = tk.Frame(f3, bg=C_CARD)
        trow.pack(fill="x", pady=(px(6), 0))
        self.var_rec_transcode = tk.BooleanVar(value=False)
        ttk.Checkbutton(trow, text="录完自动重编码",
                        variable=self.var_rec_transcode).pack(side="left")
        self.var_rec_tmode = tk.StringVar(value=core.TRANSCODE_MODES[0][1])
        ttk.Combobox(trow, textvariable=self.var_rec_tmode, state="readonly",
                     width=22, values=[txt for _, txt in core.TRANSCODE_MODES]).pack(
            side="left", padx=(px(6), px(8)))
        ttk.Label(trow, text="质量档沿用「视频转码」页的 CQ",
                  style="CardHint.TLabel").pack(side="left")

        # ============ 操作条 ============
        c4 = self._card(r)
        c4.pack(fill="x", padx=px(10), pady=(0, px(8)))
        f4 = c4.inner
        row_r = tk.Frame(f4, bg=C_CARD)
        row_r.pack(fill="x")
        self.btn_rec_start = ui.RoundButton(row_r, text="开始录制", kind="accent",
                                        command=self._start_rec)
        self.btn_rec_start.pack(side="left")
        self.btn_rec_stop = ui.RoundButton(row_r, text="停止录制", kind="ghost",
                                       command=self._stop_rec, state="disabled")
        self.btn_rec_stop.pack(side="left", padx=px(8))
        self.lbl_rec = ttk.Label(row_r, text="待命", style="Card.TLabel")
        self.lbl_rec.pack(side="left", padx=px(14))
        self.pbar_rec = ttk.Progressbar(row_r, mode="determinate", value=0,
                                        maximum=100, length=px(200))
        self.pbar_rec.pack(side="right")

    # ---------- 常看主播（解析历史）----------

    def _refresh_history_ui(self):
        """重画历史主播快捷按钮和「全部记录」菜单。"""
        if getattr(self, "hist_frame", None) is None:
            return
        s = self.scale
        px = lambda v: int(v * s)
        for w in self.hist_frame.winfo_children():
            w.destroy()

        hist = [h for h in (self.history or []) if isinstance(h, dict)]
        if not hist:
            ttk.Label(self.hist_frame,
                      text="还没有记录。解析成功一次之后，这里会出现主播快捷按钮。",
                      style="CardHint.TLabel").grid(row=0, column=0, sticky="w")
            self.btn_hist_more.state(["disabled"])
            return

        self.btn_hist_more.state(["!disabled"])
        cols = max(3, self.hist_cols)
        # 只摆最近 4 个（一行），其余的走「全部记录」菜单 —— 多一行会挤掉
        # 下方的「开始录制」按钮，得不偿失
        for i, item in enumerate(hist[:cols]):
            nick = (item.get("nick") or "").strip() or (item.get("rid") or "未知主播")
            label = nick if len(nick) <= 7 else nick[:7] + "…"
            b = ui.RoundButton(self.hist_frame, text=label, kind="chip",
                           command=lambda i=i: self._use_history(i))
            b.grid(row=i // cols, column=i % cols, sticky="w",
                   padx=(0, px(6)), pady=(0, px(6)))

        m = self.btn_hist_more.menu
        m.delete(0, "end")
        for i, item in enumerate(hist[:15]):
            nick = (item.get("nick") or "").strip() or "未知主播"
            rid = item.get("rid") or item.get("input") or ""
            m.add_command(label=f"{nick}   {rid}",
                          command=lambda i=i: self._use_history(i))
        m.add_separator()
        m.add_command(label="清空全部记录", command=self._clear_history)

    def _remember_streamer(self, room, raw_input):
        """解析成功后把主播记进历史（按 web_rid 去重，最近的在最前）。"""
        if not isinstance(room, dict):
            return
        nick = (room.get("nickname") or "").strip()
        rid = str(room.get("web_rid") or "").strip()
        raw = (raw_input or "").strip()
        if not nick and not rid:
            return
        key = rid or raw
        self.history = [h for h in (self.history or [])
                        if isinstance(h, dict)
                        and (h.get("rid") or h.get("input")) != key]
        self.history.insert(0, {"nick": nick, "rid": rid, "input": raw,
                                "ts": int(time.time())})
        del self.history[12:]
        self._refresh_history_ui()
        self._save_cfg()

    def _use_history(self, idx):
        """点主播快捷按钮：填入地址并立刻重新解析。"""
        hist = self.history or []
        if not (0 <= idx < len(hist)):
            return
        item = hist[idx]
        rid = (item.get("rid") or "").strip()
        # 优先用 web_rid 组链接：比 App 分享短链稳定，也不需要浏览器渲染
        target = f"https://live.douyin.com/{rid}" if rid else (item.get("input") or "")
        if not target:
            return
        self.nb.select(1)
        self.var_url.set(target)          # trace 会清掉上一次的解析结果
        self.lbl_probe.config(text="", foreground=C_MUTED)
        self._qlog(f"==== 快捷解析：{item.get('nick') or target}")
        self._probe_rec_source()

    def _clear_history(self):
        if not self.history:
            return
        if messagebox.askyesno("确认", "清空「常看主播」的全部记录？"):
            self.history = []
            self._refresh_history_ui()
            self._save_cfg()

    def _pick_rec_dst(self):
        p = filedialog.asksaveasfilename(title="选择录制保存位置",
                                         defaultextension=".ts",
                                         filetypes=[("视频", "*.mp4 *.ts *.mkv *.flv")])
        if p:
            self.var_rec_dst.set(p)

    # ---------- 抖音解析 ----------

    def _probe_rec_source(self):
        """解析抖音直播间，填充画质下拉框（不开始录制）。"""
        url = self.var_url.get().strip()
        if not url:
            messagebox.showinfo("提示", "请先填直播源地址")
            return
        if not core.is_douyin_input(url):
            self._probe_room = None
            self.lbl_probe.config(text="非抖音地址，直接录制", foreground=C_OK)
            self.btn_copy.state(["!disabled"])      # 直链可直接复制
            return
        if self.probe_worker and self.probe_worker.is_alive():
            # 已有一轮在跑：排队等它结束再自动重解析，否则用户点「常看主播」
            # 切到另一个主播时会毫无反应（旧结果还会把新地址盖掉）
            self._probe_pending = url
            self.lbl_probe.config(text="解析中…（已排队）", foreground=C_MUTED)
            return
        self._probe_room = None
        self._probe_input = url
        self._probe_pending = None
        self.btn_copy.state(["disabled"])
        self.btn_probe.config(state="disabled")
        self.lbl_probe.config(text="解析中…", foreground=C_MUTED)
        self.probe_worker = threading.Thread(target=self._work_probe, args=(url,), daemon=True)
        self.probe_worker.start()

    def _work_probe(self, url):
        try:
            room = core.probe_live_room(url, on_log=lambda t: self._qlog(t))
            self.q.put(("probe", True, room))
        except Exception as e:
            self.q.put(("probe", False, f"{e}"))

    def _apply_probe(self, room):
        """把探测结果填进画质下拉框和状态标签。"""
        self._probe_room = room
        avail = (room or {}).get("available") or []
        values = [core.AUTO_QUALITY] + avail
        self.cmb_quality.config(values=values)
        if self.var_quality.get() not in values:
            self.var_quality.set(values[0] if avail else core.AUTO_QUALITY)
        # 只要有地址就允许复制（未开播时可能是上一场的缓存地址）
        if core.stream_urls_all(room, "flv") or core.stream_urls_all(room, "hls"):
            self.btn_copy.state(["!disabled"])
        else:
            self.btn_copy.state(["disabled"])
        nick = room.get("nickname") or "未知主播"
        if room.get("is_live"):
            text = f"✓ {nick} · 直播中 · {len(avail)} 档画质"
            self.lbl_probe.config(text=text, foreground=C_OK)
        else:
            text = f"✗ {nick} · 未开播"
            if avail:
                text += f" · 已缓存 {len(avail)} 档地址"
            self.lbl_probe.config(text=text, foreground=C_ERR)
        # 解析成功就记进「常看主播」
        self._remember_streamer(room, self._probe_input)

    # ---------- 一键复制推流地址（转播用）----------

    def _invalidate_probe(self):
        """地址框一改，之前解析的结果就作废，避免复制到旧地址。"""
        self._probe_room = None
        if getattr(self, "btn_copy", None) is not None:
            self.btn_copy.state(["disabled"])

    def _set_clipboard(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update()          # 让内容立刻写进剪贴板

    def _copy_stream(self, proto="flv", all_qualities=False):
        """把推流地址复制到剪贴板。proto: flv / hls / both。"""
        url_in = self.var_url.get().strip()
        if not url_in:
            messagebox.showinfo("提示", "请先填直播源地址")
            return

        room = self._probe_room
        if room is None:
            if core.is_douyin_input(url_in):
                messagebox.showinfo("提示",
                                    "请先点「解析画质」。\n"
                                    "解析成功后按钮才会亮起，才能拿到真实推流地址。")
                return
            # 非抖音直链：原样复制
            self._set_clipboard(url_in)
            self._qlog(f"已复制直链地址：{url_in}")
            return

        quality = self.var_quality.get()

        # 全部画质（指定协议）
        if all_qualities:
            urls = core.stream_urls_all(room, proto)
            if not urls:
                messagebox.showwarning("提示", f"该直播源没有 {proto.upper()} 地址。")
                return
            text = "\n".join(urls.values())
            self._set_clipboard(text)
            self._qlog(f"已复制全部 {proto.upper()} 地址（{len(urls)} 档）：")
            for q, u in urls.items():
                self._qlog(f"    {q}: {u}")
            return

        # 当前画质，flv + hls 两个都取
        if proto == "both":
            pairs = [(p, *core.stream_url_for(room, quality, p)) for p in ("flv", "hls")]
            hit = [(p, q, u) for p, q, u in pairs if u]
            if not hit:
                self._show_no_url(room, quality)
                return
            self._set_clipboard("\n".join(u for _, _, u in hit))
            self._qlog(f"已复制推流地址（{len(hit)} 条，各占一行）：")
            for p, q, u in hit:
                self._qlog(f"    {p.upper()} [{q}]: {u}")
            return

        # 当前画质，单一协议
        q, url = core.stream_url_for(room, quality, proto)
        if not url:
            self._show_no_url(room, quality, proto)
            return
        self._set_clipboard(url)
        self._qlog(f"已复制 {proto.upper()} 地址（{q}）：{url}")

    def _show_no_url(self, room, quality, proto=None):
        """取不到地址时给出「到底有哪些可选」的明确提示。"""
        want = quality if quality != core.AUTO_QUALITY else "自动"
        lines = [f"没取到地址（协议 {proto.upper() if proto else 'FLV/HLS'}，画质 {want}）。"]
        for p in ("flv", "hls"):
            names = list(core.stream_urls_all(room, p).keys())
            lines.append(f"  {p.upper()} 可用画质：{'、'.join(names) if names else '无'}")
        lines.append("提示：下拉框选「自动」或换一档画质再试。")
        messagebox.showwarning("提示", "\n".join(lines))

    # ---------- 录制 ----------

    def _start_rec(self):
        if self.rec_worker and self.rec_worker.is_alive():
            return
        val = self.var_ffmpeg.get().strip()
        ffmpeg = Path(val) if val and Path(val).is_file() else core.find_ffmpeg(val or None)
        if not ffmpeg:
            messagebox.showerror("错误", "未找到 ffmpeg，请到「视频转码」页指定 ffmpeg.exe")
            return
        url = self.var_url.get().strip()
        if not url:
            messagebox.showinfo("提示", "请先填直播源地址")
            return
        dst_in = self.var_rec_dst.get().strip()
        limit_min = int(self.var_rec_limit.get() or 0)
        self.stop_event_rec.clear()
        self._set_rec_running(True)
        self._save_cfg()
        self.q.put(("log", "==== 开始录制：" + url))
        self.rec_start = time.time()
        self.rec_worker = threading.Thread(
            target=self._work_rec,
            args=(ffmpeg, url, dst_in, limit_min * 60,
                  bool(self.var_rec_reconnect.get()),
                  bool(self.var_rec_keep.get()),
                  bool(self.var_rec_mp4.get()),
                  bool(self.var_rec_wait.get()),
                  self.var_quality.get(),
                  core.mode_from_label(self.var_rec_tmode.get())
                  if self.var_rec_transcode.get() else None,
                  int(self.var_cq.get())),
            daemon=True)
        self.rec_worker.start()
        self._tick_rec()

    def _stop_rec(self):
        self.stop_event_rec.set()
        self._qlog("正在停止录制（收尾封装中）…")

    def _set_rec_running(self, running):
        self.btn_rec_start.config(state="disabled" if running else "normal")
        self.btn_rec_stop.config(state="normal" if running else "disabled")
        self.btn_probe.config(state="disabled" if running else "normal")
        if running:
            # 只在录制时切到不确定态；空闲时用确定态 value=0，否则 clam 会一直
            # 显示一截蓝色滑块，看着像「录到一半」
            self.pbar_rec.config(mode="indeterminate")
            self.pbar_rec.start(12)
            self.lbl_rec.config(text="录制中…")
        else:
            self.pbar_rec.stop()
            self.pbar_rec.config(mode="determinate", value=0)

    def _tick_rec(self):
        if self.rec_worker and self.rec_worker.is_alive():
            secs = int(time.time() - self.rec_start)
            self.lbl_rec.config(text=f"录制中 {secs // 3600:02d}:{secs % 3600 // 60:02d}:{secs % 60:02d}")
            self.root.after(1000, self._tick_rec)

    def _work_rec(self, ffmpeg, url, dst_in, limit_sec, reconnect, keep_ts,
                  need_mp4, wait_live, quality, tmode, cq):
        try:
            # ---- 1. 解析（抖音地址才会真正联网解析，直链原样返回）----
            if core.is_douyin_input(url):
                self._qlog("    正在解析直播源 …")
            try:
                stream_url, info = core.prepare_record_source(
                    url,
                    quality=None if quality == core.AUTO_QUALITY else quality,
                    wait=wait_live,
                    stop_event=self.stop_event_rec,
                    on_log=lambda t: self._qlog(t))
            except Exception as exc:
                self._qlog(f"解析失败 ✗ {exc}")
                self.q.put(("recdone", False))
                return

            if info.get("cancelled"):
                self._qlog("已取消（等待开播中断）")
                self.q.put(("recdone", False))
                return

            if info.get("douyin"):
                nick = info.get("nickname") or "未知主播"
                title = (info.get("title") or "").strip()
                self._qlog(f"    主播：{nick}　画质：{info.get('quality')}　"
                           f"room_id：{info.get('room_id')}")
                if title:
                    self._qlog(f"    标题：{title[:60]}")
                self.q.put(("probed", info))

            # ---- 2. 决定保存路径 ----
            if dst_in:
                dst = Path(dst_in)
                if dst.suffix.lower() not in (".mp4", ".ts", ".mkv", ".flv"):
                    dst = dst.with_suffix(".ts")
            else:
                base = self.var_outdir.get().strip() or str(core.app_dir())
                prefix = (info.get("nickname") or "").strip() or "直播"
                prefix = re.sub(r'[\\/:*?"<>|]', "_", prefix)[:40]
                dst = Path(base) / f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}.mp4"
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            if dst.exists():
                dst = core.unique_dst(dst)

            to_mp4 = need_mp4
            if dst.suffix.lower() == ".ts":
                to_mp4 = False
            tmp_ts = dst.with_suffix(".ts") if dst.suffix.lower() != ".ts" else dst
            self._qlog(f"    保存到 {dst}，最长 {limit_sec // 60 if limit_sec else '不限'} 分钟")

            # ---- 3. 录制 ----
            args = core.build_record_command(stream_url, tmp_ts, limit_sec, reconnect)
            okk, msg = core.run_ffmpeg(
                ffmpeg, args, duration=None,
                on_log=lambda t: self._qlog("    " + t),
                stop_event=self.stop_event_rec)
            has_data = tmp_ts.is_file() and tmp_ts.stat().st_size > 0
            if not has_data:
                self._qlog(f"录制失败 ✗ {msg or '没有收到任何数据，请检查地址'}")
                self.q.put(("recdone", False))
                return
            size = tmp_ts.stat().st_size / 1048576

            # ---- 4. 无损封装 ----
            final = tmp_ts
            if to_mp4 and str(tmp_ts.resolve()) != str(dst.resolve()):
                self._qlog(f"    收到 {size:.1f} MB，正在无损封装为 {dst.name} …")
                rok, rmsg = core.run_ffmpeg(
                    ffmpeg, core.remux_command(tmp_ts, dst), duration=None,
                    on_log=lambda t: self._qlog("    " + t))
                if rok and dst.is_file():
                    if not keep_ts:
                        try:
                            tmp_ts.unlink()
                        except Exception:
                            pass
                    final = dst
                    self._qlog(f"    完成 ✓ {dst.name} {dst.stat().st_size / 1048576:.1f} MB")
                else:
                    self._qlog(f"    封装失败 ✗ {rmsg}（ts 中间文件已保留：{tmp_ts.name}）")
                    self.q.put(("recdone", True))
                    return
            else:
                self._qlog(f"    完成 ✓ {dst.name} {size:.1f} MB")

            # ---- 5. 可选：录完自动重编码 ----
            if tmode and final.is_file():
                self._auto_transcode(ffmpeg, final, tmode, cq)

            self.q.put(("recdone", True))
        except Exception as e:
            self._qlog(f"[异常] {e}")
            self.q.put(("recdone", False))

    def _auto_transcode(self, ffmpeg, src, mode, cq):
        """录制结束后按「视频转码」页的模式设置做一次重编码。"""
        label = core.label_from_mode(mode)
        tgt = core.unique_dst(src.with_name(f"{src.stem}_{mode}{src.suffix}"))
        self._qlog(f"    自动重编码（{label}）→ {tgt.name} …")
        args, _ = core.build_command(mode, cq, src, tgt,
                                     nvenc_h264=self.nvenc_h264,
                                     nvenc_h265=self.nvenc_h265)
        ok, msg = core.run_ffmpeg(
            ffmpeg, args, duration=core.media_duration(core.find_ffprobe(ffmpeg), src),
            on_progress=lambda f: self.q.put(("progress", f)),
            on_log=lambda t: self._qlog("    " + t),
            stop_event=self.stop_event_rec)
        if ok and tgt.is_file():
            self._qlog(f"    重编码完成 ✓ {tgt.name} {tgt.stat().st_size / 1048576:.1f} MB")
        else:
            self._qlog(f"    重编码失败 ✗ {msg}")
            try:
                if tgt.exists() and tgt.stat().st_size == 0:
                    tgt.unlink()
            except Exception:
                pass


    # ---------- ffmpeg 检测 ----------

    def _detect_ffmpeg_bg(self):
        val = self.var_ffmpeg.get().strip()

        def job():
            p = core.find_ffmpeg(val or None)
            ver = core.ffmpeg_version(p) if p else "未找到 ffmpeg，请指定路径"
            nv_h = core.has_encoder(p, "h264_nvenc") if p else False
            nv_5 = core.has_encoder(p, "hevc_nvenc") if p else False
            self.q.put(("detect", str(p) if p else "", ver, nv_h, nv_5))

        threading.Thread(target=job, daemon=True).start()

    def _pick_ffmpeg(self):
        p = filedialog.askopenfilename(title="选择 ffmpeg.exe",
                                       filetypes=[("ffmpeg.exe", "*.exe")])
        if p:
            self.var_ffmpeg.set(p)
            self._detect_ffmpeg_bg()

    def _install_ffmpeg_bg(self, custom_url=None):
        if self.dl_worker and self.dl_worker.is_alive():
            self.stop_event_dl.set()
            self.btn_ff.config(text="正在取消…")
            return
        target = core.app_dir() / "ffmpeg"
        if custom_url is None:
            if not messagebox.askyesno(
                    "一键下载 ffmpeg",
                    f"将自动从国内加速源下载 ffmpeg（约 82 MB）并安装到：\n{target}\n\n"
                    "会先动态解析最新版资产名，失败则换源/换包重试。\n继续吗？"):
                return
        self.stop_event_dl.clear()
        self.btn_ff.config(text="取消下载")
        self.q.put(("log", "==== 开始下载 ffmpeg（动态解析 + 多源自动重试）===="))
        self.dl_worker = threading.Thread(
            target=self._work_install_ffmpeg, args=(target, custom_url), daemon=True)
        self.dl_worker.start()

    def _work_install_ffmpeg(self, target, custom_url=None):
        try:
            ok, msg = core.install_ffmpeg(
                target,
                on_progress=lambda f: self.q.put(("progress", f)),
                on_log=lambda t: self._qlog(t),
                stop_event=self.stop_event_dl,
                custom_url=custom_url)
        except Exception as e:
            ok, msg = False, f"下载异常：{e}"
        self.q.put(("dl_done", ok, msg))

    # ---------- 设置 ----------

    def _restore_cfg(self):
        c = self.cfg
        if c.get("ffmpeg"):
            self.var_ffmpeg.set(c["ffmpeg"])
        if c.get("outdir"):
            self.var_outdir.set(c["outdir"])
        if c.get("mode") in ("copy", "h264", "h265"):
            self.var_mode.set(c["mode"])
        if c.get("format") in ("mp4", "mkv", "mov"):
            self.var_format.set(c["format"])
        if isinstance(c.get("cq"), int) and 16 <= c["cq"] <= 32:
            self.var_cq.set(c["cq"])
        self.lbl_cq.config(text=str(self.var_cq.get()))
        self._mode_changed()
        # 直播录制设置
        if c.get("rec_quality"):
            self.var_quality.set(c["rec_quality"])
        for key, var in (("rec_reconnect", self.var_rec_reconnect),
                         ("rec_wait", self.var_rec_wait),
                         ("rec_mp4", self.var_rec_mp4),
                         ("rec_keep", self.var_rec_keep),
                         ("rec_transcode", self.var_rec_transcode)):
            if isinstance(c.get(key), bool):
                var.set(c[key])
        if c.get("rec_tmode") in [txt for _, txt in core.TRANSCODE_MODES]:
            self.var_rec_tmode.set(c["rec_tmode"])
        if isinstance(c.get("rec_limit"), int) and c["rec_limit"] >= 0:
            self.var_rec_limit.set(c["rec_limit"])

    def _mode_changed(self):
        is_copy = self.var_mode.get() == "copy"
        state = "disabled" if is_copy else "normal"
        self.scl_cq.config(state=state)
        self.lbl_cq.config(state=state)

    def _cq_changed(self, _=None):
        self.lbl_cq.config(text=str(int(self.var_cq.get())))

    def _pick_outdir(self):
        d = filedialog.askdirectory(title="选择输出目录")
        if d:
            self.var_outdir.set(d)

    def _save_cfg(self):
        core.save_config(core.app_dir(), {
            "ffmpeg": self.var_ffmpeg.get().strip(),
            "outdir": self.var_outdir.get().strip(),
            "mode": self.var_mode.get(),
            "format": self.var_format.get(),
            "cq": int(self.var_cq.get()),
            # 直播录制
            "rec_quality": self.var_quality.get(),
            "rec_reconnect": bool(self.var_rec_reconnect.get()),
            "rec_wait": bool(self.var_rec_wait.get()),
            "rec_mp4": bool(self.var_rec_mp4.get()),
            "rec_keep": bool(self.var_rec_keep.get()),
            "rec_transcode": bool(self.var_rec_transcode.get()),
            "rec_tmode": self.var_rec_tmode.get(),
            "rec_limit": int(self.var_rec_limit.get() or 0),
            # 曾解析过的主播
            "history": self.history or [],
        })

    # ---------- 运行 ----------

    def _start(self):
        if self.worker and self.worker.is_alive():
            return
        val = self.var_ffmpeg.get().strip()
        ffmpeg = Path(val) if val and Path(val).is_file() else core.find_ffmpeg(val or None)
        if not ffmpeg:
            messagebox.showerror("错误", "未找到 ffmpeg，请点「浏览…」指定 ffmpeg.exe")
            return
        if not self.files:
            messagebox.showinfo("提示", "请先添加要转换的视频文件")
            return
        ffprobe = core.find_ffprobe(ffmpeg)
        jobs = list(self.files)
        self.stop_event.clear()
        self._set_running(True)
        self._save_cfg()
        self.q.put(("log", f"==== 开始：{len(jobs)} 个文件 | 模式 {self.var_mode.get()}"
                           f" | 输出 {self.var_format.get()} ===="))
        self.worker = threading.Thread(
            target=self._work,
            args=(jobs, ffmpeg, ffprobe, self.var_mode.get(), int(self.var_cq.get()),
                  self.var_format.get(), self.var_outdir.get().strip(),
                  bool(self.var_overwrite.get()),
                  (self.nvenc_h264, self.nvenc_h265)),
            daemon=True)
        self.worker.start()

    def _stop(self):
        self.stop_event.set()
        self._log("正在停止…")

    def _set_running(self, running):
        self.btn_start.config(state="disabled" if running else "normal")
        self.btn_stop.config(state="normal" if running else "disabled")

    def _work(self, jobs, ffmpeg, ffprobe, mode, cq, fmt, outdir, overwrite, nv):
        ok = fail = 0
        if outdir:
            try:
                Path(outdir).mkdir(parents=True, exist_ok=True)
            except Exception as e:
                self._qlog(f"[错误] 无法创建输出目录 {outdir}：{e}")
        try:
            for idx, src in enumerate(jobs, 1):
                if self.stop_event.is_set():
                    self._qlog("已停止（剩余文件未处理）")
                    break
                self.q.put(("file", idx, len(jobs), src.name))
                dst = (Path(outdir) if outdir else src.parent) / (src.stem + "." + fmt)
                if dst.exists() and not overwrite:
                    dst = core.unique_dst(dst)
                if str(dst.resolve()) == str(src.resolve()):
                    dst = core.unique_dst(dst.with_stem(src.stem + "_conv"))
                    self._qlog(f"输出与源同名，自动改名 → {dst.name}")
                dur = core.media_duration(ffprobe, src) if ffprobe else None
                args, lossless = core.build_command(mode, cq, src, dst,
                                                    nvenc_h264=nv[0], nvenc_h265=nv[1])
                self._qlog(f"[{idx}/{len(jobs)}] {'无损转封装' if lossless else '重编码'} → {dst.name}")
                okk, msg = core.run_ffmpeg(
                    ffmpeg, args, dur,
                    on_progress=lambda f: self.q.put(("progress", f)),
                    on_log=lambda t: self._qlog("    " + t),
                    stop_event=self.stop_event)
                if okk and dst.is_file():
                    ok += 1
                    self._qlog(f"    完成 ✓ {dst.stat().st_size / 1048576:.1f} MB")
                else:
                    fail += 1
                    self._qlog(f"    失败 ✗ {msg}")
                    try:
                        if dst.exists() and dst.stat().st_size == 0:
                            dst.unlink()
                    except Exception:
                        pass
        except Exception as e:
            self._qlog(f"[异常] {e}")
            fail += 1
        finally:
            self.q.put(("done", ok, fail))

    def _qlog(self, text):
        self.q.put(("log", text))

    # ---------- 队列轮询 ----------

    def _poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                kind = item[0]
                if kind == "log":
                    self._log(item[1])
                elif kind == "progress":
                    self.pbar["value"] = item[1] * 100
                elif kind == "file":
                    _, i, n, name = item
                    self.lbl_state.config(text=f"[{i}/{n}] {name}")
                    self.pbar["value"] = 0
                elif kind == "done":
                    self.lbl_state.config(text=f"完成：成功 {item[1]}，失败 {item[2]}")
                    self._set_running(False)
                    self._log(f"==== 全部结束：成功 {item[1]}，失败 {item[2]} ====")
                elif kind == "recdone":
                    self._set_rec_running(False)
                    self.lbl_rec.config(text="已结束")
                elif kind == "probe":
                    _, ok, payload = item
                    self.btn_probe.config(state="normal")
                    if ok and payload:
                        self._apply_probe(payload)
                    else:
                        self._probe_room = None
                        self.btn_copy.state(["disabled"])
                        self.lbl_probe.config(text=f"解析失败：{str(payload)[:60]}",
                                              foreground=C_ERR)
                    # 解析期间若有排队的地址，现在补跑一次
                    if self._probe_pending and not (
                            self.probe_worker and self.probe_worker.is_alive()):
                        self._probe_pending = None
                        self.root.after(30, self._probe_rec_source)
                elif kind == "probed":
                    self._apply_probe(item[1])
                elif kind == "dl_done":
                    _, ok, msg = item
                    self.btn_ff.config(text="一键下载 ffmpeg")
                    self.pbar["value"] = 0
                    for line in str(msg).splitlines():
                        self._log("    " + line)
                    if ok:
                        self._log("==== ffmpeg 安装完成 ====")
                        self._detect_ffmpeg_bg()
                        messagebox.showinfo("完成", "ffmpeg 已安装完成，可以直接用了")
                    else:
                        self._log("==== ffmpeg 自动下载失败 ====")
                        url = simpledialog.askstring(
                            "手动指定下载地址",
                            "所有自动地址都没成功。\n"
                            "可直接粘贴 ffmpeg 的 zip 直链（留空放弃）：\n"
                            "例如 https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
                            parent=self.root)
                        if url and url.strip():
                            self._install_ffmpeg_bg(custom_url=url.strip())
                elif kind == "detect":
                    _, path, ver, nv_h, nv_5 = item
                    if path:
                        self.var_ffmpeg.set(path)
                        self.lbl_ff.config(text=ver.split("(")[0].strip(),
                                           foreground=C_OK)
                        self._log(f"ffmpeg 就绪：{ver}")
                    else:
                        self.lbl_ff.config(text="未找到 ffmpeg", foreground=C_ERR)
                        self._log(ver)
                    self.nvenc_h264, self.nvenc_h265 = nv_h, nv_5
                    if nv_h or nv_5:
                        self._log("检测到 NVIDIA 硬件编码（NVENC）："
                                  + " ".join(x for x, on in
                                             (("H.264", nv_h), ("H.265", nv_5)) if on))
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    # ---------- 日志 ----------

    def _log(self, text):
        """写日志，并按内容给关键行着色（重编码开关不影响可读性）。"""
        low = text.lower()
        if "✗" in text or "失败" in text or "错误" in text or "[error" in low \
                or "error" in low:
            tag = ("err",)
        elif "✓" in text or "完成" in text or "成功" in text or " ok" in low:
            tag = ("ok",)
        elif "警告" in text or "warn" in low:
            tag = ("warn",)
        elif text.startswith("===="):
            tag = ("accent",)
        elif text.lstrip().startswith("["):
            tag = ("muted",)
        else:
            tag = ()
        self.txt.config(state="normal")
        self.txt.insert("end", text + "\n", tag)
        lines = int(self.txt.index("end-1c").split(".")[0])
        if lines > 600:
            self.txt.delete("1.0", f"{lines - 400}.0")
        self.txt.see("end")
        self.txt.config(state="disabled")

    def _on_close(self):
        self.stop_event.set()
        self._save_cfg()
        self.root.destroy()


def run():
    try:
        from tkinterdnd2 import TkinterDnD
        root = TkinterDnD.Tk()
    except Exception:
        root = tk.Tk()
    App(root)
    root.mainloop()
