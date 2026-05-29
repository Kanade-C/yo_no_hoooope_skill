from __future__ import annotations

import argparse
import re
from pathlib import Path


JA_RE = re.compile(r"[\u3040-\u30ff]")
STYLE_RATIO_MIN = 0.6
STYLE_RATIO_MAX = 0.9
JA_STYLE_MARKERS = (
    "あの", "えっと", "えと", "なんか", "かな", "ですね", "でしょうか",
    "え", "ん", "まあ", "ちょっと", "その", "えー", "うーん",
)
ZH_STYLE_MARKERS = (
    "吧", "呢", "啊", "呀", "诶", "欸", "呃", "嗯", "那个", "怎么说",
    "总觉得", "大概", "可能", "有点", "稍微", "就是", "感觉", "其实",
)
HIGH_CONFIDENCE_STYLE_PAIRS = (
    ("えっと", ("呃", "那个", "怎么说")),
    ("かな", ("吧", "呢", "吗")),
    ("ちょっと", ("有点", "稍微", "一下")),
)


def require_existing(path: Path, label: str) -> Path:
    path = path.resolve()
    if not path.exists():
        raise SystemExit(f"{label} not found: {path}")
    return path


def read_srt_blocks(path: Path) -> list[str]:
    text = require_existing(path, "Subtitle file").read_text(encoding="utf-8-sig")
    return [block.strip() for block in text.strip().split("\n\n") if block.strip()]


def iter_srt_entries(path: Path) -> list[tuple[str, str, list[str]]]:
    entries: list[tuple[str, str, list[str]]] = []
    for block in read_srt_blocks(path):
        lines = block.splitlines()
        if len(lines) < 3:
            continue
        entries.append((lines[0].strip(), lines[1].strip(), [line.strip() for line in lines[2:] if line.strip()]))
    return entries


def parse_srt_time(value: str) -> float:
    match = re.fullmatch(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})", value.strip())
    if not match:
        raise ValueError(value)
    h, m, s, ms = (int(part) for part in match.groups())
    return h * 3600 + m * 60 + s + ms / 1000


def is_final_srt_path(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() != ".srt":
        return False
    name = path.name
    if any(name.endswith(suffix) for suffix in (".orig.srt", ".deepseek.raw.srt", ".deepseek.polished.srt")):
        return False
    if ".part" in path.stem or ".deepseek." in name:
        return False
    if any(part in {"deepseek_chunks", "deepseek_polish_chunks", "screenshot_check"} for part in path.parts):
        return False
    return True


def iter_final_srt_paths(root: Path) -> list[Path]:
    root = root.resolve()
    if root.is_file():
        return [root] if is_final_srt_path(root) else []
    return sorted(path for path in root.rglob("*.srt") if is_final_srt_path(path))


def marker_count(text: str, markers: tuple[str, ...]) -> int:
    return sum(len(re.findall(re.escape(marker), text)) for marker in markers)


def repeated_text_count(entries: list[tuple[str, str, list[str]]]) -> int:
    count = 0
    previous = ""
    streak = 1
    for _number, _timing, lines in entries:
        text = "".join(lines).strip()
        if text and text == previous:
            streak += 1
            if streak >= 3:
                count += 1
        else:
            streak = 1
        previous = text
    return count


def style_pair_details(orig_text: str, final_text: str) -> list[str]:
    details: list[str] = []
    for ja_marker, zh_markers in HIGH_CONFIDENCE_STYLE_PAIRS:
        ja_count = len(re.findall(re.escape(ja_marker), orig_text))
        zh_count = marker_count(final_text, zh_markers)
        ratio = zh_count / max(ja_count, 1)
        details.append(f"{ja_marker}: ja={ja_count} zh={zh_count} ratio={ratio:.3f}")
    return details


def baseline_report(args: argparse.Namespace) -> None:
    target = require_existing(Path(args.target), "SRT file or episode directory") if Path(args.target).is_file() else Path(args.target)
    if not target.exists():
        raise SystemExit(f"Target not found: {target.resolve()}")
    finals = iter_final_srt_paths(target)
    if not finals:
        raise SystemExit(f"No final SRT files found under {target.resolve()}")

    lines: list[str] = ["# HOOOOPE subtitle quality baseline", f"target: {target.resolve()}", ""]
    totals = {
        "files": 0,
        "blocks": 0,
        "long_gt48": 0,
        "long_gt60": 0,
        "two_line": 0,
        "over_two_line": 0,
        "duration_gt8_text_gt36": 0,
        "ja_residue": 0,
        "repeat_orig": 0,
        "repeat_final": 0,
        "style_ja": 0,
        "style_zh": 0,
    }

    for final in finals:
        orig = final.with_name(f"{final.stem}.orig.srt")
        final_entries = iter_srt_entries(final)
        orig_entries = iter_srt_entries(orig) if orig.exists() else []
        final_text = "\n".join("".join(lines) for _n, _t, lines in final_entries)
        orig_text = "\n".join("".join(lines) for _n, _t, lines in orig_entries)
        style_ja = marker_count(orig_text, JA_STYLE_MARKERS)
        style_zh = marker_count(final_text, ZH_STYLE_MARKERS)
        ratio = style_zh / max(style_ja, 1)
        long48 = long60 = two_line = over_two_line = dur_long = ja_residue = 0
        for _number, timing, text_lines in final_entries:
            text = "".join(text_lines)
            long48 += int(len(text) > 48)
            long60 += int(len(text) > 60)
            two_line += int(len(text_lines) == 2)
            over_two_line += int(len(text_lines) > 2)
            ja_residue += int(bool(JA_RE.search(text)))
            try:
                start_raw, end_raw = [part.strip() for part in timing.split("-->", 1)]
                duration = parse_srt_time(end_raw) - parse_srt_time(start_raw)
                dur_long += int(duration > 8 and len(text) > 36)
            except (ValueError, IndexError):
                pass
        repeat_orig = repeated_text_count(orig_entries)
        repeat_final = repeated_text_count(final_entries)
        status = "ok" if STYLE_RATIO_MIN <= ratio <= STYLE_RATIO_MAX else "warn"
        lines.extend([
            f"## {final}",
            f"blocks={len(final_entries)} orig_exists={orig.exists()}",
            f"long_gt48={long48} long_gt60={long60} two_line={two_line} over_two_line={over_two_line} duration_gt8_text_gt36={dur_long} ja_residue={ja_residue}",
            f"repeat_orig={repeat_orig} repeat_final={repeat_final}",
            f"style_ja={style_ja} style_zh={style_zh} style_energy_ratio={ratio:.3f} status={status} healthy_range={STYLE_RATIO_MIN:.1f}-{STYLE_RATIO_MAX:.1f}",
            "style_pairs: " + "; ".join(style_pair_details(orig_text, final_text)),
            "",
        ])
        totals["files"] += 1
        totals["blocks"] += len(final_entries)
        totals["long_gt48"] += long48
        totals["long_gt60"] += long60
        totals["two_line"] += two_line
        totals["over_two_line"] += over_two_line
        totals["duration_gt8_text_gt36"] += dur_long
        totals["ja_residue"] += ja_residue
        totals["repeat_orig"] += repeat_orig
        totals["repeat_final"] += repeat_final
        totals["style_ja"] += style_ja
        totals["style_zh"] += style_zh

    total_ratio = totals["style_zh"] / max(totals["style_ja"], 1)
    summary = [
        "# Summary",
        " ".join(f"{key}={value}" for key, value in totals.items() if key not in {"style_ja", "style_zh"}),
        f"style_ja={totals['style_ja']} style_zh={totals['style_zh']} style_energy_ratio={total_ratio:.3f} healthy_range={STYLE_RATIO_MIN:.1f}-{STYLE_RATIO_MAX:.1f}",
        "",
    ]
    report = "\n".join(summary + lines)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8-sig")
        print(f"Wrote baseline report {out.resolve()}")
    else:
        print(report)

