"""融合 + 总结：转录文本(+视觉笔记) → Qwen。长文本走 map-reduce。"""
import textwrap

from openai import OpenAI

from . import config


def _client():
    return OpenAI(api_key=config.DASHSCOPE_API_KEY, base_url=config.DASHSCOPE_BASE_URL)


def _chat(client, prompt: str, system: str = "你是专业的视频内容分析助手，输出准确、结构化的中文。") -> str:
    resp = client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": prompt}],
        temperature=0.3,
    )
    return resp.choices[0].message.content.strip()


def _chunks(text: str, size: int):
    return textwrap.wrap(text, size, break_long_words=False, replace_whitespace=False)


def summarize(transcript: str, meta: dict, visual_notes: str = "",
              instruction: str | None = None) -> str:
    """instruction 为可自定义的输出要求；为空则用 config 默认。"""
    client = _client()
    instruction = (instruction or "").strip() or config.load_summary_prompt()
    title = meta.get("title", "")
    header = f"视频标题：{title}\n"
    if meta.get("duration"):
        header += f"时长：{meta['duration'] // 60} 分钟\n"

    # 长转录：先分段提炼要点，再汇总（map-reduce）
    if len(transcript) > config.CHUNK_CHARS:
        partials = []
        for i, ch in enumerate(_chunks(transcript, config.CHUNK_CHARS), 1):
            partials.append(_chat(client,
                f"以下是视频转录的第 {i} 段，提炼这一段的关键要点（条目式，保留事实/数据/结论）：\n\n{ch}"))
        transcript_block = "\n\n".join(partials)
        source_label = "分段要点"
    else:
        transcript_block = transcript
        source_label = "完整转录"

    visual_block = f"\n\n【画面视觉笔记】\n{visual_notes}" if visual_notes else ""

    # 内容在前、可编辑的指令在后
    prompt = f"""{header}
【{source_label}】
{transcript_block}{visual_block}

---
{instruction}"""
    return _chat(client, prompt)
