from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


MEDIA_EXTS = {".ts", ".mp4", ".mkv", ".mov", ".webm", ".m4a", ".mp3", ".wav", ".flac"}
JA_RE = re.compile(r"[\u3040-\u30ff]")
HOOPE_RE = re.compile(r"\bHO+PE\b")
BAD_HOST_TERMS = ("阳宫", "雏乃", "陽宮", "ひなの")


def fmt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


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

    blocks = read_srt_blocks(subtitle)
    for block in blocks:
        lines = block.splitlines()
        if len(lines) < 3:
            continue
        number = lines[0].strip()
        text_lines = [line.strip() for line in lines[2:] if line.strip()]
        text = "\n".join(text_lines)

        if not text:
            issues.append(f"[空字幕] #{number}")
        if len(text_lines) > 2:
            issues.append(f"[超过两行] #{number}: {len(text_lines)} lines")
        for line in text_lines:
            if len(line) > args.max_line_chars:
                issues.append(f"[单行过长] #{number}: {len(line)} chars: {line}")
        if JA_RE.search(text):
            issues.append(f"[疑似日文残留] #{number}: {text.replace(chr(10), ' / ')}")
        for token in HOOPE_RE.findall(text):
            if token != "HOOOOPE":
                issues.append(f"[节目名疑似错误] #{number}: {token}: {text.replace(chr(10), ' / ')}")
        for bad_term in BAD_HOST_TERMS:
            if bad_term in text:
                issues.append(f"[人名疑似错误] #{number}: {bad_term}: {text.replace(chr(10), ' / ')}")
                break

    print(f"lint-final blocks={len(blocks)} issues={len(issues)}")
    for issue in issues[: args.max_report]:
        print(issue)
    if len(issues) > args.max_report:
        print(f"... {len(issues) - args.max_report} more issues")
    if issues and not args.warn_only:
        raise SystemExit(1)


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
    ]
    removed: list[Path] = []
    for pattern in patterns:
        for path in episode_dir.glob(pattern):
            if path.is_file():
                path.unlink()
                removed.append(path)

    cache_dirs = ["deepseek_chunks", "deepseek_polish_chunks"]
    cache_dirs.extend(path.name for path in episode_dir.glob("*deepseek*cache*") if path.is_dir())
    cache_dirs.extend(path.name for path in episode_dir.glob("*deepseek*chunks*") if path.is_dir())
    for dirname in sorted(set(cache_dirs)):
        path = episode_dir / dirname
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
    p.add_argument("--max-report", type=int, default=120)
    p.add_argument("--warn-only", action="store_true")
    p.set_defaults(func=lint_final)

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

    p = sub.add_parser("cleanup", help="Remove DeepSeek QA/raw/polished/check intermediate artifacts from an episode folder")
    p.add_argument("episode_dir")
    p.set_defaults(func=cleanup)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
