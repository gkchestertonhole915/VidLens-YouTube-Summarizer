"""集中配置：从环境变量 / .env 读取。"""
import os
from dotenv import load_dotenv

load_dotenv()

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

LLM_MODEL = os.getenv("VIDLENS_LLM_MODEL", "qwen-plus")
VL_MODEL = os.getenv("VIDLENS_VL_MODEL", "qwen-vl-max")
ASR_MODEL = os.getenv("VIDLENS_ASR_MODEL", "paraformer-realtime-v2")
# 长音频切段并发识别的并发数（提速；过高可能触发限流）
ASR_CONCURRENCY = int(os.getenv("VIDLENS_ASR_CONCURRENCY", "6"))

COOKIES = os.getenv("VIDLENS_COOKIES") or None
# 直接从浏览器读 cookies 绕过反爬，填浏览器名: chrome / edge / firefox / brave ...
COOKIES_FROM_BROWSER = os.getenv("VIDLENS_COOKIES_FROM_BROWSER") or None
# 访问 YouTube 用的代理，如 http://127.0.0.1:7890 / socks5://127.0.0.1:7891
PROXY = os.getenv("VIDLENS_PROXY") or None

# 单段喂给 LLM 的字符上限，超过则走 map-reduce 分段总结
CHUNK_CHARS = 8000

# —— 总结提示词（可在页面修改，存到 prompt.txt）——
DEFAULT_SUMMARY_PROMPT = """请基于上面的视频内容，输出一份结构化中文总结。

输出格式（Markdown）：
## 一句话概括
## 核心要点（5-8 条，条目式）
## 详细脉络（按主题/时间顺序分段）
## 关键结论 / 行动建议

若有「画面视觉笔记」，请把画面里的图表/文字/数据整合进来。"""
PROMPT_FILE = "prompt.txt"


def load_summary_prompt() -> str:
    from pathlib import Path
    p = Path(PROMPT_FILE)
    if p.exists() and p.read_text(encoding="utf-8").strip():
        return p.read_text(encoding="utf-8")
    return DEFAULT_SUMMARY_PROMPT


def save_summary_prompt(text: str):
    from pathlib import Path
    Path(PROMPT_FILE).write_text((text or "").strip() or DEFAULT_SUMMARY_PROMPT, encoding="utf-8")


# —— 自动视觉路由 ——
# ASR/字幕文本密度（字/秒）低于此值 → 判定为视觉主导内容，自动触发视觉路
VISION_DENSITY_THRESHOLD = float(os.getenv("VIDLENS_VISION_DENSITY", "1.2"))
# 这些分类更可能含幻灯片/代码/图表，对它们放宽阈值（更积极上视觉）
VISION_CATEGORIES = {"Education", "Science & Technology", "Howto & Style"}


def require_key():
    if not DASHSCOPE_API_KEY:
        raise SystemExit(
            "缺少 DASHSCOPE_API_KEY。请在页面填入，或复制 .env.example 为 .env 填入百炼 API key。"
        )


def set_key(key: str):
    """运行时注入 API key（页面配置时用）。"""
    global DASHSCOPE_API_KEY
    if key and key.strip():
        DASHSCOPE_API_KEY = key.strip()


def _set_env_var(key: str, value: str, env_path: str = ".env"):
    """通用：把 KEY=VALUE 写回 .env（已存在则替换，否则追加）。"""
    from pathlib import Path
    p = Path(env_path)
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    out, found = [], False
    for ln in lines:
        if ln.strip().startswith(f"{key}="):
            out.append(f"{key}={value}"); found = True
        else:
            out.append(ln)
    if not found:
        out.append(f"{key}={value}")
    p.write_text("\n".join(out) + "\n", encoding="utf-8")


def save_key_to_env(key: str, env_path: str = ".env"):
    """把 API key 写回 .env，下次启动自动加载。"""
    key = (key or "").strip()
    if key:
        _set_env_var("DASHSCOPE_API_KEY", key, env_path)


def cookies_to_netscape(content: str) -> str:
    """把 Cookie-Editor 的 JSON 或已是 Netscape 的文本，统一成 yt-dlp 要的 Netscape 格式。"""
    content = (content or "").strip()
    if content.startswith("["):                 # Cookie-Editor JSON
        import json
        data = json.loads(content)
        lines = ["# Netscape HTTP Cookie File", "# Converted by VidLens", ""]
        for c in data:
            domain = c["domain"]
            df = ("#HttpOnly_" + domain) if c.get("httpOnly") else domain
            inc = "TRUE" if not c.get("hostOnly") else "FALSE"
            path = c.get("path", "/")
            sec = "TRUE" if c.get("secure") else "FALSE"
            exp = int(c["expirationDate"]) if c.get("expirationDate") else 0
            lines.append("\t".join([df, inc, path, sec, str(exp), c["name"], c["value"]]))
        return "\n".join(lines) + "\n"
    # 已是 Netscape/文本：补个头部即可
    if "# Netscape" not in content and "# HTTP Cookie" not in content:
        content = "# Netscape HTTP Cookie File\n" + content
    return content if content.endswith("\n") else content + "\n"


def save_cookies(content: str, cookie_path: str = "cookies.txt", env_path: str = ".env"):
    """把页面粘贴的 cookie 文本转成 Netscape 存盘，并把路径记进 .env。"""
    from pathlib import Path
    global COOKIES
    if not (content or "").strip():
        return
    text = cookies_to_netscape(content)
    p = Path(cookie_path)
    p.write_text(text, encoding="utf-8", newline="\n")
    COOKIES = str(p.resolve())
    _set_env_var("VIDLENS_COOKIES", COOKIES, env_path)
