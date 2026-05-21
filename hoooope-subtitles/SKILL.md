---
name: hoooope-subtitles
description: Create Chinese subtitles, burned MP4 outputs, and Chinese note-style summaries for HOOOOPE podcast videos. Use for per-episode folders that may contain both regular and member videos, such as hooope episode-number mp4 and hooope episode-number member mp4. The workflow uses a local faster-whisper model, DeepSeek V4-Pro initial translation and self-polish, Codex final inspection, automatic duration validation, final cleanup, and dynamic project glossary injection from hooope_terms.txt.
---

# HOOOOPE Subtitles

## Core Workflow

Use this skill for any numbered HOOOOPE episode folder, not just one fixed episode number.

Expected inputs:

```text
<ep_num>/
  hooope_<ep_num>.mp4
  hooope_<ep_num>_member.mp4
model/
hooope_terms.txt
```

Process both regular and member videos when both exist. For each `<stem>`:

1. Read `references/terms-and-notes.md`, then read the project glossary `hooope_terms.txt` when present. Project glossary wording is appended later and overrides the bundled reference.
2. Confirm the local faster-whisper model folder exists at `model/` unless the user supplies another model path.
3. Transcribe Japanese speech to `<ep_num>/<stem>.orig.srt`.
4. Use DeepSeek V4-Pro for full initial translation to `<ep_num>/<stem>.deepseek.raw.srt`.
5. Use DeepSeek V4-Pro again for self-polish against the Japanese source to `<ep_num>/<stem>.deepseek.polished.srt`, and generate `<ep_num>/<stem>.qa.txt`.
6. Codex acts as final inspector. Review every QA issue block plus a 25%-30% sample. Do not reduce this review ratio because DeepSeek self-polish was used.
7. Save the final inspected Chinese subtitle as `<ep_num>/<stem>.srt`, then run `validate` and `lint-final`.
8. Generate `<ep_num>/<stem>.summary.txt` automatically from the final Chinese SRT using the note style in `references/terms-and-notes.md`, then let Codex inspect and lightly edit it.
9. Burn subtitles into the source MP4 and replace the original un-subtitled file only after duration validation passes.
10. Clean intermediate files so the episode folder remains minimal.

## Command Pattern

Use relative/project-local paths. Do not hardcode machine-specific paths such as a user home directory.

The bundled helper `scripts/hooope_subtitles.py` is resolved relative to this skill folder. In examples below, `<skill_dir>` means the folder containing this `SKILL.md`.

```powershell
$ep = "<ep_num>"
$episode = ".\$ep"
$skill = "<skill_dir>"
$videos = @("hooope_${ep}.mp4", "hooope_${ep}_member.mp4")

foreach ($video in $videos) {
  $media = Join-Path $episode $video
  if (-not (Test-Path $media)) { continue }

  $stem = [IO.Path]::GetFileNameWithoutExtension($media)
  $orig = Join-Path $episode "$stem.orig.srt"
  $raw = Join-Path $episode "$stem.deepseek.raw.srt"
  $polished = Join-Path $episode "$stem.deepseek.polished.srt"
  $qa = Join-Path $episode "$stem.qa.txt"
  $final = Join-Path $episode "$stem.srt"
  $note = Join-Path $episode "$stem.summary.txt"

  python "$skill\scripts\hooope_subtitles.py" transcribe $media --output $orig --model-dir ".\model"
  python "$skill\scripts\deepseek_translate_srt.py" $orig --output $raw --model deepseek-v4-pro --chunk-size 70 --qa-sample-ratio 0.28
  python "$skill\scripts\deepseek_polish_srt.py" $orig --translation $raw --output $polished --qa-output $qa --model deepseek-v4-pro --chunk-size 70 --qa-sample-ratio 0.28

  Copy-Item $polished $final -Force
  # Codex final inspection edits $final after reviewing $qa plus sampled source/translation blocks.
  python "$skill\scripts\hooope_subtitles.py" validate $final
  python "$skill\scripts\hooope_subtitles.py" lint-final $final
  python "$skill\scripts\deepseek_note_srt.py" $final --output $note --model deepseek-v4-pro
  python "$skill\scripts\hooope_subtitles.py" burn $media --subtitle $final --encoder auto --replace-source
}

python "$skill\scripts\hooope_subtitles.py" cleanup $episode
```

## Translation Policy

Default path:

1. DeepSeek V4-Pro translates 100% of the SRT.
2. DeepSeek V4-Pro self-polishes 100% of that translation against the Japanese source.
3. The polishing script writes a QA report.
4. Codex is the final inspector and reviews every QA issue block plus 25%-30% sampled blocks.
5. Increase Codex review to 35%-40% when the episode has dense jokes, game rules, uncertain names, or many fixed terms.

Avoid local MT models such as NLLB, MarianMT, OPUS-MT, or transformers pipelines unless the user explicitly asks for them.

The DeepSeek scripts load the bundled `references/terms-and-notes.md` first and project glossary files such as `hooope_terms.txt` after it. This order lets project glossary wording override bundled reference wording in the final prompt.

## Codex Final Inspection

Codex should not blindly re-translate the full SRT. Instead:

- Read `<stem>.qa.txt`.
- Review every QA issue block against the corresponding Japanese source and polished Chinese subtitle.
- Review sampled blocks from the QA report.
- Search the final subtitle for common bad terms: `HOPE` where it should be `HOOOOPE`, host-name mistakes, Japanese residue, empty lines, and overlong lines.
- Run `scripts/hooope_subtitles.py lint-final <stem>.srt` and fix any reported issues before burning.
- Apply targeted fixes and write the final `<stem>.srt`.
- Validate and lint the final SRT before burning.

## Auto Note

Generate `<stem>.summary.txt` from final `<stem>.srt`, not from the video. Use `scripts/deepseek_note_srt.py` for an automatic first draft. The script first extracts candidate topic boundaries from the SRT, then asks DeepSeek to write the note. The draft must follow `references/terms-and-notes.md`: note-style paragraphs, approximate timestamps, topic headings, no formal key-point list.

Codex then inspects the note for topic coverage, time accuracy, and tone.

## Burning And Validation

Burn with `scripts/hooope_subtitles.py burn ... --encoder auto --replace-source`.

Requirements:

- Prefer NVENC, fall back to libx264 when NVENC fails.
- Burn to a temporary file first.
- Use `ffprobe` to compare source and burned output durations.
- If duration difference is greater than 1 second, fail and do not replace the source video.
- If duration validation passes, replace the original un-subtitled MP4 with the burned MP4.
- Do not keep screenshot check files.

## Final Episode Folder

After cleanup, only these core assets should remain for each processed video:

```text
<ep_num>/
  hooope_<ep_num>.mp4
  hooope_<ep_num>.orig.srt
  hooope_<ep_num>.srt
  hooope_<ep_num>.summary.txt
  hooope_<ep_num>_member.mp4
  hooope_<ep_num>_member.orig.srt
  hooope_<ep_num>_member.srt
  hooope_<ep_num>_member.summary.txt
```

Delete these after final subtitle and burned video are confirmed:

- `<stem>.deepseek.raw.srt`
- `<stem>.deepseek.polished.srt`
- `<stem>.qa.txt`
- DeepSeek chunk/cache folders
- Temporary burned files
- Screenshot check files

## Fallback

If DeepSeek is unavailable, use `split-srt` and `merge-srt` from `scripts/hooope_subtitles.py` for Codex chunk translation. This fallback costs more Codex tokens and should be used only when API translation is not available.
