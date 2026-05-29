from __future__ import annotations

from pathlib import Path


STRICT_REVIEW_MODE = "public-release strict"


def stage_stop_points(stage: str, status: str, episode_dir: Path, cleanup_sentinel: str) -> dict[str, bool | str]:
    """Return the machine-checkable workflow gates recorded in the run manifest."""
    complete = status == "complete"
    sentinel_exists = (episode_dir / cleanup_sentinel).exists()
    proofread_done = complete and stage in {"post-review", "burn-cleanup"}
    qa_gates_passed = complete and stage in {"post-review", "burn-cleanup"}
    contact_sheet_inspected = sentinel_exists
    return {
        "review_mode": STRICT_REVIEW_MODE,
        "codex_proofread_done": proofread_done,
        "qa_gates_passed": qa_gates_passed,
        "screenshot_contact_sheet_inspected": contact_sheet_inspected,
        "cleanup_allowed": contact_sheet_inspected,
    }
