from __future__ import annotations

from pathlib import Path


def require_srt(path: Path) -> Path:
    if not path.exists():
        raise FileNotFoundError(f"Subtitle file not found: {path}")
    return path


def read_blocks(path: Path) -> list[str]:
    text = require_srt(path).read_text(encoding="utf-8-sig")
    return [block.strip() for block in text.strip().split("\n\n") if block.strip()]


def write_blocks(path: Path, blocks: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n\n".join(blocks).strip() + "\n", encoding="utf-8-sig")


def validate_file(path: Path) -> tuple[int, list[int]]:
    blocks = read_blocks(path)
    bad: list[int] = []
    for expected, block in enumerate(blocks, start=1):
        lines = block.splitlines()
        if len(lines) < 3 or lines[0].strip() != str(expected) or "-->" not in lines[1]:
            bad.append(expected)
    return len(blocks), bad
