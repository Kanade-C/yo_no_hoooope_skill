from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

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


def file_sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_file(path: Path, label: str) -> Path:
    path = path.resolve()
    if not path.exists():
        raise SystemExit(f"{label} not found: {path}")
    return path


def require_srt(path: Path) -> Path:
    if not path.exists():
        raise FileNotFoundError(f"Subtitle file not found: {path}")
    return path


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


def split_timing(timing: str) -> tuple[float, float]:
    start_raw, end_raw = [part.strip() for part in timing.split("-->", 1)]
    return parse_srt_time(start_raw), parse_srt_time(end_raw)


def make_timing(start: float, end: float) -> str:
    return f"{fmt_time(start)} --> {fmt_time(end)}"


def display_width(text: str) -> float:
    width = 0.0
    for char in text:
        if unicodedata.combining(char) or char in "\t\r\n":
            continue
        east_asian_width = unicodedata.east_asian_width(char)
        if east_asian_width in {"F", "W"}:
            width += 2.0
        elif east_asian_width == "A":
            width += 1.5
        else:
            width += 1.0
    return width


def chinese_char_count(text: str) -> int:
    return sum(1 for char in text if "\u4e00" <= char <= "\u9fff")


def read_srt_blocks(path: Path) -> list[str]:
    text = require_file(path, "Subtitle file").read_text(encoding="utf-8-sig")
    return [block.strip() for block in text.strip().split("\n\n") if block.strip()]


def read_blocks(path: Path) -> list[str]:
    text = require_srt(path).read_text(encoding="utf-8-sig")
    return [block.strip() for block in text.strip().split("\n\n") if block.strip()]


def write_srt_blocks(path: Path, blocks: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n\n".join(blocks).strip() + "\n", encoding="utf-8-sig")


def write_blocks(path: Path, blocks: list[str]) -> None:
    write_srt_blocks(path, blocks)


def validate_file(path: Path) -> tuple[int, list[int]]:
    blocks = read_blocks(path)
    bad: list[int] = []
    for expected, block in enumerate(blocks, start=1):
        lines = block.splitlines()
        if len(lines) < 3 or lines[0].strip() != str(expected) or "-->" not in lines[1]:
            bad.append(expected)
    return len(blocks), bad


def iter_srt_entries(path: Path) -> list[tuple[str, str, list[str]]]:
    entries: list[tuple[str, str, list[str]]] = []
    for block in read_srt_blocks(path):
        lines = block.splitlines()
        if len(lines) < 3:
            continue
        entries.append((lines[0].strip(), lines[1].strip(), [line.strip() for line in lines[2:] if line.strip()]))
    return entries


def is_final_srt_path(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() != ".srt":
        return False
    name = path.name
    if any(name.endswith(suffix) for suffix in FINAL_SRT_EXCLUDED_SUFFIXES):
        return False
    if ".part" in path.stem or ".deepseek." in name:
        return False
    if any(part in IGNORED_WORKBENCH_DIRS for part in path.parts):
        return False
    return True


def iter_final_srt_paths(root: Path) -> list[Path]:
    root = root.resolve()
    if root.is_file():
        return [root] if is_final_srt_path(root) else []
    return sorted(path for path in root.rglob("*.srt") if is_final_srt_path(path))
