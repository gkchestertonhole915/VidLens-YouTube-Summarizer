"""编排：降级链（字幕 → ASR）+ 按需视觉路 → 融合总结。"""
import json
import re
import tempfile
import threading
import time
import zipfile
from pathlib import Path

from . import config, download, subtitles, asr, keyframes, summarize

OUT_DIR = Path("output")


def _with_heartbeat(label, fn, log, interval=5):
    """黑盒慢操作（ASR/LLM）期间每隔几秒报一次已用时，让前端知道还活着。"""
    stop = threading.Event()

    def beat():
        t0 = time.time()
        while not stop.wait(interval):
            log(f"    ⏳ {label}中… 已 {int(time.time() - t0)}s")

    th = threading.Thread(target=beat, daemon=True)
    th.start()
    try:
        return fn()
    finally:
        stop.set()


def _safe_name(s: str, fallback: str = "vidlens") -> str:
    s = re.sub(r'[\\/:*?"<>|]+', "_", s or "").strip()
    return (s[:60] or fallback).rstrip(". ")


def _package(tmp: Path, meta: dict, url: str, source: str,
             transcript: str, visual_notes: str, summary: str, log) -> Path:
    """把文本产物落盘，连同已下载的媒体打成一个 zip。"""
    title = meta.get("title", "")
    (tmp / "总结.md").write_text(
        f"# {title}\n\n> 来源: {url}  ·  文本: {source}\n\n{summary}\n", encoding="utf-8")
    (tmp / "转录文本.txt").write_text(transcript, encoding="utf-8")
    if visual_notes:
        (tmp / "视觉笔记.txt").write_text(visual_notes, encoding="utf-8")
    info = {k: meta.get(k) for k in
            ("id", "title", "uploader", "channel", "duration", "upload_date",
             "view_count", "like_count", "webpage_url", "description")}
    info["text_source"] = source
    info["transcript_chars"] = len(transcript)
    (tmp / "信息.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")

    OUT_DIR.mkdir(exist_ok=True)
    zip_path = OUT_DIR / f"{_safe_name(title)}_{meta.get('id','')}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(tmp.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(tmp))
    log(f"    打包完成: {zip_path}  ({zip_path.stat().st_size/1e6:.1f} MB)")
    return zip_path


def _should_use_vision(transcript: str, meta: dict, log) -> bool:
    """按文本密度 + 视频分类自动判断是否值得上视觉路。"""
    dur = meta.get("duration") or 1
    density = len(transcript) / max(dur, 1)              # 字/秒
    cats = set(meta.get("categories") or [])
    # 命中教程/科技类则放宽阈值（×1.5），更积极地读画面里的幻灯片/代码
    threshold = config.VISION_DENSITY_THRESHOLD * (1.5 if cats & config.VISION_CATEGORIES else 1.0)
    decision = density < threshold
    log(f"    [自动路由] 文本密度 {density:.2f} 字/秒，分类 {cats or '—'}，"
        f"阈值 {threshold:.2f} → 视觉路{'开' if decision else '关'}")
    return decision


def run(url: str, vision: str = "auto", scene_threshold: float = 0.4,
        max_frames: int = 12, workdir: Path | None = None, log=print,
        proxy: str | None = None, include_audio: bool = True,
        api_key: str | None = None, summary_prompt: str | None = None) -> dict:
    if api_key:
        config.set_key(api_key)
    config.require_key()
    if proxy:
        config.PROXY = proxy.strip()
        log(f"[*] 使用代理: {config.PROXY}")
    tmp = workdir or Path(tempfile.mkdtemp(prefix="vidlens_"))
    log(f"[*] 工作目录: {tmp}")

    def _mk_progress():
        """生成一个下载进度回调：整数百分比变化时才打日志（含可被 UI 解析的 '下载 NN%'）。"""
        last = {"v": -1}
        def cb(frac, speed, eta):
            pct = int(frac * 100)
            if pct != last["v"]:
                last["v"] = pct
                log(f"    ⬇ 下载 {pct}%  {speed}  ETA {eta}")
        return cb

    log("[1/5] 获取视频元数据 …")
    meta = download.get_info(url)
    log(f"    标题: {meta.get('title')}  时长: {meta.get('duration', 0)}s")

    # —— 降级链：优先字幕，无字幕再下音频走 ASR ——
    log("[2/5] 提取文本（字幕优先，ASR 兜底）…")
    transcript, source = "", ""
    vtt = download.download_subtitles(url, tmp)
    if vtt:
        transcript = subtitles.parse_vtt(vtt)
        source = "字幕"
    if len(transcript) < 50:  # 没字幕或字幕太短 → ASR
        log("    无可用字幕，下载音频做 ASR …")
        wav = download.download_audio(url, tmp, progress=_mk_progress())
        mins = (meta.get("duration") or 0) / 60
        log(f"    音频已下载（约 {mins:.0f} 分钟），开始 ASR 转录 …")
        transcript = asr.transcribe(wav, workdir=tmp, log=log)
        source = "ASR"
    log(f"    文本来源: {source}，{len(transcript)} 字")

    # —— 视觉路：on=强制开 / off=强制关 / auto=按信号决定 ——
    log("[3/5] 判断视觉路 …")
    if vision == "on":
        use_vision = True
    elif vision == "off":
        use_vision = False
    else:  # auto
        use_vision = _should_use_vision(transcript, meta, log)

    visual_notes = ""
    if use_vision:
        log("    视觉路：下载视频 → 场景抽帧 → Qwen-VL 理解 …")
        video = download.download_video(url, tmp, progress=_mk_progress())
        frames = keyframes.extract_keyframes(video, tmp, scene_threshold, max_frames,
                                             duration=meta.get("duration"), log=log)
        log(f"    抽取关键帧 {len(frames)} 张")
        visual_notes = keyframes.describe_frames(frames)
    else:
        log("    跳过视觉路")

    log("[4/5] 融合 + LLM 总结 …")
    summary = _with_heartbeat(
        "总结", lambda: summarize.summarize(transcript, meta, visual_notes, summary_prompt), log)

    # 若选了打包含音频，但走的是字幕路（没下过音频），补下一次
    if include_audio and not list(tmp.glob("audio*.wav")):
        log("    打包：补下音频文件 …")
        try:
            download.download_audio(url, tmp, progress=_mk_progress())
        except Exception as e:
            log(f"    音频下载失败（不影响总结）: {e}")

    log("[5/5] 打包所有产物 …")
    zip_path = _package(tmp, meta, url, source, transcript, visual_notes, summary, log)

    return {
        "title": meta.get("title", ""),
        "url": url,
        "source": source,
        "transcript": transcript,
        "visual_notes": visual_notes,
        "summary": summary,
        "workdir": str(tmp),
        "zip": str(zip_path),
    }
