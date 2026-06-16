"""VTT 字幕解析与清洗：去时间轴、去重复行、合并成纯文本。"""
import re
from pathlib import Path

_TS = re.compile(r"\d{2}:\d{2}:\d{2}\.\d{3}\s*-->")
_TAG = re.compile(r"<[^>]+>")  # 去掉 <c> 等内联标签


def parse_vtt(path: Path) -> str:
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    out, prev = [], None
    for ln in lines:
        ln = ln.strip()
        if not ln or ln == "WEBVTT" or _TS.search(ln) or ln.isdigit():
            continue
        if ln.startswith(("Kind:", "Language:", "NOTE")):
            continue
        ln = _TAG.sub("", ln).strip()
        if ln and ln != prev:  # YouTube 自动字幕大量重复，去相邻重复
            out.append(ln)
            prev = ln
    return " ".join(out)
