"""关键帧路：ffmpeg 场景切换抽帧 → Qwen-VL 逐帧理解(含画面内文字)。"""
import base64
import subprocess
from pathlib import Path

from openai import OpenAI

from . import config


def _ffprobe_duration(video: Path) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nk=1:nw=1", str(video)],
            capture_output=True, text=True,
        )
        return float(out.stdout.strip())
    except Exception:
        return 0.0


def extract_keyframes(video: Path, workdir: Path, scene_threshold=0.4,
                      max_frames=12, duration: float | None = None, log=None) -> list[Path]:
    """先按场景切换抽帧；静态视频(榜单/幻灯片)抽不到时，降级为均匀采样，保证有画面。"""
    frames_dir = workdir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    # ① 场景切换抽帧（适合多镜头视频，天然去重）
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video),
         "-vf", f"select='gt(scene,{scene_threshold})'",
         "-vsync", "vfr", "-frames:v", str(max_frames),
         str(frames_dir / "kf_%03d.jpg")],
        capture_output=True, text=True,
    )
    frames = sorted(frames_dir.glob("kf_*.jpg"))
    if len(frames) >= 3:
        return frames[:max_frames]

    # ② 降级：均匀采样（适合静态榜单/幻灯片/纯展示视频）
    if log:
        log(f"    场景切换仅 {len(frames)} 帧，改用均匀采样 …")
    for f in frames:
        f.unlink(missing_ok=True)
    dur = duration or _ffprobe_duration(video)
    interval = max(dur / max_frames, 1.0) if dur else 2.0
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video),
         "-vf", f"fps=1/{interval:.3f}",
         "-frames:v", str(max_frames),
         str(frames_dir / "uf_%03d.jpg")],
        capture_output=True, text=True,
    )
    return sorted(frames_dir.glob("uf_*.jpg"))[:max_frames]


def _b64(p: Path) -> str:
    return base64.b64encode(p.read_bytes()).decode()


def describe_frames(frames: list[Path]) -> str:
    """逐帧让 Qwen-VL 提取画面信息，汇总成视觉笔记。"""
    if not frames:
        return ""
    client = OpenAI(api_key=config.DASHSCOPE_API_KEY, base_url=config.DASHSCOPE_BASE_URL)
    notes = []
    for i, f in enumerate(frames, 1):
        resp = client.chat.completions.create(
            model=config.VL_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{_b64(f)}"}},
                    {"type": "text", "text":
                        "简要描述这一帧画面的关键信息：场景、对象、以及画面内出现的所有文字/图表内容。"
                        "若是幻灯片或代码请尽量逐字提取。两三句话即可。"},
                ],
            }],
            temperature=0.2,
        )
        notes.append(f"[帧{i}] {resp.choices[0].message.content.strip()}")
    return "\n".join(notes)
