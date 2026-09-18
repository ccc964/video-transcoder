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
        self.dl_worker = None
        self.stop_event_dl = threading.Event()
        self.cfg = core.load_config(core.app_dir())
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
        s = self.scale
        need_w = max(self.root.winfo_reqwidth(), int(1000 * s))
        need_h = max(self.root.winfo_reqheight(), int(660 * s))
        w = min(need_w + 24, self.root.winfo_screenwidth() - 60)
        h = min(need_h + 24, self.root.winfo_screenheight() - 110)
        self.root.geometry(f"{w}x{h}")

    def _build_ui(self):
        s = self.scale
        pad = lambda v: int(v * s)
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TButton", padding=(pad(10), pad(4)))
        style.configure("TNotebook.Tab", padding=(pad(14), pad(5)))

        top = ttk.Frame(self.root)
        top.pack(fill="x", padx=pad(10), pady=(pad(8), pad(4)))
        ttk.Label(top, text="ffmpeg：").pack(side="left")
        ttk.Entry(top, textvariable=self.var_ffmpeg).pack(
            side="left", fill="x", expand=True, padx=pad(6))
        ttk.Button(top, text="浏览…", command=self._pick_ffmpeg).pack(side="left", padx=2)
        ttk.Button(top, text="自动检测", command=self._detect_ffmpeg_bg).pack(side="left", padx=2)
        self.btn_ff = ttk.Button(top, text="一键下载 ffmpeg", command=self._install_ffmpeg_bg)
        self.btn_ff.pack(side="left", padx=2)
        self.lbl_ff = ttk.Label(top, text="检测中…", foreground="#888888")
        self.lbl_ff.pack(side="left", padx=pad(8))

        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=pad(10), pady=pad(4))
        tab1 = ttk.Frame(self.nb)
        self.nb.add(tab1, text="视频转码")
        tab2 = ttk.Frame(self.nb)
        self.nb.add(tab2, text="直播录制")

        mid = tab1
        mid.columnconfigure(0, weight=3)
        mid.columnconfigure(1, weight=2)
        mid.rowconfigure(0, weight=1)

        # 左：文件列表
        left = ttk.LabelFrame(mid, text="文件列表（支持把视频直接拖进来）")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, pad(6)))
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(left, columns=("file", "size"), show="headings", height=9)
        self.tree.heading("file", text="文件")
        self.tree.heading("size", text="大小")
        self.tree.column("file", width=pad(380))
        self.tree.column("size", width=pad(80), anchor="e")
        self.tree.grid(row=0, column=0, sticky="nsew", padx=pad(6), pady=pad(6))
        ys = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ys.set)
        ys.grid(row=0, column=1, sticky="ns", pady=pad(6))
        btns = ttk.Frame(left)
        btns.grid(row=1, column=0, columnspan=2, sticky="ew", padx=pad(6), pady=(0, pad(6)))
        ttk.Button(btns, text="添加文件", command=self._add_files).pack(side="left", padx=2)
        ttk.Button(btns, text="添加文件夹", command=self._add_folder).pack(side="left", padx=2)
        ttk.Button(btns, text="移除选中", command=self._remove_sel).pack(side="left", padx=2)
        ttk.Button(btns, text="清空", command=self._clear_all).pack(side="left", padx=2)

        # 右：设置
        right = ttk.LabelFrame(mid, text="转码设置")
        right.grid(row=0, column=1, sticky="nsew")
        r = right
        ttk.Label(r, text="转码模式：").grid(row=0, column=0, sticky="w",
                                            padx=pad(8), pady=(pad(8), 0))
        self.mode_btns = []
        for i, (val, txt) in enumerate(MODE_LABELS):
            rb = ttk.Radiobutton(r, text=txt, value=val, variable=self.var_mode,
                                 command=self._mode_changed)
            rb.grid(row=1 + i, column=0, columnspan=2, sticky="w",
                    padx=pad(10), pady=pad(2))
            self.mode_btns.append(rb)

        ttk.Label(r, text="质量（CQ/CRF，越小越清晰）：").grid(
            row=4, column=0, sticky="w", padx=pad(8), pady=(pad(10), 0))
        row_q = ttk.Frame(r)
        row_q.grid(row=5, column=0, columnspan=2, sticky="ew", padx=pad(10))
        self.scl_cq = ttk.Scale(row_q, from_=16, to=32, variable=self.var_cq,
                                command=self._cq_changed)
        self.scl_cq.pack(side="left", fill="x", expand=True)
        self.lbl_cq = ttk.Label(row_q, text="23", width=4)
        self.lbl_cq.pack(side="left", padx=pad(6))

        ttk.Label(r, text="输出格式：").grid(row=6, column=0, sticky="w",
                                            padx=pad(8), pady=(pad(10), 0))
        self.cmb_fmt = ttk.Combobox(r, textvariable=self.var_format,
                                    values=["mp4", "mkv", "mov"], state="readonly",
                                    width=8)
        self.cmb_fmt.grid(row=7, column=0, sticky="w", padx=pad(10))

        ttk.Label(r, text="输出目录（留空=与源文件同目录）：").grid(
            row=8, column=0, columnspan=2, sticky="w", padx=pad(8), pady=(pad(10), 0))
        row_o = ttk.Frame(r)
        row_o.grid(row=9, column=0, columnspan=2, sticky="ew", padx=pad(10))
        ttk.Entry(row_o, textvariable=self.var_outdir).pack(
            side="left", fill="x", expand=True)
        ttk.Button(row_o, text="…", width=3, command=self._pick_outdir).pack(side="left")

        ttk.Checkbutton(r, text="覆盖已存在的输出文件（否则自动改名 _1/_2）",
                        variable=self.var_overwrite).grid(
            row=10, column=0, columnspan=2, sticky="w", padx=pad(10), pady=pad(8))

        self._build_record_tab(tab2)

        # 底：状态 + 日志（转码/录制共用）
        bottom = ttk.LabelFrame(self.root, text="执行日志")
        bottom.pack(fill="x", padx=pad(10), pady=(pad(4), pad(10)))
        row_b = ttk.Frame(bottom)
        row_b.pack(fill="x", padx=pad(8), pady=pad(6))
        self.btn_start = ttk.Button(row_b, text="开始转换", command=self._start)
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(row_b, text="停止", command=self._stop, state="disabled")
        self.btn_stop.pack(side="left", padx=pad(6))
        self.lbl_state = ttk.Label(row_b, text="就绪")
        self.lbl_state.pack(side="left", padx=pad(12))
        self.pbar = ttk.Progressbar(row_b, maximum=100, length=pad(260))
        self.pbar.pack(side="right")

        self.txt = tk.Text(bottom, height=9, state="disabled", wrap="none",
                           font=("Microsoft YaHei UI", 9))
        self.txt.pack(fill="x", padx=pad(8), pady=(0, pad(8)))

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

    def _build_record_tab(self, r):
        s = self.scale
        padx = lambda v: int(v * s)
        r.columnconfigure(0, weight=1)
        r.columnconfigure(1, weight=0)

        ttk.Label(r, text="直播源地址：抖音直播间链接 / 房间号 / 分享短链 / 主页链接，"
                          "或 m3u8 / flv / mp4 直链 / rtmp：").grid(
            row=0, column=0, columnspan=2, sticky="w",
            padx=padx(10), pady=(padx(14), 0))
        self.var_url = tk.StringVar()
        ttk.Entry(r, textvariable=self.var_url).grid(
            row=1, column=0, columnspan=2, sticky="ew", padx=padx(10), pady=padx(4))

        # ---- 抖音解析行 ----
        row_p = ttk.Frame(r)
        row_p.grid(row=2, column=0, columnspan=2, sticky="w",
                   padx=padx(10), pady=(padx(2), 0))
        self.btn_probe = ttk.Button(row_p, text="解析画质", command=self._probe_rec_source)
        self.btn_probe.pack(side="left")
        ttk.Label(row_p, text="录制画质：").pack(side="left", padx=(padx(12), 0))
        self.var_quality = tk.StringVar(value=core.AUTO_QUALITY)
        self.cmb_quality = ttk.Combobox(row_p, textvariable=self.var_quality,
                                        values=list(core.RECORD_QUALITIES),
                                        state="readonly", width=16)
        self.cmb_quality.pack(side="left", padx=padx(4))
        self.lbl_probe = ttk.Label(row_p, text="", foreground="#888888")
        self.lbl_probe.pack(side="left", padx=padx(10))

        ttk.Label(r, text="（填抖音地址时点一下「解析画质」可看到主播与画质档位；"
                          "直链地址无需解析，直接录制）",
                  foreground="#888888").grid(
            row=3, column=0, columnspan=2, sticky="w", padx=padx(10), pady=(padx(2), 0))

        ttk.Label(r, text="保存位置（留空=按主播名+时间自动命名）：").grid(
            row=4, column=0, columnspan=2, sticky="w", padx=padx(10), pady=(padx(8), 0))
        row_d = ttk.Frame(r)
        row_d.grid(row=5, column=0, columnspan=2, sticky="ew", padx=padx(10))
        row_d.columnconfigure(0, weight=1)
        self.var_rec_dst = tk.StringVar()
        ttk.Entry(row_d, textvariable=self.var_rec_dst).grid(
            row=0, column=0, sticky="ew")
        ttk.Button(row_d, text="…", width=3, command=self._pick_rec_dst).grid(row=0, column=1)

        row_o = ttk.Frame(r)
        row_o.grid(row=6, column=0, columnspan=2, sticky="w", padx=padx(10), pady=(padx(10), 0))
        ttk.Label(row_o, text="最长录制（分钟，0=不限）：").pack(side="left")
        self.var_rec_limit = tk.IntVar(value=0)
        ttk.Spinbox(row_o, from_=0, to=1440, textvariable=self.var_rec_limit,
                    width=6).pack(side="left", padx=padx(6))
        self.var_rec_reconnect = tk.BooleanVar(value=True)
        ttk.Checkbutton(row_o, text="HTTP 直链断流自动重连",
                        variable=self.var_rec_reconnect).pack(side="left", padx=padx(10))
        self.var_rec_wait = tk.BooleanVar(value=False)
        ttk.Checkbutton(row_o, text="未开播时自动等待开录（每 30 秒重试）",
                        variable=self.var_rec_wait).pack(side="left", padx=padx(10))

        row_c1 = ttk.Frame(r)
        row_c1.grid(row=7, column=0, columnspan=2, sticky="w", padx=padx(10), pady=(padx(6), 0))
        self.var_rec_mp4 = tk.BooleanVar(value=True)
        ttk.Checkbutton(row_c1, text="停止后自动无损转成 mp4（录制中间件为 ts，不会坏）",
                        variable=self.var_rec_mp4).pack(side="left")
        self.var_rec_keep = tk.BooleanVar(value=False)
        ttk.Checkbutton(row_c1, text="保留 ts 中间文件",
                        variable=self.var_rec_keep).pack(side="left", padx=padx(12))

        row_c2 = ttk.Frame(r)
        row_c2.grid(row=8, column=0, columnspan=2, sticky="w", padx=padx(10), pady=(padx(4), 0))
        self.var_rec_transcode = tk.BooleanVar(value=False)
        ttk.Checkbutton(row_c2, text="录完自动重编码：",
                        variable=self.var_rec_transcode).pack(side="left")
        self.var_rec_tmode = tk.StringVar(value=core.TRANSCODE_MODES[0][1])
        ttk.Combobox(row_c2, textvariable=self.var_rec_tmode, state="readonly", width=22,
                     values=[txt for _, txt in core.TRANSCODE_MODES]).pack(side="left",
                                                                          padx=padx(4))
        ttk.Label(row_c2, text="（质量档沿用「视频转码」页的 CQ 设置）",
                  foreground="#888888").pack(side="left", padx=padx(6))

        row_r = ttk.Frame(r)
        row_r.grid(row=9, column=0, columnspan=2, sticky="w", padx=padx(10), pady=padx(14))
        self.btn_rec_start = ttk.Button(row_r, text="开始录制", command=self._start_rec)
        self.btn_rec_start.pack(side="left")
        self.btn_rec_stop = ttk.Button(row_r, text="停止录制", command=self._stop_rec,
                                       state="disabled")
        self.btn_rec_stop.pack(side="left", padx=padx(8))
        self.lbl_rec = ttk.Label(row_r, text="待命")
        self.lbl_rec.pack(side="left", padx=padx(12))
        self.pbar_rec = ttk.Progressbar(row_r, mode="indeterminate", length=int(180 * s))
        self.pbar_rec.pack(side="left")

        ttk.Label(r, text="提示：录制全程不重编码（-c copy），CPU 占用极低；"
                          "抖音地址会先自动解析出推流地址再录制。").grid(
            row=10, column=0, columnspan=2, sticky="w", padx=padx(10), pady=(padx(6), padx(10)))

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
            self.lbl_probe.config(text="非抖音地址，直接录制", foreground="#1a7a3c")
            return
        if self.probe_worker and self.probe_worker.is_alive():
            return
        self.btn_probe.config(state="disabled")
        self.lbl_probe.config(text="解析中…", foreground="#888888")
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
        avail = (room or {}).get("available") or []
        values = [core.AUTO_QUALITY] + avail
        self.cmb_quality.config(values=values)
        if self.var_quality.get() not in values:
            self.var_quality.set(values[0] if avail else core.AUTO_QUALITY)
        nick = room.get("nickname") or "未知主播"
        if room.get("is_live"):
            text = f"✓ {nick} · 直播中 · {len(avail)} 档画质"
            self.lbl_probe.config(text=text, foreground="#1a7a3c")
        else:
            text = f"✗ {nick} · 未开播"
            if avail:
                text += f" · 已缓存 {len(avail)} 档地址"
            self.lbl_probe.config(text=text, foreground="#c0392b")

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
            self.pbar_rec.start(12)
            self.lbl_rec.config(text="录制中…")
        else:
            self.pbar_rec.stop()

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
                        self.lbl_probe.config(text=f"解析失败：{str(payload)[:60]}",
                                              foreground="#c0392b")
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
                                           foreground="#1a7a3c")
                        self._log(f"ffmpeg 就绪：{ver}")
                    else:
                        self.lbl_ff.config(text="未找到 ffmpeg", foreground="#c0392b")
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
        self.txt.config(state="normal")
        self.txt.insert("end", text + "\n")
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
