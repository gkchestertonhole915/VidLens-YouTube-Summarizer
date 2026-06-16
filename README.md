<div align="center">

<img src="images/banner.svg" alt="VidLens — YouTube Video Summarizer" width="100%">

# VidLens · YouTube 视频 AI 总结工具

**YouTube Video Summarizer** — 贴一个 YouTube 链接，自动提取**字幕 / 语音 / 画面**，用国产大模型（阿里云百炼 Qwen / Paraformer）生成结构化中文总结，支持网页界面与一键打包下载。

<p>
<img src="https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white" alt="Python">
<img src="https://img.shields.io/badge/Downloader-yt--dlp-FF0000?logo=youtube&logoColor=white" alt="yt-dlp">
<img src="https://img.shields.io/badge/LLM-Qwen%20%2F%20百炼-615CED" alt="Qwen">
<img src="https://img.shields.io/badge/ASR-Paraformer-00A4FF" alt="Paraformer">
<img src="https://img.shields.io/badge/UI-Gradio-F97316" alt="Gradio">
<img src="https://img.shields.io/badge/License-MIT-22c55e" alt="License">
</p>

[特性](#-特性) · [快速开始](#-快速开始) · [反爬三件套](#️-youtube-抓取的三件套缺一不可) · [图文教程](TUTORIAL.md) · [项目结构](#-项目结构)

</div>

---

> **关键词**：YouTube 视频总结 / YouTube Summarizer / 视频转文字 / AI 字幕提取 / 语音识别 ASR / 视频内容理解 / yt-dlp / 通义千问 Qwen / Paraformer / 视频 OCR

## ✨ 特性

- 🎯 **降级链而非无脑并行**：字幕优先 → 无字幕自动下音频走 ASR，省钱省时。
- 🧠 **视觉路自动路由**：按「文本密度（字/秒）」判断是否值得读画面（幻灯片/榜单/硬字幕），低密度自动开启 Qwen-VL，不浪费 token。
- 🖼️ **静态视频也能读**：场景抽帧抽不到时自动降级为均匀采样，保证榜单/PPT 类视频也能 OCR。
- ⚡ **长视频 ASR 提速**：音频切段并发识别（38 分钟音频从 ~10 分钟压到 ~2 分钟）。
- 📊 **网页界面**：左设置 / 右操作，实时分步进度条（下载、ASR 真实百分比），结果一键打包下载（视频/音频/字幕/转录/总结/信息 zip）。
- 📝 **可定制总结提示词**：页面直接改输出风格 / 格式。
- 🔑 **凭证全部页面配置**：API Key / Cookie / 代理，一键保存。

## 🧩 工作原理

```
YouTube URL ─ yt-dlp ─┬─ 字幕(优先)         ─┐
                      ├─ 音频 → Paraformer   ├─ 融合 → Qwen 总结 → Markdown + 打包下载
                      └─ 关键帧 → Qwen-VL   ─┘   (视觉路按文本密度自动触发)
```

## 🚀 快速开始

### 1. 环境依赖

- [Python 3.10+](https://www.python.org/) · [ffmpeg](https://ffmpeg.org/) · [Node.js 20+](https://nodejs.org/) · [Deno](https://deno.com/)（解 YouTube nsig）
- 阿里云百炼 API Key（[申请教程](TUTORIAL.md)）

```powershell
pip install -r requirements.txt
npm install -g deno          # 解 nsig 必需，否则只拿到缩略图
copy .env.example .env       # 填入 DASHSCOPE_API_KEY（也可在网页里填）
```

### 2. 启动 PO Token 服务（绕 YouTube 反爬，每次开机跑一次）

```powershell
powershell -File start_pot.ps1   # 首次自动 clone + 编译 bgutil 服务，监听 127.0.0.1:4416
```

### 3. 启动网页

```powershell
python app.py                    # 自动打开 http://127.0.0.1:7860
```

左侧「设置」填 **API Key**、粘贴 **YouTube Cookie**、填 **代理**（国内必填，Clash 默认 `http://127.0.0.1:7890`）→「💾 保存设置」→ 右侧贴链接开始。

> 📖 **Cookie / API Key 怎么获取？** 见 **[图文教程 TUTORIAL.md](TUTORIAL.md)**。

### 命令行用法

```powershell
python cli.py "https://www.youtube.com/watch?v=XXXX"          # 纯文本总结（视觉路自动判断）
python cli.py "<url>" --vision -o output\summary.md           # 强制读画面
python cli.py "<url>" --no-vision --save-transcript           # 关视觉、附完整转录
```

## ⚠️ YouTube 抓取的三件套（缺一不可）

YouTube 现在要同时满足三项才能拿到真实音视频流，否则只返回缩略图或报错：

| 组件 | 作用 | 配置 |
|------|------|------|
| **登录 Cookie** | 通过"确认你不是机器人" | 网页粘贴，或 `cookies.txt`（Netscape）|
| **PO Token 服务** | 提供 Proof-of-Origin | `start_pot.ps1`（端口 4416）|
| **Deno** | 破解 nsig (n-challenge) | `npm install -g deno` |

排查"拉不到视频 / Requested format is not available"：① `curl 127.0.0.1:4416/ping` ② `deno --version` ③ Cookie 是否过期。

> 部分视频（私享/会员/年龄/地区限制）即便齐全也无法访问，属正常，换公开视频即可。

## 🧱 项目结构

```
app.py              Web 界面（Gradio）
cli.py              命令行入口
start_pot.ps1       启动 PO Token 服务 + Deno 自检
convert_cookies.py  Cookie JSON → Netscape 转换
vidlens/
  config.py         配置 / 凭证 / 提示词管理
  download.py       yt-dlp：元数据/字幕/音频/视频（带实时进度）
  subtitles.py      VTT 字幕解析清洗
  asr.py            Paraformer 语音识别（长音频切段并发）
  keyframes.py      ffmpeg 抽帧（场景切换 + 均匀采样降级）+ Qwen-VL
  summarize.py      融合 + map-reduce 长文总结（提示词可定制）
  pipeline.py       降级链编排 + 自动视觉路由
```

## 🔧 模型 / 参数（`.env` 可覆盖）

| 用途 | 默认模型 | 环境变量 |
|------|----------|----------|
| 总结/融合 | `qwen-plus` | `VIDLENS_LLM_MODEL` |
| 关键帧视觉 | `qwen-vl-max` | `VIDLENS_VL_MODEL` |
| ASR | `paraformer-realtime-v2` | `VIDLENS_ASR_MODEL` |
| ASR 并发数 | `6` | `VIDLENS_ASR_CONCURRENCY` |
| 视觉触发阈值（字/秒）| `1.2` | `VIDLENS_VISION_DENSITY` |

## 📌 已知边界

- yt-dlp 受 YouTube 反爬影响，需持续更新 yt-dlp 版本。
- 超长视频转录走 map-reduce 自动分段（`config.CHUNK_CHARS`）。
- 视觉路成本与帧数线性相关，`--max-frames` 控制上限。
- 仅在 Windows + 国内网络环境下完整验证；其他环境请按需调整代理。

## 🤝 贡献

欢迎 Issue / PR。如果这个项目对你有帮助，点个 ⭐ Star 支持一下！

## 👤 作者

[𝕏 Twitter](https://x.com/AvZA24CuCD63579) · [GitHub](https://github.com/xiongwenhao112) · [CSDN](https://blog.csdn.net/weixin_66401877)

## 📄 License

[MIT](LICENSE) © xiongwenhao
