"""yt-dlp 封装：取元数据、字幕、音频。用 CLI 子进程，最稳。"""
import json
import re
import subprocess
from pathlib import Path

from . import config

# yt-dlp --progress-template 用，把进度打成可解析的一行
_PROGRESS_TMPL = ("download:VLP %(progress._percent_str)s "
                  "%(progress._speed_str)s %(progress._eta_str)s")
_PCT = re.compile(r"VLP\s+([\d.]+)%\s+(\S+)\s+(\S+)")


def _stream(args, progress) -> int:
    """流式跑 yt-dlp，实时把下载百分比/速度/ETA 喂给 progress(frac, speed, eta)。"""
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace", bufsize=1)
    tail = []
    for line in p.stdout:
        tail.append(line)
        m = _PCT.search(line)
        if m and progress:
            progress(float(m.group(1)) / 100.0, m.group(2), m.group(3))
    p.wait()
    return p.returncode, "".join(tail[-15:])


def _base_args():
    args = ["yt-dlp", "--no-playlist", "--no-warnings", "--socket-timeout", "30"]
    if config.PROXY:
        args += ["--proxy", config.PROXY]
    if config.COOKIES:
        args += ["--cookies", config.COOKIES]
    elif config.COOKIES_FROM_BROWSER:
        args += ["--cookies-from-browser", config.COOKIES_FROM_BROWSER]
    return args


def get_info(url: str) -> dict:
    """返回视频元数据 dict（title/duration/description/chapters/字幕可用性等）。"""
    out = subprocess.run(
        _base_args() + ["-J", url],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if out.returncode != 0:
        err = out.stderr.strip()
        if "not a bot" in err or "Sign in to confirm" in err:
            raise RuntimeError(
                "YouTube 触发反爬验证，需要 cookies。最稳做法：\n"
                "  1) 在已登录 YouTube 的 Chrome/Edge 装扩展 'Get cookies.txt LOCALLY'\n"
                "  2) 打开 youtube.com，点扩展导出 cookies.txt 到 D:\\VidLens\\cookies.txt\n"
                "  3) 在 .env 设置 VIDLENS_COOKIES=D:\\VidLens\\cookies.txt"
            )
        raise RuntimeError(f"yt-dlp 取元数据失败：\n{err}")
    return json.loads(out.stdout)


def download_subtitles(url: str, workdir: Path, langs=("zh-Hans", "zh", "en")) -> Path | None:
    """优先人工字幕，再退自动字幕。成功返回 .vtt 路径，否则 None。"""
    workdir.mkdir(parents=True, exist_ok=True)
    out_tmpl = str(workdir / "sub.%(ext)s")
    lang_arg = ",".join(langs)
    # 先试人工字幕，失败再试自动字幕
    for auto_flag in ("--write-subs", "--write-auto-subs"):
        subprocess.run(
            _base_args() + [
                "--skip-download", auto_flag,
                "--sub-langs", lang_arg, "--sub-format", "vtt",
                "-o", out_tmpl, url,
            ],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        vtts = list(workdir.glob("sub*.vtt"))
        if vtts:
            return vtts[0]
    return None


def download_audio(url: str, workdir: Path, progress=None) -> Path:
    """下最优音频并转 16k 单声道 wav（Paraformer 友好）。progress(frac,speed,eta) 实时进度。"""
    workdir.mkdir(parents=True, exist_ok=True)
    out_tmpl = str(workdir / "audio.%(ext)s")
    code, tail = _stream(
        _base_args() + [
            "-f", "bestaudio/best",
            "--extract-audio", "--audio-format", "wav",
            "--postprocessor-args", "ffmpeg:-ar 16000 -ac 1",
            "--newline", "--progress-template", _PROGRESS_TMPL,
            "-o", out_tmpl, url,
        ], progress,
    )
    wavs = list(workdir.glob("audio*.wav"))
    if not wavs:
        raise RuntimeError(f"音频下载失败：\n{tail.strip()}")
    return wavs[0]


def download_video(url: str, workdir: Path, progress=None) -> Path:
    """下载视频本体（供抽帧用），压到 480p 省空间。progress(frac,speed,eta) 实时进度。"""
    workdir.mkdir(parents=True, exist_ok=True)
    out_tmpl = str(workdir / "video.%(ext)s")
    code, tail = _stream(
        _base_args() + [
            "-f", "bestvideo[height<=480]+bestaudio/best[height<=480]/best",
            "--merge-output-format", "mp4",
            "--newline", "--progress-template", _PROGRESS_TMPL,
            "-o", out_tmpl, url,
        ], progress,
    )
    vids = list(workdir.glob("video*.mp4")) + list(workdir.glob("video*.mkv"))
    if not vids:
        raise RuntimeError(f"视频下载失败：\n{tail.strip()}")
    return vids[0]
