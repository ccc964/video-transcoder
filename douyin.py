# -*- coding: utf-8 -*-
"""抖音直播源解析。

把「抖音直播间链接 / 房间号 / App 分享短链 / 用户主页链接」解析成
可直接交给 ffmpeg 录制的推流地址（FLV / HLS）。

设计约束
--------
- **纯标准库**，不引入任何第三方依赖（本工具 exe 只有 12MB，不能因解析功能膨胀）
- **不下载浏览器内核**：需要渲染 JS 时才复用系统自带 Edge / Chrome 的
  ``--headless=new --dump-dom``，额外体积为 0
- 输入不是抖音链接时，调用方应原样透传，本模块不参与
"""

from __future__ import annotations

import gzip
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
from http.client import InvalidURL
from http.cookiejar import CookieJar
from typing import Dict, List, Optional, Tuple
from urllib import error as urllib_error
from urllib.parse import parse_qs, unquote, urlencode, urlparse
from urllib.request import HTTPCookieProcessor, HTTPSHandler, Request, build_opener


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

FLV_QUALITIES = {
    "or4.flv": "原画 (OR4)",
    "hd.flv": "高清 (HD)",
    "sd.flv": "标清 (SD)",
    "ld.flv": "流畅 (LD)",
}

HLS_QUALITIES = {
    "or4.m3u8": "原画 (OR4)",
    "hd.m3u8": "高清 (HD)",
    "sd.m3u8": "标清 (SD)",
    "ld.m3u8": "流畅 (LD)",
}

HLS_INDEX_QUALITIES = {
    "or4": "原画 (OR4)",
    "uhd": "超清 (UHD)",
    "hd": "高清 (HD)",
    "sd": "标清 (SD)",
    "ld": "流畅 (LD)",
    "md": "流畅 (LD)",
}

# 画质从高到低，同时用于界面下拉框排序
QUALITY_ORDER = ["原画 (OR4)", "超清 (UHD)", "高清 (HD)", "标清 (SD)", "流畅 (LD)"]

# 命令行 --quality 的短名 -> 画质全名
QUALITY_ALIASES = {
    "or4": "原画 (OR4)", "origin": "原画 (OR4)", "yuanhua": "原画 (OR4)",
    "uhd": "超清 (UHD)", "chaoqing": "超清 (UHD)",
    "hd": "高清 (HD)", "gaoqing": "高清 (HD)",
    "sd": "标清 (SD)", "biaoqing": "标清 (SD)",
    "ld": "流畅 (LD)", "liuchang": "流畅 (LD)",
}

# 抖音域名特征
DOUYIN_HOSTS = ("live.douyin.com", "v.douyin.com", "www.douyin.com",
                "douyin.com", "iesdouyin.com", "webcast.amemv.com")

# 需要浏览器渲染才能解析的输入特征
BROWSER_ONLY_HINTS = ("douyin.com/user", "iesdouyin.com/share/user")

# 系统自带 Chromium 系浏览器候选路径
SYSTEM_BROWSER_PATHS = {
    "win32": (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ),
    "darwin": (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ),
    "linux": (
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/microsoft-edge",
    ),
}

SYSTEM_BROWSER_NAMES = ("msedge", "chrome", "chromium", "chromium-browser", "google-chrome")

# 设为 0 / false 可关闭浏览器兜底（只有主页链接会用到）
BROWSER_DISABLED = os.environ.get("DOUYIN_BROWSER", "1").strip().lower() in {
    "0", "false", "no", "off"}


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------

class DouyinError(Exception):
    """解析相关的通用错误（链接无效、网络异常、页面结构变化等）。"""


class NotLiveError(DouyinError):
    """主播当前未开播。"""


# ---------------------------------------------------------------------------
# 输入识别
# ---------------------------------------------------------------------------

def is_douyin_input(text: str) -> bool:
    """判断输入是否需要用抖音解析器处理。

    - 抖音域名链接（直播间 / 短链 / 主页）→ True
    - 纯数字房间号（6 位以上）→ True
    - m3u8 / flv / rtmp 等普通直链、本地文件路径 → False（调用方原样透传）
    """
    if not text:
        return False
    s = text.strip()
    if not s:
        return False
    low = s.lower()

    # 本地文件路径、普通流协议一律不接管
    if low.startswith(("rtmp://", "rtmps://", "rtsp://", "file:", "udp://",
                       "http+", "srt://")):
        return False

    if any(host in low for host in DOUYIN_HOSTS):
        return True

    # App 里「复制链接」拿到的是带文案的整段文本，先尝试抽出 URL
    m = re.search(r"(https?://[^\s]+)", s)
    if m and any(host in m.group(1).lower() for host in DOUYIN_HOSTS):
        return True

    # 纯房间号
    if s.isdigit() and len(s) >= 6:
        return True

    return False


def quality_labels() -> List[str]:
    """界面下拉框用的画质选项（含「自动」）。"""
    return ["自动（最高画质）"] + QUALITY_ORDER


def normalize_quality(text: str) -> Optional[str]:
    """把 --quality or4 / 原画 / 原画 (OR4) 统一成画质全名。空=自动。"""
    if not text:
        return None
    t = text.strip()
    if t in QUALITY_ORDER:
        return t
    return QUALITY_ALIASES.get(t.lower())


# ---------------------------------------------------------------------------
# 系统浏览器（仅主页链接需要）
# ---------------------------------------------------------------------------

def find_system_browser() -> Optional[str]:
    """定位本机 Chromium 系浏览器可执行文件，找不到返回 None。"""
    for path in SYSTEM_BROWSER_PATHS.get(sys.platform, ()):
        if os.path.isfile(path):
            return path
    for name in SYSTEM_BROWSER_NAMES:
        found = shutil.which(name)
        if found:
            return found
    return None


# ---------------------------------------------------------------------------
# 解析器
# ---------------------------------------------------------------------------

class DouyinLiveExtractor:
    """解析抖音直播间并提取推流地址。"""

    def __init__(self, on_log=None) -> None:
        self.on_log = on_log
        self.cookie_jar = CookieJar()
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        self.opener = build_opener(
            HTTPSHandler(context=ssl_ctx),
            HTTPCookieProcessor(self.cookie_jar),
        )
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        }
        self._cookies_ready = False
        self._browser_hint_shown = False

    # ----- 基础设施 -----

    def _log(self, text: str) -> None:
        if self.on_log:
            try:
                self.on_log(text)
            except Exception:
                pass

    def _request(self, url: str, headers: Optional[dict] = None, data=None, timeout: int = 15):
        hdrs = dict(self.headers)
        if headers:
            hdrs.update(headers)
        req = Request(url, data=data, headers=hdrs)
        if data:
            req.add_header("Content-Type", "application/json")
        resp = self.opener.open(req, timeout=timeout)
        body = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
        return body.decode("utf-8", errors="replace"), resp

    def _ensure_cookies(self) -> None:
        """首次请求时再初始化 ttwid，避免仅仅 import 就联网。"""
        if self._cookies_ready:
            return
        self._cookies_ready = True
        try:
            self._request("https://live.douyin.com/", timeout=10)
            if self._has_cookie("ttwid"):
                self._log("    [OK] 已获取 ttwid cookie")
                return
            payload = json.dumps({
                "region": "cn",
                "aid": 1768,
                "needFid": False,
                "service": "www.ixigua.com",
                "migrate_info": {"ticket": "", "source": "node"},
                "cbUrlProtocol": "https",
                "union": True,
            }).encode("utf-8")
            self._request(
                "https://ttwid.bytedance.com/ttwid/union/register/",
                data=payload, timeout=10)
            if self._has_cookie("ttwid"):
                self._log("    [OK] 已从备用接口获取 ttwid cookie")
                return
            self._log("    [WARN] 未能确认 ttwid，继续尝试")
        except Exception as exc:
            self._log(f"    [WARN] cookie 初始化失败：{exc}")

    def _has_cookie(self, name: str) -> bool:
        return any(cookie.name == name for cookie in self.cookie_jar)

    # ----- 输入归一化 -----

    @staticmethod
    def _normalize_input(user_input: str) -> str:
        text = user_input.strip()
        embedded_url = re.search(r"(https?://[^\s]+)", text)
        if embedded_url:
            text = embedded_url.group(1)
        return text.strip().rstrip("/")

    def _parse_room_id(self, user_input: str) -> str:
        user_input = user_input.strip()

        short_link_match = re.search(r"(https?://v\.douyin\.com/[a-zA-Z0-9]+)", user_input)
        if short_link_match:
            try:
                html, resp = self._request(short_link_match.group(1), timeout=10)
                for pattern in (
                    r'"roomId"\s*:\s*"(\d+)"',
                    r'\\*"webRid\\*"\s*:\s*\\*"(\d+)\\*"',
                    r"room_id=(\d+)",
                ):
                    match = re.search(pattern, html) or re.search(pattern, resp.url)
                    if match:
                        return match.group(1)
                user_input = resp.url
            except Exception:
                pass

        for pattern in (
            r"live\.douyin\.com/([^/?#]+)",
            r"/live/(\d+)",
            r"room_id=(\d+)",
        ):
            match = re.search(pattern, user_input)
            if match:
                return match.group(1)

        parsed = urlparse(user_input if "://" in user_input else "https://" + user_input)
        parts = [part for part in parsed.path.strip("/").split("/") if part]
        if parts:
            return parts[-1]
        return user_input

    # ----- 候选生成 -----

    @staticmethod
    def _extract_candidates_from_text(text: str) -> List[str]:
        values: List[str] = []
        raw = text.strip()
        if not raw:
            return values

        if raw.startswith("http://") or raw.startswith("https://"):
            parsed = urlparse(raw)
            query = parse_qs(parsed.query)
            sec_uid = query.get("sec_uid", [None])[0]
            if sec_uid:
                values.append(sec_uid)
            for pattern in (
                r"(?:douyin\.com|iesdouyin\.com)/user/([^/?#]+)",
                r"iesdouyin\.com/share/user/([^/?#]+)",
                r"live\.douyin\.com/([^/?#]+)",
            ):
                m = re.search(pattern, raw)
                if m:
                    values.append(m.group(1))
        else:
            values.append(raw)

        values.append(raw)
        return values

    def _render_with_system_browser(self, url: str, budget_ms: int = 8000) -> Optional[str]:
        """用系统自带 Edge / Chrome 的 headless 模式渲染页面并返回 DOM。"""
        browser = find_system_browser()
        if not browser:
            return None
        profile_dir = tempfile.mkdtemp(prefix="dyls-browser-")
        try:
            proc = subprocess.run(
                [browser, "--headless=new", "--disable-gpu", "--no-sandbox",
                 "--no-first-run", "--no-default-browser-check",
                 "--disable-extensions", "--mute-audio",
                 f"--user-data-dir={profile_dir}",
                 f"--virtual-time-budget={budget_ms}",
                 "--dump-dom", url],
                capture_output=True, timeout=90,
            )
            dom = proc.stdout.decode("utf-8", errors="replace")
            return dom if len(dom) > 2000 else None
        except Exception:
            return None
        finally:
            shutil.rmtree(profile_dir, ignore_errors=True)

    @staticmethod
    def _candidates_from_dom(dom: str) -> List[str]:
        """从渲染后的 DOM 提取直播间候选标识。

        必须用 roomIdStr（字符串）——roomId 是 JS number，18~19 位会被
        浮点精度截断（7681452107401628425 → 7681452107401629000）。
        """
        candidates: List[str] = []
        for value in re.findall(r'roomIdStr\\?"?\s*:\s*\\?"(\d{6,})', dom):
            if value and value != "0":
                candidates.append(value)
        for value in re.findall(r'webRid\\?"?\s*:\s*\\?"(\d{6,})', dom):
            candidates.append(value)
        for value in re.findall(r"live\.douyin\.com/(\d{6,})", dom):
            candidates.append(value)
        m = re.search(r"抖音号[:：]\s*([A-Za-z0-9._-]{2,30})", dom)
        if m:
            candidates.append(m.group(1))
        return candidates

    def _extract_candidates_with_browser(self, user_input: str) -> List[str]:
        if not any(hint in user_input for hint in BROWSER_ONLY_HINTS):
            return []
        if BROWSER_DISABLED:
            return []

        dom = self._render_with_system_browser(user_input)
        if dom is None:
            if not self._browser_hint_shown:
                self._browser_hint_shown = True
                self._log("    [提示] 未找到系统 Edge / Chrome，无法解析用户主页链接")
                self._log("           建议改用直播间链接、房间号或 App 分享短链")
            return []
        return self._candidates_from_dom(dom)

    @staticmethod
    def _is_viable_candidate(value: str) -> bool:
        if not value:
            return False
        if any(char.isspace() for char in value):
            return False
        return len(value) <= 512

    def _build_candidates(self, user_input: str) -> List[str]:
        normalized = self._normalize_input(user_input)
        candidates: List[str] = []

        if "v.douyin.com" in normalized or "live.douyin.com" in normalized:
            parsed = self._parse_room_id(normalized)
            if parsed:
                candidates.extend(self._extract_candidates_from_text(parsed))

        candidates.extend(self._extract_candidates_from_text(normalized))
        candidates.extend(self._extract_candidates_with_browser(normalized))

        clean: List[str] = []
        seen = set()
        for candidate in candidates:
            value = candidate.strip().strip("/")
            if value in seen or not self._is_viable_candidate(value):
                continue
            clean.append(value)
            seen.add(value)
        return clean

    # ----- 提取 -----

    @staticmethod
    def _extract_by_suffix(text: str) -> Tuple[dict, dict]:
        flv_results = {}
        hls_results = {}

        text = text.replace("\\u002F", "/").replace("\\u0026", "&")
        text = text.replace("\\/", "/").replace('\\"', '"')
        text = text.replace("&amp;", "&").replace("&quot;", '"')

        for table, out in ((FLV_QUALITIES, flv_results), (HLS_QUALITIES, hls_results)):
            for suffix, quality_name in table.items():
                pattern = rf'(https?://[^\s"\'<>,\{{\}}\\]+?{re.escape(suffix)}\?[^\s"\'<>,\{{\}}\\]*)'
                matches = re.findall(pattern, text)
                if matches:
                    out[quality_name] = matches[-1].rstrip('"\')}]')

        # 部分页面把 HLS 暴露成 ..._hd/index.m3u8
        index_pattern = (r'(https?://[^\s"\'<>,\{\}\\]+?_((?:or4|uhd|hd|sd|ld|md))'
                         r'/index\.m3u8\?[^\s"\'<>,\{\}\\]*)')
        for url, quality_key in re.findall(index_pattern, text, re.IGNORECASE):
            quality_name = HLS_INDEX_QUALITIES.get(quality_key.lower())
            if quality_name:
                hls_results[quality_name] = url.rstrip('"\')}]')

        return flv_results, hls_results

    def _extract_from_render_data(self, html: str) -> dict:
        results = {"flv": {}, "hls": {}}
        match = re.search(
            r'<script\s+id="RENDER_DATA"\s+type="application/json">(.*?)</script>',
            html, re.DOTALL)
        json_text = None
        if match:
            json_text = unquote(match.group(1))
        else:
            match = re.search(
                r'<script\s+id="__NEXT_DATA__"\s+type="application/json">(.*?)</script>',
                html, re.DOTALL)
            if match:
                json_text = match.group(1)

        if not json_text:
            return results

        try:
            data = json.loads(json_text)
        except Exception:
            flv_r, hls_r = self._extract_by_suffix(json_text)
            results["flv"] = flv_r
            results["hls"] = hls_r
            return results

        self._recursive_find(data, results)

        if len(results["flv"]) < 4 or len(results["hls"]) < 4:
            flv_r, hls_r = self._extract_by_suffix(json_text)
            for quality, url in flv_r.items():
                results["flv"].setdefault(quality, url)
            for quality, url in hls_r.items():
                results["hls"].setdefault(quality, url)
        return results

    def _recursive_find(self, data, results: dict) -> None:
        if isinstance(data, dict):
            if "flv_pull_url" in data:
                value = data["flv_pull_url"]
                if isinstance(value, dict):
                    for key, url in value.items():
                        results["flv"].setdefault(self._classify_quality(key), url)
                elif isinstance(value, str) and value.startswith("http"):
                    results["flv"].setdefault(self._classify_quality(value), value)

            if "hls_pull_url_map" in data and isinstance(data["hls_pull_url_map"], dict):
                for key, url in data["hls_pull_url_map"].items():
                    results["hls"].setdefault(self._classify_quality(key), url)

            if "hls_pull_url" in data and isinstance(data["hls_pull_url"], str):
                url = data["hls_pull_url"]
                if url.startswith("http"):
                    results["hls"].setdefault("HLS", url)

            skip = {"flv_pull_url", "hls_pull_url_map", "hls_pull_url"}
            for key, value in data.items():
                if key not in skip:
                    self._recursive_find(value, results)
        elif isinstance(data, list):
            for item in data:
                self._recursive_find(item, results)

    @staticmethod
    def _classify_quality(text: str) -> str:
        text_lower = text.lower()
        for suffix, name in FLV_QUALITIES.items():
            if suffix in text_lower:
                return name
        checks = [
            ("full_hd1", "原画 (OR4)"), ("fullhd1", "原画 (OR4)"),
            ("uhd", "超清 (UHD)"),
            ("hd1", "高清 (HD)"),
            ("sd1", "流畅 (LD)"), ("sd2", "标清 (SD)"),
            ("_uhd", "超清 (UHD)"),
            ("_origin", "原画 (OR4)"), ("origin", "原画 (OR4)"),
            ("_or4", "原画 (OR4)"), ("_or", "原画 (OR4)"),
            ("_hd", "高清 (HD)"), ("_sd", "标清 (SD)"), ("_ld", "流畅 (LD)"),
            ("_ao", "仅音频 (AO)"),
        ]
        for keyword, name in checks:
            if keyword in text_lower:
                return name
        return "默认"

    def _try_webcast_api(self, web_rid: str) -> dict:
        results = {"flv": {}, "hls": {}}
        params = urlencode({
            "aid": "6383", "app_name": "douyin_web", "live_id": "1",
            "device_platform": "web", "language": "zh-CN",
            "browser_language": "zh-CN", "browser_platform": "Win32",
            "browser_name": "Chrome", "browser_version": "131.0.0.0",
            "web_rid": web_rid,
        })
        url = f"https://live.douyin.com/webcast/room/web/enter/?{params}"
        try:
            body, _ = self._request(url, headers={"Referer": "https://live.douyin.com/"})
            data = json.loads(body)
            if data.get("status_code") == 0 and data.get("data"):
                self._recursive_find(data["data"], results)
                if len(results["flv"]) < 4 or len(results["hls"]) < 4:
                    flv_r, hls_r = self._extract_by_suffix(body)
                    for quality, url in flv_r.items():
                        results["flv"].setdefault(quality, url)
                    for quality, url in hls_r.items():
                        results["hls"].setdefault(quality, url)
        except Exception:
            pass
        return results

    def _extract_room_info(self, html: str) -> Optional[Dict[str, object]]:
        room_block = re.search(
            r'roomStore\\":\{\\"roomInfo\\":\{\\"room\\":\{'
            r'\\"id_str\\":\\"(?P<room_id>\d+)\\".*?'
            r'\\"status\\":(?P<status>\d+).*?'
            r'\\"title\\":\\"(?P<title>.*?)\\".*?'
            r'\\"user_count_str\\":\\"(?P<user_count>.*?)\\"',
            html, re.DOTALL)

        def _owner(prefix):
            return re.search(
                prefix + r'\\":\{\\"id_str\\":\\"(?P<anchor_id>[^"]+)\\".*?'
                         r'\\"sec_uid\\":\\"(?P<sec_uid>[^"]*)\\".*?'
                         r'\\"nickname\\":\\"(?P<nickname>.*?)\\"',
                html, re.DOTALL)

        owner_block = _owner(r"owner") or _owner(r"anchor")

        room_id_match = re.findall(r'roomId\\":\\"(\d+)\\"', html)
        web_rid_match = re.findall(r'web_rid\\":\\"([^"]+)\\"', html)
        empty_room_info = 'roomInfo\\":{}' in html or 'web_stream_url\\":null' in html

        if not room_block and not room_id_match and not web_rid_match:
            return None

        return {
            "room_id": room_block.group("room_id") if room_block
            else (room_id_match[-1] if room_id_match else None),
            "web_rid": web_rid_match[-1] if web_rid_match else None,
            "status": int(room_block.group("status")) if room_block
            else (4 if empty_room_info else None),
            "title": self._decode_text(room_block.group("title")) if room_block else "",
            "user_count": self._decode_text(room_block.group("user_count")) if room_block else "",
            "anchor_id": owner_block.group("anchor_id") if owner_block else None,
            "sec_uid": owner_block.group("sec_uid") if owner_block else None,
            "nickname": self._decode_text(owner_block.group("nickname")) if owner_block else "",
        }

    @staticmethod
    def _decode_text(value: Optional[str]) -> str:
        if value is None:
            return ""
        try:
            return json.loads(f'"{value}"')
        except Exception:
            return value

    # ----- 单人解析 -----

    def _resolve_candidate(self, candidate: str) -> Optional[Dict[str, object]]:
        live_url = f"https://live.douyin.com/{candidate}"
        try:
            html, response = self._request(
                live_url, headers={"Referer": "https://live.douyin.com/"})
        except (urllib_error.HTTPError, InvalidURL, ValueError, OSError):
            return None

        room = self._extract_room_info(html)
        if not room:
            return None

        streams = {"flv": {}, "hls": {}}
        if room.get("room_id"):
            streams = self._extract_from_render_data(html)
            if not streams.get("flv") and not streams.get("hls"):
                flv_streams, hls_streams = self._extract_by_suffix(html)
                streams = {"flv": flv_streams, "hls": hls_streams}

        if (room.get("room_id")
                and (not streams.get("flv") or not streams.get("hls"))
                and room.get("web_rid")
                and str(room["web_rid"]).isdigit()):
            api_streams = self._try_webcast_api(str(room["web_rid"]))
            for stream_type in ("flv", "hls"):
                merged = dict(streams.get(stream_type, {}))
                for quality, url in api_streams.get(stream_type, {}).items():
                    merged.setdefault(quality, url)
                streams[stream_type] = merged

        room["candidate"] = candidate
        room["live_url"] = response.geturl()
        room["streams"] = streams
        room["is_live"] = self._has_streams(streams) and room.get("status") == 2
        return room

    @staticmethod
    def _has_streams(streams: dict) -> bool:
        return bool((streams or {}).get("flv") or (streams or {}).get("hls"))

    @staticmethod
    def _score_result(result: Dict[str, object]) -> Tuple[int, int, int, int]:
        streams = result.get("streams", {})
        web_rid = str(result.get("web_rid") or "")
        return (
            1 if result.get("is_live") else 0,
            len(streams.get("hls", {})),
            len(streams.get("flv", {})),
            1 if web_rid.isdigit() else 0,
        )

    # ----- 对外接口 -----

    def resolve(self, user_input: str) -> Dict[str, object]:
        """解析直播间。成功返回 room dict，失败抛 DouyinError。

        返回字段：nickname / title / room_id / web_rid / is_live /
                  live_url / streams{flv,hls} / attempts
        """
        self._ensure_cookies()
        normalized = self._normalize_input(user_input)
        candidates = self._build_candidates(normalized)
        if not candidates:
            raise DouyinError("无法从输入中提取有效的房间标识")

        best_effort: Optional[Dict[str, object]] = None
        best_score: Optional[Tuple[int, int, int, int]] = None
        attempts: List[str] = []

        for candidate in candidates:
            attempts.append(candidate)
            try:
                result = self._resolve_candidate(candidate)
            except Exception:
                continue
            if not result:
                continue
            score = self._score_result(result)
            if best_score is None or score > best_score:
                best_effort, best_score = result, score

        if best_effort is None:
            raise DouyinError("未能解析到直播间：链接可能无效，或抖音页面结构已变化")

        best_effort["input"] = user_input
        best_effort["normalized"] = normalized
        best_effort["attempts"] = attempts
        return best_effort


# ---------------------------------------------------------------------------
# 画质选择
# ---------------------------------------------------------------------------

def pick_url(streams: dict, quality: Optional[str] = None,
             prefer: str = "flv") -> Tuple[Optional[str], Optional[str]]:
    """从 streams 里挑一个可录制地址。

    返回 (画质名, 地址)。quality 为空表示自动取最高画质。
    prefer 指定优先协议（flv 更适合 -c copy 连续录制）。
    """
    order = [prefer] + [p for p in ("flv", "hls") if p != prefer]
    if quality:
        for proto in order:
            url = (streams.get(proto) or {}).get(quality)
            if url:
                return quality, url
        # 指定画质在任一协议里都不存在
        return None, None

    for proto in order:
        table = streams.get(proto) or {}
        for q in QUALITY_ORDER:
            if q in table:
                return q, table[q]
        if table:                      # 非标准画质名（如「默认」）
            q, url = next(iter(table.items()))
            return q, url
    return None, None


def available_qualities(streams: dict) -> List[str]:
    """已解析到的画质列表，按清晰度从高到低，用于界面下拉框。"""
    names = set((streams.get("flv") or {}).keys()) | set((streams.get("hls") or {}).keys())
    ordered = [q for q in QUALITY_ORDER if q in names]
    ordered += sorted(n for n in names if n not in QUALITY_ORDER)
    return ordered


# ---------------------------------------------------------------------------
# 等待开播
# ---------------------------------------------------------------------------

def has_streams(streams: Optional[dict]) -> bool:
    """streams 里是否至少有一个可录制地址。"""
    streams = streams or {}
    return bool(streams.get("flv") or streams.get("hls"))


def is_ready(room: Optional[dict]) -> bool:
    """直播间是否已可录制（在播 + 已拿到流地址）。"""
    room = room or {}
    return bool(room.get("is_live")) and has_streams(room.get("streams"))


def wait_until_live(extractor: DouyinLiveExtractor, user_input: str,
                    interval: int = 30, timeout: int = 0,
                    stop_event=None, on_log=None) -> Optional[Dict[str, object]]:
    """轮询直到主播开播可取流。

    - interval  ：轮询间隔秒数
    - timeout   ：最长等待秒数，0 = 不限
    - stop_event：threading.Event，被 set 时立即返回 None
    返回开播后的 room dict；被取消或超时返回 None。
    """
    def log(t):
        if on_log:
            try:
                on_log(t)
            except Exception:
                pass

    def cancelled() -> bool:
        return stop_event is not None and stop_event.is_set()

    started = time.time()
    round_no = 0
    while True:
        if cancelled():
            log("已取消等待开播")
            return None

        round_no += 1
        try:
            room = extractor.resolve(user_input)
            if is_ready(room):
                log(f"主播已开播：{room.get('nickname') or '未知'} ✓")
                return room
            state = "未开播" if not room.get("is_live") else "开播但暂无流地址"
            log(f"    第 {round_no} 次检测：{room.get('nickname') or '未知'} {state}，"
                f"{interval} 秒后重试")
        except Exception as exc:
            log(f"    第 {round_no} 次检测失败：{exc}，{interval} 秒后重试")

        if timeout and time.time() - started >= timeout:
            log(f"等待开播超时（{timeout} 秒），放弃")
            return None

        # 可中断的等待，保证「停止」按钮能立刻生效
        slept = 0.0
        while slept < interval:
            if cancelled():
                log("已取消等待开播")
                return None
            time.sleep(0.2)
            slept += 0.2
