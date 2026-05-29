from __future__ import annotations

import argparse
import os
import re
import time
from pathlib import Path

import requests


TIME_RE = re.compile(r"^(\d{2}):(\d{2}):(\d{2}),\d{3}\s+-->\s+")
TOPIC_HINTS = (
    "广播名",
    "来信",
    "接下来",
    "继续",
    "环节",
    "HOOOOPE",
    "After Talk",
    "Battle",
    "词语接龙",
    "普通来信",
)


def block_seconds(block: str) -> int:
    lines = block_lines(block)
    if len(lines) < 2:
        return 0
    match = TIME_RE.match(lines[1].strip())
    if not match:
        return 0
    h, m, s = map(int, match.groups())
    return h * 3600 + m * 60 + s


def read_blocks(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8-sig")
    return [block.strip() for block in text.strip().split("\n\n") if block.strip()]


def block_lines(block: str) -> list[str]:
    return block.splitlines()


def block_text(block: str) -> str:
    lines = block_lines(block)
    return " / ".join(lines[2:]).strip()


def block_time_label(block: str) -> str:
    lines = block_lines(block)
    if len(lines) < 2:
        return "00:00左右"
    match = TIME_RE.match(lines[1].strip())
    if not match:
        return "00:00左右"
    h, m, s = map(int, match.groups())
    total_minutes = h * 60 + m
    return f"{total_minutes:02d}:{s:02d}左右"


def topic_indices(blocks: list[str], max_topics: int) -> list[int]:
    max_topics = max(1, max_topics)
    hinted: list[int] = []
    for idx, block in enumerate(blocks):
        text = block_text(block)
        if any(hint in text for hint in TOPIC_HINTS):
            hinted.append(idx)

    if not hinted:
        hinted = list(range(len(blocks)))

    return balanced_indices(hinted, len(blocks), max_topics)


def balanced_indices(candidates: list[int], total_blocks: int, max_items: int) -> list[int]:
    """Pick candidates across the whole subtitle instead of front-loading early hints."""
    if not candidates or max_items <= 0:
        return []
    if len(candidates) <= max_items:
        return sorted(dict.fromkeys(candidates))

    buckets = min(max_items, max(1, total_blocks))
    selected: list[int] = []
    seen: set[int] = set()
    for bucket in range(buckets):
        start = bucket * total_blocks / buckets
        end = (bucket + 1) * total_blocks / buckets
        in_bucket = [idx for idx in candidates if start <= idx < end]
        if not in_bucket:
            continue
        pick = in_bucket[0]
        selected.append(pick)
        seen.add(pick)

    if len(selected) < max_items:
        target_positions = [
            round(i * (len(candidates) - 1) / max(1, max_items - 1))
            for i in range(max_items)
        ]
        for pos in target_positions:
            pick = candidates[pos]
            if pick not in seen:
                selected.append(pick)
                seen.add(pick)
            if len(selected) >= max_items:
                break

    return sorted(selected[:max_items])


def compact_srt_for_note(blocks: list[str], topic_idxs: list[int], max_blocks: int, window: int) -> str:
    max_blocks = max(1, max_blocks)
    window = max(1, window)
    if len(blocks) <= max_blocks:
        return "\n\n".join(blocks)

    selected_indices: set[int] = set()
    anchors = {0, max(0, len(blocks) // 4), max(0, len(blocks) // 2), max(0, len(blocks) * 3 // 4), len(blocks) - 1}
    selected_indices.update(idx for idx in anchors if 0 <= idx < len(blocks))

    half = max(1, window // 2)
    for idx in topic_idxs:
        start = max(0, idx - half)
        end = min(len(blocks), idx + half + 1)
        selected_indices.update(range(start, end))
        if len(selected_indices) >= max_blocks:
            break

    if len(selected_indices) < max_blocks:
        remaining = max_blocks - len(selected_indices)
        step = max(1, len(blocks) // remaining)
        selected_indices.update(range(0, len(blocks), step))

    selected = [blocks[idx] for idx in sorted(selected_indices)[:max_blocks]]
    return "\n\n".join(selected)


def topic_candidates(blocks: list[str], topic_idxs: list[int]) -> str:
    candidates: list[str] = []
    for idx in topic_idxs:
        start = max(0, idx - 1)
        end = min(len(blocks), idx + 4)
        snippet = " / ".join(block_text(b) for b in blocks[start:end] if block_text(b))
        candidates.append(f"- {block_time_label(blocks[idx])}: {snippet}")
    return "\n".join(candidates)


def bundled_reference_paths() -> list[Path]:
    refs = Path(__file__).resolve().parents[1] / "references"
    return [
        refs / "terms-glossary.md",
        refs / "note-style.md",
        refs / "deepseek-prompts.md",
        refs / "review-policy.md",
    ]


def load_glossary(paths: list[Path]) -> str:
    parts: list[str] = []
    all_paths = [*bundled_reference_paths(), *paths]
    seen: set[Path] = set()
    for path in all_paths:
        path = path.resolve()
        if path in seen:
            continue
        seen.add(path)
        if path.exists():
            parts.append(path.read_text(encoding="utf-8-sig").strip())
    return "\n\n".join(part for part in parts if part)


def write_note(args: argparse.Namespace) -> None:
    if not args.api_key:
        raise SystemExit("Missing API key. Set DEEPSEEK_API_KEY or pass --api-key.")

    subtitle = Path(args.subtitle)
    out = Path(args.output)
    blocks = read_blocks(subtitle)
    glossary = load_glossary([Path(p) for p in args.glossary])
    topic_idxs = topic_indices(blocks, args.max_topics)
    candidates = topic_candidates(blocks, topic_idxs)
    srt_context = compact_srt_for_note(blocks, topic_idxs, args.max_blocks, args.topic_window)

    prompt = f"""请根据最终中文字幕 SRT，生成一份面向观众的小羊 HOOOOPE 笔记。

要求：
1. 按“小羊 HOOOOPE 笔记”风格写，不要写成正式“本期要点”列表。
2. 按节目来信和话题分段，用『话题标题』作为小标题。
3. 每段加入大致时间，例如 01:27左右，时间来自话题开始处字幕。
4. 简要说明来信讲了什么、羊宫妃那怎么回应、有趣点在哪里。
5. 覆盖全片内容，不要把后半段合并成“后半场/集锦”一笔带过；前中后段应有大致均衡的篇幅。
6. 如果节目包含多个环节（如 Battle、Step Up、After Talk、通知、来信主题），每个主要环节都应单独成段或明确并入相邻段。
7. 可以参考“候选话题时间点”，但要根据 SRT 内容自行合并相近话题。
8. 初稿可以略宽一些，但文风必须是观看笔记：具体、方便回看，少用“太可爱了”“神企划”“超级好笑”等泛泛夸赞。
9. 正片约 50-60 分钟时通常写 10-14 个候选话题段；短会员视频按实际内容写 4-7 个候选话题段。Codex 后续会压缩成最终 episode note。
10. 避免只详写前 20 分钟；任何连续 15 分钟以上的节目内容都不应完全缺席。
11. 结尾可保留 #羊宫妃那。
12. 输出纯文本，不要 Markdown 代码块。

项目术语表：
{glossary or "(none)"}

候选话题时间点：
{candidates}

最终中文字幕 SRT（压缩上下文，保留全片时间线分布）：
{srt_context}
"""
    payload = {
        "model": args.model,
        "messages": [
            {"role": "system", "content": "你是熟悉声优广播节目内容整理的中文笔记编辑。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": args.temperature,
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {args.api_key}", "Content-Type": "application/json"}
    url = args.base_url.rstrip("/") + "/chat/completions"
    last_error = None
    for attempt in range(1, args.retries + 1):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=args.timeout)
            response.raise_for_status()
            text = response.json()["choices"][0]["message"]["content"].strip()
            break
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            wait = min(args.retry_wait * attempt, 30)
            print(f"note generation attempt {attempt} failed: {exc}")
            if attempt < args.retries:
                time.sleep(wait)
    else:
        raise RuntimeError(f"note generation failed after {args.retries} attempts: {last_error}")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n", encoding="utf-8-sig")
    print(f"Wrote {out.resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate HOOOOPE note-style summary from final Chinese SRT via DeepSeek.")
    parser.add_argument("subtitle")
    parser.add_argument("--output", required=True)
    parser.add_argument("--api-key", default=os.environ.get("DEEPSEEK_API_KEY"))
    parser.add_argument("--base-url", default=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    parser.add_argument("--model", default=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro"))
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-wait", type=int, default=3)
    parser.add_argument("--max-blocks", type=int, default=260)
    parser.add_argument("--max-topics", type=int, default=24)
    parser.add_argument("--topic-window", type=int, default=10)
    parser.add_argument(
        "--glossary",
        action="append",
        default=["hoooope_terms.txt", "model/hoooope_terms.txt", "hooope_terms.txt", "model/hooope_terms.txt"],
    )
    args = parser.parse_args()
    write_note(args)


if __name__ == "__main__":
    main()
