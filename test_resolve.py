# -*- coding: utf-8 -*-
"""验证下载地址解析与自动换源：先给个坏地址，确认能自动跳到下一个源。"""
import sys
from pathlib import Path

import core

print("=== 候选地址清单 ===")
for i, (url, label) in enumerate(core.resolve_download_candidates(), 1):
    print(f"{i}. {label}")
    print(f"   {url}")

print("\n=== 故意给坏地址，测试自动换源 ===")
target = Path(r"D:\workbuddy\ffmpeg_dl_test")
ok, msg = core.install_ffmpeg(target,
                             on_progress=lambda f: None,
                             on_log=lambda t: print(t),
                             custom_url="https://example.invalid/broken.zip")
print("RESULT:", ok, msg)
sys.exit(0 if ok else 1)
