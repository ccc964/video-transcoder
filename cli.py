# -*- coding: utf-8 -*-
"""命令行入口：python main.py --cli [参数] 输入..."""
import sys
from pathlib import Path

import core


def run(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="视频转码",
                                 description="基于 ffmpeg 的批量视频转码/转封装 + 直播录制")
    ap.add_argument("inputs", nargs="*", help="视频文件或文件夹（--record 模式下可省略）")
    ap.add_argument("-m", "--mode", choices=["copy", "h264", "h265"],
                    default="copy", help="copy=无损转封装（默认）")
    ap.add_argument("-f", "--format", default="mp4", help="输出容器：mp4/mkv/mov")
    ap.add_argument("--cq", type=int, default=23, help="重编码质量 16-32，越小越清晰")
    ap.add_argument("-o", "--outdir", default="", help="输出目录，默认与源文件同目录")
    ap.add_argument("--ffmpeg", default="", help="ffmpeg.exe 路径（默认自动查找）")
    ap.add_argument("--record", default="", metavar="URL",
                    help="录制直播源（m3u8/flv/rtmp），与 inputs 二选一")
    ap.add_argument("--limit", type=int, default=0, help="最长录制分钟数，0=不限")
    ap.add_argument("--install-ffmpeg", action="store_true",
                    help="一键下载安装 ffmpeg 到 exe 同目录的 ffmpeg\\ 下，然后退出")
    ap.add_argument("--ffmpeg-url", default="",
                    help="配合 --install-ffmpeg：手动指定 zip 直链（自动源全失败时用）")
    a = ap.parse_args(argv)

    if a.install_ffmpeg:
        ok, msg = core.install_ffmpeg(
            Path(a.outdir) if a.outdir else None,
            on_progress=lambda f: None,
            on_log=lambda t: print(t),
            custom_url=a.ffmpeg_url or None)
        print(msg)
        return 0 if ok else 1

    ffmpeg = core.find_ffmpeg(a.ffmpeg or None)
    if not ffmpeg:
        print("未找到 ffmpeg，请用 --ffmpeg 指定路径")
        return 2

    if a.record:
        from time import strftime
        if a.outdir:
            dst = Path(a.outdir)
            if dst.suffix.lower() not in (".mp4", ".ts", ".mkv", ".flv"):
                dst = dst.with_suffix(".ts")
        else:
            dst = Path(f"直播_{strftime('%Y%m%d_%H%M%S')}.mp4")
        if dst.exists():
            dst = core.unique_dst(dst)
        tmp_ts = dst.with_suffix(".ts") if dst.suffix.lower() != ".ts" else dst
        print(f"[录] {a.record} -> {dst}")
        okk, msg = core.run_ffmpeg(ffmpeg, core.build_record_command(
            a.record, tmp_ts, a.limit * 60))
        if not (tmp_ts.is_file() and tmp_ts.stat().st_size > 0):
            print(f"    fail: {msg or '没有收到数据'}")
            return 1
        print(f"    已录制 {tmp_ts.stat().st_size / 1048576:.1f} MB")
        if str(tmp_ts.resolve()) != str(dst.resolve()):
            print(f"    封装为 {dst.name} …")
            rok, rmsg = core.run_ffmpeg(ffmpeg, core.remux_command(tmp_ts, dst))
            if rok:
                tmp_ts.unlink(missing_ok=True)
            else:
                print(f"    fail: {rmsg}（ts 已保留）")
                return 1
        print(f"    ok {dst.stat().st_size / 1048576:.1f} MB")
        return 0
    ffprobe = core.find_ffprobe(ffmpeg)
    nv_h = core.has_encoder(ffmpeg, "h264_nvenc")
    nv_5 = core.has_encoder(ffmpeg, "hevc_nvenc")
    print(f"ffmpeg: {ffmpeg}  NVENC: h264={'Y' if nv_h else 'N'} h265={'Y' if nv_5 else 'N'}")

    files = []
    for p in map(Path, a.inputs):
        if p.is_dir():
            files += [f for f in sorted(p.iterdir())
                      if f.is_file() and f.suffix.lower() in core.VIDEO_EXTS]
        elif p.is_file():
            files.append(p)
    if not files:
        print("没有可处理的视频文件")
        return 1

    ok = fail = 0
    if a.outdir:
        Path(a.outdir).mkdir(parents=True, exist_ok=True)
    for src in files:
        dst = (Path(a.outdir) if a.outdir else src.parent) / (src.stem + "." + a.format)
        if str(dst.resolve()) == str(src.resolve()):
            dst = core.unique_dst(dst.with_stem(src.stem + "_conv"))
            print(f"    输出与源同名，自动改名 -> {dst.name}")
        elif dst.exists():
            dst = core.unique_dst(dst)
        args, lossless = core.build_command(a.mode, a.cq, src, dst,
                                            nvenc_h264=nv_h, nvenc_h265=nv_5)
        print(f"[转] {src.name} -> {dst.name} ({'无损' if lossless else '重编码'})")
        okk, msg = core.run_ffmpeg(ffmpeg, args)
        if okk:
            ok += 1
            print(f"    ok {dst.stat().st_size / 1048576:.1f} MB")
        else:
            fail += 1
            print(f"    fail: {msg}")
    print(f"完成：成功 {ok}，失败 {fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
