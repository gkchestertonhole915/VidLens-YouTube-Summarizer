"""ASR 兜底：本地 wav 走 DashScope Paraformer。长音频切段并发，大幅提速。"""
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import dashscope
from dashscope.audio.asr import Recognition

from . import config


def _duration(path: Path) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nk=1:nw=1", str(path)],
            capture_output=True, text=True,
        )
        return float(out.stdout.strip())
    except Exception:
        return 0.0


def _split(wav_path: Path, workdir: Path, chunk_secs: int) -> list[Path]:
    """按时长切段（wav 是 PCM，-c copy 可精确切，无损无重编码）。"""
    cdir = workdir / "asr_chunks"
    cdir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(wav_path),
         "-f", "segment", "-segment_time", str(chunk_secs), "-c", "copy",
         str(cdir / "chunk_%03d.wav")],
        capture_output=True, text=True,
    )
    return sorted(cdir.glob("chunk_*.wav"))


def _one(path: Path, retries: int = 3) -> str:
    """单段识别，失败重试（应对偶发限流）。"""
    dashscope.api_key = config.DASHSCOPE_API_KEY
    last = ""
    for attempt in range(retries):
        rec = Recognition(model=config.ASR_MODEL, format="wav",
                          sample_rate=16000, language_hints=["zh", "en"], callback=None)
        r = rec.call(str(path))
        if r.status_code == 200:
            return " ".join(s.get("text", "") for s in (r.get_sentence() or [])).strip()
        last = r.message
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Paraformer 识别失败: {last}")


def transcribe(wav_path: Path, workdir: Path | None = None, log=None,
               chunk_secs: int = 300) -> str:
    """短音频直接识别；长音频切段并发识别后按序拼接。"""
    workdir = workdir or Path(wav_path).parent
    dur = _duration(wav_path)
    # 短音频（≤ 6 分钟）直接单次，省去切分开销
    if dur and dur <= chunk_secs * 1.2:
        return _one(wav_path)

    chunks = _split(wav_path, workdir, chunk_secs)
    if len(chunks) <= 1:
        return _one(wav_path)

    total, done = len(chunks), 0
    results: list[str] = [""] * total
    workers = min(config.ASR_CONCURRENCY, total)
    if log:
        log(f"    🎙 音频切成 {total} 段，{workers} 路并发转录 …")
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_one, c): i for i, c in enumerate(chunks)}
        for f in as_completed(futs):
            results[futs[f]] = f.result()
            done += 1
            if log:
                log(f"    🎙 转录 {done}/{total} 段完成")
    return " ".join(x for x in results if x).strip()
