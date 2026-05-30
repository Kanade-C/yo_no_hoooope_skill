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

## Default Workflow

For full subtitle production, use the staged pipeline where possible:

```powershell
python <skill_dir>\scripts\hoooope_subtitles.py pipeline <episode_dir>
python <skill_dir>\scripts\hoooope_subtitles.py pipeline <episode_dir> --stage post-review
python <skill_dir>\scripts\hoooope_subtitles.py mark-proofread <episode_dir>
python <skill_dir>\scripts\hoooope_subtitles.py pipeline <episode_dir> --stage burn-cleanup
python <skill_dir>\scripts\hoooope_subtitles.py cleanup <episode_dir>
```

Always read `references/workflow.md` before acting on an episode folder: it holds the full step-by-step production flow, folder layout, checkpoints, resume rules, and the summary-only branch. Continue from the earliest missing or invalid checkpoint; do not restart completed valid work unless the user asks for a fresh run or a concrete defect requires regeneration.

## Non-Negotiables

- Preserve quality: production uses Whisper large-v3-turbo plus local Silero VAD as the main ASR, Qwen3-ASR-1.7B risk-segment comparison as the default high-quality ASR enhancement, DeepSeek V4-Pro translation, DeepSeek V4-Pro self-polish, Codex final proofread, local QA gates, summary inspection, duration validation, and screenshot QA.
- Public-release strict is the default: Codex final proofread covers 100% of source/final subtitle blocks. Reduced review is allowed only when the user explicitly trades quality for speed or cost.
- After Codex proofread, write the hash-anchored proofread receipt with `mark-proofread`; `burn-cleanup` requires matching receipt evidence by default.
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
