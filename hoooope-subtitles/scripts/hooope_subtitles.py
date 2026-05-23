from __future__ import annotations

import argparse
import re
import subprocess
import sys
import unicodedata
from pathlib import Path


MEDIA_EXTS = {".ts", ".mp4", ".mkv", ".mov", ".webm", ".m4a", ".mp3", ".wav", ".flac"}
JA_RE = re.compile(r"[\u3040-\u30ff]")
HOOPE_RE = re.compile(r"\bHO+PE\b")
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


def find_term_issues(text: str) -> list[str]:
    issues: list[str] = []
    for bad_term, suggestion in BAD_FIXED_TERMS.items():
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
    required = [
        "model.bin",
        "config.json",
        "tokenizer.json",
        "vocabulary.json",
        "preprocessor_config.json",
    ]
    missing = [name for name in required if not (model_dir / name).exists()]
    if missing:
        raise SystemExit(f"Model folder is missing: {', '.join(missing)} in {model_dir}")
    return model_dir


def load_model(model_dir: Path, device: str | None):
    from faster_whisper import WhisperModel

    attempts: list[tuple[str, str]] = []
    if device:
        attempts.append((device, "float16" if device == "cuda" else "int8"))
    else:
        attempts.extend([("cuda", "float16"), ("cuda", "int8_float16"), ("cpu", "int8")])

    errors: list[str] = []
    for dev, compute_type in attempts:
        try:
            model = WhisperModel(str(model_dir), device=dev, compute_type=compute_type)
            print(f"Using {dev} {compute_type}")
            return model
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{dev}/{compute_type}: {exc}")

    raise SystemExit("Could not load faster-whisper model:\n" + "\n".join(errors))


def transcribe(args: argparse.Namespace) -> None:
    src = require_file(Path(args.media), "Media file")
    if src.suffix.lower() not in MEDIA_EXTS:
        raise SystemExit(f"Unsupported media extension: {src.suffix}")

    model_dir = validate_model(Path(args.model_dir))
    out = Path(args.output) if args.output else src.with_suffix(".orig.srt")
    model = load_model(model_dir, args.device)

    segments, info = model.transcribe(
        str(src),
        language="ja",
        task="transcribe",
        beam_size=args.beam_size,
        vad_filter=True,
        word_timestamps=False,
    )
    print(f"Detected language: {info.language} ({info.language_probability:.2f})")

    blocks: list[str] = []
    index = 1
    for segment in segments:
        text = " ".join(segment.text.strip().split())
        if not text:
            continue
        blocks.extend(
            [
                str(index),
                f"{fmt_time(segment.start)} --> {fmt_time(segment.end)}",
                text,
                "",
            ]
        )
        index += 1

    out.write_text("\n".join(blocks), encoding="utf-8-sig")
    print(f"Wrote {out.resolve()}")


def validate_srt_file(path: Path) -> tuple[int, list[int]]:
    text = require_file(path, "Subtitle file").read_text(encoding="utf-8-sig")
    blocks = [block for block in text.strip().split("\n\n") if block.strip()]
    bad: list[int] = []
    for expected, block in enumerate(blocks, start=1):
        lines = block.splitlines()
        if len(lines) < 3 or lines[0].strip() != str(expected) or "-->" not in lines[1]:
            bad.append(expected)
    return len(blocks), bad


def read_srt_blocks(path: Path) -> list[str]:
    text = require_file(path, "Subtitle file").read_text(encoding="utf-8-sig")
    return [block.strip() for block in text.strip().split("\n\n") if block.strip()]


def write_srt_blocks(path: Path, blocks: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n\n".join(blocks).strip() + "\n", encoding="utf-8-sig")


def validate(args: argparse.Namespace) -> None:
    count, bad = validate_srt_file(Path(args.subtitle))
    print(f"blocks={count}, bad={bad[:20]}")
    if bad:
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
                    f"[字幕持续过长需人工确认] #{number}: {duration:.1f}s: {text.replace(chr(10), ' / ')}"
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
    issues: list[str] = []
    if bad:
        issues.append(f"[结构错误] blocks={count}, bad={bad[:20]}")

    for number, _timing, text_lines in iter_srt_entries(subtitle):
        text = "\n".join(text_lines)
        for issue in find_term_issues(text):
            issues.append(f"[固定译名疑似错误] #{number}: {issue}: {text.replace(chr(10), ' / ')}")
        for term in SUSPICIOUS_TERMS:
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
    rows = ["# Proper noun candidates", ""]
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

————————————

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
            step = max(1, len(subtitle_times) // max(1, args.subtitle_frames))
            times.extend(subtitle_times[::step][: args.subtitle_frames])

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

    patterns = [
        "*.deepseek.raw.srt",
        "*.deepseek.polished.srt",
        "*.qa.txt",
        "*.zh.burned.mp4",
        "*.burned.tmp.mp4",
        "*.subtitle_check.jpg",
        "*subtitle_check*.jpg",
        "*.contact_sheet.jpg",
        "*.check.*.jpg",
        "*.review.todo.txt",
        "*.proper-nouns.txt",
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
    cache_paths.extend(path for path in episode_dir.rglob("*deepseek*cache*") if path.is_dir())
    cache_paths.extend(path for path in episode_dir.rglob("*deepseek*chunks*") if path.is_dir())
    cache_paths.extend(path for path in episode_dir.rglob("*screenshot_check") if path.is_dir())
    for path in sorted(set(cache_paths)):
        if path.exists() and path.is_dir():
            if (path / ".keep").exists() or (path / ".no_cleanup").exists():
                print(f"Skipping preserved directory {path}")
                continue
            import shutil

            shutil.rmtree(path)
            removed.append(path)

    print(f"Removed {len(removed)} intermediate artifacts")
    for path in removed:
        print(path)


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
    combined = ("\n\n————————————\n\n").join(sections).strip() + "\n"
    out.write_text(combined, encoding="utf-8-sig")
    char_count = chinese_char_count(combined)
    print(f"Wrote combined summary {out.resolve()} from {len(summary_files)} files")
    print(f"summary_chinese_chars={char_count}")
    if char_count > args.max_chars and not args.warn_only:
        raise SystemExit(f"Combined summary exceeds {args.max_chars} Chinese chars: {char_count}")
    if char_count > args.max_chars:
        print(f"[summary length warning] exceeds {args.max_chars} Chinese chars: {char_count}")
    if not args.keep_parts:
        for path in summary_files:
            path.unlink()
            print(f"Removed per-video summary {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="HOOOOPE Japanese transcription and subtitle burning helper.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("transcribe", help="Transcribe Japanese speech to <stem>.orig.srt")
    p.add_argument("media")
    p.add_argument("--model-dir", default="model")
    p.add_argument("--output")
    p.add_argument("--device", choices=["cuda", "cpu"])
    p.add_argument("--beam-size", type=int, default=5)
    p.set_defaults(func=transcribe)

    p = sub.add_parser("validate", help="Validate basic SRT numbering and timestamps")
    p.add_argument("subtitle")
    p.set_defaults(func=validate)

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
    p.set_defaults(func=terms_audit)

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
    p.set_defaults(func=cleanup)

    p = sub.add_parser("combine-summaries", help="Combine per-video summary files into one episode-level note")
    p.add_argument("episode_dir")
    p.add_argument("--output")
    p.add_argument("--keep-parts", action="store_true", help="Keep per-video summary files after combining")
    p.add_argument("--max-chars", type=int, default=3000)
    p.add_argument("--warn-only", action="store_true")
    p.set_defaults(func=combine_summaries)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
