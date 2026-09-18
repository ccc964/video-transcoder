# -*- coding: utf-8 -*-
"""打包脚本：生成单文件 exe 到 dist/，并把 ffmpeg/ffprobe 复制进去实现便携。"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
import core

NAME = "视频转码"
ICON = ROOT / "assets" / "app.ico"


def _resolve_shim(p):
    """Chocolatey 的 bin 下可能是垫片 exe（~0.4MB）：先读 .shim，再搜 lib 目录兜底。"""
    shim = p.with_suffix(".shim")
    if shim.is_file():
        try:
            for line in shim.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.lower().startswith("path"):
                    target = line.split("=", 1)[1].strip().strip('"')
                    if Path(target).is_file():
                        return Path(target)
        except Exception:
            pass
    if p.is_file() and p.stat().st_size >= 5 * 1024 * 1024:
        return p
    # 垫片且无 .shim 说明：搜 chocolatey lib 里最大的同名 exe
    lib = Path(r"C:\ProgramData\chocolatey\lib")
    best = None
    if lib.is_dir():
        for cand in lib.glob(f"**/bin/{p.name}"):
            if cand.is_file() and (best is None or cand.stat().st_size > best.stat().st_size):
                best = cand
    return best or p


def bundle_ffmpeg():
    """把真实的 ffmpeg.exe / ffprobe.exe 复制到 dist\\ffmpeg\\。"""
    ff = _resolve_shim(core.find_ffmpeg())
    fp = _resolve_shim(core.find_ffprobe(core.find_ffmpeg()))
    if not ff or not fp or ff.stat().st_size < 5 * 1024 * 1024:
        print("警告：未能定位完整版 ffmpeg，跳过内置（目标机器需自行提供）")
        return
    dst_dir = ROOT / "dist" / "ffmpeg"
    dst_dir.mkdir(parents=True, exist_ok=True)
    for src in (ff, fp):
        shutil.copy2(src, dst_dir / src.name)
    print(f"内置 ffmpeg -> {dst_dir} ({ff.name} {ff.stat().st_size // 1048576}MB)")


def _move_old_exe_aside():
    """沙箱会拦截删除操作导致 PyInstaller 覆盖旧 exe 失败，所以先把旧 exe 改名让开。"""
    import time
    exe = ROOT / "dist" / f"{NAME}.exe"
    if not exe.exists():
        return
    aside = ROOT / "build" / "prev"
    aside.mkdir(parents=True, exist_ok=True)
    target = aside / f"{NAME}_{time.strftime('%Y%m%d_%H%M%S')}.exe"
    exe.rename(target)
    print(f"旧 exe 已移到 {target}")


def _prune_workpaths(keep):
    """尽力删掉更早的构建目录（沙箱可能拦住删除，失败不影响打包）。"""
    gone = 0
    for d in sorted((ROOT / "build").glob("pyi_*")):
        if d == keep:
            continue
        try:
            shutil.rmtree(d)
            gone += 1
        except Exception:
            pass
    if gone:
        print(f"清理旧构建目录 {gone} 个")


def main():
    import time
    if not ICON.exists():
        subprocess.check_call([sys.executable, str(ROOT / "build" / "make_icon.py")])
    _move_old_exe_aside()
    # 不用 --clean：沙箱会拦截删除旧构建缓存导致打包中断；改用每次全新的 workpath
    work = ROOT / "build" / f"pyi_{time.strftime('%Y%m%d_%H%M%S')}"
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm",
           "--name", NAME, "--onefile", "--windowed",
           "--icon", str(ICON),
           "--workpath", str(work),
           "--specpath", str(ROOT / "build"),
           "--collect-all", "tkinterdnd2",
           "--hidden-import", "PIL._tkinter_finder",
           str(ROOT / "main.py")]
    print(" ".join(cmd))
    try:
        subprocess.check_call(cmd, cwd=str(ROOT))
    finally:
        _prune_workpaths(work)
    if "--with-ffmpeg" in sys.argv:
        bundle_ffmpeg()
    else:
        print("跳过内置 ffmpeg（首次运行可点「一键下载 ffmpeg」，交付体积仅 exe）")
    print("\n打包完成 ->", ROOT / "dist" / f"{NAME}.exe")


if __name__ == "__main__":
    main()
