# -*- coding: utf-8 -*-
"""转码引擎：纯逻辑、无 GUI 依赖，可被界面/命令行/自检脚本复用。"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import douyin

CFG_NAME = "vt_config.json"
VIDEO_EXTS = {".ts", ".mp4", ".mkv", ".mov", ".avi", ".flv", ".wmv",
              ".webm", ".m4v", ".mpg", ".mpeg", ".3gp", ".mts", ".m2ts"}

NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


# ---------- ffmpeg 查找与探测 ----------

def app_dir():
    """exe 同目录（onefile 打包后 __file__ 指向临时解压目录，配置必须放这里才不丢）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def find_ffmpeg(configured=None):
    """优先级：exe 同目录(内置/一键下载) > 用户指定 > PATH > Chocolatey。"""
    candidates = []
    base = app_dir()
    candidates.append(base / "ffmpeg.exe")
    candidates.append(base / "ffmpeg" / "ffmpeg.exe")
    if configured:
        candidates.append(configured)
    w = shutil.which("ffmpeg")
    if w:
        candidates.append(w)
    candidates.append(r"C:\ProgramData\chocolatey\bin\ffmpeg.exe")
    for c in candidates:
        try:
            if c and Path(c).is_file():
                return Path(c)
        except Exception:
            pass
    return None


def find_ffprobe(ffmpeg_path):
    if not ffmpeg_path:
        return None
    p = Path(ffmpeg_path).parent / "ffprobe.exe"
    if p.is_file():
        return p
    w = shutil.which("ffprobe")
    return Path(w) if w else None


def ffmpeg_version(ffmpeg_path):
    try:
        r = subprocess.run([str(ffmpeg_path), "-hide_banner", "-version"],
                           capture_output=True, text=True, timeout=20,
                           creationflags=NO_WINDOW)
        first = (r.stdout or "").splitlines()
        return first[0] if first else "未知版本"
    except Exception as e:
        return f"不可用: {e}"


def has_encoder(ffmpeg_path, name):
    try:
        r = subprocess.run([str(ffmpeg_path), "-hide_banner", "-encoders"],
                           capture_output=True, text=True, timeout=30,
                           creationflags=NO_WINDOW)
        return name in (r.stdout or "")
    except Exception:
        return False


def media_duration(ffprobe_path, media_path):
    """返回秒数，失败返回 None。"""
    try:
        r = subprocess.run([str(ffprobe_path), "-v", "error", "-show_entries",
                            "format=duration", "-of", "json", str(media_path)],
                           capture_output=True, text=True, timeout=60,
                           creationflags=NO_WINDOW)
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:
        return None


# ---------- 命令构造 ----------

def build_command(mode, cq, src, dst, nvenc_h264=True, nvenc_h265=True):
    """返回 (完整参数列表, 是否无损)。mode: copy / h264 / h265"""
    src, dst = str(src), str(dst)
    args = ["-hide_banner", "-nostdin", "-nostats", "-loglevel", "warning",
            "-progress", "pipe:1"]
    if mode == "copy":
        args += ["-fflags", "+genpts", "-i", src,
                 "-map", "0", "-c", "copy", "-y", dst]
        return args, True
    if mode == "h264":
        if nvenc_h264:
            vcodec = "h264_nvenc"
            vopts = ["-preset", "p5", "-rc", "vbr", "-cq", str(cq), "-b:v", "0"]
        else:
            vcodec = "libx264"
            vopts = ["-preset", "medium", "-crf", str(cq)]
        args += ["-i", src, "-map", "0:v:0", "-map", "0:a?",
                 "-c:v", vcodec] + vopts + \
                ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-y", dst]
        return args, False
    if mode == "h265":
        if nvenc_h265:
            vcodec = "hevc_nvenc"
            vopts = ["-preset", "p6", "-rc", "vbr", "-cq", str(cq), "-b:v", "0"]
        else:
            vcodec = "libx265"
            vopts = ["-preset", "medium", "-crf", str(cq)]
        args += ["-i", src, "-map", "0:v:0", "-map", "0:a?",
                 "-c:v", vcodec] + vopts + ["-tag:v", "hvc1"] + \
                ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-y", dst]
        return args, False
    raise ValueError(f"未知模式: {mode}")


# ---------- 执行 ----------

_TIME_RE = re.compile(r"out_time=(\d+):(\d+):(\d+(?:\.\d+)?)")


def run_ffmpeg(ffmpeg_path, args, duration=None,
               on_progress=None, on_log=None, stop_event=None):
    """阻塞执行。返回 (是否成功, 失败原因)。on_progress(0~1)、on_log(文本)。"""
    if not ffmpeg_path or not Path(ffmpeg_path).is_file():
        return False, (f"ffmpeg 不存在：{ffmpeg_path}\n"
                       "（请在界面重新指定，或点「一键下载 ffmpeg」重新装一份）")
    proc = subprocess.Popen([str(ffmpeg_path)] + list(args),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace",
                            bufsize=1, creationflags=NO_WINDOW)
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            m = _TIME_RE.match(line)
            if m and duration:
                secs = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
                if on_progress:
                    on_progress(min(1.0, secs / duration))
            elif re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", line):
                if line == "progress=end" and on_progress:
                    on_progress(1.0)
            else:
                if on_log:
                    on_log(line)
            if stop_event is not None and stop_event.is_set():
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()
                return False, "已取消"
        code = proc.wait()
        if code == 0:
            return True, ""
        return False, f"ffmpeg 退出码 {code}"
    finally:
        try:
            if proc.poll() is None:
                proc.kill()
        except Exception:
            pass


# ---------- ffmpeg 一键下载安装 ----------
# 说明：清华镜像站(mirrors.tuna.tsinghua.edu.cn)未收录 ffmpeg 的 Windows 二进制
# （TUNA 的 github-release 里没有 BtbN/FFmpeg-Builds，也没有 /ffmpeg 目录）。
#
# 为什么不会因版本更新失效（两层保险）：
#   1) 动态解析：查 GitHub API 的 latest release，从资产清单里按正则挑 win64-gpl-shared
#      的 zip，取体积最小者。上游改版本号/资产名也能自动跟上。
#   2) 固定别名：BtbN 的资产名本身不含具体版本（ffmpeg-master-latest-win64-gpl-shared.zip），
#      上游每次发版都是同名覆盖，"latest" 这个 tag 永远存在 → 死链风险极低。
#   3) 再加 gyan.dev 的 ffmpeg-release-essentials.zip 别名 + 版本页兜底。
#   4) 全部失败时，界面会弹出输入框让你直接粘贴任意 zip 直链（终极兜底）。
GITHUB_API_LATEST = "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/tags/latest"
PINNED_ASSET = "ffmpeg-master-latest-win64-gpl-shared.zip"
ASSET_NAME_RE = re.compile(r"^ffmpeg-(?:master|n[\d.]+)-latest-win64-gpl-shared(?:-\d+)?\.zip$")
PROXIES = [
    ("https://gh-proxy.com/", "gh-proxy 加速"),
    ("https://ghfast.top/", "ghfast 加速"),
]
DIRECT = ("", "GitHub 直连")
GYAN_ALIAS = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
GYAN_PAGE = "https://www.gyan.dev/ffmpeg/builds/"


def _http_text(url, timeout=25):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _pick_asset(assets):
    """从 release 资产里挑最小体积的 win64-gpl-shared 包（GPL 版才带 x264/x265 软编）。"""
    ok = [a for a in assets if ASSET_NAME_RE.match(a.get("name", ""))]
    if not ok:
        raise RuntimeError("release 资产里没有匹配 win64-gpl-shared 的包")
    ok.sort(key=lambda a: a.get("size", 0))
    a = ok[0]
    return a["name"], a["browser_download_url"], a.get("size", 0) / 1048576


def resolve_download_candidates(custom_url=None, on_log=None):
    """按优先级列出可尝试的下载地址 [(url, 说明)]。"""
    cands, seen = [], set()

    def add(url, label):
        if url and url not in seen:
            seen.add(url)
            cands.append((url, label))

    if custom_url:
        add(custom_url, "自定义地址")

    def add_dynamic(prefix, pname):
        """查 GitHub API 拿当前 latest 的真实资产名（版本更新也能跟上）。"""
        try:
            data = json.loads(_http_text(prefix + GITHUB_API_LATEST, timeout=30))
            name, url, mb = _pick_asset(data.get("assets", []))
            add(prefix + url, f"{pname} 动态解析 → {name}（{mb:.0f}MB）")
        except Exception as e:
            if on_log:
                on_log(f"    {pname} 动态解析失败：{e}")

    # 1) 加速源动态解析（首选）
    for prefix, pname in PROXIES:
        add_dynamic(prefix, pname)
    # 2) 加速源固定别名兜底（BtbN 资产名本身不含版本号，同名覆盖）
    for prefix, pname in PROXIES:
        add(prefix + "https://github.com/BtbN/FFmpeg-Builds/releases/download/"
                     f"latest/{PINNED_ASSET}",
            f"{pname} 固定别名 → {PINNED_ASSET}（82MB）")
    # 3) gyan.dev 官方别名 + 版本页
    add(GYAN_ALIAS, "gyan.dev 官方别名（106MB）")
    try:
        html = _http_text(GYAN_PAGE)
        names = sorted(set(re.findall(r"ffmpeg-[\d.]+-essentials_build\.zip", html)),
                       key=lambda n: [int(x) for x in re.findall(r"\d+", n)][:3],
                       reverse=True)
        if names:
            add(f"https://www.gyan.dev/ffmpeg/builds/{names[0]}",
                f"gyan.dev 版本页 → {names[0]}")
    except Exception as e:
        if on_log:
            on_log(f"    gyan.dev 版本页解析失败：{e}")
    # 4) GitHub 直连放最后（国内多为超时，仅作兜底）
    add_dynamic(DIRECT[0], DIRECT[1])
    add("https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
        f"{PINNED_ASSET}", f"{DIRECT[1]} 固定别名（82MB）")
    return cands


def _download(url, dst, on_progress=None, on_log=None, stop_event=None):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp, open(dst, "wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        last_report = 0
        while True:
            if stop_event is not None and stop_event.is_set():
                raise RuntimeError("已取消")
            chunk = resp.read(262144)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if on_progress and total:
                on_progress(done / total)
            if on_log and done - last_report >= 20 * 1048576:
                last_report = done
                on_log(f"    已下载 {done / 1048576:.0f} MB"
                       + (f" / {total / 1048576:.0f} MB" if total else ""))
    if dst.stat().st_size < 1048576:
        raise RuntimeError("下载内容异常（文件过小）")


def _extract_ffmpeg(zip_path, target_dir):
    """把压缩包里 ffmpeg.exe / ffprobe.exe 及同目录依赖 dll 解到目标目录。"""
    import posixpath
    import zipfile
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        hits = [n for n in names if n.lower().endswith("/ffmpeg.exe")]
        if not hits:
            raise RuntimeError("压缩包里没有找到 ffmpeg.exe")
        bindir = posixpath.dirname(hits[0])
        members = [n for n in names
                   if posixpath.dirname(n) == bindir
                   and not n.lower().endswith("ffplay.exe")]
        import shutil as _sh
        for n in members:
            with z.open(n) as src, open(target_dir / posixpath.basename(n), "wb") as out:
                _sh.copyfileobj(src, out, 262144)
    return len(members)


def install_ffmpeg(target_dir=None, on_progress=None, on_log=None,
                   stop_event=None, custom_url=None):
    """一键下载安装 ffmpeg 到 exe 同目录的 ffmpeg\\ 下。返回 (成功?, 消息)。"""
    import tempfile
    target = Path(target_dir) if target_dir else (app_dir() / "ffmpeg")
    target.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="ffmpeg_dl_"))
    candidates = resolve_download_candidates(custom_url, on_log)
    if on_log:
        on_log(f"    共 {len(candidates)} 个下载地址候选，按顺序尝试")
    errors = []
    for url, label in candidates:
        if stop_event is not None and stop_event.is_set():
            return False, "已取消"
        try:
            if on_log:
                on_log(f"    尝试：{label}")
            zip_path = tmp / "ffmpeg.zip"
            _download(url, zip_path, on_progress, on_log, stop_event)
            n = _extract_ffmpeg(zip_path, target)
            exe = target / "ffmpeg.exe"
            if not exe.is_file():
                raise RuntimeError("解压后没有 ffmpeg.exe")
            ver = ffmpeg_version(exe)
            if "不可用" in ver:
                raise RuntimeError(f"装好的 ffmpeg 无法运行：{ver}")
            try:
                zip_path.unlink()
            except Exception:
                pass
            return True, f"已安装 {n} 个文件到 {target}\n{ver.split('Copyright')[0].strip()}"
        except Exception as e:
            errors.append(f"{label} → {e}")
            if on_log:
                on_log(f"    失败：{e}")
    return False, "所有下载地址都失败了（可在界面手动粘贴 zip 直链重试）：\n" + "\n".join(errors[-6:])



# ---------- 直播源解析（抖音） ----------
# 把「抖音直播间链接 / 房间号 / App 分享短链 / 用户主页链接」解析成 ffmpeg 可直接
# 录制的推流地址。非抖音输入原样透传，因此填入 m3u8/flv/rtmp 直链时行为完全不变。
#
# 解析逻辑全在 douyin.py（纯标准库，不新增任何第三方依赖）。

# 界面下拉框用的画质选项，第 0 项是「自动」
RECORD_QUALITIES = douyin.quality_labels()
AUTO_QUALITY = RECORD_QUALITIES[0]

# 「录完自动重编码」可选模式（copy 无意义，这里只列真正的重编码）
TRANSCODE_MODES = (
    ("h264", "H.264 重编码（兼容性最好）"),
    ("h265", "H.265 重编码（体积最小）"),
)


def mode_from_label(label):
    """界面文案 → 模式名，未命中返回 None。"""
    for mode, text in TRANSCODE_MODES:
        if text == label:
            return mode
    return None


def label_from_mode(mode):
    """模式名 → 界面文案。"""
    for m, text in TRANSCODE_MODES:
        if m == mode:
            return text
    return mode or ""


def normalize_quality(text):
    """把 or4 / 原画 / 原画 (OR4) 统一成画质全名；auto 或空返回 None（表示自动）。"""
    return douyin.normalize_quality(text)


def is_douyin_input(text) -> bool:
    """输入是否需要走抖音解析。"""
    return douyin.is_douyin_input(text or "")


def probe_live_room(url, on_log=None):
    """只探测直播间信息，不要求已开播（供界面「解析画质」按钮 / CLI --list 用）。

    返回 room dict，额外带 ``available``（可选画质列表）。
    非抖音输入返回 None。
    """
    if not is_douyin_input(url):
        return None
    room = douyin.DouyinLiveExtractor(on_log=on_log).resolve(url)
    room["available"] = douyin.available_qualities(room.get("streams", {}))
    return room


def prepare_record_source(url, quality=None, wait=False, interval=30, timeout=0,
                          stop_event=None, on_log=None, prefer="flv"):
    """把录制输入统一解析成可录制的推流地址。

    返回 (stream_url, info)：

    - 非抖音输入     → (原样 url, {"douyin": False})
    - 抖音且解析成功 → (真实推流地址, {"douyin": True, "nickname": …, …})
    - 等待开播被取消 → (None, {"douyin": True, "cancelled": True})

    解析失败抛 douyin.DouyinError；未开播且未开启等待时抛 douyin.NotLiveError。
    """
    url = (url or "").strip()
    if not is_douyin_input(url):
        return url, {"douyin": False}

    log = on_log or (lambda t: None)
    extractor = douyin.DouyinLiveExtractor(on_log=log)

    room = extractor.resolve(url)
    if not douyin.is_ready(room):
        if not wait:
            who = room.get("nickname") or "该主播"
            state = "未开播" if not room.get("is_live") else "已开播但暂未取到流地址"
            raise douyin.NotLiveError(f"{who} {state}")
        log("尚未开播，进入等待模式（点「停止」可随时取消）…")
        room = douyin.wait_until_live(extractor, url, interval=interval,
                                      timeout=timeout, stop_event=stop_event,
                                      on_log=log)
        if room is None:
            return None, {"douyin": True, "cancelled": True}

    picked, stream_url = douyin.pick_url(room["streams"], quality, prefer=prefer)
    if not stream_url:
        avail = "、".join(douyin.available_qualities(room["streams"])) or "无"
        raise douyin.DouyinError(f"该直播间没有画质「{quality}」，可选：{avail}")

    return stream_url, {
        "douyin": True,
        "cancelled": False,
        "is_live": True,
        "nickname": room.get("nickname") or "",
        "title": room.get("title") or "",
        "room_id": room.get("room_id"),
        "web_rid": room.get("web_rid"),
        "quality": picked,
        "available": douyin.available_qualities(room["streams"]),
        "live_url": room.get("live_url") or "",
    }


# ---------- 直播录制 ----------

def build_record_command(url, dst_ts, limit_sec=0, reconnect=True):
    """录制直播源到临时 ts（流式容器，中途停止也不会坏）。"""
    args = ["-hide_banner", "-nostdin", "-nostats", "-loglevel", "warning",
            "-progress", "pipe:1", "-user_agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"]
    if reconnect and url.lower().startswith(("http://", "https://")):
        args += ["-reconnect", "1", "-reconnect_streamed", "1",
                 "-reconnect_delay_max", "10"]
    args += ["-i", str(url), "-map", "0", "-c", "copy", "-y"]
    if limit_sec and limit_sec > 0:
        args += ["-t", str(int(limit_sec))]
    args += [str(dst_ts)]
    return args


def remux_command(src, dst):
    return ["-hide_banner", "-nostdin", "-nostats", "-loglevel", "warning",
            "-fflags", "+genpts", "-i", str(src),
            "-map", "0", "-c", "copy", "-y", str(dst)]


# ---------- 输出命名与配置 ----------

def unique_dst(dst):
    dst = Path(dst)
    if not dst.exists():
        return dst
    i = 1
    while True:
        c = dst.with_name(f"{dst.stem}_{i}{dst.suffix}")
        if not c.exists():
            return c
        i += 1


def load_config(base_dir):
    try:
        return json.loads((Path(base_dir) / CFG_NAME).read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(base_dir, cfg):
    try:
        (Path(base_dir) / CFG_NAME).write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
