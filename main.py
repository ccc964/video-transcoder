# -*- coding: utf-8 -*-
"""统一入口：无参数开界面 / --cli 走命令行 / --smoke 自检。"""
import os
import sys

# --windowed 打包模式下 stdout/stderr 为 None，print 会直接崩
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")


import core


def smoke(report_path):
    """打包后自检：写报告文件，退出码 0 = 通过。"""
    lines = []
    ok = [True]

    def check(name, fn):
        try:
            detail = fn()
            lines.append(f"PASS {name}: {detail}")
        except Exception as e:
            ok[0] = False
            lines.append(f"FAIL {name}: {e!r}")

    check("python", lambda: sys.version.split()[0])
    check("engine-import", lambda: ("ok"))

    def _douyin():
        import douyin
        assert douyin.is_douyin_input("https://live.douyin.com/123456")
        assert not douyin.is_douyin_input("https://a.com/x.m3u8")
        assert douyin.normalize_quality("or4") == "原画 (OR4)"
        return f"解析器就绪，{len(core.RECORD_QUALITIES)} 档画质选项"
    check("douyin-engine", _douyin)

    def _resolve():
        """解析函数必须存在且对直链是透传的（不联网）。"""
        url, info = core.prepare_record_source("http://example.com/live.m3u8")
        assert url == "http://example.com/live.m3u8" and info["douyin"] is False
        return "直链透传正常"
    check("record-source-passthrough", _resolve)

    def _ffmpeg():
        p = core.find_ffmpeg()
        if not p:
            return "未找到（GUI 仍可用，可手动指定）"
        return str(p)
    check("ffmpeg-detect", _ffmpeg)

    def _tk():
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        root.destroy()
        return tkinter.TkVersion

    check("tkinter", _tk)

    def _gui():
        import app
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        a = app.App(root)
        root.update_idletasks()
        n = len(a.files)
        root.destroy()
        return f"App 实例化成功，当前文件数 {n}"

    check("gui-instantiate", _gui)

    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("SMOKE " + ("PASS" if ok[0] else "FAIL") + "\n")
            f.write("\n".join(lines) + "\n")
    except Exception:
        pass
    return 0 if ok[0] else 1


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "--smoke":
        path = argv[1] if len(argv) > 1 else "smoke_report.txt"
        return smoke(path)
    if argv and argv[0] == "--cli":
        import cli
        return cli.run(argv[1:])
    import app
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
