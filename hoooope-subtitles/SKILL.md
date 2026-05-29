---
name: hoooope-subtitles
description: Create Chinese subtitles, burned MP4 outputs, and concise Chinese note-style summaries for HOOOOPE podcast episode folders or MP4 batches. Use for HOOOOPE work involving transcription, DeepSeek V4-Pro translation/polish, Codex final subtitle inspection, QA gates, summary generation, burn-in validation, screenshot checks, cleanup, resume work, or summary-only requests.
---

# HOOOOPE Subtitles

This is a HOOOOPE production skill, not a generic subtitle skill. Keep the main prompt lean: use this file to route the job, then load the specific reference file needed for the current stage.

## Operating Contract

The user may provide only source MP4 files or an episode folder. Codex owns transcription, translation, QA inspection, final subtitle edits, burn validation, screenshot inspection, cleanup, and final reporting.

QA artifacts such as `<stem>.qa.txt`, `<stem>.orig.audit.txt`, `<stem>.review.todo.txt`, proper-noun candidate files, baseline reports, and screenshot contact sheets are Codex workbench inputs. Consume them before reporting completion; do not hand them to the user as homework.

Use project-local paths. Throughout this skill, `<skill_dir>` means this skill folder, so the command-block path `<skill_dir>\scripts\hoooope_subtitles.py` is just the bundled helper resolved relative to the skill folder. Never hardcode an absolute user path. The skill slug and helper name use four `o` characters: `hoooope-subtitles` and `hoooope_subtitles.py`.

## Reference Loading

Load only the reference needed for the current task:

- `references/workflow.md`: folder layout, checkpoints, resume behavior, staged pipeline use, cleanup, final report, and summary-only scope.
- `references/translation-and-asr.md`: ASR baseline, source smoothing/audit, DeepSeek V4-Pro translation and polish, cache/hash behavior, and failure recovery.
- `references/review-and-qa.md`: Codex full-pass proofread, only-corrections editing, lint/terms/review gates, long-duration handling, burn validation, and screenshot QA.
- `references/summary-and-tone.md`: auto note generation, summary compression, final combined note, and Yomiya tone micro-review.
- `references/terms-glossary.md`: terminology, HOOOOPE fixed-term traps, names, brands, and recurring bad-term corrections.
- `references/deepseek-prompts.md`: DeepSeek V4-Pro translation, self-polish, and note prompt policy.
- `references/note-style.md`: episode-summary style, compression, topic selection, and output shape.
- `references/review-policy.md`: public-release strict review coverage, reduced-review mode, QA gates, and tone priority.
- `references/terms-and-notes.md`: compatibility router for the split reference files.

## Default Workflow

For full subtitle production, use the staged pipeline where possible:

```powershell
python <skill_dir>\scripts\hoooope_subtitles.py pipeline <episode_dir>
python <skill_dir>\scripts\hoooope_subtitles.py pipeline <episode_dir> --stage post-review
python <skill_dir>\scripts\hoooope_subtitles.py pipeline <episode_dir> --stage burn-cleanup
python <skill_dir>\scripts\hoooope_subtitles.py cleanup <episode_dir>
```

Default production flow:

1. Read `references/workflow.md` and inspect the episode folder.
2. If the user asked for summary-only, do not touch MP4s; read current final Chinese SRTs, write the summary, and stop.
3. Organize each root MP4 into its own same-stem folder, preserving date-based stems such as `hope_25_0513`.
4. Read `references/translation-and-asr.md`, `references/terms-glossary.md`, `references/deepseek-prompts.md`, and `references/review-policy.md`; append project glossary wording from `hoooope_terms.txt` when present, with `hooope_terms.txt` only as legacy fallback.
5. Confirm the local ASR model paths, then transcribe raw ASR to `<stem>.orig.raw.srt` with Whisper large-v3-turbo plus local Silero VAD as the production backbone.
6. Run `smooth-source` to create `<stem>.orig.srt`, then `orig-audit`; by default run Qwen3-ASR-1.7B risk-segment comparison to `<stem>.asr.compare.txt` as a high-quality sidecar. Use it to fix only obvious source errors that would poison downstream translation; never let Qwen overwrite the main Whisper timing SRT automatically.
7. Run DeepSeek V4-Pro initial translation to `<stem>.deepseek.raw.srt`; pipeline defaults to `--translate-workers 2 --translate-context-blocks 20` for read-only context.
8. Run DeepSeek V4-Pro self-polish to `<stem>.deepseek.polished.srt` and `<stem>.qa.txt`; polish cache includes dependency hashes for prompt, glossary, model, and chunk strategy.
9. Copy polished output to `<stem>.srt`; read `references/review-and-qa.md` and `references/review-policy.md`, then Codex proofreads 100% of source/final subtitles with only-corrections edits.
10. Run the local QA gates: `normalize-punctuation`, `review-todo`, `wrap-final`, `validate`, `baseline-report`, `lint-final --strict-public`, `terms-audit`, `proper-noun-candidates`, and `final-ready`; fix high-risk issues and rerun. `review-todo` must run before `wrap-final` physically splits blocks.
11. Read `references/summary-and-tone.md`, `references/note-style.md`, and `references/review-policy.md`; do the Yomiya tone micro-review before final note generation.
12. Generate per-video notes from final SRTs, inspect/compress them, then run `combine-summaries` to write one episode-level summary outside video folders.
13. Burn final SRTs into MP4s with duration validation, run `screenshot-check`, inspect contact sheets, and reburn if visual QA fails.
14. Run `cleanup` only after final subtitles, burned videos, screenshot QA, and the combined summary are confirmed. Do not delete screenshot-check files before contact sheets have been inspected.

For resume work, scan checkpoints first and continue from the earliest missing or invalid stage. Do not restart completed valid work unless the user asks for a fresh run or a concrete defect requires regeneration.

## Non-Negotiables

- Preserve quality: production uses Whisper large-v3-turbo plus local Silero VAD as the main ASR, Qwen3-ASR-1.7B risk-segment comparison as the default high-quality ASR enhancement, DeepSeek V4-Pro translation, DeepSeek V4-Pro self-polish, Codex final proofread, local QA gates, summary inspection, duration validation, and screenshot QA.
- Public-release strict is the default: Codex final proofread covers 100% of source/final subtitle blocks. Reduced review is allowed only when the user explicitly trades quality for speed or cost.
- Summary-only means no MP4 organization, no ASR, no reburn, no cleanup, and no video edits.
- Codex final proofread uses only-corrections editing: patch only changed blocks, preserve stable blocks, and never regenerate the full SRT as the review output.
- Do not downgrade DeepSeek stages or skip self-polish for speed or cost unless the user explicitly requests that tradeoff.
- Do not replace Whisper timing with Qwen text automatically. Qwen comparison is evidence for Codex source review, not an autonomous source-SRT rewrite stage.
- Do not treat helper reports as formalities. Read them, fix high-risk issues, and rerun checks before burning or reporting.
- Never create or patch Japanese or Chinese subtitle text through a PowerShell pipeline or here-string; use UTF-8 files and explicit `utf-8-sig` or `utf-8` reads/writes.
- HOOOOPE fixed-term traps belong in `references/terms-glossary.md`, project glossary files, or helper audits, not repeated throughout this main prompt.

## Validation

For helper regression checks, run:

```powershell
python <skill_dir>\scripts\hoooope_subtitles.py self-test
python <skill_dir>\scripts\hoooope_subtitles.py doctor <episode_dir>
```

For skill structure validation, run the skill-creator validator:

```powershell
python <skill_dir>\..\.system\skill-creator\scripts\quick_validate.py <skill_dir>
```

Before final delivery, confirm the main `SKILL.md` remains short enough to be a routing guide rather than a full production manual.
