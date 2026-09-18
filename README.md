# 视频转码 + 直播录制

基于 ffmpeg 的视频批量转码/转封装 + 直播源录制工具。**交付只要一个 exe（12MB）**，
换电脑拷过去双击即用，首次运行点一下「一键下载 ffmpeg」即可（约 82MB，实测 8 秒下完）。

## ffmpeg 从哪来（重要）

- 程序启动会按顺序找 ffmpeg：**exe 同目录 → 同目录 ffmpeg\ 文件夹 → 系统 PATH → Chocolatey**。
- 找不到就点右上角 **「一键下载 ffmpeg」**，自动下载并装到 `exe同目录\ffmpeg\`，
  装完自动使用、自动验证版本；整个文件夹拷走即带走 ffmpeg。

### 下载地址是怎么拿的（不会因为版本更新就失效）

没有用"写死版本号"的链接，而是四层保险，按顺序自动尝试、失败自动换下一个：

| 层 | 做法 | 说明 |
|---|---|---|
| 1 | **GitHub API 动态解析** | 请求 `https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/tags/latest`，从资产清单里用正则 `^ffmpeg-(master\|n\d+\.\d+)-latest-win64-gpl-shared(-\d+)?\.zip$` 挑体积最小的包。上游改版本号、改资产名也能自动跟上 |
| 2 | **固定别名** | BtbN 的资产名本身不含版本号（`ffmpeg-master-latest-win64-gpl-shared.zip`），发新版是**同名覆盖**，`latest` 这个 tag 永久存在 → 不会变成死链 |
| 3 | **gyan.dev 别名 + 版本页** | `ffmpeg-release-essentials.zip` 是官方"永远最新"别名；另外解析它的 builds 页面，取页面里版本号最大的 `ffmpeg-x.y.z-essentials_build.zip` |
| 4 | **手动兜底** | 全部失败时界面会弹出输入框，让你直接粘贴任意 zip 直链；命令行用 `--ffmpeg-url` |

加速源（都会套在上面第 1、2 层上）：`gh-proxy.com` → `ghfast.top` → GitHub 直连（放最后，国内多超时）。
实测：gh-proxy 走 API 解析 200，ghfast 的 API 返回 403（所以它主要靠固定别名），GitHub API 直连偶尔可通。

实测日志（故意先给一个坏地址，验证会自动跳到下一个源）：
```
尝试：自定义地址            → 失败：Tunnel connection failed: 502
尝试：gh-proxy 加速 动态解析 → ffmpeg-master-latest-win64-gpl-shared.zip（82MB）
已下载 80 MB / 82 MB        → 已安装 9 个文件
```

关于清华源：清华镜像站（mirrors.tuna.tsinghua.edu.cn）**没有**收录 Windows 版 ffmpeg 二进制
——它的 github-release 目录里没有 BtbN/FFmpeg-Builds，也没有单独的 ffmpeg 目录（已实测 404）。
需要多台机器离线用时，先在一台能联网的机器点「一键下载 ffmpeg」，然后把生成的 `ffmpeg\`
文件夹连同 exe 一起拷过去即可（文件夹即全部依赖，无需再下第二遍）。

## 图形界面（双击 视频转码.exe）

### 页签 1：视频转码
把视频拖进窗口（或点「添加文件/添加文件夹」）→ 选模式和格式 → 开始转换。

### 页签 2：直播录制
1. 粘贴直播源地址（m3u8 / flv / mp4 直链 / rtmp）
2. 保存位置留空则自动命名为 `直播_日期_时间.mp4`
3. 点「开始录制」，随时点「停止录制」
4. 停止后自动无损封装成 mp4（录制过程用 ts 中间文件，中途断电/停止文件也不会坏）
5. 可设最长录制分钟数（0=不限）；HTTP 直链断流会自动重连

录制全程 `-c copy` 不重编码，CPU/显卡几乎零占用。

## 命令行

```
视频转码.exe --cli -m copy -f mp4 "C:\视频\9.9录屏.ts"

视频转码.exe --cli --install-ffmpeg -o D:\目标目录

视频转码.exe --cli --record "https://xxx/live.m3u8" -o D:\录制.mp4 --limit 120
```

转码参数：
- `-m copy`   无损转封装（默认，不重编码、零画质损失、速度最快）
- `-m h264`   H.264 重编码（优先 NVENC 硬件加速，没有则自动退回 libx264）
- `-m h265`   H.265 重编码（体积最小，优先 NVENC）
- `-f mp4`    输出容器：mp4 / mkv / mov
- `--cq 23`   重编码质量 16-32，越小越清晰（默认 23）
- `-o 目录`   输出目录（默认与源文件同目录）

录制参数：
- `--record URL`  直播源地址
- `-o 文件`       保存位置（.mp4/.ts/.mkv/.flv）
- `--limit 120`   最长录制分钟数，0=不限

安装参数：
- `--install-ffmpeg`          下载安装 ffmpeg 到 exe 同目录 ffmpeg\（-o 可指定目标目录）
- `--ffmpeg-url URL`          配合 --install-ffmpeg：手动指定 zip 直链（自动源全失败时用）

## 转码模式怎么选

| 场景 | 模式 | 原因 |
|---|---|---|
| ts 录屏转 mp4 存档 | 无损转封装 | 秒级完成，画质/音质 100% 原样 |
| 发给别人 / 剪辑软件不认 | H.264 重编码 | 兼容性最好，CQ 22-24 即可 |
| 手机空间不够 | H.265 重编码 | 同画质体积约省 40%，速度稍慢 |

## 防呆规则

- 输出文件已存在 → 自动改名 `xxx_1.mp4`，绝不覆盖源文件
- 输出与源同名（mp4→mp4 同目录）→ 自动改名 `_conv`
- 失败或取消的 0 字节残留文件自动清理
- 录制中断（断网/断电）ts 中间文件仍可播放
- 配置记忆在 exe 同目录 `vt_config.json`

## 源码运行（改代码用）

```
安装环境.bat   → 首次运行，创建 .venv 并装依赖
启动程序.bat   → 开图形界面
调试启动.bat   → 带控制台调试
打包exe.bat    → 重新打包 exe 到 dist\（自动内置 ffmpeg）
selftest.py    → 引擎自检
```

## 常用 ffmpeg 命令速查（本工具等价命令）

```bash
# 无损转封装（ts→mp4，画面声音原样拷贝）
ffmpeg -i 输入.ts -map 0 -c copy 输出.mp4

# H.264 硬编（RTX 显卡 NVENC）
ffmpeg -i 输入.ts -c:v h264_nvenc -rc vbr -cq 23 -b:v 0 -c:a aac -b:a 192k 输出.mp4

# H.265 硬编（更小的体积）
ffmpeg -i 输入.ts -c:v hevc_nvenc -rc vbr -cq 24 -b:v 0 -tag:v hvc1 -c:a aac 输出.mp4

# 录制直播源（断流重连，ts 中间文件防损坏）
ffmpeg -reconnect 1 -reconnect_streamed 1 -i 直播源.m3u8 -map 0 -c copy -y 录制.ts

# 压缩 mp4 但画质几乎不变（CPU 慢编，质量上限更高）
ffmpeg -i 输入.mp4 -c:v libx264 -crf 20 -preset slow -c:a copy 输出.mp4

# 只截取片段（00:01:30 起，剪 60 秒，无损）
ffmpeg -ss 00:01:30 -i 输入.mp4 -t 60 -c copy 片段.mp4

# 提取音频为 m4a
ffmpeg -i 输入.mp4 -vn -c:a copy 输出.m4a

# 查看文件信息（编码器、码率、时长）
ffprobe -v error -show_format -show_streams 输入.mp4
```

## 排错

- 换电脑后提示找不到 ffmpeg：确认 `ffmpeg\ffmpeg.exe` 和 exe 在同一文件夹；也可在界面手动指定。
- 录制没有数据：地址失效或需要特定 Referer 的源暂不支持，换个源试试。
- 打包后闪退：运行 `视频转码.exe --smoke D:\smoke.txt`，看报告里的 FAIL 项。
- 无损模式报错：个别容器/编码组合不能直接转封装，改用 H.264 模式或输出为 mkv。
