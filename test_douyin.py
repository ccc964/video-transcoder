# -*- coding: utf-8 -*-
"""抖音直播源解析测试：输入识别 + 画质选择 + 直链透传 + 真实解析/录制。

用法：
    python test_douyin.py                # 只跑离线用例
    python test_douyin.py 127453393722   # 指定房间号，额外跑联网用例
    python test_douyin.py 127453393722 --record   # 再录 6 秒验证能出流
"""
import sys
import tempfile
from pathlib import Path

import core
import douyin


def head(t):
    print(f"\n=== {t} ===")


def test_input_detection():
    head("输入识别（离线）")
    cases = [
        ("https://live.douyin.com/123456789", True, "直播间链接"),
        ("https://v.douyin.com/iAbCdEf/", True, "App 分享短链"),
        ("https://www.douyin.com/user/MS4wLjABAAAxxx", True, "用户主页链接"),
        ("127453393722", True, "纯房间号"),
        ("8.88 复制打开抖音 https://v.douyin.com/abc/ 看看", True, "带文案的分享文本"),
        ("12345", False, "位数不足的短数字"),
        ("https://example.com/live.m3u8", False, "普通 m3u8 直链"),
        ("rtmp://live.example.com/app", False, "rtmp 直链"),
        ("D:/videos/a.mp4", False, "本地文件"),
    ]
    bad = 0
    for text, want, desc in cases:
        got = douyin.is_douyin_input(text)
        if got != want:
            bad += 1
        print(f"  {'OK  ' if got == want else 'FAIL'} {str(got):<5} {desc}")
    print(f"  小计：{len(cases) - bad}/{len(cases)} 通过")
    return bad == 0


def test_quality_pick():
    head("画质选择（离线）")
    streams = {
        "flv": {"高清 (HD)": "http://a/hd.flv", "流畅 (LD)": "http://a/ld.flv"},
        "hls": {"原画 (OR4)": "http://a/or4.m3u8"},
    }
    ok = True

    q, u = douyin.pick_url(streams)
    ok &= q == "高清 (HD)" and u == "http://a/hd.flv"
    print(f"  自动取最高（优先 FLV）-> {q}  {'OK' if q == '高清 (HD)' else 'FAIL'}")

    q, u = douyin.pick_url(streams, "原画 (OR4)")
    ok &= q == "原画 (OR4)" and u.endswith("or4.m3u8")
    print(f"  指定原画（回落到 HLS）-> {q}  {'OK' if q == '原画 (OR4)' else 'FAIL'}")

    q, u = douyin.pick_url(streams, "超清 (UHD)")
    ok &= q is None and u is None
    print(f"  指定不存在的画质      -> {q}  {'OK' if q is None else 'FAIL'}")

    ok &= douyin.available_qualities(streams) == ["原画 (OR4)", "高清 (HD)", "流畅 (LD)"]
    print(f"  画质列表排序          -> {douyin.available_qualities(streams)}")

    ok &= douyin.normalize_quality("or4") == "原画 (OR4)"
    ok &= douyin.normalize_quality("hd") == "高清 (HD)"
    ok &= douyin.normalize_quality("auto") is None
    print(f"  命令行短名归一化      -> or4/hd/auto  {'OK' if ok else 'FAIL'}")
    return ok


def test_passthrough():
    head("直链透传（离线，保证向后兼容）")
    ok = True
    for url in ("https://example.com/a.m3u8", "rtmp://x/y", "D:/v/a.mp4"):
        s, info = core.prepare_record_source(url)
        same = s == url and info.get("douyin") is False
        ok &= same
        print(f"  {'OK  ' if same else 'FAIL'} {url}")
    return ok


def test_resolve(room):
    head(f"真实解析（联网）：{room}")
    ex = douyin.DouyinLiveExtractor(on_log=lambda t: print("   " + t))
    r = ex.resolve(room)
    print(f"  主播   ：{r.get('nickname')}")
    print(f"  标题   ：{(r.get('title') or '')[:50]}")
    print(f"  roomId ：{r.get('room_id')}   web_rid：{r.get('web_rid')}")
    print(f"  开播中 ：{r.get('is_live')}   可录制：{douyin.is_ready(r)}")
    avail = douyin.available_qualities(r["streams"])
    print(f"  可选画质：{avail}")
    if not avail:
        print("  （主播未开播，跳过录制验证）")
        return True
    q, u = douyin.pick_url(r["streams"])
    print(f"  自动选中：{q}")
    print(f"  推流地址：{(u or '')[:88]}…")
    return True


def test_record(room):
    head("录制验证（联网，录 6 秒）")
    ffmpeg = core.find_ffmpeg()
    if not ffmpeg:
        print("  未找到 ffmpeg，跳过")
        return True
    url, info = core.prepare_record_source(room, on_log=lambda t: print("   " + t))
    if not info.get("douyin"):
        print("  FAIL 未识别为抖音地址")
        return False
    print(f"  解析到 {info.get('nickname')} | 画质 {info.get('quality')}")
    tmp = Path(tempfile.mkdtemp(prefix="dy_test_"))
    ts, mp4 = tmp / "rec.ts", tmp / "rec.mp4"
    okk, msg = core.run_ffmpeg(
        ffmpeg, core.build_record_command(url, ts, limit_sec=6, reconnect=True),
        on_log=lambda t: print("   [ff] " + t))
    if not (ts.is_file() and ts.stat().st_size > 0):
        print(f"  FAIL 没有录到数据：{msg}")
        return False
    print(f"  录到 {ts.stat().st_size / 1048576:.2f} MB")
    rok, rmsg = core.run_ffmpeg(ffmpeg, core.remux_command(ts, mp4))
    dur = core.media_duration(core.find_ffprobe(ffmpeg), mp4) if mp4.is_file() else None
    good = rok and dur and dur > 3
    print(f"  封装 mp4：{mp4.stat().st_size / 1048576:.2f} MB，时长 {dur:.2f}s"
          if good else f"  FAIL 封装失败：{rmsg}")
    print(f"  产物目录：{tmp}")
    return good


def main():
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    room = argv[0] if argv else ""
    results = [
        ("输入识别", test_input_detection()),
        ("画质选择", test_quality_pick()),
        ("直链透传", test_passthrough()),
    ]
    if room:
        try:
            results.append(("真实解析", test_resolve(room)))
        except Exception as e:
            print(f"\n  解析异常：{e}")
            results.append(("真实解析", False))
        if "--record" in sys.argv:
            try:
                results.append(("录制验证", test_record(room)))
            except Exception as e:
                print(f"\n  录制异常：{e}")
                results.append(("录制验证", False))

    print("\n" + "=" * 46)
    for name, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    passed = all(ok for _, ok in results)
    print("  ----", "全部通过" if passed else "存在失败", "----")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
