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
- `.hoooope_proofread_receipt.json`

When resuming, reuse valid checkpoints unless the user asks for a fresh run or a concrete defect is found. If source SRT text changes, regenerate downstream DeepSeek outputs or rely on hash sidecars to reject stale cache.

## Pipeline Stages

Prefer the staged coordinator:

```powershell
python <skill_dir>\scripts\hoooope_subtitles.py pipeline <episode_dir>
python <skill_dir>\scripts\hoooope_subtitles.py pipeline <episode_dir> --stage post-review
python <skill_dir>\scripts\hoooope_subtitles.py mark-proofread <episode_dir>
python <skill_dir>\scripts\hoooope_subtitles.py pipeline <episode_dir> --stage burn-cleanup
python <skill_dir>\scripts\hoooope_subtitles.py cleanup <episode_dir>
```

The default `prepare-review` stage organizes MP4s, creates or reuses source SRTs, writes Whisper large-v3-turbo raw ASR to `<stem>.orig.raw.srt`, smooths it to `<stem>.orig.srt`, runs source audit, runs Qwen3-ASR-1.7B risk-segment comparison to `<stem>.asr.compare.txt`, runs DeepSeek translation and self-polish (with automatic retry on API failures), seeds the final SRT, then stops for Codex proofread. Initial translation defaults to `--translate-workers 2 --translate-context-blocks 20`, which uses read-only context instead of overlap-and-discard; pass `--translate-workers 1` only as a manual legacy fallback. Each pipeline run updates v2 `.hoooope_run_manifest.json` with stage status, artifact hashes, and machine-checkable stop points: `post_review_stage_completed`, `codex_proofread_done`, `proofread_evidence`, `qa_gates_passed`, `screenshot_contact_sheet_inspected`, and `cleanup_allowed`. `post-review` only means the local QA/notes stage ran; it does not by itself prove Codex proofread. After Codex applies final only-corrections edits, run `mark-proofread` to write `.hoooope_proofread_receipt.json` with final SRT hashes. `burn-cleanup` requires that receipt to exist and match current SRT hashes by default, then creates the burned MP4 plus screenshot check and stops for contact-sheet inspection. After visual QA passes, re-run `burn-cleanup` with `--cleanup --cleanup-confirmed` to write a sentinel file and run cleanup. A cleanup request without screenshot QA confirmation fails instead of silently deleting or skipping work. Run `cleanup` directly only after the sentinel exists, or pass `--force` to skip the check.

Use individual helper subcommands for recovery: `doctor`, `transcribe`, `smooth-source`, `orig-audit`, `qwen-compare`, `validate`, `lint-final --strict-public`, `terms-audit`, `proper-noun-candidates`, `review-todo`, `combine-summaries`, `final-ready`, `mark-proofread`, `burn`, `screenshot-check`, and `cleanup`.

## Full Production Flow

Step by step. The staged pipeline automates most of this; follow these when running stages manually or resuming.

1. Read this file and inspect the episode folder.
2. If the user asked for summary-only, do not touch MP4s; read current final Chinese SRTs, write the summary, and stop.
3. Organize each root MP4 into its own same-stem folder, preserving date-based stems such as `hope_25_0513`.
4. Read `references/translation-and-asr.md`, `references/terms-glossary.md`, `references/deepseek-prompts.md`, and `references/review-policy.md`; append project glossary wording from `hoooope_terms.txt` when present, with `hooope_terms.txt` only as legacy fallback.
5. Confirm the local ASR model paths, then transcribe raw ASR to `<stem>.orig.raw.srt` with Whisper large-v3-turbo plus local Silero VAD as the production backbone.
6. Run `smooth-source` to create `<stem>.orig.srt`, then `orig-audit`; by default run Qwen3-ASR-1.7B risk-segment comparison to `<stem>.asr.compare.txt` as a high-quality sidecar. Use it to fix only obvious source errors that would poison downstream translation; never let Qwen overwrite the main Whisper timing SRT automatically.
7. Run DeepSeek V4-Pro initial translation to `<stem>.deepseek.raw.srt`; pipeline defaults to `--translate-workers 2 --translate-context-blocks 20` for read-only context.
8. Run DeepSeek V4-Pro self-polish to `<stem>.deepseek.polished.srt` and `<stem>.qa.txt`; polish cache includes dependency hashes for prompt, glossary, model, and chunk strategy.
9. Copy polished output to `<stem>.srt`; read `references/review-and-qa.md` and `references/review-policy.md`, then Codex proofreads 100% of source/final subtitles with only-corrections edits. After proofread, run `mark-proofread <episode_dir>` so the manifest can verify final SRT hashes.
10. Run the local QA gates: `normalize-punctuation`, `review-todo`, `wrap-final`, `validate`, `baseline-report`, `lint-final --strict-public`, `terms-audit`, `proper-noun-candidates`, and `final-ready`; fix high-risk issues and rerun. `review-todo` must run before `wrap-final` physically splits blocks.
11. Read `references/summary-and-tone.md`, `references/note-style.md`, and `references/review-policy.md`; do the Yomiya tone micro-review before final note generation.
12. Generate per-video notes from final SRTs, inspect/compress them, then run `combine-summaries` to write one episode-level summary outside video folders.
13. Burn final SRTs into MP4s with duration validation, run `screenshot-check`, inspect contact sheets, and reburn if visual QA fails.
14. Run `cleanup` only after final subtitles, burned videos, screenshot QA, and the combined summary are confirmed. Do not delete screenshot-check files before contact sheets have been inspected.

For resume work, scan checkpoints first and continue from the earliest missing or invalid stage. Do not restart completed valid work unless the user asks for a fresh run or a concrete defect requires regeneration.

## Summary-Only Scope

If the user asks only for a summary, do not organize MP4s, reburn videos, rerun ASR, or cleanup media artifacts. Read the existing final Chinese SRTs, write or update the episode summary, and stop.

## Cleanup

After final subtitles, burned videos, screenshot QA, and combined summary are confirmed, keep only final MP4, `.orig.raw.srt`, `.orig.srt`, final `.srt`, `.hoooope_run_manifest.json`, and the episode-level summary. Remove DeepSeek raw/polished files and sidecar hashes, QA reports, review todo files, proper-noun candidates, explicit chunk/cache folders, screenshot-check files, temporary burned files, and per-video summaries after combination. Never run cleanup before contact sheets have been inspected.

## Final Report

Report the number of videos processed, whether burned MP4s replaced source files, duration validation result and largest observed difference, screenshot/contact-sheet QA result, cleanup result, any accepted residual lint items, and the final episode folder path.
