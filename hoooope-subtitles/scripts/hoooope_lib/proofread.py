from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import config
from . import srt_util


def receipt_path(episode_dir: Path) -> Path:
    return episode_dir / config.PROOFREAD_RECEIPT


def build_receipt(episode_dir: Path, review_mode: str = config.STRICT_REVIEW_MODE) -> dict[str, object]:
    finals = srt_util.iter_final_srt_paths(episode_dir)
    return {
        "schema": "hoooope-proofread-receipt-v1",
        "review_mode": review_mode,
        "hashed_at": datetime.now(timezone.utc).isoformat(),
        "final_srt_hashes": [
            {
                "path": str(path.resolve()),
                "sha256": srt_util.file_sha256(path),
            }
            for path in finals
        ],
    }


def write_receipt(episode_dir: Path, review_mode: str = config.STRICT_REVIEW_MODE) -> Path:
    episode_dir = episode_dir.resolve()
    if not episode_dir.exists():
        raise SystemExit(f"Episode directory not found: {episode_dir}")
    finals = srt_util.iter_final_srt_paths(episode_dir)
    if not finals:
        raise SystemExit(f"No final SRT files found under {episode_dir}")
    path = receipt_path(episode_dir)
    path.write_text(json.dumps(build_receipt(episode_dir, review_mode), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_receipt(episode_dir: Path) -> dict[str, object] | None:
    path = receipt_path(episode_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def evidence(episode_dir: Path) -> dict[str, object]:
    path = receipt_path(episode_dir)
    receipt = load_receipt(episode_dir)
    finals = {str(path.resolve()): srt_util.file_sha256(path) for path in srt_util.iter_final_srt_paths(episode_dir)}
    result: dict[str, object] = {
        "receipt_path": str(path),
        "receipt_exists": receipt is not None,
        "hashed_at": None,
        "srt_hash_match": False,
        "missing_from_receipt": sorted(finals),
        "changed_since_receipt": [],
    }
    if receipt is None:
        return result
    receipt_hashes = {
        str(item.get("path")): item.get("sha256")
        for item in receipt.get("final_srt_hashes", [])
        if isinstance(item, dict)
    }
    missing = sorted(path for path in finals if path not in receipt_hashes)
    changed = sorted(path for path, digest in finals.items() if receipt_hashes.get(path) != digest)
    result.update(
        {
            "review_mode": receipt.get("review_mode"),
            "hashed_at": receipt.get("hashed_at"),
            "missing_from_receipt": missing,
            "changed_since_receipt": changed,
            "srt_hash_match": not missing and not changed and bool(finals),
        }
    )
    return result


def proofread_done(episode_dir: Path) -> bool:
    data = evidence(episode_dir)
    return bool(data.get("receipt_exists") and data.get("srt_hash_match"))
