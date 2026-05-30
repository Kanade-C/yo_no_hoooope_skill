from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DurationCheckConfig:
    source: Path
    output: Path
    tolerance: float = 1.0


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


def verify_duration_pair(config: DurationCheckConfig) -> None:
    src_duration = ffprobe_duration(config.source)
    out_duration = ffprobe_duration(config.output)
    diff = abs(src_duration - out_duration)
    print(f"source={src_duration:.3f}s output={out_duration:.3f}s diff={diff:.3f}s")
    if diff > config.tolerance:
        raise SystemExit(f"Duration mismatch exceeds {config.tolerance}s: {diff:.3f}s")
