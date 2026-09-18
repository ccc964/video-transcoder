# -*- coding: utf-8 -*-
"""直播录制测试：录公开 HLS 测试流 6 秒 → 验证 ts → 封装 mp4。"""
import sys
from pathlib import Path
import tempfile

import core

URLS = [
    "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8",
    "https://demo.unified-streaming.com/k8s/features/stable/video/tears-of-steel/tears-of-steel.ism/.m3u8",
]

def main():
    ffmpeg = core.find_ffmpeg()
    tmp = Path(tempfile.mkdtemp(prefix="rec_test_"))
    ts = tmp / "rec.ts"
    mp4 = tmp / "rec.mp4"
    for url in URLS:
        print("try:", url)
        okk, msg = core.run_ffmpeg(
            ffmpeg, core.build_record_command(url, ts, limit_sec=6, reconnect=True),
            on_log=lambda t: print("   [ffmpeg]", t))
        if ts.is_file() and ts.stat().st_size > 0:
            print(f"  recorded {ts.stat().st_size} bytes (ok={okk}, {msg})")
            break
        print("  fail:", msg)
    else:
        print("ALL SOURCES FAIL")
        return 1
    rok, rmsg = core.run_ffmpeg(ffmpeg, core.remux_command(ts, mp4))
    print("remux:", rok, rmsg, mp4.stat().st_size if mp4.exists() else 0)
    ok = mp4.is_file() and mp4.stat().st_size > 100000
    print("RECORD TEST", "PASS" if ok else "FAIL", "->", tmp)
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
