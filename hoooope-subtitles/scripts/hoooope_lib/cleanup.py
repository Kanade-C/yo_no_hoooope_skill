from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from .config import CLEANUP_SENTINEL


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
        "*.asr.compare.txt",
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
    cache_paths.extend(path for path in episode_dir.rglob("screenshot_check") if path.is_dir())
    cache_paths.extend(path for path in episode_dir.rglob("*.screenshot_check") if path.is_dir())
    for path in sorted(set(cache_paths)):
        if path.exists() and path.is_dir():
            if (path / ".keep").exists() or (path / ".no_cleanup").exists():
                print(f"Skipping preserved directory {path}")
                continue
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

    if getattr(args, "release_only", False):
        release_paths = [
            episode_dir / ".hoooope_proofread_receipt.json",
            episode_dir / ".hoooope_run_manifest.json",
            episode_dir / CLEANUP_SENTINEL,
        ]
        release_paths.extend(path for path in episode_dir.rglob("*.orig.raw.srt") if path.is_file())
        for path in release_paths:
            if path.is_file():
                path.unlink()
                removed.append(path)

    print(f"Removed {len(removed)} intermediate artifacts")
    for path in removed:
        print(path)
