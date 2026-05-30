from __future__ import annotations

import importlib
import importlib.util
import re
from dataclasses import dataclass
from pathlib import Path

from . import srt_util

LINE_SPLIT_CHARS = "，。！？；、： "
STRONG_SPLIT_PUNCT = "，。！？；："
WEAK_SPLIT_PUNCT = "、 /／"
LEADING_CONNECTIVES = (
    "但是", "不过", "然后", "所以", "而且", "因为", "如果", "虽然", "其实", "就是",
    "还有", "或者", "以及", "并且", "可是", "结果", "于是", "另外", "毕竟",
)
TRAILING_PARTICLES = (
    "的话", "之后", "以前", "时候", "这里", "那里", "这样", "那样", "这个", "那个",
    "所以", "但是", "不过", "然后",
)
CLAUSE_END_CHARS = "了呢吧啊哦呀嘛啦的"
PROTECTED_SPAN_RE = re.compile(
    r"[A-Za-z][A-Za-z0-9&'./+\-]*(?:\s+[A-Za-z][A-Za-z0-9&'./+\-]*)*"
    r"|\d+(?:[.:/年月日号-]\d+)*"
)
BRACKET_PAIRS = {
    "「": "」",
    "『": "』",
    "《": "》",
    "（": "）",
    "(": ")",
    "[": "]",
    "【": "】",
}

SPLIT_BALANCE_WEIGHT = 2.0
SPLIT_LENGTH_BALANCE_WEIGHT = 1.2
SPLIT_CHAR_OVERFLOW_PENALTY = 6
SPLIT_WIDTH_OVERFLOW_PENALTY = 4
SPLIT_STRONG_PUNCT_BONUS = -55
SPLIT_WEAK_PUNCT_BONUS = -18
SPLIT_LEADING_CONNECTIVE_BONUS = -16
SPLIT_TRAILING_PARTICLE_BONUS = -10
SPLIT_CLAUSE_END_BONUS = -6
SPLIT_BEFORE_PUNCT_PENALTY = 30
SPLIT_AWKWARD_LEFT_SUFFIX_PENALTY = 15
SPLIT_AWKWARD_RIGHT_PREFIX_PENALTY = 12
SPLIT_VERY_SHORT_SIDE_PENALTY = 20
SPLIT_SHORT_SIDE_PENALTY = 18
SPLIT_ASCII_SIDE_PENALTY = 55

_SPACY_ZH_NLP = None
_SPACY_ZH_ATTEMPTED = False


@dataclass(frozen=True)
class WrapFinalConfig:
    subtitle: Path
    output: Path | None = None
    max_line_chars: int = 28
    max_line_width: float = 56.0
    sub_split_duration_seconds: float = 5.5
    sub_split_chars: int = 24
    sub_split_min_chars: int = 14
    sub_split_min_side_chars: int = 5
    sub_split_min_duration_seconds: float = 1.2
    no_sub_split: bool = False
    dry_run: bool = False


def protected_split_spans(line: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for match in PROTECTED_SPAN_RE.finditer(line):
        if match.end() - match.start() > 1:
            spans.append((match.start(), match.end()))

    stack: list[tuple[str, int]] = []
    closers = {close: open_ for open_, close in BRACKET_PAIRS.items()}
    for idx, char in enumerate(line):
        if char in BRACKET_PAIRS:
            stack.append((char, idx))
        elif char in closers:
            for stack_idx in range(len(stack) - 1, -1, -1):
                open_char, start = stack[stack_idx]
                if open_char == closers[char]:
                    spans.append((start, idx + 1))
                    del stack[stack_idx:]
                    break
    return spans


def inside_protected_span(index: int, spans: list[tuple[int, int]]) -> bool:
    return any(start < index < end for start, end in spans)


def get_spacy_zh_nlp():
    global _SPACY_ZH_ATTEMPTED, _SPACY_ZH_NLP
    if _SPACY_ZH_ATTEMPTED:
        return _SPACY_ZH_NLP
    _SPACY_ZH_ATTEMPTED = True
    spec = importlib.util.find_spec("spacy")
    if spec is None:
        return None
    try:
        spacy = importlib.import_module("spacy")
        for model_name in ("zh_core_web_md", "zh_core_web_sm"):
            try:
                _SPACY_ZH_NLP = spacy.load(model_name)
                return _SPACY_ZH_NLP
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        return None
    return None


def nlp_split_candidates(line: str) -> set[int]:
    nlp = get_spacy_zh_nlp()
    if nlp is None:
        return set()
    try:
        doc = nlp(line)
    except Exception:  # noqa: BLE001
        return set()

    candidates: set[int] = set()
    preferred_deps = {"advmod", "mark", "cc", "conj", "dep", "punct", "ROOT"}
    for token in doc:
        end = token.idx + len(token.text)
        if 0 < end < len(line):
            candidates.add(end)
        if token.dep_ in preferred_deps and 0 < token.idx < len(line):
            candidates.add(token.idx)
    for sent in getattr(doc, "sents", []):
        end = sent.end_char
        if 0 < end < len(line):
            candidates.add(end)
    return candidates


def readable_split_candidates(line: str) -> list[int]:
    spans = protected_split_spans(line)
    candidates: set[int] = set(nlp_split_candidates(line))
    candidates.update(idx + 1 for idx, char in enumerate(line) if char in LINE_SPLIT_CHARS)

    for connective in LEADING_CONNECTIVES:
        start = 0
        while True:
            idx = line.find(connective, start)
            if idx < 0:
                break
            if idx > 0:
                candidates.add(idx)
            end = idx + len(connective)
            if end < len(line):
                candidates.add(end)
            start = end

    for particle in TRAILING_PARTICLES:
        start = 0
        while True:
            idx = line.find(particle, start)
            if idx < 0:
                break
            end = idx + len(particle)
            if 0 < end < len(line):
                candidates.add(end)
            start = end

    for idx, char in enumerate(line[:-1], start=1):
        if char in CLAUSE_END_CHARS:
            candidates.add(idx)

    return sorted(
        idx for idx in candidates
        if 0 < idx < len(line)
        and not inside_protected_span(idx, spans)
        and line[:idx].strip()
        and line[idx:].strip()
    )


def split_candidate_score(line: str, index: int, max_chars: int, max_width: float) -> float:
    left = line[:index].strip()
    right = line[index:].strip()
    left_width = srt_util.display_width(left)
    right_width = srt_util.display_width(right)
    midpoint = len(line) / 2
    score = abs(index - midpoint) * SPLIT_BALANCE_WEIGHT
    score += abs(len(left) - len(right)) * SPLIT_LENGTH_BALANCE_WEIGHT
    score += max(0, len(left) - max_chars) * SPLIT_CHAR_OVERFLOW_PENALTY
    score += max(0, len(right) - max_chars) * SPLIT_CHAR_OVERFLOW_PENALTY
    score += max(0.0, left_width - max_width) * SPLIT_WIDTH_OVERFLOW_PENALTY
    score += max(0.0, right_width - max_width) * SPLIT_WIDTH_OVERFLOW_PENALTY

    before = line[index - 1]
    after = line[index] if index < len(line) else ""
    if before in STRONG_SPLIT_PUNCT:
        score += SPLIT_STRONG_PUNCT_BONUS
    elif before in WEAK_SPLIT_PUNCT:
        score += SPLIT_WEAK_PUNCT_BONUS
    if any(right.startswith(conn) for conn in LEADING_CONNECTIVES):
        score += SPLIT_LEADING_CONNECTIVE_BONUS
    if any(left.endswith(particle) for particle in TRAILING_PARTICLES):
        score += SPLIT_TRAILING_PARTICLE_BONUS
    if before in CLAUSE_END_CHARS:
        score += SPLIT_CLAUSE_END_BONUS
    if after in "，。！？；、：":
        score += SPLIT_BEFORE_PUNCT_PENALTY
    if left[-1:] in "的地得":
        score += SPLIT_AWKWARD_LEFT_SUFFIX_PENALTY
    if right[:1] in "的地得了着过":
        score += SPLIT_AWKWARD_RIGHT_PREFIX_PENALTY
    if len(left) < 6 or len(right) < 6:
        score += SPLIT_VERY_SHORT_SIDE_PENALTY
    if len(left) < 10 or len(right) < 10:
        score += SPLIT_SHORT_SIDE_PENALTY
    if re.fullmatch(r"[A-Za-z0-9&'./+\-\s]+", left):
        score += SPLIT_ASCII_SIDE_PENALTY
    if re.fullmatch(r"[A-Za-z0-9&'./+\-\s]+", right):
        score += SPLIT_ASCII_SIDE_PENALTY
    return score


def split_readable_line(line: str, max_chars: int, max_width: float) -> list[str]:
    if len(line) <= max_chars and srt_util.display_width(line) <= max_width:
        return [line]
    if not line:
        return [line]
    candidates = readable_split_candidates(line)
    if candidates:
        split_at = min(candidates, key=lambda idx: split_candidate_score(line, idx, max_chars, max_width))
    else:
        spans = protected_split_spans(line)
        midpoint = len(line) // 2
        fallback_candidates = [idx for idx in range(1, len(line)) if not inside_protected_span(idx, spans)]
        split_at = min(fallback_candidates or [midpoint], key=lambda idx: abs(idx - midpoint))
    left = line[:split_at].strip()
    right = line[split_at:].strip()
    if not left or not right:
        return [line]
    return [left, right]


def long_block_split_point(text: str, config: WrapFinalConfig) -> int | None:
    compact = " ".join(text.split())
    if len(compact) < config.sub_split_min_chars:
        return None
    strong_candidates: list[int] = []
    weak_candidates: list[int] = []
    for idx, char in enumerate(compact[:-1], start=1):
        if not config.sub_split_min_side_chars <= idx <= len(compact) - config.sub_split_min_side_chars:
            continue
        if char in STRONG_SPLIT_PUNCT:
            strong_candidates.append(idx)
        elif char in WEAK_SPLIT_PUNCT:
            weak_candidates.append(idx)
    candidates = strong_candidates or weak_candidates
    if not candidates:
        return None
    midpoint = len(compact) / 2
    return min(candidates, key=lambda point: abs(point - midpoint))


def split_long_final_block(number: str, timing: str, text: str, config: WrapFinalConfig) -> list[tuple[str, str, str]]:
    try:
        start, end = srt_util.split_timing(timing)
    except (ValueError, IndexError):
        return [(number, timing, text)]
    duration = end - start
    compact_len = len("".join(text.split()))
    if config.no_sub_split or (
        duration < config.sub_split_duration_seconds
        and compact_len < config.sub_split_chars
    ):
        return [(number, timing, text)]
    split_at = long_block_split_point(text, config)
    if split_at is None:
        return [(number, timing, text)]

    compact = " ".join(text.split())
    split_char = compact[split_at - 1] if split_at > 0 else ""
    left = compact[:split_at].strip()
    right = compact[split_at:].lstrip(STRONG_SPLIT_PUNCT + WEAK_SPLIT_PUNCT).strip()
    if split_char in WEAK_SPLIT_PUNCT:
        left = left.rstrip(WEAK_SPLIT_PUNCT).strip()
    if not left or not right:
        return [(number, timing, text)]

    ratio = len(left) / (len(left) + len(right))
    mid_time = start + duration * max(0.35, min(0.65, ratio))
    if mid_time - start < config.sub_split_min_duration_seconds or end - mid_time < config.sub_split_min_duration_seconds:
        return [(number, timing, text)]
    return [
        (number, srt_util.make_timing(start, mid_time), left),
        (number, srt_util.make_timing(mid_time, end), right),
    ]


def wrap_final_file(config: WrapFinalConfig) -> tuple[int, int, int, int]:
    subtitle = srt_util.require_file(config.subtitle, "Final Chinese SRT")
    review_todo = subtitle.with_name(f"{subtitle.stem}.review.todo.txt")
    if not review_todo.exists():
        print(f"[wrap-final] warning: {review_todo.name} not found; run review-todo before wrap-final so block numbers remain aligned")
    blocks = srt_util.read_srt_blocks(subtitle)
    updated_entries: list[tuple[str, str, list[str]]] = []
    changed = 0
    split_long = 0
    for block in blocks:
        lines = block.splitlines()
        if len(lines) < 3:
            updated_entries.append((str(len(updated_entries) + 1), lines[1] if len(lines) > 1 else "", lines[2:]))
            continue
        number, timing = lines[0], lines[1]
        text = " ".join(line.strip() for line in lines[2:] if line.strip())
        split_entries = split_long_final_block(number, timing, text, config)
        if len(split_entries) > 1:
            split_long += 1
        if len(split_entries) > 1 or text != " ".join(line.strip() for line in lines[2:] if line.strip()):
            changed += 1
        for _orig_number, split_timing_text, split_text in split_entries:
            wrapped = split_readable_line(split_text, config.max_line_chars, config.max_line_width)
            if len(wrapped) > 2:
                wrapped = wrapped[:2]
            if len(split_entries) == 1 and wrapped != lines[2:]:
                changed += 1
            updated_entries.append(("", split_timing_text, wrapped))

    updated = [
        "\n".join([str(idx), timing, *wrapped])
        for idx, (_number, timing, wrapped) in enumerate(updated_entries, start=1)
    ]
    output = config.output if config.output else subtitle
    if changed and not config.dry_run:
        srt_util.write_srt_blocks(output, updated)
    return len(blocks), len(updated), changed, split_long
