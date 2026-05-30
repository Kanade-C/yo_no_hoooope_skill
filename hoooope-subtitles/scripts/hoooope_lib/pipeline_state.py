from __future__ import annotations

from pathlib import Path

from . import config
from . import proofread


def stage_stop_points(stage: str, status: str, episode_dir: Path, cleanup_sentinel: str) -> dict[str, object]:
    """Return the machine-checkable workflow gates recorded in the v2 manifest."""
    complete = status == "complete"
    sentinel_exists = (episode_dir / cleanup_sentinel).exists()
    proofread_evidence = proofread.evidence(episode_dir)
    post_review_complete = complete and stage in {"post-review", "burn-cleanup"}
    qa_gates_passed = post_review_complete
    contact_sheet_inspected = sentinel_exists
    return {
        "review_mode": config.STRICT_REVIEW_MODE,
        "post_review_stage_completed": post_review_complete,
        "codex_proofread_done": bool(proofread_evidence.get("receipt_exists") and proofread_evidence.get("srt_hash_match")),
        "proofread_evidence": proofread_evidence,
        "qa_gates_passed": qa_gates_passed,
        "screenshot_contact_sheet_inspected": contact_sheet_inspected,
        "cleanup_allowed": contact_sheet_inspected,
    }
