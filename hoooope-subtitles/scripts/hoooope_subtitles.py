from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

from hooope_lib import asr_audio as asr_audio_lib
from hooope_lib import audit_rules as audit_rules_lib
from hooope_lib import baseline as baseline_lib
from hooope_lib import pipeline_state as pipeline_state_lib
from hooope_lib import srt_io as srt_io_lib
from hooope_lib.audit_rules import ASR_HOMOPHONE_CONTEXT_RULES, ASR_PROMPT_SEED_TERMS


MEDIA_EXTS = {".ts", ".mp4", ".mkv", ".mov", ".webm", ".m4a", ".mp3", ".wav", ".flac"}
DEFAULT_TRANSCRIBE_MODEL_DIR = "model/large_v3_turbo"
DEFAULT_QWEN_ASR_MODEL_DIR = "model/qwen-3-asr-1.7b"
DEFAULT_STABLE_REGROUP = "clues"
PIPELINE_TRANSLATION_MODEL = "deepseek-v4-pro"
PIPELINE_TRANSLATE_CHUNK_SIZE = 100
PIPELINE_TRANSLATE_WORKERS = 2
PIPELINE_TRANSLATE_CONTEXT_BLOCKS = 20
PIPELINE_POLISH_CHUNK_SIZE = 50
PIPELINE_POLISH_WORKERS = 2
PIPELINE_DEEPSEEK_QA_SAMPLE_RATIO = 0.28
PIPELINE_MIN_SUMMARY_CHARS = 1500
PIPELINE_MAX_SUMMARY_CHARS = 3000
PIPELINE_DEFAULT_VAD_ONNX = "model/silero_vad.onnx"
JA_RE = re.compile(r"[\u3040-\u30ff]")
HOOPE_RE = re.compile(r"\bHO+PE\b", re.IGNORECASE)
BAD_HOST_TERMS = ("阳宫", "雏乃", "陽宮", "ひなの")
BAD_FIXED_TERMS: dict[str, str] = {
    "AGVIOT": "AVIOT",
    "ＡＶＩＯＴ": "AVIOT",
    "生驹ゆりえ": "伊驹百合绘",
    "生驹百合绘": "伊驹百合绘",
    "伊驹小百合": "伊驹百合绘",
    "水野サク": "水野咲",
    "水野佐久": "水野咲",
    "村上真夏酱": "村上真夏",
    "HOOOPE": "HOOOOPE",
    "HOOOOOP": "HOOOOPE",
    "Sheepッチ": "咩咩吉 or Sheeputchi, depending on context",
    "シープッチ": "咩咩吉 or Sheeputchi, depending on context",
    "赞助播出村上真夏": "Supported by 村上真夏",
    "由村上真夏赞助": "Supported by 村上真夏",
}
SUSPICIOUS_TERMS: tuple[str, ...] = (
    "AGVIOT",
    "ＡＶＩＯＴ",
    "陽宮",
    "ひなの",
    "生驹",
    "水野サク",
    "水野さく",
    "Open",
    "OPEN",
    "サポーテッドバイ",
    "シープッチ",
    "Sheepッチ",
)
ASCII_PUNCT_RE = re.compile(r"[,!?:;]")
KATAKANA_TERM_RE = re.compile(r"[\u30a1-\u30ffー]{3,}")
LATIN_TERM_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9&'./+-]{2,}\b")
TITLE_LIKE_RE = re.compile(r"[「『《](.*?)[」』》]")
KANA_NICKNAME_RE = re.compile(r"[\u3041-\u309f\u30a1-\u30ffー]{2,}")
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
_SPACY_ZH_NLP = None
_SPACY_ZH_ATTEMPTED = False
# Split scoring keeps long spoken subtitles readable without changing meaning:
# balance weights prefer visually even halves, overflow penalties avoid lines
# beyond release limits, punctuation/phrase bonuses favor natural clause breaks,
# and side penalties reject tiny, Latin-heavy, or grammatically awkward halves.
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
ASR_SUSPICIOUS_OPEN_RE = re.compile(r"(Open|OPEN|オープン|おーぷん)")
SRT_TIMING_RE = re.compile(r"^\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}$")
IGNORED_WORKBENCH_DIRS = {
    "deepseek_chunks",
    "deepseek_polish_chunks",
    "screenshot_check",
}
FINAL_SRT_EXCLUDED_SUFFIXES = (
    ".orig.raw.srt",
    ".orig.srt",
    ".deepseek.raw.srt",
    ".deepseek.polished.srt",
)
TEXT_PUNCT_TRANSLATION = str.maketrans({
    ",": "，",
    "!": "！",
    "?": "？",
    ":": "：",
    ";": "；",
})
HOOOOPE_OPENING_MISHEAR_RE = re.compile(
    r"(?:エ\s*クステンド|ネクスト|ステップ|STEP|Step).*"
    r"(?:陽宮|羊宮|ようみや|ヨ[ーォ]?ミヤ|小宮|神谷).*"
    r"(?:オープン|おーぷん|ポープ|ホップ|Open|OPEN|新)"
)
HOOOOPE_TITLE_MISHEAR_RE = re.compile(
    r"(?:陽宮|羊宮|ようみや|ヨ[ーォ]?ミヤ|小宮|神谷).{0,8}"
    r"(?:ポープ|ホップ|Open|OPEN|オープン|おーぷん)"
)
HOOOOPE_ACCOUNT_MISHEAR_RE = re.compile(
    r"(?:番組公式|公式).{0,12}(?:x|X|エックス).{0,12}"
    r"(?:アカウント).{0,16}(?:bx\s*ホープ|ex\s*hope|exhope|ホープ)"
)
AIUEO_COMPOSITION_MISHEAR_RE = re.compile(
    r"(?:み[、,\s]*ず[、,\s]*の|水野).{0,12}"
    r"(?:相植え|藍植え|愛植え|あいうえ|アイウエ|作文)"
)
SOURCE_TAIL_NOUN_RE = re.compile(
    r"(?:生放送)?(?:番組|コーナー|企画|作品|楽曲|曲|テーマ|お題|お知らせ|"
    r"メール|お便り|投稿|イラスト|名前|ニックネーム|時間)(?:です|でした)?$"
)
SOURCE_ATTRIBUTIVE_END_RE = re.compile(
    r"(?:の|な|た|する|していく|届けていく|お届けしていく|となるよう|になるよう|"
    r"という|みたいな|ような)$"
)
ROMAJI_BASE = {
    "あ": "a", "い": "i", "う": "u", "え": "e", "お": "o",
    "か": "ka", "き": "ki", "く": "ku", "け": "ke", "こ": "ko",
    "さ": "sa", "し": "shi", "す": "su", "せ": "se", "そ": "so",
    "た": "ta", "ち": "chi", "つ": "tsu", "て": "te", "と": "to",
    "な": "na", "に": "ni", "ぬ": "nu", "ね": "ne", "の": "no",
    "は": "ha", "ひ": "hi", "ふ": "fu", "へ": "he", "ほ": "ho",
    "ま": "ma", "み": "mi", "む": "mu", "め": "me", "も": "mo",
    "や": "ya", "ゆ": "yu", "よ": "yo",
    "ら": "ra", "り": "ri", "る": "ru", "れ": "re", "ろ": "ro",
    "わ": "wa", "を": "o", "ん": "n",
    "が": "ga", "ぎ": "gi", "ぐ": "gu", "げ": "ge", "ご": "go",
    "ざ": "za", "じ": "ji", "ず": "zu", "ぜ": "ze", "ぞ": "zo",
    "だ": "da", "ぢ": "ji", "づ": "zu", "で": "de", "ど": "do",
    "ば": "ba", "び": "bi", "ぶ": "bu", "べ": "be", "ぼ": "bo",
    "ぱ": "pa", "ぴ": "pi", "ぷ": "pu", "ぺ": "pe", "ぽ": "po",
    "ぁ": "a", "ぃ": "i", "ぅ": "u", "ぇ": "e", "ぉ": "o",
}
ROMAJI_DIGRAPHS = {
    "きゃ": "kya", "きゅ": "kyu", "きょ": "kyo",
    "しゃ": "sha", "しゅ": "shu", "しょ": "sho",
    "ちゃ": "cha", "ちゅ": "chu", "ちょ": "cho",
    "にゃ": "nya", "にゅ": "nyu", "にょ": "nyo",
    "ひゃ": "hya", "ひゅ": "hyu", "ひょ": "hyo",
    "みゃ": "mya", "みゅ": "myu", "みょ": "myo",
    "りゃ": "rya", "りゅ": "ryu", "りょ": "ryo",
    "ぎゃ": "gya", "ぎゅ": "gyu", "ぎょ": "gyo",
    "じゃ": "ja", "じゅ": "ju", "じょ": "jo",
    "びゃ": "bya", "びゅ": "byu", "びょ": "byo",
    "ぴゃ": "pya", "ぴゅ": "pyu", "ぴょ": "pyo",
}


def fmt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_srt_time(value: str) -> float:
    match = re.fullmatch(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})", value.strip())
    if not match:
        raise ValueError(value)
    h, m, s, ms = (int(part) for part in match.groups())
    return h * 3600 + m * 60 + s + ms / 1000


def display_width(text: str) -> float:
    width = 0.0
    for char in text:
        if unicodedata.combining(char):
            continue
        if char in "\t\r\n":
            continue
        east_asian_width = unicodedata.east_asian_width(char)
        if east_asian_width in {"F", "W"}:
            width += 2.0
        elif east_asian_width == "A":
            width += 1.5
        else:
            width += 1.0
    return width


def iter_srt_entries(path: Path) -> list[tuple[str, str, list[str]]]:
    entries: list[tuple[str, str, list[str]]] = []
    for block in read_srt_blocks(path):
        lines = block.splitlines()
        if len(lines) < 3:
            continue
        number = lines[0].strip()
        timing = lines[1].strip()
        text_lines = [line.strip() for line in lines[2:] if line.strip()]
        entries.append((number, timing, text_lines))
    return entries


def find_term_issues(text: str, rules: dict[str, object] | None = None) -> list[str]:
    issues: list[str] = []
    fixed_terms = rules.get("bad_fixed_terms", BAD_FIXED_TERMS) if rules else BAD_FIXED_TERMS
    for bad_term, suggestion in dict(fixed_terms).items():
        if bad_term in text:
            issues.append(f"{bad_term} -> {suggestion}")
    return issues


def text_payload(text_lines: list[str]) -> str:
    return "\n".join(text_lines)


def compact_text(text: str, limit: int = 80) -> str:
    text = " ".join(text.replace("\n", " / ").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "..."


def chinese_char_count(text: str) -> int:
    return sum(1 for char in text if "\u4e00" <= char <= "\u9fff")


def katakana_to_hiragana(text: str) -> str:
    chars: list[str] = []
    for char in text:
        code = ord(char)
        if 0x30A1 <= code <= 0x30F6:
            chars.append(chr(code - 0x60))
        else:
            chars.append(char)
    return "".join(chars)


def romanize_kana(text: str) -> str:
    text = katakana_to_hiragana(text.strip())
    result: list[str] = []
    geminate = False
    idx = 0
    while idx < len(text):
        char = text[idx]
        if char == "っ":
            geminate = True
            idx += 1
            continue
        if char == "ー":
            if result:
                last = result[-1][-1:]
                if last in "aeiou":
                    result[-1] += last
            idx += 1
            continue
        pair = text[idx : idx + 2]
        if pair in ROMAJI_DIGRAPHS:
            piece = ROMAJI_DIGRAPHS[pair]
            idx += 2
        else:
            piece = ROMAJI_BASE.get(char, "")
            idx += 1
        if not piece:
            continue
        if geminate and piece[0] not in "aeiou":
            piece = piece[0] + piece
        geminate = False
        result.append(piece)
    romanized = "".join(result)
    return romanized[:1].upper() + romanized[1:] if romanized else ""


def skill_reference_paths() -> list[Path]:
    refs = Path(__file__).resolve().parents[1] / "references"
    return [
        refs / "terms-glossary.md",
        refs / "review-policy.md",
    ]


def extract_prompt_terms(text: str, limit: int = 80) -> list[str]:
    terms: list[str] = []
    for pattern in (
        r"HOOOOPE(?: [A-Za-z][A-Za-z ]+)?",
        r"AVIOT",
        r"Extend Step HOOOOPE",
        r"After Talk",
        r"Sheeputchi",
        r"[\u4e00-\u9fff]{2,8}",
        r"[\u30a1-\u30ffー]{3,}",
    ):
        for match in re.finditer(pattern, text):
            term = match.group(0).strip()
            if 2 <= len(term) <= 24 and term not in terms:
                terms.append(term)
            if len(terms) >= limit:
                return terms
    return terms


def build_initial_prompt(args: argparse.Namespace) -> str | None:
    if args.no_initial_prompt:
        return None

    buckets: dict[str, list[str]] = {"glossary": [], "core": [], "cli": []}
    seen: dict[str, str] = {}
    rules = audit_rules_lib.load_audit_rules(args, bad_fixed_terms=BAD_FIXED_TERMS, suspicious_terms=SUSPICIOUS_TERMS)
    source_counts: dict[str, int] = {}

    def add_term(term: str, source: str, bucket: str) -> None:
        term = term.strip()
        if not term:
            return
        previous_bucket = seen.get(term)
        if previous_bucket:
            if previous_bucket != bucket:
                buckets[previous_bucket] = [item for item in buckets[previous_bucket] if item != term]
                buckets[bucket].append(term)
                seen[term] = bucket
            return
        buckets[bucket].append(term)
        seen[term] = bucket
        source_counts[source] = source_counts.get(source, 0) + 1

    for term in rules.get("asr_seed_terms", ASR_PROMPT_SEED_TERMS):
        add_term(str(term), "rules", "core")

    for raw_path in args.initial_prompt_file or []:
        path = Path(raw_path)
        if path.exists():
            for term in extract_prompt_terms(path.read_text(encoding="utf-8-sig"), limit=80):
                add_term(term, "initial_prompt_file", "glossary")

    for raw_path in args.glossary or []:
        path = Path(raw_path)
        if path.exists():
            for term in extract_prompt_terms(path.read_text(encoding="utf-8-sig"), limit=80):
                add_term(term, "glossary", "glossary")

    for reference in skill_reference_paths():
        if reference.exists():
            for term in extract_prompt_terms(reference.read_text(encoding="utf-8-sig"), limit=80):
                add_term(term, "reference", "glossary")

    if args.initial_prompt:
        for term in re.split(r"[,\n、，;；]+", args.initial_prompt):
            add_term(term, "cli", "cli")

    term_limit = max(1, args.initial_prompt_terms)
    priority_terms = buckets["core"] + buckets["cli"]
    priority_tail = priority_terms[-term_limit:]
    normal_budget = max(0, term_limit - len(priority_tail))
    ordered_terms = buckets["glossary"][:normal_budget] + priority_tail
    char_budget = min(max(360, term_limit * 18), 1600)
    while ordered_terms and len("、".join(ordered_terms)) > char_budget:
        if len(ordered_terms) <= len(priority_tail):
            break
        ordered_terms.pop(0)
    while ordered_terms and len("、".join(ordered_terms)) > char_budget and len(ordered_terms) > 1:
        ordered_terms.pop(0)

    prompt = "、".join(ordered_terms)
    if prompt and getattr(args, "verbose_prompt_sources", False):
        loaded_paths = rules.get("_paths", [])
        tail_terms = ordered_terms[-20:]
        bucket_counts = {name: len(items) for name, items in buckets.items()}
        print(
            f"ASR initial_prompt source_counts={source_counts} bucket_counts={bucket_counts} "
            f"chars={len(prompt)} audit_rules={loaded_paths}"
        )
        print(f"ASR initial_prompt tail_terms={tail_terms}")
    return prompt or None


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
    left_width = display_width(left)
    right_width = display_width(right)
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
    if len(line) <= max_chars and display_width(line) <= max_width:
        return [line]
    if not line:
        return [line]
    candidates = readable_split_candidates(line)
    if candidates:
        split_at = min(candidates, key=lambda idx: split_candidate_score(line, idx, max_chars, max_width))
    else:
        spans = protected_split_spans(line)
        midpoint = len(line) // 2
        fallback_candidates = [
            idx for idx in range(1, len(line))
            if not inside_protected_span(idx, spans)
        ]
        split_at = min(fallback_candidates or [midpoint], key=lambda idx: abs(idx - midpoint))
    left = line[:split_at].strip()
    right = line[split_at:].strip()
    if not left or not right:
        return [line]
    return [left, right]


def risk_reasons(number: str, timing: str, text: str, args: argparse.Namespace | None = None) -> list[str]:
    reasons: list[str] = []
    if JA_RE.search(text):
        reasons.append("日文残留")
    if find_term_issues(text):
        reasons.append("固定译名")
    if any(term in text for term in SUSPICIOUS_TERMS):
        reasons.append("可疑专名")
    if any(token != "HOOOOPE" for token in HOOPE_RE.findall(text)):
        reasons.append("节目名")
    if any(display_width(line) > 56 for line in text.splitlines()):
        reasons.append("显示宽度")
    if any(len(line) > 28 for line in text.splitlines()):
        reasons.append("长行")
    try:
        start_raw, end_raw = [part.strip() for part in timing.split("-->", 1)]
        duration = parse_srt_time(end_raw) - parse_srt_time(start_raw)
        if duration > 30:
            reasons.append(f"超长时间轴{duration:.1f}s")
    except (ValueError, IndexError):
        reasons.append("时间轴异常")
    tone_markers = ("我觉得", "可能", "或许", "谢谢", "抱歉", "不好意思", "开心", "高兴", "喜欢", "怎么办", "真的", "感觉")
    if any(marker in text for marker in tone_markers):
        reasons.append("语气抽查")
    if re.search(r"[？！…]|哈哈|诶|哎|咦|啊", text):
        reasons.append("反应/笑点")
    if args is not None and args.include_all_long and len(text) >= args.long_text_chars:
        reasons.append("长句信息量")
    return reasons


def require_file(path: Path, label: str) -> Path:
    path = path.resolve()
    if not path.exists():
        raise SystemExit(f"{label} not found: {path}")
    return path


def validate_model(model_dir: Path) -> Path:
    model_dir = model_dir.resolve()
    required = ["config.json", "tokenizer.json"]
    missing = [name for name in required if not (model_dir / name).exists()]
    if not (model_dir / "model.bin").exists() and not any(model_dir.glob("model*.safetensors")):
        missing.append("model.bin or model*.safetensors")
    if (model_dir / "model.bin").exists() and not (model_dir / "vocabulary.json").exists() and not (model_dir / "vocabulary.txt").exists():
        missing.append("vocabulary.json or vocabulary.txt")
    if missing:
        raise SystemExit(f"Model folder is missing: {', '.join(missing)} in {model_dir}")
    return model_dir


def stable_whisper_backend(model_dir: Path) -> str:
    return "faster" if (model_dir / "model.bin").exists() else "hf"


def compute_type_for_device(device: str | None, requested: str | None) -> str:
    if requested:
        return requested
    if device == "cpu":
        return "int8"
    return "float16"


def resolve_silero_vad_path(raw_path: str | None, model_dir: Path) -> Path:
    candidates: list[Path] = []
    if raw_path:
        candidates.append(Path(raw_path))
    candidates.extend(
        [
            Path("model") / "silero_vad.onnx",
            model_dir / "silero_vad.onnx",
        ]
    )
    for candidate in candidates:
        path = candidate.resolve()
        if path.exists():
            return path
    raise RuntimeError(
        "Silero VAD ONNX model not found. Expected one of: "
        + ", ".join(str(path) for path in candidates)
    )


def write_stable_result_srt(result, out: Path) -> None:
    try:
        result.to_srt_vtt(str(out), segment_level=True, word_level=False)
    except TypeError:
        result.to_srt_vtt(str(out))


class LocalSileroOnnxModel:
    def __init__(self, onnx_path: Path):
        import numpy as np
        import onnxruntime as ort

        self._np = np
        self.session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
        self.reset_states()

    def reset_states(self) -> None:
        self.state = self._np.zeros((2, 1, 128), dtype=self._np.float32)

    def __call__(self, chunk, sampling_rate: int):
        import torch

        if hasattr(chunk, "detach"):
            audio = chunk.detach().cpu().numpy()
        else:
            audio = self._np.asarray(chunk)
        audio = audio.astype(self._np.float32, copy=False).reshape(1, -1)
        result = self.session.run(
            None,
            {
                "input": audio,
                "state": self.state,
                "sr": self._np.array(sampling_rate, dtype=self._np.int64),
            },
        )
        self.state = result[1]
        return torch.tensor(result[0][0, 0], dtype=torch.float32)


def patch_stable_whisper_local_vad(stable_whisper, vad_onnx: Path) -> None:
    from stable_whisper import stabilization
    from stable_whisper.stabilization import silero_vad

    def load_local_silero_vad_model(*_args, **_kwargs):
        return LocalSileroOnnxModel(vad_onnx), None

    silero_vad.load_silero_vad_model = load_local_silero_vad_model
    stabilization.load_silero_vad_model = load_local_silero_vad_model


def stable_regroup_value(value: str):
    if value.lower() == "clues":
        return True
    if value.lower() in {"false", "none", "off"}:
        return False
    if value.lower() in {"true", "default"}:
        return True
    return value


def transcribe_stable(args: argparse.Namespace, src: Path, out: Path, model_dir: Path, initial_prompt: str | None) -> None:
    stable_spec = importlib.util.find_spec("stable_whisper")
    if stable_spec is None:
        raise RuntimeError("stable_whisper is not installed. Install the stable-ts package before transcription.")
    stable_whisper = importlib.import_module("stable_whisper")

    vad_onnx = resolve_silero_vad_path(args.vad_onnx, model_dir)
    patch_stable_whisper_local_vad(stable_whisper, vad_onnx)
    device = args.device or "cuda"
    compute_type = compute_type_for_device(device, args.compute_type)
    wav: Path | None = None
    cleanup_paths: list[Path] = []
    try:
        wav, cleanup_paths = asr_audio_lib.prepare_asr_wav(src, args)
        print(f"Prepared ASR WAV: {wav}")
        backend = stable_whisper_backend(model_dir)
        print(f"Using stable-whisper {backend} backend: model={model_dir} device={device} compute_type={compute_type}")
        print(f"Using local Silero VAD ONNX: {vad_onnx}")
        print(f"Using stable-whisper regroup policy: {args.regroup}")
        if backend == "faster":
            model = stable_whisper.load_faster_whisper(
                str(model_dir),
                device=device,
                compute_type=compute_type,
            )
        else:
            model = stable_whisper.load_hf_whisper(str(model_dir), device=device)
        common_kwargs = {
            "language": "ja",
            "task": "transcribe",
            "beam_size": args.beam_size,
            "initial_prompt": initial_prompt,
            "vad": {"onnx": True},
            "regroup": stable_regroup_value(args.regroup),
            "suppress_silence": True,
            "vad_filter": True,
            "condition_on_previous_text": False,
            "no_speech_threshold": args.no_speech_threshold,
            "temperature": 0.0,
        }
        result = model.transcribe_stable(str(wav), **common_kwargs)
        write_stable_result_srt(result, out)
        count, bad = validate_srt_file(out)
        if bad:
            raise RuntimeError(f"stable-whisper wrote invalid SRT: blocks={count}, bad={bad[:20]}")
    except Exception as exc:  # noqa: BLE001
        out.unlink(missing_ok=True)
        raise RuntimeError(f"Stable transcription failed for {src}: {exc}") from exc
    finally:
        for path in cleanup_paths:
            path.unlink(missing_ok=True)


def transcribe(args: argparse.Namespace) -> None:
    src = require_file(Path(args.media), "Media file")
    if src.suffix.lower() not in MEDIA_EXTS:
        raise SystemExit(f"Unsupported media extension: {src.suffix}")

    model_dir = validate_model(Path(args.model_dir))
    out = Path(args.output) if args.output else src.with_suffix(".orig.srt")
    initial_prompt = build_initial_prompt(args)
    if initial_prompt:
        print(f"Using ASR initial_prompt terms={len(initial_prompt.split('、'))}")
    transcribe_stable(args, src, out, model_dir, initial_prompt)
    print(f"Wrote {out.resolve()}")


def validate_srt_file(path: Path) -> tuple[int, list[int]]:
    try:
        return srt_io_lib.validate_file(path)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc)) from exc


def read_srt_blocks(path: Path) -> list[str]:
    try:
        return srt_io_lib.read_blocks(path)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc)) from exc


def write_srt_blocks(path: Path, blocks: list[str]) -> None:
    srt_io_lib.write_blocks(path, blocks)


def is_under_ignored_workbench_dir(path: Path) -> bool:
    return any(part in IGNORED_WORKBENCH_DIRS for part in path.parts)


def is_final_srt_path(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() != ".srt":
        return False
    if is_under_ignored_workbench_dir(path):
        return False
    name = path.name
    if any(name.endswith(suffix) for suffix in FINAL_SRT_EXCLUDED_SUFFIXES):
        return False
    if ".part" in path.stem or ".deepseek." in name:
        return False
    return True


def iter_final_srt_paths(root: Path) -> list[Path]:
    root = root.resolve()
    if root.is_file():
        return [root] if is_final_srt_path(root) else []
    return sorted(path for path in root.rglob("*.srt") if is_final_srt_path(path))


def validate(args: argparse.Namespace) -> None:
    count, bad = validate_srt_file(Path(args.subtitle))
    print(f"blocks={count}, bad={bad[:20]}")
    if bad:
        raise SystemExit(1)


def normalize_text_punctuation_line(line: str, args: argparse.Namespace) -> str:
    normalized = line.translate(TEXT_PUNCT_TRANSLATION)
    if args.ascii_ellipsis:
        normalized = normalized.replace("...", "……")
    if args.ascii_quotes:
        normalized = normalized.replace('"', "”")
    return normalized


def normalize_punctuation_in_blocks(blocks: list[str], args: argparse.Namespace) -> tuple[list[str], int]:
    updated: list[str] = []
    changed_lines = 0
    for block in blocks:
        lines = block.splitlines()
        if len(lines) < 3:
            updated.append(block)
            continue
        number, timing = lines[0], lines[1]
        text_lines: list[str] = []
        for line in lines[2:]:
            normalized = normalize_text_punctuation_line(line, args)
            if normalized != line:
                changed_lines += 1
            text_lines.append(normalized)
        updated.append("\n".join([number, timing, *text_lines]))
    return updated, changed_lines


def normalize_punctuation(args: argparse.Namespace) -> None:
    target = require_file(Path(args.target), "SRT file or episode directory") if Path(args.target).is_file() else Path(args.target)
    if not target.exists():
        raise SystemExit(f"Target not found: {target}")
    subtitles = iter_final_srt_paths(target)
    if not subtitles:
        raise SystemExit(f"No final SRT files found under {target}")
    if args.output and len(subtitles) != 1:
        raise SystemExit("--output can only be used when target resolves to exactly one final SRT")

    total_changed = 0
    for subtitle in subtitles:
        blocks = read_srt_blocks(subtitle)
        updated, changed_lines = normalize_punctuation_in_blocks(blocks, args)
        total_changed += changed_lines
        output = Path(args.output) if args.output else subtitle
        if changed_lines and not args.dry_run:
            write_srt_blocks(output, updated)
        print(f"normalize-punctuation file={subtitle.resolve()} blocks={len(blocks)} changed_lines={changed_lines} output={output.resolve()}")
    print(f"normalize-punctuation files={len(subtitles)} changed_lines={total_changed}")


def split_timing(timing: str) -> tuple[float, float]:
    start_raw, end_raw = [part.strip() for part in timing.split("-->", 1)]
    return parse_srt_time(start_raw), parse_srt_time(end_raw)


def make_timing(start: float, end: float) -> str:
    return f"{fmt_time(start)} --> {fmt_time(end)}"


JA_TERMINAL_ENDINGS = (
    "\u3002", "\uff01", "\uff1f", "?", "!",
    "\u3067\u3059", "\u307e\u3059", "\u3067\u3057\u305f", "\u307e\u3057\u305f",
    "\u304f\u3060\u3055\u3044", "\u304f\u3060\u3055\u3044\u306d", "\u3068\u601d\u3044\u307e\u3059",
)
JA_CONTINUATION_ENDINGS = (
    "\u3001", "\uff0c", "\u3068", "\u3066", "\u3067", "\u306b", "\u3092", "\u304c", "\u306f", "\u3082", "\u306e",
    "\u4eca\u3001", "\u306e\u3067", "\u306e\u3067\u3001", "\u3093\u3067", "\u3051\u3069", "\u3051\u308c\u3069", "\u3051\u308c\u3069\u3082",
)
JA_CLAUSE_PATTERNS = (
    "\u3067\u3059\u306d \u306b\u306f", "\u3067\u3059\u304c", "\u306e\u3067", "\u3051\u308c\u3069\u3082", "\u3067\u3059\u3051\u308c\u3069\u3082", "\u3068\u3044\u3046\u3053\u3068\u3067",
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
            if pattern == "\u3067\u3059\u306d \u306b\u306f":
                points.append(idx + len("\u3067\u3059\u306d"))
            else:
                points.append(idx + len(pattern))
    for idx, char in enumerate(text[:-1], start=1):
        if char in "\u3001\u3002\uff01\uff1f?!" and idx > 8:
            points.append(idx)
    return sorted(set(idx for idx in points if 6 <= idx <= len(text) - 6))


def smooth_source_srt(args: argparse.Namespace) -> None:
    path = Path(args.subtitle)
    entries = []
    for number, timing, text_lines in iter_srt_entries(path):
        start, end = split_timing(timing)
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
            left = text[:split_at].strip(" \u3001")
            right = text[split_at:].strip(" \u3001")
            left = re.sub(r"\s*\u306b\u306f$", "", left)
            right = re.sub(r"^\u306b\u306f\s*", "", right)
            if left and right:
                ratio = max(0.25, min(0.75, len(left) / (len(left) + len(right))))
                mid_time = entry["start"] + duration * ratio
                smoothed.append({"start": entry["start"], "end": mid_time, "text": left})
                smoothed.append({"start": mid_time, "end": entry["end"], "text": right})
                continue
        smoothed.append(entry)

    blocks = []
    for number, entry in enumerate(smoothed, start=1):
        blocks.append("\n".join([str(number), make_timing(entry["start"], entry["end"]), entry["text"]]))

    output = Path(args.output) if args.output else path
    write_srt_blocks(output, blocks)
    print(f"smooth-source blocks={len(entries)} -> {len(smoothed)} output={output.resolve()}")


def orig_audit(args: argparse.Namespace) -> None:
    subtitle = Path(args.subtitle).resolve()
    entries = iter_srt_entries(subtitle)
    rules = audit_rules_lib.load_audit_rules(args, subtitle, bad_fixed_terms=BAD_FIXED_TERMS, suspicious_terms=SUSPICIOUS_TERMS)
    issues: list[str] = [
        "# HOOOOPE Japanese source SRT audit",
        f"source: {subtitle}",
        "",
    ]
    issue_count = 0

    previous_text = ""
    repeat_count = 1
    for idx, (number, timing, text_lines) in enumerate(entries):
        text = "".join(text_lines).strip()
        reasons: list[str] = []
        if not text:
            reasons.append("empty source text")
        if ASR_SUSPICIOUS_OPEN_RE.search(text):
            reasons.append("possible HOOOOPE misheard as Open/opun")
        if "HOPE" in text and "HOOOOPE" not in text:
            reasons.append("possible HOOOOPE spelling issue")
        if HOOOOPE_OPENING_MISHEAR_RE.search(text):
            reasons.append("likely opening/title ASR error for Extend Step HOOOOPE")
        if HOOOOPE_TITLE_MISHEAR_RE.search(text) and "HOOOOPE" not in text:
            reasons.append("likely program title ASR error for 羊宮妃那のHOOOOPE")
        if HOOOOPE_ACCOUNT_MISHEAR_RE.search(text):
            reasons.append("official X account or hashtag line may be misrecognized")
        if AIUEO_COMPOSITION_MISHEAR_RE.search(text):
            reasons.append("possible あいうえお作文 / 水野 acrostic ASR error")
        context_start = max(0, idx - args.context_window)
        context_end = min(len(entries), idx + args.context_window + 1)
        context_text = " ".join("".join(row[2]) for row in entries[context_start:context_end])
        for rule in audit_rules_lib.ordered_rule_items(rules, "homophone_context_rules"):
            pattern = re.compile(str(rule.get("pattern", "")))
            context_tokens = tuple(str(token) for token in rule.get("context", []))
            if pattern.search(text) and any(token in context_text for token in context_tokens):
                reasons.append(str(rule.get("reason", "possible homophone ASR error; verify surrounding context")))
        for rule in audit_rules_lib.ordered_rule_items(rules, "source_regex_rules"):
            pattern = re.compile(str(rule.get("pattern", "")))
            if pattern.search(text):
                detail = str(rule.get("reason", rule.get("id", "source regex rule")))
                reasons.append(detail)
        for bad_term in ("AGVIOT", "ＡＶＩＯＴ", "生驹", "水野サク", "サポーテッドバイ"):
            if bad_term in text:
                reasons.append(f"suspicious ASR term: {bad_term}")
        if re.search(r"[A-Za-z]{5,}", text) and not any(ok in text for ok in ("HOOOOPE", "AVIOT", "After", "Talk", "Step", "Room")):
            reasons.append("unusual long Latin token in Japanese source")
        if len(text) <= args.min_chars:
            reasons.append("very short block; check missed short reaction only if context matters")
        try:
            start_raw, end_raw = [part.strip() for part in timing.split("-->", 1)]
            duration = parse_srt_time(end_raw) - parse_srt_time(start_raw)
            if duration >= args.long_duration_seconds and len(text) <= args.short_text_chars:
                reasons.append(f"long duration with short text: {duration:.1f}s")
        except (ValueError, IndexError):
            reasons.append("invalid timing")

        if text == previous_text:
            repeat_count += 1
            if repeat_count >= 3:
                reasons.append(f"repeated source text x{repeat_count}")
        else:
            repeat_count = 1
        previous_text = text

        if reasons:
            issue_count += 1
            issues.extend([
                f"## #{number} {timing}",
                f"- reasons: {', '.join(reasons)}",
                f"- text: {text}",
                "",
            ])

    output = Path(args.output) if args.output else subtitle.with_name(f"{subtitle.stem}.audit.txt")
    output.write_text("\n".join(issues).strip() + "\n", encoding="utf-8-sig")
    print(f"orig-audit entries={len(entries)} issues={issue_count} output={output.resolve()}")
    if issue_count and args.fail_on_issues:
        raise SystemExit(1)


def qwen_result_text(item) -> str:
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        for key in ("text", "transcription", "content"):
            value = item.get(key)
            if isinstance(value, str):
                return value.strip()
    for key in ("text", "transcription", "content"):
        value = getattr(item, key, None)
        if isinstance(value, str):
            return value.strip()
    return str(item).strip()


def audit_risk_numbers(audit_path: Path) -> set[int]:
    if not audit_path.exists():
        return set()
    text = audit_path.read_text(encoding="utf-8-sig")
    return {int(match.group(1)) for match in re.finditer(r"^## #(\d+)\s", text, flags=re.MULTILINE)}


def qwen_compare(args: argparse.Namespace) -> None:
    media = require_file(Path(args.media), "Media file")
    orig = require_file(Path(args.orig), "Source SRT")
    output = Path(args.output) if args.output else orig.with_name(f"{orig.stem}.qwen.compare.txt")
    qwen_model_dir = Path(args.qwen_model_dir).resolve()
    if not qwen_model_dir.exists():
        message = f"qwen model dir missing: {qwen_model_dir}"
        if args.required:
            raise SystemExit(message)
        output.write_text(f"# Qwen ASR comparison\n\nstatus: skipped\nreason: {message}\n", encoding="utf-8-sig")
        print(f"qwen-compare skipped output={output.resolve()} reason={message}")
        return
    if importlib.util.find_spec("qwen_asr") is None:
        message = "qwen_asr package is not installed; install qwen-asr to enable Qwen3-ASR comparison"
        if args.required:
            raise SystemExit(message)
        output.write_text(f"# Qwen ASR comparison\n\nstatus: skipped\nreason: {message}\nmodel: {qwen_model_dir}\n", encoding="utf-8-sig")
        print(f"qwen-compare skipped output={output.resolve()} reason={message}")
        return

    risk_numbers = audit_risk_numbers(Path(args.audit)) if args.audit else set()
    entries = iter_srt_entries(orig)
    if risk_numbers:
        selected = [entry for entry in entries if entry[0] in risk_numbers]
    else:
        selected = []
    selected = selected[: max(1, args.max_segments)]
    if not selected:
        output.write_text(
            f"# Qwen ASR comparison\n\nstatus: no-risk-segments\nmodel: {qwen_model_dir}\nsource: {orig}\n",
            encoding="utf-8-sig",
        )
        print(f"qwen-compare no-risk-segments output={output.resolve()}")
        return

    import torch
    from qwen_asr import Qwen3ASRModel

    device_map = "cuda:0" if torch.cuda.is_available() else "cpu"
    dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
    model = Qwen3ASRModel.from_pretrained(
        str(qwen_model_dir),
        dtype=dtype,
        device_map=device_map,
        max_inference_batch_size=max(1, args.batch_size),
        max_new_tokens=args.max_new_tokens,
    )

    temp_paths: list[Path] = []
    rows: list[str] = [
        "# Qwen ASR comparison",
        "",
        "status: complete",
        f"mode: risk-segments",
        f"model: {qwen_model_dir}",
        f"source: {orig}",
        f"media: {media}",
        "",
    ]
    try:
        segment_paths: list[Path] = []
        for number, timing, text_lines in selected:
            start_raw, end_raw = [part.strip() for part in timing.split("-->", 1)]
            start = max(0.0, parse_srt_time(start_raw) - args.padding_seconds)
            end = parse_srt_time(end_raw) + args.padding_seconds
            wav = asr_audio_lib.extract_segment_wav(media, start, max(0.1, end - start), args.audio_sample_rate)
            temp_paths.append(wav)
            segment_paths.append(wav)
        results = model.transcribe(
            audio=[str(path) for path in segment_paths],
            language=["Japanese"] * len(segment_paths),
        )
        for (number, timing, text_lines), result in zip(selected, results):
            whisper_text = "".join(text_lines).strip()
            qwen_text = qwen_result_text(result)
            rows.extend([
                f"## #{number} {timing}",
                f"- whisper: {whisper_text}",
                f"- qwen: {qwen_text}",
                "",
            ])
    finally:
        if not args.keep_segments:
            for path in temp_paths:
                path.unlink(missing_ok=True)
    output.write_text("\n".join(rows).strip() + "\n", encoding="utf-8-sig")
    print(f"qwen-compare segments={len(selected)} output={output.resolve()}")


def lint_final(args: argparse.Namespace) -> None:
    subtitle = Path(args.subtitle)
    count, bad = validate_srt_file(subtitle)
    issues: list[str] = []
    if bad:
        issues.append(f"[结构错误] blocks={count}, bad={bad[:20]}")

    entries = iter_srt_entries(subtitle)
    previous_text = ""
    repeat_count = 1
    for number, timing, text_lines in entries:
        text = "\n".join(text_lines)

        if not text:
            issues.append(f"[空字幕] #{number}")
        if len(text_lines) > 2:
            issues.append(f"[超过两行] #{number}: {len(text_lines)} lines")
        for line in text_lines:
            if len(line) > args.max_line_chars:
                issues.append(f"[单行过长] #{number}: {len(line)} chars: {line}")
            width = display_width(line)
            if width > args.max_line_width:
                issues.append(f"[显示宽度过长] #{number}: {width:.1f} units: {line}")
            if args.strict_public and ASCII_PUNCT_RE.search(line):
                issues.append(f"[公开发布标点需统一] #{number}: {line}")
        try:
            start_raw, end_raw = [part.strip() for part in timing.split("-->", 1)]
            duration = parse_srt_time(end_raw) - parse_srt_time(start_raw)
            if duration > args.max_duration_seconds:
                issues.append(
                    f"[字幕持续过长需Codex处理] #{number}: {duration:.1f}s: {text.replace(chr(10), ' / ')}"
                )
        except (ValueError, IndexError):
            issues.append(f"[时间轴格式异常] #{number}: {timing}")
        if JA_RE.search(text):
            issues.append(f"[疑似日文残留] #{number}: {text.replace(chr(10), ' / ')}")
        for token in HOOPE_RE.findall(text):
            if token != "HOOOOPE":
                issues.append(f"[节目名疑似错误] #{number}: {token}: {text.replace(chr(10), ' / ')}")
        if re.search(r"\bOpen\b|\bOPEN\b", text) and (
            "Extend Step" in text or "HOOOOPE" in text or "羊宫妃那" in text
        ):
            issues.append(f"[开场疑似误译Open] #{number}: {text.replace(chr(10), ' / ')}")
        for bad_term in BAD_HOST_TERMS:
            if bad_term in text:
                issues.append(f"[人名疑似错误] #{number}: {bad_term}: {text.replace(chr(10), ' / ')}")
                break
        term_issues = find_term_issues(text)
        if term_issues:
            issues.append(
                f"[固定译名疑似错误] #{number}: {'; '.join(term_issues)}: {text.replace(chr(10), ' / ')}"
            )
        if text == previous_text:
            repeat_count += 1
            if args.strict_public and repeat_count >= 3:
                issues.append(f"[连续重复字幕] #{number}: repeated {repeat_count} times: {text.replace(chr(10), ' / ')}")
        else:
            previous_text = text
            repeat_count = 1

    print(f"lint-final blocks={len(entries)} issues={len(issues)}")
    for issue in issues[: args.max_report]:
        print(issue)
    if len(issues) > args.max_report:
        print(f"... {len(issues) - args.max_report} more issues")
    if issues and not args.warn_only:
        raise SystemExit(1)


def terms_audit(args: argparse.Namespace) -> None:
    subtitle = Path(args.subtitle)
    count, bad = validate_srt_file(subtitle)
    rules = audit_rules_lib.load_audit_rules(args, subtitle, bad_fixed_terms=BAD_FIXED_TERMS, suspicious_terms=SUSPICIOUS_TERMS)
    suspicious_terms = tuple(str(term) for term in rules.get("suspicious_terms", SUSPICIOUS_TERMS))
    issues: list[str] = []
    if bad:
        issues.append(f"[结构错误] blocks={count}, bad={bad[:20]}")

    for number, _timing, text_lines in iter_srt_entries(subtitle):
        text = "\n".join(text_lines)
        for issue in find_term_issues(text, rules):
            issues.append(f"[固定译名疑似错误] #{number}: {issue}: {text.replace(chr(10), ' / ')}")
        for term in suspicious_terms:
            if term in text:
                issues.append(f"[可疑专有名词] #{number}: {term}: {text.replace(chr(10), ' / ')}")
        if JA_RE.search(text):
            issues.append(f"[假名/日文残留] #{number}: {text.replace(chr(10), ' / ')}")
        for token in HOOPE_RE.findall(text):
            if token != "HOOOOPE":
                issues.append(f"[节目名疑似错误] #{number}: {token}: {text.replace(chr(10), ' / ')}")

    print(f"terms-audit blocks={count} issues={len(issues)}")
    for issue in issues[: args.max_report]:
        print(issue)
    if len(issues) > args.max_report:
        print(f"... {len(issues) - args.max_report} more issues")
    if issues and not args.warn_only:
        raise SystemExit(1)


def long_block_split_point(text: str, args: argparse.Namespace) -> int | None:
    compact = " ".join(text.split())
    if len(compact) < args.sub_split_min_chars:
        return None
    strong_candidates: list[int] = []
    weak_candidates: list[int] = []
    for idx, char in enumerate(compact[:-1], start=1):
        if not args.sub_split_min_side_chars <= idx <= len(compact) - args.sub_split_min_side_chars:
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


def split_long_final_block(number: str, timing: str, text: str, args: argparse.Namespace) -> list[tuple[str, str, str]]:
    try:
        start, end = split_timing(timing)
    except (ValueError, IndexError):
        return [(number, timing, text)]
    duration = end - start
    compact_len = len("".join(text.split()))
    if args.no_sub_split or (
        duration < args.sub_split_duration_seconds
        and compact_len < args.sub_split_chars
    ):
        return [(number, timing, text)]
    split_at = long_block_split_point(text, args)
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
    if mid_time - start < args.sub_split_min_duration_seconds or end - mid_time < args.sub_split_min_duration_seconds:
        return [(number, timing, text)]
    return [
        (number, make_timing(start, mid_time), left),
        (number, make_timing(mid_time, end), right),
    ]


def wrap_final(args: argparse.Namespace) -> None:
    subtitle = require_file(Path(args.subtitle), "Final Chinese SRT")
    review_todo = subtitle.with_name(f"{subtitle.stem}.review.todo.txt")
    if not review_todo.exists():
        print(f"[wrap-final] warning: {review_todo.name} not found; run review-todo before wrap-final so block numbers remain aligned")
    blocks = read_srt_blocks(subtitle)
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
        split_entries = split_long_final_block(number, timing, text, args)
        if len(split_entries) > 1:
            split_long += 1
        if len(split_entries) > 1 or text != " ".join(line.strip() for line in lines[2:] if line.strip()):
            changed += 1
        for _orig_number, split_timing_text, split_text in split_entries:
            wrapped = split_readable_line(split_text, args.max_line_chars, args.max_line_width)
            if len(wrapped) > 2:
                wrapped = wrapped[:2]
            if len(split_entries) == 1 and wrapped != lines[2:]:
                changed += 1
            updated_entries.append(("", split_timing_text, wrapped))

    updated = [
        "\n".join([str(idx), timing, *wrapped])
        for idx, (_number, timing, wrapped) in enumerate(updated_entries, start=1)
    ]
    output = Path(args.output) if args.output else subtitle
    if changed and not args.dry_run:
        write_srt_blocks(output, updated)
    print(f"wrap-final blocks={len(blocks)} -> {len(updated)} changed={changed} split_long={split_long} output={output.resolve()}")


def review_todo(args: argparse.Namespace) -> None:
    orig = require_file(Path(args.orig), "Original Japanese SRT")
    final = require_file(Path(args.final), "Final Chinese SRT")
    orig_entries = {number: (timing, text_payload(lines)) for number, timing, lines in iter_srt_entries(orig)}
    final_entries = iter_srt_entries(final)
    rows: list[str] = [
        "# HOOOOPE subtitle review todo",
        "",
        "Review these blocks before public release. They are selected by automatic risk signals; do not rewrite unless the Japanese source supports the edit.",
        "",
    ]
    count = 0
    for number, timing, lines in final_entries:
        zh = text_payload(lines)
        reasons = risk_reasons(number, timing, zh, args)
        ja_timing, ja = orig_entries.get(number, ("", ""))
        if ja and args.length_ratio:
            ja_len = max(1, len(ja))
            zh_len = len(zh.replace("\n", ""))
            ratio = zh_len / ja_len
            if ratio < args.min_ratio or ratio > args.max_ratio:
                reasons.append(f"日中信息量比{ratio:.2f}")
        if not reasons:
            continue
        count += 1
        rows.extend(
            [
                f"## #{number} {timing}",
                f"- reason: {', '.join(dict.fromkeys(reasons))}",
                f"- JA: {compact_text(ja, args.text_limit)}",
                f"- ZH: {compact_text(zh, args.text_limit)}",
                "",
            ]
        )
    out = Path(args.output) if args.output else final.with_name(f"{final.stem}.review.todo.txt")
    out.write_text("\n".join(rows).strip() + "\n", encoding="utf-8-sig")
    print(f"Wrote {out.resolve()} items={count}")


def proper_noun_candidates(args: argparse.Namespace) -> None:
    orig = require_file(Path(args.orig), "Original Japanese SRT")
    counts: dict[str, int] = {}
    examples: dict[str, str] = {}
    for _number, _timing, lines in iter_srt_entries(orig):
        text = text_payload(lines)
        candidates = []
        candidates.extend(KATAKANA_TERM_RE.findall(text))
        candidates.extend(LATIN_TERM_RE.findall(text))
        candidates.extend(match.group(1).strip() for match in TITLE_LIKE_RE.finditer(text) if match.group(1).strip())
        for candidate in candidates:
            if len(candidate) < args.min_chars:
                continue
            counts[candidate] = counts.get(candidate, 0) + 1
            examples.setdefault(candidate, compact_text(text, 100))
    nickname_rows = ["## Kana nickname romanization candidates", ""]
    nickname_seen: set[str] = set()
    for term, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        if not KANA_NICKNAME_RE.fullmatch(term):
            continue
        romanized = romanize_kana(term)
        if not romanized or term in nickname_seen:
            continue
        nickname_seen.add(term)
        nickname_rows.append(f"- `{term}` -> `{romanized}` x{count}: {examples[term]}")
    rows = ["# Proper noun candidates", ""]
    if len(nickname_rows) > 2:
        rows.extend(nickname_rows)
        rows.append("")
        rows.append("## Raw candidates")
        rows.append("")
    for term, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[: args.max_terms]:
        rows.append(f"- `{term}` x{count}: {examples[term]}")
    out = Path(args.output) if args.output else orig.with_name(f"{orig.stem}.proper-nouns.txt")
    out.write_text("\n".join(rows).strip() + "\n", encoding="utf-8-sig")
    print(f"Wrote {out.resolve()} terms={len(counts)}")


def split_srt(args: argparse.Namespace) -> None:
    src = require_file(Path(args.subtitle), "Subtitle file")
    blocks = read_srt_blocks(src)
    if not blocks:
        raise SystemExit(f"No SRT blocks found in {src}")

    out_dir = Path(args.output_dir) if args.output_dir else src.parent / "chunks" / src.stem
    translated_dir = out_dir.parent / f"{out_dir.name}_translated"
    out_dir.mkdir(parents=True, exist_ok=True)
    translated_dir.mkdir(parents=True, exist_ok=True)

    part_count = 0
    for part_count, start in enumerate(range(0, len(blocks), args.chunk_size), start=1):
        chunk = blocks[start : start + args.chunk_size]
        part = out_dir / f"{src.stem}.part{part_count:03d}.srt"
        write_srt_blocks(part, chunk)

    print(f"Wrote {part_count} chunks to {out_dir.resolve()}")
    print(f"Put translated chunks with the same filenames in {translated_dir.resolve()}")


def merge_srt(args: argparse.Namespace) -> None:
    src_dir = Path(args.chunk_dir).resolve()
    if not src_dir.exists():
        raise SystemExit(f"Chunk directory not found: {src_dir}")

    parts = sorted(src_dir.glob("*.srt"))
    if not parts:
        raise SystemExit(f"No .srt chunks found in {src_dir}")

    blocks: list[str] = []
    for part in parts:
        blocks.extend(read_srt_blocks(part))

    bad: list[int] = []
    for expected, block in enumerate(blocks, start=1):
        lines = block.splitlines()
        if len(lines) < 3 or lines[0].strip() != str(expected) or "-->" not in lines[1]:
            bad.append(expected)

    if bad:
        raise SystemExit(f"Merged SRT numbering/timestamp validation failed: bad={bad[:20]}")

    out = Path(args.output)
    write_srt_blocks(out, blocks)
    print(f"Wrote {out.resolve()} from {len(parts)} chunks, blocks={len(blocks)}")


def summary_template(args: argparse.Namespace) -> None:
    src = require_file(Path(args.media), "Media file")
    subtitle = require_file(Path(args.subtitle), "Subtitle file")
    count, bad = validate_srt_file(subtitle)
    if bad:
        raise SystemExit(f"Subtitle validation failed: blocks={count}, bad={bad[:20]}")

    out = Path(args.output) if args.output else src.with_name(f"{src.stem}.summary.txt")
    template = f"""[日期可选] 小羊 HOOOOPE 笔记

[根据 {subtitle.name} 的润色中文字幕，用 1-2 句总述本期氛围和主要内容。]

----------

『[话题/来信标题]』
[大致时间] 听众来信或节目话题讲了什么，羊宫妃那怎么回应，有什么有趣的展开。写成自然段，不要写成要点列表。

『[下一个话题/来信标题]』
[大致时间] 继续用自然段概括。可以根据节目内容添加更多话题段落。

#羊宫妃那
"""
    out.write_text(template, encoding="utf-8-sig")
    print(f"Wrote {out.resolve()}")


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print(" ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def ffprobe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path.resolve()),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def verify_duration_pair(source: Path, output: Path, tolerance: float) -> None:
    src_duration = ffprobe_duration(source)
    out_duration = ffprobe_duration(output)
    diff = abs(src_duration - out_duration)
    print(f"source={src_duration:.3f}s output={out_duration:.3f}s diff={diff:.3f}s")
    if diff > tolerance:
        raise SystemExit(f"Duration mismatch exceeds {tolerance}s: {diff:.3f}s")


def burn_command(args: argparse.Namespace, src: Path, out: Path, vf: str, encoder: str) -> list[str]:
    base = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-i",
        str(src.resolve()),
        "-vf",
        vf,
    ]

    if encoder == "h264_nvenc":
        video = [
            "-c:v",
            "h264_nvenc",
            "-cq",
            str(args.cq),
            "-preset",
            args.nvenc_preset,
        ]
    else:
        video = [
            "-c:v",
            "libx264",
            "-crf",
            str(args.crf),
            "-preset",
            args.preset,
        ]

    audio = ["-c:a", "aac", "-b:a", args.audio_bitrate]
    return base + video + audio + [str(out.resolve())]


def burn(args: argparse.Namespace) -> None:
    src = require_file(Path(args.media), "Media file")
    subtitle = require_file(Path(args.subtitle), "Subtitle file")
    count, bad = validate_srt_file(subtitle)
    if bad:
        raise SystemExit(f"Subtitle validation failed: blocks={count}, bad={bad[:20]}")

    if args.replace_source:
        out = src.with_name(f"{src.stem}.burned.tmp{src.suffix}")
    else:
        out = Path(args.output) if args.output else src.with_name(f"{src.stem}.zh.burned.mp4")
    workdir = src.parent.resolve()
    subtitle_name = subtitle.resolve().name if subtitle.parent.resolve() == workdir else str(subtitle.resolve())

    style = (
        f"FontName={args.font},"
        f"FontSize={args.font_size},"
        "PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,"
        "BorderStyle=1,"
        f"Outline={args.outline},"
        "Shadow=0,"
        "Alignment=2,"
        f"MarginV={args.margin_v}"
    )
    vf = f"subtitles={subtitle_name}:charenc=UTF-8:force_style='{style}'"

    if args.encoder == "auto":
        try:
            run(burn_command(args, src, out, vf, "h264_nvenc"), cwd=workdir)
        except subprocess.CalledProcessError:
            print("NVENC burn failed; falling back to libx264")
            run(burn_command(args, src, out, vf, "libx264"), cwd=workdir)
    else:
        run(burn_command(args, src, out, vf, args.encoder), cwd=workdir)

    verify_duration_pair(src, out, args.duration_tolerance)

    if args.replace_source:
        backup = src.with_name(f"{src.stem}.source.tmp{src.suffix}")
        if backup.exists():
            backup.unlink()
        src.replace(backup)
        out.replace(src)
        backup.unlink()
        print(f"Replaced source with burned video: {src.resolve()}")
        print(f"Wrote {src.resolve()}")
    else:
        print(f"Wrote {out.resolve()}")


def verify_duration(args: argparse.Namespace) -> None:
    source = require_file(Path(args.source), "Source media")
    output = require_file(Path(args.output), "Output media")
    verify_duration_pair(source, output, args.tolerance)


def screenshot_check(args: argparse.Namespace) -> None:
    media = require_file(Path(args.media), "Media file")
    subtitle = Path(args.subtitle) if args.subtitle else None
    if subtitle is not None:
        require_file(subtitle, "Subtitle file")

    duration = ffprobe_duration(media)
    times = [duration * pct / 100 for pct in args.percent]

    if subtitle is not None:
        entries = iter_srt_entries(subtitle)
        subtitle_times: list[float] = []
        for _number, timing, text_lines in entries:
            if not text_lines:
                continue
            try:
                start_raw, end_raw = [part.strip() for part in timing.split("-->", 1)]
                start = parse_srt_time(start_raw)
                end = parse_srt_time(end_raw)
            except (ValueError, IndexError):
                continue
            subtitle_times.append((start + end) / 2)
        if subtitle_times:
            frame_count = max(1, args.subtitle_frames)
            if len(subtitle_times) <= frame_count:
                times.extend(subtitle_times)
            else:
                for idx in range(frame_count):
                    sample_index = round(idx * (len(subtitle_times) - 1) / (frame_count - 1))
                    times.append(subtitle_times[sample_index])

    unique_times: list[float] = []
    for value in sorted(times):
        value = min(max(value, 0.0), max(duration - 0.1, 0.0))
        if not unique_times or abs(value - unique_times[-1]) > 1.0:
            unique_times.append(value)

    out_dir = Path(args.output_dir) if args.output_dir else media.parent / f"{media.stem}.screenshot_check"
    out_dir.mkdir(parents=True, exist_ok=True)
    frames: list[Path] = []
    for idx, seconds in enumerate(unique_times, start=1):
        frame = out_dir / f"{media.stem}.check.{idx:02d}.{int(seconds):05d}s.jpg"
        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-ss",
            f"{seconds:.3f}",
            "-i",
            str(media.resolve()),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(frame.resolve()),
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        frames.append(frame)

    print(f"Wrote {len(frames)} screenshot check frames to {out_dir.resolve()}")
    try:
        from PIL import Image, ImageDraw
    except Exception as exc:  # noqa: BLE001
        print(f"Could not create contact sheet because Pillow is unavailable: {exc}")
        return

    images = [Image.open(frame).convert("RGB") for frame in frames]
    thumbs = []
    for image in images:
        ratio = args.thumb_width / image.width
        thumbs.append(image.resize((args.thumb_width, max(1, int(image.height * ratio)))))
    if not thumbs:
        return
    thumb_height = max(image.height for image in thumbs)
    columns = max(1, args.columns)
    rows = max(args.rows, (len(thumbs) + columns - 1) // columns)
    margin = 8
    label_height = 22
    sheet = Image.new(
        "RGB",
        (columns * args.thumb_width + margin * (columns + 1), rows * (thumb_height + label_height) + margin * (rows + 1)),
        "white",
    )
    draw = ImageDraw.Draw(sheet)
    for idx, (frame, thumb) in enumerate(zip(frames, thumbs), start=0):
        col = idx % columns
        row = idx // columns
        x = margin + col * (args.thumb_width + margin)
        y = margin + row * (thumb_height + label_height + margin)
        sheet.paste(thumb, (x, y))
        draw.text((x, y + thumb.height + 3), frame.stem, fill=(0, 0, 0))
    sheet_path = out_dir / f"{media.stem}.contact_sheet.jpg"
    sheet.save(sheet_path, quality=92)
    print(f"Wrote contact sheet {sheet_path.resolve()}")


def cleanup(args: argparse.Namespace) -> None:
    episode_dir = Path(args.episode_dir).resolve()
    if not episode_dir.exists():
        raise SystemExit(f"Episode directory not found: {episode_dir}")
    sentinel = episode_dir / CLEANUP_SENTINEL
    if not sentinel.exists() and not args.force:
        raise SystemExit(
            f"Screenshot QA not confirmed: {sentinel.name} missing.\n"
            f"Inspect contact sheets first, then run the pipeline with --cleanup-confirmed, "
            f"or pass --force to skip this check."
        )

    patterns = [
        "*.deepseek.raw.srt",
        "*.deepseek.raw.srt.source.sha256",
        "*.deepseek.raw.srt.dependency.sha256",
        "*.deepseek.polished.srt",
        "*.deepseek.polished.srt.input.sha256",
        "*.deepseek.polished.srt.dependency.sha256",
        "*.qa.txt",
        "*.zh.burned.mp4",
        "*.burned.tmp.mp4",
        "*.subtitle_check.jpg",
        "*.contact_sheet.jpg",
        "*.check.*.jpg",
        "*.orig.audit.txt",
        "*.review.todo.txt",
        "*.proper-nouns.txt",
        CLEANUP_SENTINEL,
    ]
    removed: list[Path] = []
    for pattern in patterns:
        for path in episode_dir.rglob(pattern):
            if path.is_file():
                path.unlink()
                removed.append(path)

    cache_dirs = ["deepseek_chunks", "deepseek_polish_chunks"]
    cache_paths: list[Path] = []
    for dirname in cache_dirs:
        cache_paths.extend(path for path in episode_dir.rglob(dirname) if path.is_dir())
    cache_paths.extend(path for path in episode_dir.rglob("screenshot_check") if path.is_dir())
    cache_paths.extend(path for path in episode_dir.rglob("*.screenshot_check") if path.is_dir())
    for path in sorted(set(cache_paths)):
        if path.exists() and path.is_dir():
            if (path / ".keep").exists() or (path / ".no_cleanup").exists():
                print(f"Skipping preserved directory {path}")
                continue
            import shutil

            shutil.rmtree(path)
            removed.append(path)

    # Some Windows cleanup runs can leave the directory shell after deleting its files.
    # Remove matching empty workbench directories bottom-up as a final pass.
    for path in sorted(episode_dir.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if not path.is_dir():
            continue
        if path.name in {"deepseek_chunks", "deepseek_polish_chunks"} or path.name.endswith(".screenshot_check"):
            if (path / ".keep").exists() or (path / ".no_cleanup").exists():
                continue
            try:
                next(path.iterdir())
            except StopIteration:
                path.rmdir()
                removed.append(path)

    combined_summary = episode_dir / f"{episode_dir.name}.summary.txt"
    if combined_summary.exists():
        for path in episode_dir.rglob("*.summary.txt"):
            if path.is_file() and path.parent != episode_dir:
                path.unlink()
                removed.append(path)
    else:
        print(f"Skipping per-video summary cleanup; combined summary missing: {combined_summary}")

    print(f"Removed {len(removed)} intermediate artifacts")
    for path in removed:
        print(path)


def doctor(args: argparse.Namespace) -> None:
    episode_dir = Path(args.episode_dir).resolve() if args.episode_dir else Path.cwd()
    checks: list[tuple[str, bool, str]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append((name, ok, detail))

    for binary in ("ffmpeg", "ffprobe"):
        found = shutil.which(binary)
        add(binary, bool(found), found or "not found on PATH")

    required_modules = {
        "stable_whisper": "stable_whisper",
        "faster_whisper": "faster_whisper",
        "onnxruntime": "onnxruntime",
        "torch": "torch",
        "requests": "requests",
        "Pillow": "PIL",
        "demucs": "demucs",
    }
    for label, module_name in required_modules.items():
        spec = importlib.util.find_spec(module_name)
        add(f"python:{label}", spec is not None, module_name if spec else "missing")
    spacy_spec = importlib.util.find_spec("spacy")
    add("python:spacy(optional)", spacy_spec is not None, "spacy" if spacy_spec else "missing optional package")

    model_dir = Path(args.model_dir)
    if not model_dir.is_absolute():
        model_dir = (episode_dir / model_dir).resolve() if (episode_dir / model_dir).exists() else (Path.cwd() / model_dir).resolve()
    add("asr model dir", model_dir.exists(), str(model_dir))

    qwen_model_dir = Path(getattr(args, "qwen_model_dir", DEFAULT_QWEN_ASR_MODEL_DIR))
    if not qwen_model_dir.is_absolute():
        qwen_model_dir = (episode_dir / qwen_model_dir).resolve() if (episode_dir / qwen_model_dir).exists() else (Path.cwd() / qwen_model_dir).resolve()
    add("qwen asr model dir", qwen_model_dir.exists(), str(qwen_model_dir))
    qwen_spec = importlib.util.find_spec("qwen_asr")
    add("python:qwen_asr(optional)", qwen_spec is not None, "qwen_asr" if qwen_spec else "missing optional package")

    vad_onnx = Path(args.vad_onnx)
    if not vad_onnx.is_absolute():
        vad_onnx = (episode_dir / vad_onnx).resolve() if (episode_dir / vad_onnx).exists() else (Path.cwd() / vad_onnx).resolve()
    add("vad onnx", vad_onnx.exists(), str(vad_onnx))

    add("DEEPSEEK_API_KEY", bool(os.environ.get("DEEPSEEK_API_KEY")), "set" if os.environ.get("DEEPSEEK_API_KEY") else "missing")
    glossaries = pipeline_existing_glossaries(episode_dir, args.glossary)
    add("glossary readable", bool(glossaries), ", ".join(glossaries) if glossaries else "no glossary found")
    for raw_path in glossaries:
        path = Path(raw_path)
        try:
            path.read_text(encoding="utf-8-sig")
            add(f"glossary:{path.name}", True, str(path.resolve()))
        except OSError as exc:
            add(f"glossary:{path.name}", False, str(exc))

    failed_required = False
    for name, ok, detail in checks:
        status = "ok" if ok else "missing"
        print(f"[doctor] {status}: {name} - {detail}")
        if not ok and "(optional)" not in name:
            failed_required = True
    if failed_required:
        raise SystemExit(1)


def combine_summaries(args: argparse.Namespace) -> None:
    episode_dir = Path(args.episode_dir).resolve()
    if not episode_dir.exists():
        raise SystemExit(f"Episode directory not found: {episode_dir}")

    summary_files = sorted(
        path
        for path in episode_dir.rglob("*.summary.txt")
        if path.is_file() and path.parent != episode_dir
    )
    if not summary_files:
        raise SystemExit(f"No per-video summary files found under {episode_dir}")

    out = Path(args.output) if args.output else episode_dir / f"{episode_dir.name}.summary.txt"
    sections: list[str] = []
    for path in summary_files:
        title = path.parent.name
        text = path.read_text(encoding="utf-8-sig").strip()
        sections.append(f"## {title}\n\n{text}")

    out.parent.mkdir(parents=True, exist_ok=True)
    combined = ("\n\n----------\n\n").join(sections).strip() + "\n"
    out.write_text(combined, encoding="utf-8-sig")
    char_count = chinese_char_count(combined)
    print(f"Wrote combined summary {out.resolve()} from {len(summary_files)} files")
    print(f"summary_chinese_chars={char_count}")
    if char_count < args.min_chars:
        print(
            f"[summary length warning] below soft target {args.min_chars} Chinese chars: {char_count}; "
            "consider expanding high-value moments if coverage feels thin"
        )
    if char_count > args.max_chars and not args.warn_only:
        raise SystemExit(f"Combined summary exceeds {args.max_chars} Chinese chars: {char_count}")
    if char_count > args.max_chars:
        print(f"[summary length warning] exceeds {args.max_chars} Chinese chars: {char_count}")
    if not args.keep_parts:
        for path in summary_files:
            path.unlink()
            print(f"Removed per-video summary {path}")


def final_ready(args: argparse.Namespace) -> None:
    episode_dir = Path(args.episode_dir).resolve()
    if not episode_dir.exists():
        raise SystemExit(f"Episode directory not found: {episode_dir}")
    problems: list[str] = []
    finals = iter_final_srt_paths(episode_dir)
    if not finals:
        problems.append("No final .srt files found")
    for final in finals:
        stem = final.stem
        orig = final.with_name(f"{stem}.orig.srt")
        media = final.with_suffix(".mp4")
        count, bad = validate_srt_file(final)
        print(f"[final-ready] {stem}: final_blocks={count} bad={bad[:5]}")
        if bad:
            problems.append(f"{final}: invalid SRT structure")
        if not orig.exists():
            problems.append(f"{stem}: missing {orig.name}")
        if not media.exists():
            problems.append(f"{stem}: missing {media.name}")
        for number, timing, text_lines in iter_srt_entries(final):
            if len(text_lines) > 2:
                problems.append(f"{stem} #{number}: more than two subtitle lines")
            for line in text_lines:
                if len(line) > args.max_line_chars or display_width(line) > args.max_line_width:
                    problems.append(f"{stem} #{number}: long line: {line}")
            if JA_RE.search("\n".join(text_lines)):
                problems.append(f"{stem} #{number}: Japanese residue")
            for token in HOOPE_RE.findall("\n".join(text_lines)):
                if token != "HOOOOPE":
                    problems.append(f"{stem} #{number}: HOOOOPE spelling issue: {token}")
            try:
                start_raw, end_raw = [part.strip() for part in timing.split("-->", 1)]
                duration = parse_srt_time(end_raw) - parse_srt_time(start_raw)
                if duration > args.max_duration_seconds:
                    problems.append(f"{stem} #{number}: long duration {duration:.1f}s")
            except (ValueError, IndexError):
                problems.append(f"{stem} #{number}: invalid timing")
    summary = episode_dir / f"{episode_dir.name}.summary.txt"
    if not summary.exists():
        problems.append(f"Missing combined summary: {summary.name}")
    else:
        chars = chinese_char_count(summary.read_text(encoding="utf-8-sig"))
        print(f"[final-ready] summary_chinese_chars={chars}")
        if chars < args.min_summary_chars:
            print(
                f"[final-ready] summary length warning: below soft target "
                f"{args.min_summary_chars} Chinese chars: {chars}"
            )
        if chars > args.max_summary_chars:
            problems.append(f"Combined summary exceeds {args.max_summary_chars} Chinese chars: {chars}")
    if problems:
        print(f"final-ready issues={len(problems)}")
        for problem in problems[: args.max_report]:
            print(f"- {problem}")
        if len(problems) > args.max_report:
            print(f"... {len(problems) - args.max_report} more issues")
        if not args.warn_only:
            raise SystemExit(1)
    else:
        print("final-ready issues=0")


def pipeline_skill_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def pipeline_script(name: str) -> Path:
    return pipeline_skill_dir() / "scripts" / name


PIPELINE_DEEPSEEK_MAX_RETRIES = 3
PIPELINE_DEEPSEEK_RETRY_DELAY = 10
CLEANUP_SENTINEL = ".screenshot_qa_passed"


def pipeline_run(cmd: list[str], dry_run: bool = False) -> None:
    print(" ".join(str(part) for part in cmd))
    if not dry_run:
        subprocess.run(cmd, check=True)


def file_sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pipeline_manifest_path(episode_dir: Path) -> Path:
    return episode_dir / ".hoooope_run_manifest.json"


def pipeline_record_manifest(args: argparse.Namespace, episode_dir: Path, videos: list[Path], glossaries: list[str], status: str, failure: str | None = None) -> None:
    if args.dry_run:
        return
    manifest = {
        "schema": "hoooope-run-manifest-v1",
        "stage": args.stage,
        "status": status,
        "failure": failure,
        "config": {
            "translate_model": PIPELINE_TRANSLATION_MODEL,
            "translate_chunk_size": PIPELINE_TRANSLATE_CHUNK_SIZE,
            "translate_workers": getattr(args, "translate_workers", PIPELINE_TRANSLATE_WORKERS),
            "translate_context_blocks": getattr(args, "translate_context_blocks", PIPELINE_TRANSLATE_CONTEXT_BLOCKS),
            "polish_chunk_size": PIPELINE_POLISH_CHUNK_SIZE,
            "polish_workers": PIPELINE_POLISH_WORKERS,
            "deepseek_qa_sample_ratio": PIPELINE_DEEPSEEK_QA_SAMPLE_RATIO,
            "asr_main_model_dir": getattr(args, "model_dir", DEFAULT_TRANSCRIBE_MODEL_DIR),
            "asr_enhancement": getattr(args, "asr_enhancement", "qwen-risk"),
            "qwen_model_dir": getattr(args, "qwen_model_dir", DEFAULT_QWEN_ASR_MODEL_DIR),
        },
        "stop_points": pipeline_state_lib.stage_stop_points(args.stage, status, episode_dir, CLEANUP_SENTINEL),
        "glossaries": [str(Path(path).resolve()) for path in glossaries],
        "videos": [],
    }
    for media in videos:
        stem = media.stem
        workdir = media.parent
        artifacts = {
            "media": media,
            "orig_raw": workdir / f"{stem}.orig.raw.srt",
            "orig": workdir / f"{stem}.orig.srt",
            "orig_audit": workdir / f"{stem}.orig.audit.txt",
            "deepseek_raw": workdir / f"{stem}.deepseek.raw.srt",
            "deepseek_polished": workdir / f"{stem}.deepseek.polished.srt",
            "qa": workdir / f"{stem}.qa.txt",
            "asr_compare": workdir / f"{stem}.asr.compare.txt",
            "final": workdir / f"{stem}.srt",
            "summary": workdir / f"{stem}.summary.txt",
        }
        manifest["videos"].append({
            "stem": stem,
            "workdir": str(workdir),
            "artifacts": {
                name: {"path": str(path), "exists": path.exists(), "sha256": file_sha256(path)}
                for name, path in artifacts.items()
            },
        })
    pipeline_manifest_path(episode_dir).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def pipeline_run_with_retry(cmd: list[str], dry_run: bool = False, max_retries: int = PIPELINE_DEEPSEEK_MAX_RETRIES, retry_delay: float = PIPELINE_DEEPSEEK_RETRY_DELAY) -> None:
    print(" ".join(str(part) for part in cmd))
    if dry_run:
        return
    import time
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            subprocess.run(cmd, check=True)
            return
        except subprocess.CalledProcessError as exc:
            last_error = exc
            if attempt < max_retries:
                delay = retry_delay * (2 ** (attempt - 1))
                print(f"[pipeline] DeepSeek command failed (attempt {attempt}/{max_retries}), retrying in {delay:.0f}s: {exc}")
                time.sleep(delay)
    raise RuntimeError(f"DeepSeek command failed after {max_retries} attempts") from last_error


def pipeline_maybe_run_with_retry(cmd: list[str], outputs: list[Path], dry_run: bool = False, force: bool = False, max_retries: int = PIPELINE_DEEPSEEK_MAX_RETRIES) -> None:
    if not force and outputs and all(path.exists() for path in outputs):
        print(f"[pipeline] skip existing checkpoint: {', '.join(path.name for path in outputs)}")
        return
    pipeline_run_with_retry(cmd, dry_run=dry_run, max_retries=max_retries)


def pipeline_existing_glossaries(episode_dir: Path, extra: list[str] | None = None) -> list[str]:
    candidates = [
        Path("hoooope_terms.txt"),
        Path("model/hoooope_terms.txt"),
        Path("hooope_terms.txt"),
        Path("model/hooope_terms.txt"),
        episode_dir / "hoooope_terms.txt",
        episode_dir / "hooope_terms.txt",
        episode_dir.parent / "model" / "hoooope_terms.txt",
        episode_dir.parent / "model" / "hooope_terms.txt",
    ]
    candidates.extend(Path(path) for path in (extra or []))
    found: list[str] = []
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if path.exists():
            found.append(str(path))
    return found


def pipeline_command_with_glossaries(cmd: list[str], glossaries: list[str]) -> list[str]:
    for glossary in glossaries:
        cmd.extend(["--glossary", glossary])
    return cmd


def pipeline_organize_root_mp4s(episode_dir: Path, dry_run: bool = False) -> list[Path]:
    root_media = sorted(path for path in episode_dir.iterdir() if path.is_file() and path.suffix.lower() == ".mp4")
    planned: list[Path] = []
    for media in root_media:
        workdir = episode_dir / media.stem
        target = workdir / media.name
        planned.append(target)
        if target.exists():
            print(f"[pipeline] organized media already exists: {target}")
            continue
        print(f"[pipeline] organize {media} -> {target}")
        if not dry_run:
            workdir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(media), str(target))
    return planned


def pipeline_episode_videos(episode_dir: Path) -> list[Path]:
    videos: list[Path] = []
    for workdir in sorted(path for path in episode_dir.iterdir() if path.is_dir()):
        if workdir.name in IGNORED_WORKBENCH_DIRS:
            continue
        videos.extend(sorted(path for path in workdir.iterdir() if path.is_file() and path.suffix.lower() == ".mp4"))
    return videos


def pipeline_maybe_run(cmd: list[str], outputs: list[Path], dry_run: bool = False, force: bool = False) -> None:
    if not force and outputs and all(path.exists() for path in outputs):
        print(f"[pipeline] skip existing checkpoint: {', '.join(path.name for path in outputs)}")
        return
    pipeline_run(cmd, dry_run=dry_run)


def pipeline_prepare_review(args: argparse.Namespace, episode_dir: Path, videos: list[Path], glossaries: list[str]) -> None:
    helper = str(Path(__file__).resolve())
    translate_script = str(pipeline_script("deepseek_translate_srt.py"))
    polish_script = str(pipeline_script("deepseek_polish_srt.py"))
    model_dir = args.model_dir
    vad_onnx = args.vad_onnx

    for media in videos:
        workdir = media.parent
        stem = media.stem
        orig_raw = workdir / f"{stem}.orig.raw.srt"
        orig = workdir / f"{stem}.orig.srt"
        raw = workdir / f"{stem}.deepseek.raw.srt"
        polished = workdir / f"{stem}.deepseek.polished.srt"
        qa = workdir / f"{stem}.qa.txt"
        final = workdir / f"{stem}.srt"

        if not orig.exists():
            if args.skip_asr:
                raise SystemExit(f"Missing {orig}; rerun without --skip-asr or provide the source SRT.")
            if not orig_raw.exists():
                transcribe_cmd = [
                    sys.executable,
                    helper,
                    "transcribe",
                    str(media),
                    "--output",
                    str(orig_raw),
                    "--model-dir",
                    model_dir,
                    "--vad-onnx",
                    vad_onnx,
                ]
                pipeline_command_with_glossaries(transcribe_cmd, glossaries)
                pipeline_run(transcribe_cmd, dry_run=args.dry_run)
            else:
                print(f"[pipeline] reuse raw ASR checkpoint: {orig_raw.name}")
            pipeline_run([sys.executable, helper, "smooth-source", str(orig_raw), "--output", str(orig)], dry_run=args.dry_run)
        else:
            print(f"[pipeline] skip existing checkpoint: {orig.name}")

        pipeline_maybe_run(
            [sys.executable, helper, "orig-audit", str(orig)],
            [orig.with_name(f"{orig.stem}.audit.txt")],
            dry_run=args.dry_run,
        )
        if args.asr_enhancement != "off":
            audit = orig.with_name(f"{orig.stem}.audit.txt")
            compare = workdir / f"{stem}.asr.compare.txt"
            qwen_cmd = [
                sys.executable,
                helper,
                "qwen-compare",
                str(media),
                "--orig",
                str(orig),
                "--audit",
                str(audit),
                "--output",
                str(compare),
                "--qwen-model-dir",
                args.qwen_model_dir,
                "--max-segments",
                str(args.qwen_max_segments),
            ]
            if args.asr_enhancement == "qwen-risk-required":
                qwen_cmd.append("--required")
            pipeline_maybe_run(qwen_cmd, [compare], dry_run=args.dry_run, force=args.force_asr_compare)

        raw_outputs = [raw, raw.with_name(raw.name + ".source.sha256")]
        translate_cmd = [
            sys.executable,
            translate_script,
            str(orig),
            "--output",
            str(raw),
            "--model",
            PIPELINE_TRANSLATION_MODEL,
            "--chunk-size",
            str(PIPELINE_TRANSLATE_CHUNK_SIZE),
            "--workers",
            str(args.translate_workers),
            "--context-blocks",
            str(args.translate_context_blocks),
            "--qa-sample-ratio",
            str(PIPELINE_DEEPSEEK_QA_SAMPLE_RATIO),
        ]
        if args.force_deepseek:
            translate_cmd.append("--force")
        pipeline_command_with_glossaries(translate_cmd, glossaries)
        pipeline_maybe_run_with_retry(translate_cmd, raw_outputs, dry_run=args.dry_run, force=args.force_deepseek)

        polished_outputs = [polished, polished.with_name(polished.name + ".input.sha256"), polished.with_name(polished.name + ".dependency.sha256"), qa]
        polish_cmd = [
            sys.executable,
            polish_script,
            str(orig),
            "--translation",
            str(raw),
            "--output",
            str(polished),
            "--qa-output",
            str(qa),
            "--model",
            PIPELINE_TRANSLATION_MODEL,
            "--chunk-size",
            str(PIPELINE_POLISH_CHUNK_SIZE),
            "--polish-workers",
            str(PIPELINE_POLISH_WORKERS),
            "--qa-sample-ratio",
            str(PIPELINE_DEEPSEEK_QA_SAMPLE_RATIO),
        ]
        if args.force_deepseek:
            polish_cmd.append("--force")
        pipeline_command_with_glossaries(polish_cmd, glossaries)
        pipeline_maybe_run_with_retry(polish_cmd, polished_outputs, dry_run=args.dry_run, force=args.force_deepseek)

        if not final.exists():
            print(f"[pipeline] seed final SRT {final}")
            if not args.dry_run:
                shutil.copyfile(polished, final)
        else:
            print(f"[pipeline] preserve existing final SRT: {final.name}")

    print("[pipeline] stop: Codex final proofread is required before post-review stages.")
    print("[pipeline] read references/review-and-qa.md and apply only changed-block corrections to each final .srt.")


def pipeline_post_review(args: argparse.Namespace, episode_dir: Path, videos: list[Path], glossaries: list[str]) -> None:
    helper = str(Path(__file__).resolve())
    note_script = str(pipeline_script("deepseek_note_srt.py"))
    if args.summary_only:
        finals = iter_final_srt_paths(episode_dir)
        if not finals:
            raise SystemExit(f"No final Chinese SRT files found under {episode_dir} for summary-only mode")
        for final in finals:
            note = final.with_name(f"{final.stem}.summary.txt")
            if not note.exists():
                note_cmd = [
                    sys.executable,
                    note_script,
                    str(final),
                    "--output",
                    str(note),
                    "--model",
                    PIPELINE_TRANSLATION_MODEL,
                ]
                pipeline_command_with_glossaries(note_cmd, glossaries)
                pipeline_run(note_cmd, dry_run=args.dry_run)
        combined = episode_dir / f"{episode_dir.name}.summary.txt"
        if not combined.exists():
            pipeline_run(
                [
                    sys.executable,
                    helper,
                    "combine-summaries",
                    str(episode_dir),
                    "--min-chars",
                    str(PIPELINE_MIN_SUMMARY_CHARS),
                    "--max-chars",
                    str(PIPELINE_MAX_SUMMARY_CHARS),
                ],
                dry_run=args.dry_run,
            )
        print("[pipeline] summary-only stop: no MP4 organization, ASR, subtitle QA, burn, final-ready, cleanup, or video edits.")
        return

    for media in videos:
        stem = media.stem
        workdir = media.parent
        orig = workdir / f"{stem}.orig.srt"
        final = workdir / f"{stem}.srt"
        note = workdir / f"{stem}.summary.txt"
        pipeline_run([sys.executable, helper, "normalize-punctuation", str(final)], dry_run=args.dry_run)
        pipeline_run([sys.executable, helper, "review-todo", "--orig", str(orig), "--final", str(final)], dry_run=args.dry_run)
        pipeline_run([sys.executable, helper, "wrap-final", str(final)], dry_run=args.dry_run)
        pipeline_run([sys.executable, helper, "validate", str(final)], dry_run=args.dry_run)
        pipeline_run([sys.executable, helper, "baseline-report", str(final)], dry_run=args.dry_run)
        pipeline_run([sys.executable, helper, "lint-final", str(final), "--strict-public"], dry_run=args.dry_run)
        pipeline_run([sys.executable, helper, "terms-audit", str(final)], dry_run=args.dry_run)
        pipeline_run([sys.executable, helper, "proper-noun-candidates", str(orig)], dry_run=args.dry_run)

        if not note.exists():
            note_cmd = [
                sys.executable,
                note_script,
                str(final),
                "--output",
                str(note),
                "--model",
                PIPELINE_TRANSLATION_MODEL,
            ]
            pipeline_command_with_glossaries(note_cmd, glossaries)
            pipeline_run(note_cmd, dry_run=args.dry_run)

    combined = episode_dir / f"{episode_dir.name}.summary.txt"
    if not combined.exists():
        pipeline_run(
            [
                sys.executable,
                helper,
                "combine-summaries",
                str(episode_dir),
                "--min-chars",
                str(PIPELINE_MIN_SUMMARY_CHARS),
                "--max-chars",
                str(PIPELINE_MAX_SUMMARY_CHARS),
            ],
            dry_run=args.dry_run,
        )
    pipeline_run([sys.executable, helper, "final-ready", str(episode_dir)], dry_run=args.dry_run)


def pipeline_burn_cleanup(args: argparse.Namespace, episode_dir: Path, videos: list[Path]) -> None:
    helper = str(Path(__file__).resolve())
    pipeline_run([sys.executable, helper, "final-ready", str(episode_dir)], dry_run=args.dry_run)
    for media in videos:
        final = media.with_suffix(".srt")
        pipeline_run(
            [
                sys.executable,
                helper,
                "burn",
                str(media),
                "--subtitle",
                str(final),
                "--encoder",
                args.encoder,
                "--replace-source",
            ],
            dry_run=args.dry_run,
        )
        pipeline_run([sys.executable, helper, "screenshot-check", str(media), "--subtitle", str(final)], dry_run=args.dry_run)
    print("[pipeline] inspect generated contact sheets before cleanup.")
    if args.cleanup_confirmed:
        sentinel = episode_dir / CLEANUP_SENTINEL
        if not args.dry_run:
            sentinel.write_text("", encoding="utf-8")
        print(f"[pipeline] screenshot QA confirmed; sentinel written: {sentinel.name}")
    if args.cleanup:
        sentinel = episode_dir / CLEANUP_SENTINEL
        if sentinel.exists() or args.cleanup_confirmed:
            pipeline_run([sys.executable, helper, "cleanup", str(episode_dir)], dry_run=args.dry_run)
        else:
            raise SystemExit(
                "[pipeline] --cleanup requested but screenshot QA is not confirmed. "
                f"Inspect contact sheets, then rerun with --cleanup-confirmed to write {CLEANUP_SENTINEL}."
            )


def pipeline(args: argparse.Namespace) -> None:
    episode_dir = Path(args.episode_dir).resolve()
    if not episode_dir.exists():
        raise SystemExit(f"Episode directory not found: {episode_dir}")
    if args.summary_only and args.stage != "post-review":
        raise SystemExit("summary-only scope allows only --stage post-review; do not organize, transcribe, burn, or cleanup MP4s.")

    planned_videos: list[Path] = []
    if args.stage == "prepare-review":
        planned_videos = pipeline_organize_root_mp4s(episode_dir, dry_run=args.dry_run)
    videos = pipeline_episode_videos(episode_dir)
    if args.dry_run and args.stage == "prepare-review" and not videos:
        videos = planned_videos
    if not videos and args.summary_only:
        if not iter_final_srt_paths(episode_dir):
            raise SystemExit(f"No final Chinese SRT files found under {episode_dir} for summary-only mode")
    elif not videos:
        raise SystemExit(f"No per-video MP4 files found under {episode_dir}")

    glossaries = pipeline_existing_glossaries(episode_dir, args.glossary)
    print(f"[pipeline] stage={args.stage} videos={len(videos)} glossaries={len(glossaries)} dry_run={args.dry_run}")

    try:
        pipeline_record_manifest(args, episode_dir, videos, glossaries, "running")
        if args.stage == "prepare-review":
            pipeline_prepare_review(args, episode_dir, videos, glossaries)
        elif args.stage == "post-review":
            pipeline_post_review(args, episode_dir, videos, glossaries)
        elif args.stage == "burn-cleanup":
            pipeline_burn_cleanup(args, episode_dir, videos)
        pipeline_record_manifest(args, episode_dir, videos, glossaries, "complete")
    except Exception as exc:
        pipeline_record_manifest(args, episode_dir, videos, glossaries, "failed", str(exc))
        raise


def self_test(args: argparse.Namespace) -> None:
    workdir = Path(args.workdir).resolve() if args.workdir else Path(tempfile.mkdtemp(prefix="hoooope_self_test_"))
    workdir.mkdir(parents=True, exist_ok=True)

    subsplit = workdir / "subsplit_cases.srt"
    subsplit.write_text(
        """1
00:10:19,100 --> 00:10:30,570
我在会员限定视频里看到“剥长橘子皮”企划，回老家时也挑战了一下。

2
00:11:13,520 --> 00:11:20,680
这个也是Culture的会员限定视频，那个，大家知道橘子吗？

3
00:47:03,005 --> 00:47:10,430
虽然也会被说“赶紧吃掉”，但最后还是会说着“真拿你没办法啊”然后帮我收拾掉。

4
00:00:00,000 --> 00:00:03,800
这是一个字数超过二十四但是时间比较短，仍然可以尝试拆分的例子。
""",
        encoding="utf-8-sig",
    )
    wrapped = workdir / "subsplit_cases.wrapped.srt"
    wrap_final(argparse.Namespace(
        subtitle=str(subsplit),
        output=str(wrapped),
        max_line_chars=28,
        max_line_width=56.0,
        sub_split_duration_seconds=5.5,
        sub_split_chars=24,
        sub_split_min_chars=14,
        sub_split_min_side_chars=5,
        sub_split_min_duration_seconds=1.2,
        no_sub_split=False,
        dry_run=False,
    ))
    wrapped_text = wrapped.read_text(encoding="utf-8-sig")
    for expected in ("剥长橘子皮", "会员限定视频", "真拿你没办法"):
        if expected not in wrapped_text:
            raise SystemExit(f"self-test failed: missing preserved Chinese text {expected!r}")

    tail = workdir / "tail.orig.srt"
    tail.write_text(
        """1
00:00:22,000 --> 00:00:24,650
今週のメールテーマは

2
00:00:24,760 --> 00:00:30,650
最近ちょっと嬉しかったことです

3
00:00:30,760 --> 00:00:35,470
皆さんからたくさん投稿をいただきました
""",
        encoding="utf-8-sig",
    )
    tail_smooth = workdir / "tail.smooth.srt"
    smooth_source_srt(argparse.Namespace(
        subtitle=str(tail),
        output=str(tail_smooth),
        merge_gap_seconds=6.0,
        max_merged_chars=60,
        max_merged_duration_seconds=12.0,
        min_semantic_chars=14,
        comfort_semantic_chars=24,
        min_semantic_duration_seconds=2.0,
        orphan_fragment_chars=2,
        orphan_merge_gap_seconds=14.0,
        orphan_max_merged_duration_seconds=18.0,
        tail_fragment_chars=10,
        tail_merge_gap_seconds=6.0,
        tail_max_merged_duration_seconds=18.0,
        tail_chain_merge_gap_seconds=6.0,
        tail_chain_max_chars=96,
        tail_chain_max_duration_seconds=22.0,
        split_duration_seconds=8.0,
        split_chars=42,
    ))
    if "メールテーマ" not in tail_smooth.read_text(encoding="utf-8-sig"):
        raise SystemExit("self-test failed: Japanese source text was not preserved")

    homophone = workdir / "homophone.orig.srt"
    homophone.write_text(
        """1
00:00:01,000 --> 00:00:03,000
イラストを描く時に

2
00:00:03,100 --> 00:00:05,000
某人間みたいになって

3
00:00:05,100 --> 00:00:07,000
投稿するのが恥ずかしいです
""",
        encoding="utf-8-sig",
    )
    audit = workdir / "homophone.audit.txt"
    orig_audit(argparse.Namespace(
        subtitle=str(homophone),
        output=str(audit),
        min_chars=2,
        short_text_chars=8,
        long_duration_seconds=12.0,
        context_window=2,
        fail_on_issues=False,
    ))
    audit_text = audit.read_text(encoding="utf-8-sig")
    if "verify against surrounding context" not in audit_text or "suggested source patch" in audit_text:
        raise SystemExit("self-test failed: homophone audit should report context risk without a fixed patch")

    split_matrix = [
        ("虽然也会被说“赶紧吃掉”，但最后还是会说着“真拿你没办法啊”然后帮我收拾掉。", 13),
        ("HOOOOPE Battle这个环节听起来很简单，但是真的开始之后又意外地很难呢。", 25),
        ("我在想如果是那种有点害羞的时候，可能就会怎么说呢……稍微停顿一下吧。", 16),
    ]
    for line, expected_index in split_matrix:
        candidates = readable_split_candidates(line)
        actual_index = min(candidates, key=lambda idx: split_candidate_score(line, idx, 28, 56.0))
        if actual_index != expected_index:
            raise SystemExit(f"self-test failed: split index changed for {line!r}: {actual_index} != {expected_index}")

    glossary_terms = workdir / "prompt_terms.txt"
    glossary_terms.write_text("\n".join(f"普通术语{i}" for i in range(120)), encoding="utf-8")
    prompt = build_initial_prompt(argparse.Namespace(
        no_initial_prompt=False,
        audit_rules=[],
        initial_prompt_file=[],
        glossary=[str(glossary_terms)],
        initial_prompt="羊宮妃那のこもれびじかん,羊宫妃那的林荫时光",
        initial_prompt_terms=40,
        verbose_prompt_sources=False,
    ))
    prompt_tail = (prompt or "").split("、")[-20:]
    if "羊宮妃那のこもれびじかん" not in prompt_tail or "羊宫妃那的林荫时光" not in prompt_tail:
        raise SystemExit("self-test failed: high-priority ASR prompt terms were not kept in tail")

    import deepseek_polish_srt as polish_mod
    import deepseek_translate_srt as translate_mod

    class FakeResponse:
        def __init__(self, content: str):
            self.content = content

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": self.content}}]}

    def translate_fixture(blocks: list[str], changed_time: bool = False) -> str:
        output_blocks: list[str] = []
        for block in blocks:
            lines = block.splitlines()
            timing = "00:00:09,000 --> 00:00:10,000" if changed_time else lines[1]
            output_blocks.append("\n".join([lines[0], timing, "测试译文"]))
        return "\n\n".join(output_blocks)

    def extract_translate_blocks(payload: dict) -> list[str]:
        text = payload["messages"][1]["content"].split("需要翻译并输出的 SRT 分块：", 1)[1]
        return translate_mod.read_blocks_from_text(text)

    source_for_translate = workdir / "translate.orig.srt"
    source_for_translate.write_text(
        """1
00:00:01,000 --> 00:00:02,000
こんにちは

2
00:00:03,000 --> 00:00:04,000
こんばんは
""",
        encoding="utf-8-sig",
    )
    translated_out = workdir / "translate.zh.srt"
    original_translate_post = translate_mod.requests.post
    try:
        def fake_translate_post(url, headers=None, json=None, timeout=None):  # noqa: ANN001
            return FakeResponse("```srt\n" + translate_fixture(extract_translate_blocks(json)) + "\n```")

        translate_mod.requests.post = fake_translate_post
        translate_mod.translate(argparse.Namespace(
            input=str(source_for_translate),
            output=str(translated_out),
            api_key="test",
            base_url="https://example.invalid",
            model="test-model",
            temperature=0.0,
            timeout=1,
            retries=1,
            retry_wait=0,
            sleep=0,
            force=True,
            glossary=[],
            cache_dir=str(workdir / "translate_cache"),
            qa_output=None,
            qa_sample_ratio=0.5,
            chunk_size=1,
            workers=2,
            context_blocks=1,
            alignment_mode="strict",
        ))
        translated_blocks = translate_mod.read_blocks(translated_out)
        if len(translated_blocks) != 2 or translate_mod.block_header(translated_blocks[1]) != ("2", "00:00:03,000 --> 00:00:04,000"):
            raise SystemExit("self-test failed: workers=2 translation did not preserve block headers")

        legacy_out = workdir / "translate.legacy.zh.srt"
        translate_mod.translate(argparse.Namespace(
            input=str(source_for_translate),
            output=str(legacy_out),
            api_key="test",
            base_url="https://example.invalid",
            model="test-model",
            temperature=0.0,
            timeout=1,
            retries=1,
            retry_wait=0,
            sleep=0,
            force=True,
            glossary=[],
            cache_dir=str(workdir / "translate_legacy_cache"),
            qa_output=None,
            qa_sample_ratio=0.5,
            chunk_size=20,
            workers=1,
            context_blocks=1,
            alignment_mode="strict",
        ))
        if len(translate_mod.read_blocks(legacy_out)) != 2:
            raise SystemExit("self-test failed: workers=1 legacy translation path did not produce all blocks")

        def fake_changed_time_post(url, headers=None, json=None, timeout=None):  # noqa: ANN001
            return FakeResponse(translate_fixture(extract_translate_blocks(json), changed_time=True))

        translate_mod.requests.post = fake_changed_time_post
        fixed = translate_mod.translate_chunk(
            translate_mod.read_blocks(source_for_translate)[:1],
            "",
            argparse.Namespace(
                api_key="test",
                base_url="https://example.invalid",
                model="test-model",
                temperature=0.0,
                timeout=1,
                retries=1,
                retry_wait=0,
                force=True,
            ),
            1,
        )
        if translate_mod.block_header(fixed[0])[1] != "00:00:01,000 --> 00:00:02,000":
            raise SystemExit("self-test failed: changed translation timestamp was not repaired")

        def fake_mismatch_post(url, headers=None, json=None, timeout=None):  # noqa: ANN001
            return FakeResponse("")

        translate_mod.requests.post = fake_mismatch_post
        try:
            translate_mod.translate_chunk(
                translate_mod.read_blocks(source_for_translate)[:1],
                "",
                argparse.Namespace(
                    api_key="test",
                    base_url="https://example.invalid",
                    model="test-model",
                    temperature=0.0,
                    timeout=1,
                    retries=1,
                    retry_wait=0,
                    force=True,
                ),
                1,
            )
        except RuntimeError:
            pass
        else:
            raise SystemExit("self-test failed: block count mismatch did not fail")
    finally:
        translate_mod.requests.post = original_translate_post

    polish_args = argparse.Namespace(model="test-model", temperature=0.1, chunk_size=50, workers=2)
    polish_cache = workdir / "polish.part001.polished.srt"
    zh_blocks = translate_mod.read_blocks(translated_out)
    polish_mod.write_blocks(polish_cache, zh_blocks)
    polish_mod.write_input_hash(polish_cache, polish_mod.blocks_hash(translate_mod.read_blocks(source_for_translate), zh_blocks))
    dep_a = polish_mod.polish_dependency_hash("术语A", polish_args)
    polish_mod.write_dependency_hash(polish_cache, dep_a)
    if polish_mod.cached_polish_valid(polish_cache, translate_mod.read_blocks(source_for_translate), zh_blocks, dep_a) is None:
        raise SystemExit("self-test failed: polish dependency cache should be valid")
    dep_b = polish_mod.polish_dependency_hash("术语B", polish_args)
    if polish_mod.cached_polish_valid(polish_cache, translate_mod.read_blocks(source_for_translate), zh_blocks, dep_b) is not None:
        raise SystemExit("self-test failed: polish dependency cache did not invalidate after glossary change")

    print(f"self-test ok workdir={workdir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="HOOOOPE Japanese transcription and subtitle burning helper.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("transcribe", help="Transcribe Japanese speech to <stem>.orig.srt")
    p.add_argument("media")
    p.add_argument("--model-dir", default=DEFAULT_TRANSCRIBE_MODEL_DIR)
    p.add_argument("--output")
    p.add_argument("--device", choices=["cuda", "cpu"])
    p.add_argument("--compute-type", choices=["float16", "int8_float16", "int8", "float32"])
    p.add_argument("--beam-size", type=int, default=5)
    p.add_argument("--glossary", action="append", default=["hoooope_terms.txt", "model/hoooope_terms.txt", "hooope_terms.txt", "model/hooope_terms.txt"])
    p.add_argument("--initial-prompt")
    p.add_argument("--initial-prompt-file", action="append")
    p.add_argument("--initial-prompt-terms", type=int, default=80)
    p.add_argument("--no-initial-prompt", action="store_true")
    p.add_argument("--audit-rules", action="append", help="Optional audit_rules.json file; can be passed multiple times")
    p.add_argument("--verbose-prompt-sources", action="store_true", help="Print ASR initial_prompt source counts")
    p.add_argument("--vad-onnx", help="Path to local silero_vad.onnx; defaults to model/silero_vad.onnx")
    p.add_argument("--regroup", default=DEFAULT_STABLE_REGROUP)
    p.add_argument("--audio-sample-rate", type=int, default=16000)
    p.add_argument("--no-speech-threshold", type=float, default=0.6)
    p.add_argument("--asr-audio-mode", choices=["loudnorm", "vocal-isolate", "auto-ab"], default="loudnorm")
    p.add_argument("--vocal-separator", choices=["demucs", "mdx"], default="demucs")
    p.add_argument("--demucs-model", default="htdemucs")
    p.add_argument("--auto-ab-sample-seconds", type=float, default=30.0)
    p.add_argument("--auto-ab-min-sample-seconds", type=float, default=5.0)
    p.add_argument("--auto-ab-ratio-threshold", type=float, default=0.9)
    p.add_argument("--auto-ab-statistic", choices=["median", "average"], default="median")
    p.add_argument("--keep-asr-audio", action="store_true")
    p.set_defaults(func=transcribe)

    p = sub.add_parser("validate", help="Validate basic SRT numbering and timestamps")
    p.add_argument("subtitle")
    p.set_defaults(func=validate)

    p = sub.add_parser("normalize-punctuation", help="Normalize punctuation in subtitle text lines only")
    p.add_argument("target", help="Final SRT file or episode directory")
    p.add_argument("--output", help="Output path; only valid for a single input SRT")
    p.add_argument("--ascii-ellipsis", action="store_true", help="Convert ... to …… in subtitle text")
    p.add_argument("--ascii-quotes", action="store_true", help="Convert straight double quotes to Chinese closing quotes in subtitle text")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=normalize_punctuation)

    p = sub.add_parser("smooth-source", help="Merge/split Japanese source SRT into subtitle-friendly semantic blocks")
    p.add_argument("subtitle")
    p.add_argument("--output")
    p.add_argument("--merge-gap-seconds", type=float, default=6.0)
    p.add_argument("--max-merged-chars", type=int, default=60)
    p.add_argument("--max-merged-duration-seconds", type=float, default=12.0)
    p.add_argument("--min-semantic-chars", type=int, default=14)
    p.add_argument("--comfort-semantic-chars", type=int, default=24)
    p.add_argument("--min-semantic-duration-seconds", type=float, default=2.0)
    p.add_argument("--orphan-fragment-chars", type=int, default=2)
    p.add_argument("--orphan-merge-gap-seconds", type=float, default=14.0)
    p.add_argument("--orphan-max-merged-duration-seconds", type=float, default=18.0)
    p.add_argument("--tail-fragment-chars", type=int, default=10)
    p.add_argument("--tail-merge-gap-seconds", type=float, default=6.0)
    p.add_argument("--tail-max-merged-duration-seconds", type=float, default=18.0)
    p.add_argument("--tail-chain-merge-gap-seconds", type=float, default=6.0)
    p.add_argument("--tail-chain-max-chars", type=int, default=96)
    p.add_argument("--tail-chain-max-duration-seconds", type=float, default=22.0)
    p.add_argument("--split-duration-seconds", type=float, default=8.0)
    p.add_argument("--split-chars", type=int, default=42)
    p.set_defaults(func=smooth_source_srt)

    p = sub.add_parser("orig-audit", help="Audit Japanese source SRT for likely ASR source errors")
    p.add_argument("subtitle")
    p.add_argument("--output")
    p.add_argument("--min-chars", type=int, default=2)
    p.add_argument("--short-text-chars", type=int, default=8)
    p.add_argument("--long-duration-seconds", type=float, default=12.0)
    p.add_argument("--context-window", type=int, default=2)
    p.add_argument("--fail-on-issues", action="store_true")
    p.add_argument("--audit-rules", action="append", help="Optional audit_rules.json file; can be passed multiple times")
    p.set_defaults(func=orig_audit)

    p = sub.add_parser("qwen-compare", help="Run Qwen3-ASR on high-risk source segments and write a comparison report")
    p.add_argument("media")
    p.add_argument("--orig", required=True, help="Whisper-produced Japanese source SRT")
    p.add_argument("--audit", help="orig-audit report used to select risk segments")
    p.add_argument("--output")
    p.add_argument("--qwen-model-dir", default=DEFAULT_QWEN_ASR_MODEL_DIR)
    p.add_argument("--max-segments", type=int, default=24)
    p.add_argument("--batch-size", type=int, default=4)
    p.add_argument("--max-new-tokens", type=int, default=256)
    p.add_argument("--padding-seconds", type=float, default=1.0)
    p.add_argument("--audio-sample-rate", type=int, default=16000)
    p.add_argument("--keep-segments", action="store_true")
    p.add_argument("--required", action="store_true", help="Fail instead of writing a skipped report when Qwen runtime is unavailable")
    p.set_defaults(func=qwen_compare)

    p = sub.add_parser("lint-final", help="Lint final Chinese SRT for residue, terms, and readable line length")
    p.add_argument("subtitle")
    p.add_argument("--max-line-chars", type=int, default=28)
    p.add_argument("--max-line-width", type=float, default=56.0)
    p.add_argument("--max-duration-seconds", type=float, default=30.0)
    p.add_argument("--max-report", type=int, default=120)
    p.add_argument("--strict-public", action="store_true")
    p.add_argument("--warn-only", action="store_true")
    p.set_defaults(func=lint_final)

    p = sub.add_parser("terms-audit", help="Audit final SRT for suspicious names, brands, and fixed terms")
    p.add_argument("subtitle")
    p.add_argument("--max-report", type=int, default=160)
    p.add_argument("--warn-only", action="store_true")
    p.add_argument("--audit-rules", action="append", help="Optional audit_rules.json file; can be passed multiple times")
    p.set_defaults(func=terms_audit)

    p = sub.add_parser("wrap-final", help="Conservatively wrap long final Chinese subtitle lines")
    p.add_argument("subtitle")
    p.add_argument("--output")
    p.add_argument("--max-line-chars", type=int, default=28)
    p.add_argument("--max-line-width", type=float, default=56.0)
    p.add_argument("--sub-split-duration-seconds", type=float, default=5.5)
    p.add_argument("--sub-split-chars", type=int, default=24)
    p.add_argument("--sub-split-min-chars", type=int, default=14)
    p.add_argument("--sub-split-min-side-chars", type=int, default=5)
    p.add_argument("--sub-split-min-duration-seconds", type=float, default=1.2)
    p.add_argument("--no-sub-split", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=wrap_final)

    p = sub.add_parser("review-todo", help="Create a review todo file from high-risk JA/ZH subtitle blocks")
    p.add_argument("--orig", required=True)
    p.add_argument("--final", required=True)
    p.add_argument("--output")
    p.add_argument("--length-ratio", action="store_true", default=True)
    p.add_argument("--min-ratio", type=float, default=0.25)
    p.add_argument("--max-ratio", type=float, default=2.8)
    p.add_argument("--include-all-long", action="store_true")
    p.add_argument("--long-text-chars", type=int, default=42)
    p.add_argument("--text-limit", type=int, default=120)
    p.set_defaults(func=review_todo)

    p = sub.add_parser("proper-noun-candidates", help="Extract possible proper nouns from Japanese source SRT")
    p.add_argument("orig")
    p.add_argument("--output")
    p.add_argument("--min-chars", type=int, default=3)
    p.add_argument("--max-terms", type=int, default=120)
    p.set_defaults(func=proper_noun_candidates)

    p = sub.add_parser("split-srt", help="Split an SRT into numbered chunks for LLM translation")
    p.add_argument("subtitle")
    p.add_argument("--chunk-size", type=int, default=60)
    p.add_argument("--output-dir")
    p.set_defaults(func=split_srt)

    p = sub.add_parser("merge-srt", help="Merge translated SRT chunks and validate numbering")
    p.add_argument("chunk_dir")
    p.add_argument("--output", required=True)
    p.set_defaults(func=merge_srt)

    p = sub.add_parser("summary-template", help="Create a Chinese episode summary .txt template")
    p.add_argument("media")
    p.add_argument("--subtitle", required=True)
    p.add_argument("--output")
    p.set_defaults(func=summary_template)

    p = sub.add_parser("burn", help="Burn a polished Chinese SRT into an MP4")
    p.add_argument("media")
    p.add_argument("--subtitle", required=True)
    p.add_argument("--output")
    p.add_argument("--font", default="Microsoft YaHei")
    p.add_argument("--font-size", type=int, default=22)
    p.add_argument("--outline", type=int, default=2)
    p.add_argument("--margin-v", type=int, default=24)
    p.add_argument("--crf", type=int, default=18)
    p.add_argument("--preset", default="medium")
    p.add_argument("--encoder", choices=["auto", "h264_nvenc", "libx264"], default="auto")
    p.add_argument("--cq", type=int, default=20)
    p.add_argument("--nvenc-preset", default="p5")
    p.add_argument("--audio-bitrate", default="160k")
    p.add_argument("--replace-source", action="store_true", help="Replace the input video after successful burn and duration check")
    p.add_argument("--duration-tolerance", type=float, default=1.0)
    p.set_defaults(func=burn)

    p = sub.add_parser("verify-duration", help="Verify source/output durations differ by no more than tolerance")
    p.add_argument("source")
    p.add_argument("output")
    p.add_argument("--tolerance", type=float, default=1.0)
    p.set_defaults(func=verify_duration)

    p = sub.add_parser("screenshot-check", help="Create sampled frames and a contact sheet for burned subtitle QA")
    p.add_argument("media")
    p.add_argument("--subtitle")
    p.add_argument("--output-dir")
    p.add_argument("--percent", type=float, nargs="+", default=[5, 25, 50, 75, 95])
    p.add_argument("--subtitle-frames", type=int, default=3)
    p.add_argument("--thumb-width", type=int, default=480)
    p.add_argument("--columns", type=int, default=4)
    p.add_argument("--rows", type=int, default=2)
    p.set_defaults(func=screenshot_check)

    p = sub.add_parser("cleanup", help="Remove DeepSeek QA/raw/polished/check intermediate artifacts from an episode folder")
    p.add_argument("episode_dir")
    p.add_argument("--force", action="store_true", help="Skip screenshot QA sentinel check")
    p.set_defaults(func=cleanup)

    p = sub.add_parser("combine-summaries", help="Combine per-video summary files into one episode-level note")
    p.add_argument("episode_dir")
    p.add_argument("--output")
    p.add_argument("--keep-parts", action="store_true", help="Keep per-video summary files after combining")
    p.add_argument("--max-chars", type=int, default=3000)
    p.add_argument("--min-chars", type=int, default=1500)
    p.add_argument("--warn-only", action="store_true")
    p.set_defaults(func=combine_summaries)

    p = sub.add_parser("final-ready", help="Run final pre-burn/pre-cleanup readiness checks for an episode folder")
    p.add_argument("episode_dir")
    p.add_argument("--max-line-chars", type=int, default=28)
    p.add_argument("--max-line-width", type=float, default=56.0)
    p.add_argument("--max-duration-seconds", type=float, default=30.0)
    p.add_argument("--max-summary-chars", type=int, default=3000)
    p.add_argument("--min-summary-chars", type=int, default=1500)
    p.add_argument("--max-report", type=int, default=120)
    p.add_argument("--warn-only", action="store_true")
    p.set_defaults(func=final_ready)

    p = sub.add_parser("baseline-report", help="Report subtitle quality and style-energy baseline metrics")
    p.add_argument("target", help="Final SRT file or episode directory")
    p.add_argument("--output")
    p.set_defaults(func=baseline_lib.baseline_report)

    p = sub.add_parser("pipeline", help="Run the staged HOOOOPE production coordinator")
    p.add_argument("episode_dir")
    p.add_argument(
        "--stage",
        choices=["prepare-review", "post-review", "burn-cleanup"],
        default="prepare-review",
        help="prepare-review runs ASR/DeepSeek and stops for Codex proofread; post-review runs local QA and notes; burn-cleanup burns after QA.",
    )
    p.add_argument("--dry-run", action="store_true", help="Print commands without executing them")
    p.add_argument("--summary-only", action="store_true", help="Guard against MP4 organization, burn, or cleanup")
    p.add_argument("--skip-asr", action="store_true", help="Require existing .orig.srt files instead of transcribing")
    p.add_argument("--force-deepseek", action="store_true", help="Force DeepSeek translation/polish reruns")
    p.add_argument("--model-dir", default=DEFAULT_TRANSCRIBE_MODEL_DIR)
    p.add_argument("--vad-onnx", default=PIPELINE_DEFAULT_VAD_ONNX)
    p.add_argument("--asr-enhancement", choices=["qwen-risk", "qwen-risk-required", "off"], default="qwen-risk", help="Run Qwen3-ASR risk-segment comparison after Whisper source audit")
    p.add_argument("--qwen-model-dir", default=DEFAULT_QWEN_ASR_MODEL_DIR)
    p.add_argument("--qwen-max-segments", type=int, default=24)
    p.add_argument("--force-asr-compare", action="store_true", help="Regenerate ASR comparison reports even if sidecars exist")
    p.add_argument("--glossary", action="append", default=[])
    p.add_argument("--translate-workers", type=int, default=PIPELINE_TRANSLATE_WORKERS, help="DeepSeek initial translation workers; 1 uses the legacy serial overlap path")
    p.add_argument("--translate-context-blocks", type=int, default=PIPELINE_TRANSLATE_CONTEXT_BLOCKS, help="Read-only context blocks for concurrent initial translation")
    p.add_argument("--encoder", choices=["auto", "h264_nvenc", "libx264"], default="auto")
    p.add_argument("--cleanup", action="store_true", help="Request intermediate cleanup after burn-cleanup")
    p.add_argument("--cleanup-confirmed", action="store_true", help="Write screenshot QA sentinel file to enable cleanup")
    p.set_defaults(func=pipeline)

    p = sub.add_parser("doctor", help="Check local HOOOOPE subtitle dependencies without network access")
    p.add_argument("episode_dir", nargs="?", help="Episode directory used to resolve local glossary/model paths")
    p.add_argument("--model-dir", default=DEFAULT_TRANSCRIBE_MODEL_DIR)
    p.add_argument("--qwen-model-dir", default=DEFAULT_QWEN_ASR_MODEL_DIR)
    p.add_argument("--vad-onnx", default=PIPELINE_DEFAULT_VAD_ONNX)
    p.add_argument("--glossary", action="append", default=[])
    p.set_defaults(func=doctor)

    p = sub.add_parser("self-test", help="Run UTF-8-safe helper regression tests")
    p.add_argument("--workdir", help="Optional directory for generated test fixtures; defaults to a system temp directory")
    p.set_defaults(func=self_test)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
