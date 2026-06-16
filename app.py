"""VidLens Web UI（Gradio）：贴 YouTube 链接 → 实时进度 → Markdown 总结。
启动:  python app.py   然后浏览器打开 http://127.0.0.1:7860
前提:  .env 已配 DASHSCOPE_API_KEY；如抓 YouTube 需先 start_pot.ps1 + cookies。
"""
import os
# 本地回环地址绕过系统 HTTP 代理，否则 Gradio 启动自检会被代理重置 (WinError 10054)
os.environ["NO_PROXY"] = "127.0.0.1,localhost,0.0.0.0," + os.environ.get("NO_PROXY", "")
os.environ["no_proxy"] = os.environ["NO_PROXY"]

import queue
import re
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

import gradio as gr

from vidlens import pipeline, config

OUT_DIR = Path("output")
OUT_DIR.mkdir(exist_ok=True)

_TUTORIAL_MD = """
### 一、获取 百炼 API Key（用于 ASR 转录 / 视觉理解 / LLM 总结）

1. 打开 **https://bailian.console.aliyun.com/** ，用阿里云账号登录（没有就用支付宝/手机号免费注册）。
2. 首次进入会提示**开通"阿里云百炼"服务**，点同意开通（有免费额度，新用户通常送上百万 tokens）。
3. 右上角头像旁 → **API-KEY**（或左侧菜单「API-KEY 管理」）→ **创建我的 API-KEY**。
4. 复制以 **`sk-`** 开头的字符串，粘贴到上面的「百炼 API Key」框，勾「记住」。

> 费用：通义千问总结 + Paraformer 语音识别都很便宜，先用免费额度即可；超出按量计费（一个长视频通常几分钱到几毛钱）。

---

### 二、获取 YouTube Cookie（绕过"确认你不是机器人"反爬）

1. 给浏览器装扩展 **Cookie-Editor**（Chrome 应用商店 / Edge 加载项里搜 `Cookie-Editor`，免费）。
2. 浏览器打开并**登录 youtube.com**（保持登录状态）。
3. 点浏览器右上角的 **Cookie-Editor 图标** → 右下角 **Export（导出）** → 选 **Netscape** 格式（会自动复制到剪贴板）。
4. 回到本页面，把内容**粘贴到「YouTube Cookie」框** → 点 **💾 保存凭证**（看到"✅ 已保存"即成功）。之后贴链接开始总结即可。

> ⚠️ Cookie = 你的账号登录凭证，**请勿分享给他人**。它只会保存在你本机的 `cookies.txt`（已加入 .gitignore）。Cookie 会过期（通常数周到数月），失效后重新导出粘贴即可。

---

### 三、代理（国内访问 YouTube 必需）

YouTube 在国内需科学上网。开着你的代理软件（如 Clash），把它的 HTTP 代理地址填进「代理」框，默认 `http://127.0.0.1:7890`。
"""

STEP_NAMES = ["获取视频元数据", "提取文本（字幕 / ASR）", "视觉路处理", "LLM 总结", "打包产物"]
_STEP_RE = re.compile(r"\[(\d)/5\]")
_PCT_RE = re.compile(r"下载 (\d+)%")
_ASR_RE = re.compile(r"转录 (\d+)/(\d+) 段")


def _cookie_count(text: str) -> int:
    n = 0
    for ln in config.cookies_to_netscape(text).splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#"):
            n += 1
    return n


def _save_creds(api_key, cookies_text, remember, proxy, summary_prompt):
    """独立保存设置到 .env / cookies.txt / prompt.txt，返回状态文字。"""
    saved = []
    if (cookies_text or "").strip():
        try:
            config.save_cookies(cookies_text)           # 存为 Netscape cookies.txt
            saved.append(f"Cookie（{_cookie_count(cookies_text)} 条）")
        except Exception as e:
            return f"❌ Cookie 解析失败（请确认是 Netscape 格式）：{e}"
    if (api_key or "").strip():
        config.set_key(api_key)
        if remember:
            config.save_key_to_env(api_key)
            saved.append("API Key")
    if (proxy or "").strip():
        config.PROXY = proxy.strip()
        config._set_env_var("VIDLENS_PROXY", proxy.strip())
        saved.append("代理")
    if (summary_prompt or "").strip():
        config.save_summary_prompt(summary_prompt)
        saved.append("总结提示词")
    if not saved:
        return "⚠️ 没有可保存的内容"
    return "✅ 已保存：" + "、".join(saved) + "（下次启动自动加载）"


def _steps_html(steps):
    """渲染分步进度面板：图标 + 步骤名 + 进度条（已完成满条/进行中流动/未开始空条/错误红条）。"""
    css = """<style>
    @keyframes vlmove{0%{background-position:200% 0}100%{background-position:0 0}}
    .vl-active{background:linear-gradient(90deg,#3b82f6 25%,#93c5fd 50%,#3b82f6 75%);
      background-size:200% 100%;animation:vlmove 1.1s linear infinite;height:100%;width:100%}
    </style>"""
    icons = {"pending": "⚪", "active": "🔵", "done": "✅", "error": "❌"}
    fill = {"done": "#16a34a", "error": "#dc2626"}
    rows = []
    for s in steps:
        st = s["status"]
        if st == "active" and s.get("pct") is not None:
            # 有真实下载百分比 → 确定性蓝条
            bar = (f'<div style="height:100%;width:{s["pct"]}%;background:#3b82f6;'
                   f'transition:width .3s">&nbsp;</div>')
        elif st == "active":
            bar = '<div class="vl-active"></div>'      # 无百分比 → 流动动画
        elif st in fill:
            bar = f'<div style="height:100%;width:100%;background:{fill[st]}"></div>'
        else:
            bar = ""
        extra = f' · {s["pct"]}%' if (st == "active" and s.get("pct") is not None) else ""
        secs = (f'<span style="color:#888;font-size:12px;margin-left:8px">{s["secs"]:.1f}s</span>'
                if s.get("secs") else
                f'<span style="color:#60a5fa;font-size:12px;margin-left:8px">{extra}</span>' if extra else "")
        weight = "600" if st == "active" else "400"
        color = "#e5e7eb" if st in ("active", "done") else "#9ca3af"
        rows.append(f"""
        <div style="display:flex;align-items:center;gap:10px;margin:7px 0;">
          <span style="width:22px;text-align:center">{icons[st]}</span>
          <div style="flex:1">
            <div style="font-size:13px;font-weight:{weight};color:{color}">{s['name']}{secs}</div>
            <div style="height:8px;background:#27272a;border-radius:4px;overflow:hidden;margin-top:4px">{bar}</div>
          </div>
        </div>""")
    return css + "<div style='padding:4px 2px'>" + "".join(rows) + "</div>"


def _run(url, api_key, cookies_text, remember, proxy, vision, max_frames, scene, save_transcript, include_audio, summary_prompt):
    """生成器：分步进度面板 + 文字日志 + Markdown 总结 + zip 下载。"""
    steps = [{"name": n, "status": "pending", "secs": None} for n in STEP_NAMES]
    blank = _steps_html(steps)

    url = (url or "").strip()
    if not url:
        yield blank, "⚠️ 请先填入 YouTube 链接", "", None
        return
    if not (api_key or "").strip():
        yield blank, "⚠️ 请先填入百炼 API Key（见下方教程）", "", None
        return
    # 保存凭证：cookie 文本（JSON/Netscape 都行）转存并接入；key 可选记住
    if (cookies_text or "").strip():
        try:
            config.save_cookies(cookies_text)
        except Exception as e:
            yield blank, f"⚠️ Cookie 解析失败：{e}", "", None
            return
    if remember:
        config.save_key_to_env(api_key)

    logs = []
    q: queue.Queue = queue.Queue()
    result_box = {}
    cur = {"i": -1, "t": 0.0}

    def _activate(idx):
        """把当前步标完成并记耗时，激活新步。"""
        now = time.time()
        if cur["i"] >= 0 and steps[cur["i"]]["status"] == "active":
            steps[cur["i"]]["status"] = "done"
            steps[cur["i"]]["secs"] = now - cur["t"]
        for j in range(idx):            # 之前的都算完成
            if steps[j]["status"] == "pending":
                steps[j]["status"] = "done"
        steps[idx]["status"] = "active"
        steps[idx]["pct"] = None      # 新步重置下载百分比
        cur["i"], cur["t"] = idx, now

    def log(msg):
        q.put(("log", f"{datetime.now():%H:%M:%S}  {msg}"))

    def worker():
        try:
            result_box["data"] = pipeline.run(
                url, vision=vision, scene_threshold=scene,
                max_frames=int(max_frames), log=log, proxy=proxy,
                include_audio=include_audio, api_key=api_key,
                summary_prompt=summary_prompt,
            )
            q.put(("done", None))
        except Exception as e:
            q.put(("error", f"{e}\n\n{traceback.format_exc()}"))

    threading.Thread(target=worker, daemon=True).start()

    while True:
        kind, payload = q.get()
        if kind == "log":
            logs.append(payload)
            m = _STEP_RE.search(payload)
            if m:
                _activate(int(m.group(1)) - 1)
            pm = _PCT_RE.search(payload)
            if pm and cur["i"] >= 0:
                p = int(pm.group(1))
                # 满 100% 说明下载完、但这步后面还有活（ASR/抽帧）→ 回到流动动画
                steps[cur["i"]]["pct"] = None if p >= 100 else p
            am = _ASR_RE.search(payload)        # ASR 分段进度 → 真实百分比
            if am and cur["i"] >= 0:
                p = int(int(am.group(1)) / int(am.group(2)) * 100)
                steps[cur["i"]]["pct"] = None if p >= 100 else p
            yield _steps_html(steps), "\n".join(logs), "", None
        elif kind == "error":
            if cur["i"] >= 0:
                steps[cur["i"]]["status"] = "error"
            logs.append("❌ 出错")
            yield _steps_html(steps), "\n".join(logs) + "\n\n" + payload, "", None
            return
        elif kind == "done":
            now = time.time()
            if cur["i"] >= 0:
                steps[cur["i"]]["status"] = "done"
                steps[cur["i"]]["secs"] = now - cur["t"]
            for s in steps:
                if s["status"] == "pending":
                    s["status"] = "done"
            r = result_box["data"]
            md = f"# {r['title']}\n\n> 来源: {r['url']}  ·  文本: {r['source']}\n\n{r['summary']}\n"
            if save_transcript:
                md += f"\n\n---\n## 完整转录\n\n{r['transcript']}\n"
                if r["visual_notes"]:
                    md += f"\n## 视觉笔记\n\n{r['visual_notes']}\n"
            logs.append(f"✅ 完成，产物已打包：{r['zip']}")
            yield _steps_html(steps), "\n".join(logs), md, r["zip"]
            return


with gr.Blocks(title="VidLens") as demo:
    gr.Markdown("# 🎬 VidLens —— YouTube 视频内容总结\n贴链接，自动「字幕优先 / ASR 兜底」提取文本并用 Qwen 总结。")
    gr.Markdown(
        "作者主页："
        "[𝕏 Twitter](https://x.com/AvZA24CuCD63579) · "
        "[GitHub](https://github.com/xiongwenhao112) · "
        "[CSDN](https://blog.csdn.net/weixin_66401877)"
    )

    _have_cookie = bool(config.COOKIES and Path(config.COOKIES).exists())
    with gr.Row():
        # —— 左侧：设置栏 ——
        with gr.Column(scale=1, min_width=320):
            gr.Markdown("### ⚙️ 设置")
            api_key = gr.Textbox(
                label="百炼 API Key", type="password", value=config.DASHSCOPE_API_KEY,
                placeholder="sk-...  在 bailian.console.aliyun.com 申请",
            )
            cookies_text = gr.Textbox(
                label="YouTube Cookie（Netscape）" + ("　已配置，留空沿用旧的" if _have_cookie else ""),
                lines=3, placeholder="粘贴 Cookie-Editor 导出的 Netscape 内容（见教程）",
            )
            proxy = gr.Textbox(
                label="代理（国内访问必填）", value=os.environ.get("VIDLENS_PROXY", ""),
                placeholder="http://127.0.0.1:7890",
            )
            with gr.Row():
                remember = gr.Checkbox(label="记住到 .env", value=True)
                save_btn = gr.Button("💾 保存设置", variant="secondary", size="sm")
            save_status = gr.Markdown("")

            with gr.Accordion("高级选项", open=False):
                vision = gr.Radio(
                    label="视觉路（读画面里的幻灯片/图表/硬字幕）",
                    choices=[("自动判断（按文本密度，推荐）", "auto"),
                             ("强制开启（更慢更贵）", "on"),
                             ("强制关闭", "off")],
                    value="auto")
                max_frames = gr.Slider(2, 30, value=12, step=1, label="最多关键帧数")
                scene = gr.Slider(0.1, 0.9, value=0.4, step=0.05, label="场景切换阈值（越小抽帧越多）")
                save_transcript = gr.Checkbox(label="在右侧展示完整转录/视觉笔记", value=False)
                include_audio = gr.Checkbox(label="打包包含音频文件（zip 会变大）", value=True)
                summary_prompt = gr.Textbox(
                    label="总结提示词（改成你想要的输出风格/格式）",
                    value=config.load_summary_prompt(), lines=8,
                )

            with gr.Accordion("📖 如何获取 API Key 和 Cookie", open=False):
                gr.Markdown(_TUTORIAL_MD)

        # —— 右侧：主操作区 ——
        with gr.Column(scale=2):
            with gr.Row():
                url = gr.Textbox(label="YouTube 链接", scale=3,
                                 placeholder="https://www.youtube.com/watch?v=...")
                btn = gr.Button("开始总结", variant="primary", scale=1)
            step_html = gr.HTML(value=_steps_html(
                [{"name": n, "status": "pending", "secs": None} for n in STEP_NAMES]))
            summary = gr.Markdown(label="总结结果")
            file_out = gr.File(label="下载全部产物（zip：视频/音频/字幕/转录/总结/信息）")
            with gr.Accordion("详细日志", open=False):
                log_box = gr.Textbox(label="", lines=12, max_lines=12, interactive=False)

    save_btn.click(_save_creds, [api_key, cookies_text, remember, proxy, summary_prompt], save_status)

    _inputs = [url, api_key, cookies_text, remember, proxy, vision, max_frames, scene, save_transcript, include_audio, summary_prompt]
    _outputs = [step_html, log_box, summary, file_out]
    btn.click(_run, _inputs, _outputs)
    url.submit(_run, _inputs, _outputs)


if __name__ == "__main__":
    demo.queue().launch(server_name="127.0.0.1", server_port=7860,
                        inbrowser=True, theme=gr.themes.Soft())
