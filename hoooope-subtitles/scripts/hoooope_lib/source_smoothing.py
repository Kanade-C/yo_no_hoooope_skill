from __future__ import annotations

import argparse
import re
from pathlib import Path

from . import srt_util as srt_util_lib
from .srt_util import iter_srt_entries, write_srt_blocks

SOURCE_TAIL_NOUN_RE = re.compile(
    r"(?:生放送)?(?:番組|コーナー|企画|作品|楽曲|曲|テーマ|お題|お知らせ|"
    r"メール|お便り|投稿|イラスト|名前|ニックネーム|時間)(?:です|でした)?$"
)
SOURCE_ATTRIBUTIVE_END_RE = re.compile(
    r"(?:の|な|た|する|していく|届けていく|お届けしていく|となるよう|になるよう|"
    r"という|みたいな|ような)$"
)

JA_TERMINAL_ENDINGS = (
    "。", "！", "？", "?", "!",
    "です", "ます", "でした", "ました",
    "ください", "くださいね", "と思います",
)
JA_CONTINUATION_ENDINGS = (
    "、", "，", "と", "て", "で", "に", "を", "が", "は", "も", "の",
    "今、", "ので", "ので、", "んで", "けど", "けれど", "けれども",
)
JA_CLAUSE_PATTERNS = (
    "ですね には", "ですが", "ので", "けれども", "ですけれども", "ということで",
)


def is_terminal_source_text(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped) and stripped.endswith(JA_TERMINAL_ENDINGS)


def is_continuation_source_text(text: str) -> bool:
    stripped = text.strip()
    return not stripped or stripped.endswith(JA_CONTINUATION_ENDINGS)


def source_needs_more_context(text: str, duration: float, args: argparse.Namespace) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if is_terminal_source_text(stripped):
        return False
    if is_continuation_source_text(stripped):
        return True
    if len(stripped) < args.min_semantic_chars:
        return True
    if duration < args.min_semantic_duration_seconds and len(stripped) < args.comfort_semantic_chars:
        return True
    return False


def is_source_tail_noun_fragment(text: str, args: argparse.Namespace) -> bool:
    stripped = re.sub(r"\s+", "", text.strip())
    if not stripped or len(stripped) > args.tail_fragment_chars:
        return False
    return bool(SOURCE_TAIL_NOUN_RE.search(stripped))


def should_merge_tail_noun_fragment(current: str, nxt: str, args: argparse.Namespace) -> bool:
    if not is_source_tail_noun_fragment(nxt, args):
        return False
    current_stripped = re.sub(r"\s+", "", current.strip())
    if not current_stripped:
        return True
    if current_stripped.endswith(JA_CONTINUATION_ENDINGS):
        return True
    return bool(SOURCE_ATTRIBUTIVE_END_RE.search(current_stripped))


def source_has_pending_attributive_tail(text: str) -> bool:
    stripped = re.sub(r"\s+", "", text.strip())
    return bool(stripped and SOURCE_ATTRIBUTIVE_END_RE.search(stripped))


def complete_pending_source_chains(entries: list[dict[str, float | str]], args: argparse.Namespace) -> list[dict[str, float | str]]:
    completed: list[dict[str, float | str]] = []
    idx = 0
    while idx < len(entries):
        current = dict(entries[idx])
        if idx + 1 < len(entries):
            nxt = entries[idx + 1]
            gap = float(nxt["start"]) - float(current["end"])
            combined_len = len(str(current["text"])) + len(str(nxt["text"]))
            combined_duration = float(nxt["end"]) - float(current["start"])
            if (
                gap <= args.tail_chain_merge_gap_seconds
                and combined_len <= args.tail_chain_max_chars
                and combined_duration <= args.tail_chain_max_duration_seconds
                and (
                    source_needs_more_context(
                        str(current["text"]),
                        float(current["end"]) - float(current["start"]),
                        args,
                    )
                    or source_has_pending_attributive_tail(str(current["text"]))
                )
                and is_terminal_source_text(str(nxt["text"]))
            ):
                current["end"] = nxt["end"]
                current["text"] = (str(current["text"]) + " " + str(nxt["text"])).strip()
                idx += 1
        completed.append(current)
        idx += 1
    return completed


def source_split_points(text: str) -> list[int]:
    points: list[int] = []
    for pattern in JA_CLAUSE_PATTERNS:
        idx = text.find(pattern)
        if idx > 0:
            if pattern == "ですね には":
                points.append(idx + len("ですね"))
            else:
                points.append(idx + len(pattern))
    for idx, char in enumerate(text[:-1], start=1):
        if char in "、。！？?!" and idx > 8:
            points.append(idx)
    return sorted(set(idx for idx in points if 6 <= idx <= len(text) - 6))


def smooth_source_srt(args: argparse.Namespace) -> None:
    path = Path(args.subtitle)
    entries = []
    for number, timing, text_lines in iter_srt_entries(path):
        start, end = srt_util_lib.split_timing(timing)
        entries.append({"start": start, "end": end, "text": " ".join(text_lines).strip()})

    merged = []
    idx = 0
    while idx < len(entries):
        current = dict(entries[idx])
        while idx + 1 < len(entries):
            nxt = entries[idx + 1]
            gap = nxt["start"] - current["end"]
            combined_len = len(current["text"]) + len(nxt["text"])
            combined_duration = nxt["end"] - current["start"]
            orphan_fragment = len(current["text"].strip()) <= args.orphan_fragment_chars and not is_terminal_source_text(current["text"])
            tail_fragment = should_merge_tail_noun_fragment(current["text"], nxt["text"], args)
            allowed_gap = (
                args.tail_merge_gap_seconds
                if tail_fragment
                else args.orphan_merge_gap_seconds
                if orphan_fragment
                else args.merge_gap_seconds
            )
            allowed_duration = (
                args.tail_max_merged_duration_seconds
                if tail_fragment
                else args.orphan_max_merged_duration_seconds
                if orphan_fragment
                else args.max_merged_duration_seconds
            )
            if (
                gap <= allowed_gap
                and combined_len <= args.max_merged_chars
                and combined_duration <= allowed_duration
                and (
                    tail_fragment
                    or source_needs_more_context(
                        current["text"],
                        current["end"] - current["start"],
                        args,
                    )
                )
            ):
                current["end"] = nxt["end"]
                current["text"] = (current["text"] + " " + nxt["text"]).strip()
                idx += 1
                continue
            break
        merged.append(current)
        idx += 1

    merged = complete_pending_source_chains(merged, args)

    smoothed = []
    for entry in merged:
        duration = entry["end"] - entry["start"]
        text = entry["text"]
        points = source_split_points(text)
        if duration >= args.split_duration_seconds and len(text) >= args.split_chars and points:
            midpoint = len(text) / 2
            split_at = min(points, key=lambda point: abs(point - midpoint))
            left = text[:split_at].strip(" 、")
            right = text[split_at:].strip(" 、")
            left = re.sub(r"\s*には$", "", left)
            right = re.sub(r"^には\s*", "", right)
            if left and right:
                ratio = max(0.25, min(0.75, len(left) / (len(left) + len(right))))
                mid_time = entry["start"] + duration * ratio
                smoothed.append({"start": entry["start"], "end": mid_time, "text": left})
                smoothed.append({"start": mid_time, "end": entry["end"], "text": right})
                continue
        smoothed.append(entry)

    blocks = []
    for number, entry in enumerate(smoothed, start=1):
        blocks.append("\n".join([str(number), srt_util_lib.make_timing(entry["start"], entry["end"]), entry["text"]]))

    output = Path(args.output) if args.output else path
    write_srt_blocks(output, blocks)
    print(f"smooth-source blocks={len(entries)} -> {len(smoothed)} output={output.resolve()}")
