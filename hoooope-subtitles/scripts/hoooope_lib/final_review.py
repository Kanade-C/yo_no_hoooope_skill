from __future__ import annotations

import argparse
import re
from pathlib import Path

from . import audit_rules as audit_rules_lib
from . import srt_util as srt_util_lib
from .srt_util import iter_srt_entries, require_file
from .config import (
    ASCII_PUNCT_RE,
    ASR_SUSPICIOUS_OPEN_RE,
    AIUEO_COMPOSITION_MISHEAR_RE,
    BAD_FIXED_TERMS,
    BAD_HOST_TERMS,
    HOOOOPE_ACCOUNT_MISHEAR_RE,
    HOOOOPE_OPENING_MISHEAR_RE,
    HOOOOPE_TITLE_MISHEAR_RE,
    HOOPE_RE,
    JA_RE,
    KANA_NICKNAME_RE,
    KATAKANA_TERM_RE,
    LATIN_TERM_RE,
    SUSPICIOUS_TERMS,
    TITLE_LIKE_RE,
    TONE_MARKERS,
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


def validate_srt_file(path: Path) -> tuple[int, list[int]]:
    try:
        return srt_util_lib.validate_file(path)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc)) from exc


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
    if any(srt_util_lib.display_width(line) > 56 for line in text.splitlines()):
        reasons.append("显示宽度")
    if any(len(line) > 28 for line in text.splitlines()):
        reasons.append("长行")
    try:
        start_raw, end_raw = [part.strip() for part in timing.split("-->", 1)]
        duration = srt_util_lib.parse_srt_time(end_raw) - srt_util_lib.parse_srt_time(start_raw)
        if duration > 30:
            reasons.append(f"超长时间轴{duration:.1f}s")
    except (ValueError, IndexError):
        reasons.append("时间轴异常")
    if any(marker in text for marker in TONE_MARKERS):
        reasons.append("语气抽查")
    if re.search(r"[？！…]|哈哈|诶|哎|咦|啊", text):
        reasons.append("反应/笑点")
    if args is not None and args.include_all_long and len(text) >= args.long_text_chars:
        reasons.append("长句信息量")
    return reasons


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
            duration = srt_util_lib.parse_srt_time(end_raw) - srt_util_lib.parse_srt_time(start_raw)
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
            width = srt_util_lib.display_width(line)
            if width > args.max_line_width:
                issues.append(f"[显示宽度过长] #{number}: {width:.1f} units: {line}")
            if args.strict_public and ASCII_PUNCT_RE.search(line):
                issues.append(f"[公开发布标点需统一] #{number}: {line}")
        try:
            start_raw, end_raw = [part.strip() for part in timing.split("-->", 1)]
            duration = srt_util_lib.parse_srt_time(end_raw) - srt_util_lib.parse_srt_time(start_raw)
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
