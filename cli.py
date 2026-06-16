"""VidLens CLI:  python cli.py <youtube_url> [--vision] [-o out.md]"""
import argparse
import sys
from pathlib import Path

# Windows 控制台默认 GBK，输出含 emoji/中文会崩，强制 UTF-8
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

from vidlens import pipeline


def main():
    ap = argparse.ArgumentParser(description="VidLens — YouTube 视频总结")
    ap.add_argument("url", help="YouTube 视频链接")
    ap.add_argument("--vision", dest="vision", action="store_const", const="on", default="auto",
                    help="强制开启关键帧视觉理解（默认 auto：按文本密度自动决定）")
    ap.add_argument("--no-vision", dest="vision", action="store_const", const="off",
                    help="强制关闭视觉路")
    ap.add_argument("--scene", type=float, default=0.4, help="场景切换阈值(0-1)，越小帧越多")
    ap.add_argument("--max-frames", type=int, default=12, help="最多抽取关键帧数")
    ap.add_argument("-o", "--output", help="总结输出到 markdown 文件")
    ap.add_argument("--save-transcript", action="store_true", help="同时保存完整转录")
    args = ap.parse_args()

    try:
        result = pipeline.run(
            args.url, vision=args.vision,
            scene_threshold=args.scene, max_frames=args.max_frames,
            log=lambda m: print(m, file=sys.stderr),
        )
    except Exception as e:
        print(f"[错误] {e}", file=sys.stderr)
        sys.exit(1)

    md = f"# {result['title']}\n\n> 来源: {result['url']}  |  文本: {result['source']}\n\n{result['summary']}\n"
    if args.save_transcript:
        md += f"\n\n---\n## 完整转录\n\n{result['transcript']}\n"
        if result["visual_notes"]:
            md += f"\n## 视觉笔记\n\n{result['visual_notes']}\n"

    if args.output:
        Path(args.output).write_text(md, encoding="utf-8")
        print(f"已写入: {args.output}", file=sys.stderr)
    else:
        print(md)
    print(f"\n📦 全部产物已打包: {result['zip']}", file=sys.stderr)


if __name__ == "__main__":
    main()
