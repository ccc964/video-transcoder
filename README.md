# 视频转码 + 直播录制

基于 ffmpeg 的视频批量转码/转封装 + 直播源录制工具。**交付只要一个 exe（11.5MB）**，
换电脑拷过去双击即用，首次运行点一下「一键下载 ffmpeg」即可（约 82MB，实测 8 秒下完）。

**直播录制支持抖音直播间直接开录**：粘贴直播间链接、房间号、App 分享短链或用户主页链接，
工具自动解析出推流地址再录制，不用自己去抓流。

界面是**圆角卡片式布局**（Win11 风格）：浅灰底 + 白色圆角卡片、圆角按钮/输入框/胶囊页签，
执行日志按结果着色（成功绿、失败红、警告橙）；解析过的主播会进「常看主播」，下次一键重新解析。
分辨率再低也不会把按钮裁掉——内容会自动改为可滚动。

## 下载 / 安装

**直接下载 exe（推荐，无需 Python）**

👉 [VideoTranscoder.exe](https://github.com/ccc964/video-transcoder/releases/latest/download/VideoTranscoder.exe)（v2.1，11.5 MB）

首次运行点界面上的「一键下载 ffmpeg」即可，不需要单独装 Python 或 ffmpeg。

**从源码跑**

```bash
git clone https://github.com/ccc964/video-transcoder.git
cd video-transcoder
pip install -r requirements.txt
```

Windows 下直接双击 `启动程序.bat`（会自动用本地 `.venv`）；想自己打包 exe 双击 `打包exe.bat`。

> 国内直连 github.com 可能超时，clone/推送可套加速代理，例如把地址换成
> `https://ghfast.top/https://github.com/ccc964/video-transcoder.git`。

## ffmpeg 从哪来（重要）

- 程序启动会按顺序找 ffmpeg：**exe 同目录 → 同目录 ffmpeg\ 文件夹 → 系统 PATH → Chocolatey**。
- 找不到就点顶部 **「一键下载 ffmpeg」**，自动下载并装到 `exe同目录\ffmpeg\`，
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

1. 粘贴**直播源地址**：
   - 抖音：直播间链接 / 房间号 / App 分享短链 / 用户主页链接 —— 会自动解析
   - 或任意 `m3u8` / `flv` / `mp4` 直链 / `rtmp` —— 直接录制，不走解析
2. （可选）点 **「解析画质」**：显示主播昵称、开播状态，并把画质下拉框收敛成该直播间真实可用的档位
3. （可选）选 **录制画质**：默认「自动（最高画质）」，也可指定原画 / 高清 / 标清 / 流畅
4. 保存位置留空则自动命名为 `主播名_日期_时间.mp4`（非抖音源为 `直播_日期_时间.mp4`）
5. 点「开始录制」，随时点「停止录制」
6. 停止后自动无损封装成 mp4（录制过程用 ts 中间文件，中途断电/停止文件也不会坏）

几个好用的勾选项：

| 选项 | 作用 |
|---|---|
| HTTP 直链断流自动重连 | 网络抖动导致断流时自动续录（默认开） |
| 未开播时自动等待开录 | 每 30 秒重试一次，主播一开播就自动开始录；点「停止」可取消 |
| 停止后自动无损转成 mp4 | 用 ts 中间文件录制，停止后封装（默认开） |
| 保留 ts 中间文件 | 想留原始流时勾上 |
| 录完自动重编码 | 录完接着按 H.264 / H.265 重编码一遍，质量档沿用「视频转码」页的 CQ |

录制全程 `-c copy` 不重编码，CPU/显卡几乎零占用。

### 一键复制推流地址（转播用）

解析成功后，「解析画质」旁边的 **「复制推流地址」** 按钮会亮起，点开是一个下拉菜单：

| 菜单项 | 复制内容 |
|---|---|
| 复制 FLV 地址（当前画质） | 当前画质档的 FLV 地址，**转播首选**（延迟低、适合 `-c copy` 直推） |
| 复制 HLS(m3u8) 地址（当前画质） | 当前画质档的 `index.m3u8`，兼容性最好但延迟较高 |
| 复制该画质 FLV + HLS（两行） | 两条地址各占一行，一次拿走按需取用 |
| 复制全部画质（FLV / HLS） | 该协议下所有档位的地址，每行一条 |

复制什么画质取决于上面 **「录制画质」** 下拉框：选「自动（最高画质）」就取该协议下的最高档。
复制内容同时打印在下方「执行日志」里，方便肉眼核对。

**直链输入也能用**：填的不是抖音地址时，点「解析画质」后按钮同样亮起，复制到的就是你填的原地址。

两点注意：
- 按钮在**未解析**（或改了地址之后）是灰的，避免复制到上一场的过期地址 —— 抖音推流地址带
  签名有效期，换一场直播就作废，必须重新解析。
- 选了一档该直播间**没有**的画质时，会弹窗告诉你两种协议各有哪些档位可用，不会静默复制错东西。

这个按钮只负责复制地址，可以直接粘到 OBS / 其他平台的拉流工具里；本工具不代你推流。

### 常看主播（解析历史快捷入口）

每次解析成功后，该主播会**自动记进「常看主播」**，下次不用再找链接：

- 卡片里显示**最近 4 个**主播，点一下 = 自动填入地址 + 立刻重新解析，直接等结果就行。
- 点 **「全部记录」** 下拉可看到最近 15 个（带房间号），或 **清空全部记录**。
- 记录存在 exe 同目录的 `vt_config.json` 的 `history` 字段里，重启不丢。
- 快捷入口**存的是 `web_rid` 而不是你当初粘的链接**，点击时组成 `https://live.douyin.com/<web_rid>`：
  这样 App 分享短链过期、或当初用的是需要浏览器渲染的主页链接，都不影响再次解析。
- 按 `web_rid` 去重：同一主播重复解析只保留一条，最近用的排最前，最多留 12 条。
- 解析进行中再点另一个主播**不会没反应**：新请求会排队，等当前这轮结束后自动补跑。

⚠️ 抖音推流地址带签名有效期，**换一场直播旧地址就作废**，所以快捷入口是「重新解析」而不是
「复用旧地址」。

## 命令行

```
视频转码.exe --cli -m copy -f mp4 "C:\视频\9.9录屏.ts"

视频转码.exe --cli --install-ffmpeg -o D:\目标目录

视频转码.exe --cli --record "https://xxx/live.m3u8" -o D:\录制.mp4 --limit 120

# 抖音直播间直接录（画质自动取最高）
视频转码.exe --cli --record 123456789 -o D:\正茶司_直播.mp4

# 先看看有哪些画质，再按时长和画质录
视频转码.exe --cli --record https://live.douyin.com/123456789 --list
视频转码.exe --cli --record 123456789 --quality or4 --limit 180 --transcode h265

# 主播还没开播：挂着等，开播自动开始录
视频转码.exe --cli --record 123456789 --wait
视频转码.exe --cli --record 123456789 --wait 3600
```

转码参数：
- `-m copy`   无损转封装（默认，不重编码、零画质损失、速度最快）
- `-m h264`   H.264 重编码（优先 NVENC 硬件加速，没有则自动退回 libx264）
- `-m h265`   H.265 重编码（体积最小，优先 NVENC）
- `-f mp4`    输出容器：mp4 / mkv / mov
- `--cq 23`   重编码质量 16-32，越小越清晰（默认 23）
- `-o 目录`   输出目录（默认与源文件同目录）

录制参数：
- `--record URL`   直播源：抖音直播间链接 / 房间号 / 分享短链 / 主页链接，或 m3u8 / flv / rtmp
- `-o 文件`        保存位置（.mp4/.ts/.mkv/.flv），留空则按主播名+时间自动命名
- `--limit 120`    最长录制分钟数，0=不限
- `--quality NAME` 录制画质：`auto`（默认，最高可用）/ `or4` / `uhd` / `hd` / `sd` / `ld`
- `--list`         只解析并列出可用画质，不录制
- `--wait [SEC]`   未开播时等待开播再录；SEC 可选，不写=不限时长
- `--transcode MODE` 录完自动重编码：`h264` / `h265`

安装参数：
- `--install-ffmpeg`          下载安装 ffmpeg 到 exe 同目录 ffmpeg\（-o 可指定目标目录）
- `--ffmpeg-url URL`          配合 --install-ffmpeg：手动指定 zip 直链（自动源全失败时用）

## 抖音直播源解析怎么做的

解析逻辑全在 `douyin.py`，**纯 Python 标准库，不引入任何第三方依赖**，
因此 exe 体积几乎没变化（不打包浏览器内核）。

### 支持哪些输入

| 输入 | 示例 | 是否需要额外组件 |
|---|---|---|
| 房间号 | `123456789` | 不需要 |
| 直播间链接 | `https://live.douyin.com/123456789` | 不需要 |
| App 分享短链 | `https://v.douyin.com/xxxxx/` | 不需要 |
| 带文案的分享文本 | `8.88 复制打开抖音… https://v.douyin.com/xxx/` | 不需要 |
| 用户主页链接 | `https://www.douyin.com/user/MS4wLjAB…` | **需要本机有 Edge / Chrome** |

前四种走纯 HTTP，速度快、零依赖。**用户主页链接**是唯一需要渲染 JS 的场景：
抖音主页是 SPA，直接抓 HTML 只能拿到约 72KB 的空壳。
这时工具会调用本机自带的 Edge / Chrome 的 headless 模式取渲染后的 DOM：

```
msedge.exe --headless=new --disable-gpu --user-data-dir=<临时目录> \
           --virtual-time-budget=8000 --dump-dom "https://www.douyin.com/user/<sec_uid>"
```

Windows 默认自带 Edge，所以**不需要为此下载任何东西**（这也是不打包 Chromium 内核的原因，
那会多出约 700MB）。可以用环境变量 `DOUYIN_BROWSER=0` 关掉这个兜底。

### 提取策略（三级）

1. **结构化提取**：从页面 `RENDER_DATA` 里解析 `flv_pull_url` / `hls_pull_url_map`
2. **全页文本搜索**：正则匹配 `or4.flv` / `hd.flv` / `*.m3u8` 等后缀
3. **Webcast API 兜底**：前两步拿不全时，调抖音接口补齐

解析出多种画质（原画 OR4 / 超清 UHD / 高清 HD / 标清 SD / 流畅 LD）和两种协议
（FLV / HLS）。录制默认优先 FLV —— 它是连续流，配合 `-c copy` 录制更省事。

> **长录制注意**：抖音推流地址带签名有效期。如果超长录制中途遇到签名过期导致断流，
> 停止后重新点一次录制即可（工具默认会自动重连 10 次以内的抖动）。


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
test_douyin.py → 抖音解析测试
record_test.py → 直播录制测试
```

### 文件职责

| 文件 | 作用 |
|---|---|
| `core.py` | 转码引擎 + ffmpeg 查找/下载 + **`prepare_record_source()` 录制源解析** |
| `douyin.py` | 抖音直播源解析（**纯标准库**，可单独使用） |
| `selftest.py` / `test_douyin.py` | 引擎自检 / 抖音解析测试 |
| `ui.py` | **圆角控件库**（RoundCard/RoundButton/RoundMenubutton/RoundEntry/RoundSlider/TabBar
+ 自绘勾选指示器）。纯 tkinter 自绘，**不依赖 sv_ttk / PIL 等任何第三方库** |
| `app.py` | tkinter 图形界面 |
| `cli.py` | 命令行入口 |
| `main.py` | 统一入口：无参数开界面 / `--cli` / `--smoke` 自检 |

`douyin.py` 不依赖本项目任何东西，想单独拿去做别的用途直接拷走即可：

```python
import douyin
room = douyin.DouyinLiveExtractor().resolve("123456789")
print(room["nickname"], douyin.available_qualities(room["streams"]))
quality, url = douyin.pick_url(room["streams"])      # 自动取最高画质
```

跑测试：

```bash
python test_douyin.py                     # 离线用例（输入识别 / 画质选择 / 直链透传）
python test_douyin.py 123456789           # 加上真实解析
python test_douyin.py 123456789 --record  # 再录 6 秒验证能出流
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

- **双击 bat 报「系统找不到指定的路径 / 文件」**：还没装运行环境。先双击 `安装环境.bat`，
  完成后才能用 `启动程序.bat` / `调试启动.bat` / `打包exe.bat`（这三个脚本已加前置检查，会明确提示）。
- **`启动程序.bat` 双击没反应，或报 `No module named 'tkinter'`**：用来建虚拟环境的 Python
  不含 tkinter。本程序是图形界面必须有它，而**微软商店版 / 精简版 / 某些软件自带的 Python
  都不带 tkinter**。`安装环境.bat` 会自动按 `py -3.13 → 3.12 → 3.11 → 3.10 → python`
  顺序挑选**第一个通过 tkinter 检测**的解释器；若全军覆没会给出明确提示。
  手工排查：`python -c "import tkinter"`，报错就换成
  [python.org 官方安装包](https://www.python.org/downloads/)（勾选 Add Python to PATH），
  然后重跑 `安装环境.bat`（它会自动重建不合格的 .venv）。
- 换电脑后提示找不到 ffmpeg：确认 `ffmpeg\ffmpeg.exe` 和 exe 在同一文件夹；也可在界面手动指定。
- 录制没有数据：地址失效或需要特定 Referer 的源暂不支持，换个源试试。
- 抖音链接解析失败：
  - 提示「未开播」→ 主播确实没开播，勾上「未开播时自动等待开录」或先用 `--list` 确认状态。
  - 提示找不到 Edge / Chrome → 只有**用户主页链接**需要浏览器渲染，改用直播间链接、房间号或
    App 分享短链即可（这三种纯 HTTP 可解）。也可装个 Edge 后重试。
  - 提示「未能解析到直播间」→ 链接可能无效，或抖音改了页面结构，用 `--list` 看详细输出。
- 打包后闪退：运行 `视频转码.exe --smoke D:\smoke.txt`，看报告里的 FAIL 项。
- 无损模式报错：个别容器/编码组合不能直接转封装，改用 H.264 模式或输出为 mkv。
