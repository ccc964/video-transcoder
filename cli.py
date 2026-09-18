# -*- coding: utf-8 -*-
"""命令行入口：python main.py --cli [参数] 输入..."""
import sys
from pathlib import Path

import core


def run(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="视频转码",
                                 description="基于 ffmpeg 的批量视频转码/转封装 + 直播录制"
                                             "（支持抖音直播间链接直接录制）")
    ap.add_argument("inputs", nargs="*", help="视频文件或文件夹（--record 模式下可省略）")
    ap.add_argument("-m", "--mode", choices=["copy", "h264", "h265"],
                    default="copy", help="copy=无损转封装（默认）")
    ap.add_argument("-f", "--format", default="mp4", help="输出容器：mp4/mkv/mov")
    ap.add_argument("--cq", type=int, default=23, help="重编码质量 16-32，越小越清晰")
    ap.add_argument("-o", "--outdir", default="", help="输出目录，默认与源文件同目录")
    ap.add_argument("--ffmpeg", default="", help="ffmpeg.exe 路径（默认自动查找）")
    ap.add_argument("--record", default="", metavar="URL",
                    help="录制直播源：抖音直播间链接 / 房间号 / 分享短链 / 主页链接，"
                         "或 m3u8 / flv / rtmp 直链")
    ap.add_argument("--limit", type=int, default=0, help="最长录制分钟数，0=不限")
    ap.add_argument("--quality", default="auto",
                    help="录制画质：auto（默认，最高可用）/ or4 / uhd / hd / sd / ld")
    ap.add_argument("--list", action="store_true",
                    help="只解析 --record 给的地址并列出可用画质，不录制")
    ap.add_argument("--wait", nargs="?", const=0, type=int, default=None,
                    metavar="SEC", help="未开播时等待开播再录；可选最长等待秒数（默认不限）")
    ap.add_argument("--transcode", choices=["h264", "h265"], default="",
                    help="录完自动重编码为指定编码（默认不重编码）")
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

    # ---- 只解析画质，不录制 ----
    if a.list:
        if not a.record:
            print("--list 需要配合 --record URL 使用")
            return 2
        room = core.probe_live_room(a.record, on_log=lambda t: print(t))
        if room is None:
            print(f"{a.record} 不是抖音地址，无需解析，可直接 --record 录制")
            return 0
        print(f"主播  ：{room.get('nickname') or '未知'}")
        print(f"标题  ：{(room.get('title') or '').strip()[:60] or '-'}")
        print(f"状态  ：{'直播中' if room.get('is_live') else '未开播'}")
        print(f"roomId：{room.get('room_id') or '-'}   web_rid：{room.get('web_rid') or '-'}")
        avail = room.get("available") or []
        if not avail:
            print("可用画质：暂无（主播未开播或暂未取到流地址）")
        else:
            print("可用画质：")
            for q in avail:
                has_flv = "有" if room["streams"]["flv"].get(q) else "无"
                has_hls = "有" if room["streams"]["hls"].get(q) else "无"
                print(f"    {q:<12} FLV {has_flv}   HLS {has_hls}")
        return 0

    ffmpeg = core.find_ffmpeg(a.ffmpeg or None)
    if not ffmpeg:
        print("未找到 ffmpeg，请用 --ffmpeg 指定路径")
        return 2

    if a.record:
        from time import strftime
        import re as _re

        # 1) 解析（抖音地址才联网解析；直链原样返回，行为与之前完全一致）
        if core.is_douyin_input(a.record):
            print(f"[解析] {a.record}")
        quality = core.normalize_quality(a.quality)
        if quality is None and a.quality.lower() not in ("auto", ""):
            print(f"未知画质「{a.quality}」，可用：auto/or4/uhd/hd/sd/ld")
            return 2
        try:
            stream_url, info = core.prepare_record_source(
                a.record,
                quality=quality,
                wait=(a.wait is not None),
                timeout=a.wait or 0,
                on_log=lambda t: print(t))
        except Exception as exc:
            print(f"[解析失败] {exc}")
            return 1

        if stream_url is None:
            print("已取消")
            return 1

        if info.get("douyin"):
            print(f"       主播 {info.get('nickname') or '未知'} | "
                  f"画质 {info.get('quality')} | room_id {info.get('room_id')}")

        # 2) 目标路径
        if a.outdir:
            dst = Path(a.outdir)
            if dst.suffix.lower() not in (".mp4", ".ts", ".mkv", ".flv"):
                dst = dst.with_suffix(".ts")
        else:
            prefix = (info.get("nickname") or "").strip() or "直播"
            prefix = _re.sub(r'[\\/:*?"<>|]', "_", prefix)[:40]
            dst = Path(f"{prefix}_{strftime('%Y%m%d_%H%M%S')}.mp4")
        if dst.exists():
            dst = core.unique_dst(dst)
        tmp_ts = dst.with_suffix(".ts") if dst.suffix.lower() != ".ts" else dst

        # 3) 录制
        print(f"[录] -> {dst}")
        okk, msg = core.run_ffmpeg(ffmpeg, core.build_record_command(
            stream_url, tmp_ts, a.limit * 60))
        if not (tmp_ts.is_file() and tmp_ts.stat().st_size > 0):
            print(f"    fail: {msg or '没有收到数据'}")
            return 1
        print(f"    已录制 {tmp_ts.stat().st_size / 1048576:.1f} MB")

        # 4) 无损封装
        final = tmp_ts
        if str(tmp_ts.resolve()) != str(dst.resolve()):
            print(f"    封装为 {dst.name} …")
            rok, rmsg = core.run_ffmpeg(ffmpeg, core.remux_command(tmp_ts, dst))
            if rok:
                tmp_ts.unlink(missing_ok=True)
                final = dst
            else:
                print(f"    fail: {rmsg}（ts 已保留）")
                return 1
        print(f"    ok {final.stat().st_size / 1048576:.1f} MB")

        # 5) 可选：录完自动重编码
        if a.transcode and final.is_file():
            tgt = core.unique_dst(final.with_name(f"{final.stem}_{a.transcode}{final.suffix}"))
            print(f"    自动重编码（{a.transcode}）-> {tgt.name} …")
            args, _ = core.build_command(a.transcode, a.cq, final, tgt,
                                         nvenc_h264=core.has_encoder(ffmpeg, "h264_nvenc"),
                                         nvenc_h265=core.has_encoder(ffmpeg, "hevc_nvenc"))
            tok, tmsg = core.run_ffmpeg(
                ffmpeg, args,
                duration=core.media_duration(core.find_ffprobe(ffmpeg), final))
            if tok and tgt.is_file():
                print(f"    ok {tgt.stat().st_size / 1048576:.1f} MB")
            else:
                print(f"    fail: {tmsg}")
                return 1
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
