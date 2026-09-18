# -*- coding: utf-8 -*-
"""自检：造真实测试视频 → 三种模式各转一遍 → 逐个验证输出可解码。"""
import subprocess
import sys
import tempfile
from pathlib import Path

import core


def make_sample(ffmpeg, path, seconds=1):
    subprocess.check_call(
        [str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", f"testsrc=duration={seconds}:size=480x270:rate=15",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
         "-shortest", str(path)],
        creationflags=core.NO_WINDOW)
    assert path.is_file() and path.stat().st_size > 0


def probe_ok(ffprobe, path):
    d = core.media_duration(ffprobe, path)
    return d is not None and d > 0.3


def main():
    ffmpeg = core.find_ffmpeg()
    assert ffmpeg, "未找到 ffmpeg"
    ffprobe = core.find_ffprobe(ffmpeg)
    nv_h = core.has_encoder(ffmpeg, "h264_nvenc")
    nv_5 = core.has_encoder(ffmpeg, "hevc_nvenc")
    tmp = Path(tempfile.mkdtemp(prefix="vt_selftest_"))
    results = []

    def case(name, mode, fmt, cq=23):
        src = tmp / f"src_{mode}_{fmt}.mp4"
        make_sample(ffmpeg, src)
        dst = tmp / f"out_{name}.{fmt}"
        args, lossless = core.build_command(mode, cq, src, dst,
                                            nvenc_h264=nv_h, nvenc_h265=nv_5)
        okk, msg = core.run_ffmpeg(ffmpeg, args)
        ok = okk and dst.is_file() and dst.stat().st_size > 0 \
            and (ffprobe is None or probe_ok(ffprobe, dst))
        size = dst.stat().st_size if dst.exists() else 0
        results.append((name, ok, msg or f"{size} bytes, lossless={lossless}"))

    case("copy_mp4", "copy", "mp4")
    case("copy_mkv", "copy", "mkv")
    case("h264_mp4", "h264", "mp4")
    case("h265_mp4", "h265", "mp4")

    # unique_dst 防覆盖
    a = tmp / "src_copy_mp4.mp4"
    b = core.unique_dst(tmp / "out_copy_mp4.mp4")
    results.append(("unique_dst", b.name == "out_copy_mp4_1.mp4", b.name))

    # remux（录制收尾封装用的同一条命令）
    c = tmp / "remux_out.mkv"
    rok, rmsg = core.run_ffmpeg(ffmpeg, core.remux_command(a, c))
    results.append(("remux_mkv", rok and c.is_file() and c.stat().st_size > 0, rmsg or "ok"))

    failed = [r for r in results if not r[1]]
    for name, ok, detail in results:
        print(("PASS" if ok else "FAIL"), name, "-", detail)
    print("目录:", tmp)
    if failed:
        sys.exit(1)
    print("SELFTEST PASS")


if __name__ == "__main__":
    main()
