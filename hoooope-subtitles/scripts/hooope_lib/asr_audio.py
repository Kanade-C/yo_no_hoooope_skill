from __future__ import annotations

import argparse
import math
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path


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


def extract_loudnorm_wav(src: Path, sample_rate: int = 16000) -> Path:
    fd, tmp_name = tempfile.mkstemp(prefix=f"{src.stem}.asr.", suffix=".wav")
    try:
        import os

        os.close(fd)
    except OSError:
        pass
    Path(tmp_name).unlink(missing_ok=True)
    wav = Path(tmp_name)
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(src),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-af",
        "loudnorm=I=-16:TP=-1.5:LRA=11",
        str(wav),
    ]
    subprocess.run(command, check=True)
    return wav


def extract_segment_wav(src: Path, start: float, duration: float, sample_rate: int = 16000) -> Path:
    if duration <= 0:
        raise RuntimeError(f"Cannot extract non-positive duration segment: start={start:.3f}, duration={duration:.3f}")
    fd, tmp_name = tempfile.mkstemp(prefix=f"{src.stem}.sample.", suffix=".wav")
    try:
        import os

        os.close(fd)
    except OSError:
        pass
    Path(tmp_name).unlink(missing_ok=True)
    wav = Path(tmp_name)
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{max(0.0, start):.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        str(src.resolve()),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        str(wav),
    ]
    subprocess.run(command, check=True)
    if not wav.exists() or wav.stat().st_size <= 44:
        wav.unlink(missing_ok=True)
        raise RuntimeError(f"FFmpeg wrote an empty segment: start={start:.3f}, duration={duration:.3f}")
    return wav


def wav_rms(path: Path) -> float:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        frame_count = wav.getnframes()
        frames = wav.readframes(wav.getnframes())
    if width != 2 or not frames or frame_count <= 0:
        return 0.0
    sample_count = len(frames) // 2
    if sample_count == 0:
        return 0.0
    total = 0.0
    for idx in range(0, len(frames), 2):
        value = int.from_bytes(frames[idx : idx + 2], "little", signed=True)
        total += value * value
    rms = math.sqrt(total / sample_count)
    return rms / max(1, channels)


def demucs_command(input_wav: Path, output_dir: Path, model: str) -> list[str]:
    return [
        sys.executable,
        "-m",
        "demucs",
        "--two-stems",
        "vocals",
        "-n",
        model,
        "-o",
        str(output_dir.resolve()),
        str(input_wav.resolve()),
    ]


def find_demucs_stems(output_dir: Path, input_wav: Path) -> tuple[Path, Path | None]:
    matches = list(output_dir.rglob(f"{input_wav.stem}/vocals.wav"))
    if not matches:
        raise RuntimeError(f"Demucs did not write vocals.wav under {output_dir}")
    vocals = matches[0]
    accomp = vocals.with_name("no_vocals.wav")
    return vocals, accomp if accomp.exists() else None


def isolate_vocals_subprocess(input_wav: Path, args: argparse.Namespace, label: str = "full") -> tuple[Path, Path | None]:
    if args.vocal_separator != "demucs":
        raise RuntimeError("Only demucs vocal separator is implemented; MDX is reserved for a future backend")
    out_dir = Path(tempfile.mkdtemp(prefix=f"hoooope_demucs_{label}_"))
    cmd = demucs_command(input_wav, out_dir, args.demucs_model)
    print(" ".join(cmd))
    try:
        subprocess.run(cmd, check=True)
        vocals, accomp = find_demucs_stems(out_dir, input_wav)
        if args.keep_asr_audio:
            keep_dir = input_wav.parent / f"{input_wav.stem}.{label}.demucs"
            keep_dir.mkdir(parents=True, exist_ok=True)
            kept_vocals = keep_dir / "vocals.wav"
            shutil.copy2(vocals, kept_vocals)
            if accomp is not None:
                shutil.copy2(accomp, keep_dir / "no_vocals.wav")
            return kept_vocals, keep_dir / "no_vocals.wav" if accomp is not None else None
        fd, tmp_name = tempfile.mkstemp(prefix=f"{input_wav.stem}.vocals.", suffix=".wav")
        try:
            import os

            os.close(fd)
        except OSError:
            pass
        isolated = Path(tmp_name)
        shutil.copy2(vocals, isolated)
        accomp_tmp: Path | None = None
        if accomp is not None:
            fd, accomp_name = tempfile.mkstemp(prefix=f"{input_wav.stem}.accomp.", suffix=".wav")
            try:
                import os

                os.close(fd)
            except OSError:
                pass
            accomp_tmp = Path(accomp_name)
            shutil.copy2(accomp, accomp_tmp)
        return isolated, accomp_tmp
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


def stratified_sample_starts(duration: float, sample_duration: float) -> list[float]:
    if duration <= 0:
        return [0.0]
    effective_sample = min(sample_duration, max(1.0, duration))
    if duration <= effective_sample * 2:
        return [0.0]
    raw = [min(300.0, duration * 0.15), duration * 0.50, duration * 0.80]
    starts: list[float] = []
    max_start = max(0.0, duration - effective_sample)
    for value in raw:
        start = min(max(0.0, value), max_start)
        if not any(abs(start - existing) < effective_sample / 2 for existing in starts):
            starts.append(start)
    return starts or [0.0]


def should_use_vocal_isolation(src: Path, args: argparse.Namespace) -> bool:
    duration = ffprobe_duration(src)
    starts = stratified_sample_starts(duration, args.auto_ab_sample_seconds)
    ratios: list[float] = []
    temp_paths: list[Path] = []
    try:
        for idx, start in enumerate(starts, start=1):
            segment_duration = min(args.auto_ab_sample_seconds, max(0.0, duration - start))
            if segment_duration < args.auto_ab_min_sample_seconds:
                print(f"auto-ab sample{idx} skipped: start={start:.1f}s remaining={segment_duration:.1f}s below minimum={args.auto_ab_min_sample_seconds:.1f}s")
                continue
            sample = extract_segment_wav(src, start, segment_duration, args.audio_sample_rate)
            temp_paths.append(sample)
            vocals, accomp = isolate_vocals_subprocess(sample, args, label=f"sample{idx}")
            temp_paths.append(vocals)
            if accomp is not None:
                temp_paths.append(accomp)
            vocal_rms = wav_rms(vocals)
            accomp_rms = wav_rms(accomp) if accomp is not None else 0.0
            ratio = accomp_rms / max(vocal_rms, 1e-6)
            ratios.append(ratio)
            print(f"auto-ab sample{idx} start={start:.1f}s vocal_rms={vocal_rms:.2f} accompaniment_rms={accomp_rms:.2f} ratio={ratio:.3f}")
    finally:
        if not args.keep_asr_audio:
            for path in temp_paths:
                path.unlink(missing_ok=True)
    if not ratios:
        print("auto-ab found no valid samples; falling back to loudnorm")
        return False
    sorted_ratios = sorted(ratios)
    median = sorted_ratios[len(sorted_ratios) // 2]
    average = sum(ratios) / len(ratios)
    decision_ratio = median if args.auto_ab_statistic == "median" else average
    print(f"auto-ab ratios={','.join(f'{value:.3f}' for value in ratios)} statistic={args.auto_ab_statistic} value={decision_ratio:.3f} threshold={args.auto_ab_ratio_threshold:.3f}")
    return decision_ratio >= args.auto_ab_ratio_threshold


def prepare_asr_wav(src: Path, args: argparse.Namespace) -> tuple[Path, list[Path]]:
    cleanup_paths: list[Path] = []
    mode = args.asr_audio_mode
    if mode == "auto-ab":
        mode = "vocal-isolate" if should_use_vocal_isolation(src, args) else "loudnorm"
        print(f"auto-ab selected asr_audio_mode={mode}")
    loudnorm = extract_loudnorm_wav(src, args.audio_sample_rate)
    if not args.keep_asr_audio:
        cleanup_paths.append(loudnorm)
    if mode == "loudnorm":
        return loudnorm, cleanup_paths
    vocals, accomp = isolate_vocals_subprocess(loudnorm, args, label="full")
    if not args.keep_asr_audio:
        cleanup_paths.append(vocals)
    if accomp is not None and not args.keep_asr_audio:
        cleanup_paths.append(accomp)
    print(f"Prepared isolated vocal WAV: {vocals}")
    return vocals, cleanup_paths

