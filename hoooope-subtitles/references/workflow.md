# Workflow Reference

Use this when planning or resuming an episode folder.

## Folder Layout

Expected input:

```text
<episode>/
  hope_<yy>_<mmdd>.mp4
  hope_<yy>_<mmdd>_*.mp4
model/
hoooope_terms.txt
```

Date-based stems such as `hope_25_0513` are preferred. Legacy `hoooope_<episode>` names remain valid. Each root MP4 must move into a same-stem work folder, and all derived files for that video stay in that folder.

```text
<episode>/
  <episode>.summary.txt
  hope_25_0513/
    hope_25_0513.mp4
    hope_25_0513.orig.raw.srt
    hope_25_0513.orig.srt
    hope_25_0513.srt
```

Process every MP4 in the episode folder, including regular and member videos. Do not merge multiple videos into one translation prompt.

## Checkpoints

Per video:

- `<stem>.orig.raw.srt`
- `<stem>.orig.srt`
- `<stem>.orig.audit.txt`
- `<stem>.deepseek.raw.srt` plus `<stem>.deepseek.raw.srt.source.sha256`
- `<stem>.deepseek.polished.srt` plus input and dependency hash sidecars
- `<stem>.qa.txt`
- `<stem>.srt`
- `<stem>.summary.txt`

Per episode:

- `<episode>.summary.txt`
- `.hoooope_run_manifest.json`

When resuming, reuse valid checkpoints unless the user asks for a fresh run or a concrete defect is found. If source SRT text changes, regenerate downstream DeepSeek outputs or rely on hash sidecars to reject stale cache.

## Pipeline Stages

Prefer the staged coordinator:

```powershell
python <skill_dir>\scripts\hoooope_subtitles.py pipeline <episode_dir>
python <skill_dir>\scripts\hoooope_subtitles.py pipeline <episode_dir> --stage post-review
python <skill_dir>\scripts\hoooope_subtitles.py pipeline <episode_dir> --stage burn-cleanup
python <skill_dir>\scripts\hoooope_subtitles.py cleanup <episode_dir>
```

The default `prepare-review` stage organizes MP4s, creates or reuses source SRTs, writes Whisper large-v3-turbo raw ASR to `<stem>.orig.raw.srt`, smooths it to `<stem>.orig.srt`, runs source audit, runs Qwen3-ASR-1.7B risk-segment comparison to `<stem>.asr.compare.txt`, runs DeepSeek translation and self-polish (with automatic retry on API failures), seeds the final SRT, then stops for Codex proofread. Initial translation defaults to `--translate-workers 2 --translate-context-blocks 20`, which uses read-only context instead of overlap-and-discard; pass `--translate-workers 1` only as a manual legacy fallback. Each pipeline run updates `.hoooope_run_manifest.json` with stage status, artifact hashes, and machine-checkable stop points: `codex_proofread_done`, `qa_gates_passed`, `screenshot_contact_sheet_inspected`, and `cleanup_allowed`. `post-review` assumes Codex has applied final subtitle corrections, then runs local QA and notes. `burn-cleanup` assumes final QA passed and creates the burned MP4 plus screenshot check, then stops for contact-sheet inspection. After visual QA passes, re-run `burn-cleanup` with `--cleanup --cleanup-confirmed` to write a sentinel file and run cleanup. A cleanup request without screenshot QA confirmation fails instead of silently deleting or skipping work. Run `cleanup` directly only after the sentinel exists, or pass `--force` to skip the check.

Use individual helper subcommands for recovery: `doctor`, `transcribe`, `smooth-source`, `orig-audit`, `qwen-compare`, `validate`, `lint-final --strict-public`, `terms-audit`, `proper-noun-candidates`, `review-todo`, `combine-summaries`, `final-ready`, `burn`, `screenshot-check`, and `cleanup`.

## Summary-Only Scope

If the user asks only for a summary, do not organize MP4s, reburn videos, rerun ASR, or cleanup media artifacts. Read the existing final Chinese SRTs, write or update the episode summary, and stop.

## Cleanup

After final subtitles, burned videos, screenshot QA, and combined summary are confirmed, keep only final MP4, `.orig.raw.srt`, `.orig.srt`, final `.srt`, `.hoooope_run_manifest.json`, and the episode-level summary. Remove DeepSeek raw/polished files and sidecar hashes, QA reports, review todo files, proper-noun candidates, explicit chunk/cache folders, screenshot-check files, temporary burned files, and per-video summaries after combination. Never run cleanup before contact sheets have been inspected.

## Final Report

Report the number of videos processed, whether burned MP4s replaced source files, duration validation result and largest observed difference, screenshot/contact-sheet QA result, cleanup result, any accepted residual lint items, and the final episode folder path.
