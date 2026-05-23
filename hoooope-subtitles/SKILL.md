---
name: hoooope-subtitles
description: Create Chinese subtitles, burned MP4 outputs, and Chinese note-style summaries for HOOOOPE podcast videos. Use for per-episode or per-batch folders that may contain one regular video plus member videos, preferably named with date-based stems such as hope_25_0513. The workflow uses a local faster-whisper model, DeepSeek V4-Pro initial translation and self-polish, Codex final inspection, automatic duration validation, final cleanup, and dynamic project glossary injection from hooope_terms.txt.
---

# HOOOOPE Subtitles

## Core Workflow

Use this skill for any HOOOOPE episode or batch folder, not just one fixed episode number.

Expected inputs:

```text
<episode>/
  hope_<yy>_<mmdd>.mp4
  hope_<yy>_<mmdd>_*.mp4
  # legacy names are also supported:
  hooope_<episode>.mp4
  hooope_<episode>_member*.mp4
model/
hooope_terms.txt
```

Use date-based stems when possible, for example `hope_25_0513.mp4`, `hope_25_0520.mp4`, `hope_25_0527.mp4`, and `hope_25_0603.mp4`. Date-based names are clearer than episode/member ordinals and should be preserved through folder and file names. Legacy `hoooope_<episode>` names remain valid for older folders.

Process every `.mp4` in the episode folder, including the regular video and any number of member videos. First organize each root-level MP4 into its own `<episode>/<stem>/` work folder, then keep all derived files for that MP4 in the same folder. Do not merge multiple videos into one translation prompt; each video keeps its own transcript, subtitles, summary, burn validation, and final files. For each `<stem>`:

1. Read `references/terms-and-notes.md`, then read the project glossary `hooope_terms.txt` when present. Project glossary wording is appended later and overrides the bundled reference.
2. Confirm the local faster-whisper model folder exists at `model/` unless the user supplies another model path.
3. Transcribe Japanese speech to `<episode>/<stem>/<stem>.orig.srt`.
4. Use DeepSeek V4-Pro for full initial translation to `<episode>/<stem>/<stem>.deepseek.raw.srt`.
5. Use DeepSeek V4-Pro again for self-polish against the Japanese source to `<episode>/<stem>/<stem>.deepseek.polished.srt`, and generate `<episode>/<stem>/<stem>.qa.txt`.
6. Codex acts as final inspector. Review every QA issue block plus a 25%-30% sample. Do not reduce this review ratio because DeepSeek self-polish was used.
7. Save the final inspected Chinese subtitle as `<episode>/<stem>/<stem>.srt`, then run `validate`, `lint-final --strict-public`, `terms-audit`, `proper-noun-candidates`, and `review-todo`. Codex uses these outputs to fix high-risk translation issues; the user is not expected to inspect them.
8. Generate `<episode>/<stem>/<stem>.summary.txt` automatically from the final Chinese SRT using the note style in `references/terms-and-notes.md`. The automatic draft may be broader to avoid missing useful moments; Codex then checks factual consistency and edits it into a concise, balanced viewing note. Prefer about 2,000 Chinese characters for the final combined episode summary and do not exceed 3,000 Chinese characters unless the user explicitly asks for a long note.
9. Burn subtitles into the source MP4 and replace the original un-subtitled file only after duration validation passes.
10. Run `screenshot-check` on the burned MP4. Codex inspects the contact sheet for subtitle visibility, placement, overlap, and mixed-width line rendering; the user is not expected to inspect it.
11. Clean intermediate files so each video folder remains minimal.
12. Combine all per-video `*.summary.txt` notes into one episode-level note at `<episode>/<episode>.summary.txt`. Each section starts with the video folder name as the title and sections are separated by `————————————`. After the combined note is written successfully, delete the per-video `*.summary.txt` files by default.

## Command Pattern

Use relative/project-local paths. Do not hardcode machine-specific paths such as a user home directory.

The bundled helper `scripts/hooope_subtitles.py` is resolved relative to this skill folder. In examples below, `<skill_dir>` means the folder containing this `SKILL.md`.

```powershell
$episode_id = "<episode_folder>"
$episode = ".\$episode_id"
$skill = "<skill_dir>"

# Put each root-level MP4 into its own work folder before transcription.
Get-ChildItem -LiteralPath $episode -Filter "*.mp4" -File | Sort-Object Name | ForEach-Object {
  $stem = [IO.Path]::GetFileNameWithoutExtension($_.Name)
  $workdir = Join-Path $episode $stem
  New-Item -ItemType Directory -Force -Path $workdir | Out-Null
  Move-Item -LiteralPath $_.FullName -Destination (Join-Path $workdir $_.Name)
}

$videos = Get-ChildItem -LiteralPath $episode -Directory |
  Sort-Object Name |
  ForEach-Object { Get-ChildItem -LiteralPath $_.FullName -Filter "*.mp4" -File | Sort-Object Name }

foreach ($video in $videos) {
  $media = $video.FullName
  $workdir = $video.DirectoryName

  $stem = [IO.Path]::GetFileNameWithoutExtension($media)
  $orig = Join-Path $workdir "$stem.orig.srt"
  $raw = Join-Path $workdir "$stem.deepseek.raw.srt"
  $polished = Join-Path $workdir "$stem.deepseek.polished.srt"
  $qa = Join-Path $workdir "$stem.qa.txt"
  $final = Join-Path $workdir "$stem.srt"
  $note = Join-Path $workdir "$stem.summary.txt"

  python "$skill\scripts\hooope_subtitles.py" transcribe $media --output $orig --model-dir ".\model"
  python "$skill\scripts\deepseek_translate_srt.py" $orig --output $raw --model deepseek-v4-pro --chunk-size 100 --qa-sample-ratio 0.28
  python "$skill\scripts\deepseek_polish_srt.py" $orig --translation $raw --output $polished --qa-output $qa --model deepseek-v4-pro --chunk-size 100 --polish-workers 4 --qa-sample-ratio 0.28

  Copy-Item $polished $final -Force
  # Codex final inspection edits $final after reviewing $qa plus sampled source/translation blocks.
  python "$skill\scripts\hooope_subtitles.py" validate $final
  python "$skill\scripts\hooope_subtitles.py" lint-final $final --strict-public
  python "$skill\scripts\hooope_subtitles.py" terms-audit $final
  python "$skill\scripts\hooope_subtitles.py" proper-noun-candidates $orig
  python "$skill\scripts\hooope_subtitles.py" review-todo --orig $orig --final $final
  python "$skill\scripts\deepseek_note_srt.py" $final --output $note --model deepseek-v4-pro
  python "$skill\scripts\hooope_subtitles.py" burn $media --subtitle $final --encoder auto --replace-source
  python "$skill\scripts\hooope_subtitles.py" screenshot-check $media --subtitle $final
}

python "$skill\scripts\hooope_subtitles.py" cleanup $episode
python "$skill\scripts\hooope_subtitles.py" combine-summaries $episode
```

## Translation Policy

Default path:

1. DeepSeek V4-Pro translates 100% of the SRT.
2. DeepSeek V4-Pro self-polishes 100% of that translation against the Japanese source.
3. The polishing script writes a QA report.
4. Codex is the final inspector and reviews every QA issue block plus 25%-30% sampled blocks.
5. For subtitles intended for broad audiences, raise the Codex final review to at least about 35% targeted sampling. Increase to 35%-40% or more when the episode has dense jokes, game rules, uncertain names, many fixed terms, or obvious machine-translation tone.

Avoid local MT models such as NLLB, MarianMT, OPUS-MT, or transformers pipelines unless the user explicitly asks for them.

The DeepSeek scripts load the bundled `references/terms-and-notes.md` first and project glossary files such as `hooope_terms.txt` after it. This order lets project glossary wording override bundled reference wording in the final prompt.

Initial translation chunks include a 10-subtitle overlap with the previous chunk. The final merged raw translation deduplicates by SRT block number, so every source subtitle appears exactly once in the output while each chunk can see preceding context. Overlap is included in translation cache filenames to avoid reusing non-overlap cache files.

Self-polish remains a full 100% second pass against the Japanese source and raw Chinese translation. It may run chunk polishing concurrently with `--polish-workers` because each raw chunk has already been produced and cached by the serial context-aware translation pass. Do not use concurrency to skip or reduce the self-polish pass.

## Codex Final Inspection

Codex should not blindly re-translate the full SRT. Instead:

- Read `<stem>.qa.txt`.
- Review every QA issue block against the corresponding Japanese source and polished Chinese subtitle.
- Review sampled blocks from the QA report.
- Search the final subtitle for common bad terms: `HOPE` where it should be `HOOOOPE`, host-name mistakes, member-name mistakes, fixed-term mistakes, Japanese residue, empty lines, overlong lines, and unusually long subtitle durations.
- Check opening/title blocks manually. If `Open` appears near `Extend Step`, `HOOOOPE`, or `羊宫妃那`, treat it as a likely ASR mistranscription of `HOOOOPE` and correct it unless the episode clearly discusses opening/closing something.
- Run `scripts/hooope_subtitles.py lint-final <stem>.srt --strict-public`, `scripts/hooope_subtitles.py terms-audit <stem>.srt`, `scripts/hooope_subtitles.py proper-noun-candidates <stem>.orig.srt`, and `scripts/hooope_subtitles.py review-todo --orig <stem>.orig.srt --final <stem>.srt`, then fix high-risk issues before burning. `lint-final` also reports subtitle durations longer than the default threshold; inspect these and either split/adjust the subtitle or confirm the long display is appropriate for a silent drawing, cooking, crafting, or visual-only segment.
- Do a translation-quality pass for broad audiences. Review sampled non-QA blocks that are likely to expose machine translation weakness: listener-letter openings, host reactions, jokes, self-corrections, uncertain names, brand/product names, game rules, and dense long sentences.
- Prefer natural Chinese subtitle rhythm over literal Japanese word order. Preserve meaning and personality, but remove machine-translation tone, over-formal phrasing, and awkward direct translations.
- Keep Yomiya Hina's distinctive hesitation, teasing, self-correction, and staff interaction when they carry personality or humor. Compress filler only when it creates reading burden without adding tone.
- Apply targeted fixes and write the final `<stem>.srt`.
- Validate and lint the final SRT before burning.
- After burning, run `scripts/hooope_subtitles.py screenshot-check <stem>.mp4 --subtitle <stem>.srt`. Codex inspects the contact sheet and fixes/reburns if subtitles are unreadable, too low, overlapping important visual information, or visually too wide.

## Yomiya Tone Micro-Review

After the final Chinese SRT passes basic validation and before generating the summary, do a targeted micro-review for Yomiya Hina's speaking tone. This is not a rewrite stage. Use this priority order: faithfulness to the Japanese source, natural Chinese subtitles, then Yomiya tone.

Use `celebrity-yomiya-hina` only as an optional tone-calibration reference. It must not rewrite facts, dates, names, event information, product information, or segment rules. Do not make subtitles sound like a fictional persona, fan imitation, or composed SNS post.

Review only blocks likely to carry tone:

- First-person feelings, reactions, self-corrections, hesitation, uncertainty, embarrassment, or laughter.
- Responses to listener letters.
- Thanks, announcements, requests for submissions, and closing remarks.
- Moments where she is carefully choosing words.

Apply edits only when the current Chinese is clearly too stiff, too promotional, too internet-slangy, too artificially cute, too assertive compared with the source, or emotionally flattened. Keep lines unchanged when they are already faithful and natural. Do not add `我觉得`, `可能`, `如果方便的话`, or similar softeners unless the Japanese source is tentative or self-checking.

## Auto Note

Generate `<stem>.summary.txt` from final `<stem>.srt`, not from the video. Use `scripts/deepseek_note_srt.py` for an automatic first draft. The script first extracts candidate topic boundaries from the SRT, then asks DeepSeek to write the note. The draft must follow `references/terms-and-notes.md`: note-style paragraphs, approximate timestamps, topic headings, no formal key-point list.

Codex then inspects and edits the note for topic coverage, factual consistency, time accuracy, tone, and length. The final note should be selective rather than exhaustive: keep the parts that help a viewer decide what to revisit, especially moments about Yomiya Hina herself. Before combining summaries, verify facts that viewers may rely on: dates, event titles, performers, brands, product names, work titles, corner names, and `Supported by` title text. `combine-summaries` reports Chinese character count and fails above 3,000 chars by default; shorten the summary rather than asking the user to inspect it.

After all per-video notes are inspected, run `scripts/hooope_subtitles.py combine-summaries <episode>` to create a single episode-level note outside the per-video folders. The combined file should live directly under the episode folder, for example `<episode>/<episode>.summary.txt`, and contain one section per video. The command deletes the per-video `*.summary.txt` files after successful combination; use `--keep-parts` only when explicitly preserving drafts for debugging.

```text
## hope_25_0513

[that video's note]

————————————

## hope_25_0520

[that video's note]
```

Coverage and length requirements:

- Treat the summary as a concise episode note, not a full program digest. It should be useful to someone deciding which parts of the episode to revisit.
- The combined episode-level summary should usually be about 2,000 Chinese characters and must stay under 3,000 Chinese characters unless the user explicitly asks for a longer note. If there are multiple videos in one episode, allocate the length by content value, not evenly by file count.
- Cover the whole episode with roughly balanced attention to the beginning, middle, and end. Do not let the first 20 minutes consume most of the note unless the remaining episode is genuinely repetitive.
- Be selective. Prioritize: moments where Yomiya Hina expresses her own thoughts, judgment, values, preferences, memories, or recent personal state; funny or distinctive reactions, verbal habits, mistakes, self-corrections, and staff interactions; listener letters or corners that reveal something about Yomiya Hina herself.
- Compress or omit low-value details: routine announcements, product copy, mechanical corner rules, repeated listener letters with the same point, and generic topic transitions. Keep these only when Yomiya Hina adds a notable reaction or interpretation.
- Do not collapse later segments into vague phrases such as `later listener letters` or `miscellaneous messages` when the SRT shows distinct high-value topics. Instead, pick the strongest later moments and name them clearly.
- For a 50-60 minute regular episode, aim for about 7-10 topic sections. For a short member video, use the actual content density, typically 2-4 sections. Merge adjacent weak sections instead of listing every corner.
- Every major corner or recurring segment should be checked, but not every corner must receive its own section. Represent a corner when it contains a strong Yomiya-centered moment; otherwise compress it into nearby context or omit it.
- Before accepting the note, skim SRT timestamps at approximately 0%, 25%, 50%, 75%, and the final 5 minutes, plus any obvious segment markers found by searching terms such as `环节`, `Battle`, `Step Up`, `After Talk`, `通知`, `来信`, and `接下来`.
- If any continuous 15-minute span of a regular episode has no representation, first look for the strongest Yomiya-centered moment in that span and swap out a weaker section elsewhere. Expand only if the note remains under the length limit.
- Light editing is not enough when coverage is skewed or the note reads like a full transcript outline. Rewrite the note from a short SRT outline if needed.

## Burning And Validation

Burn with `scripts/hooope_subtitles.py burn ... --encoder auto --replace-source`.

Requirements:

- Prefer NVENC, fall back to libx264 when NVENC fails.
- Burn to a temporary file first.
- Use `ffprobe` to compare source and burned output durations.
- If duration difference is greater than 1 second, fail and do not replace the source video.
- If duration validation passes, replace the original un-subtitled MP4 with the burned MP4.
- After replacement, run `screenshot-check`; Codex inspects the generated contact sheet before cleanup. Check whether subtitles cover important visual content, sit too low, are too large, lose contrast, or overflow because of mixed Chinese/English/Japanese width.
- Do not keep screenshot check files after visual QA is complete.

## Final Episode Folder

After cleanup, only these core assets should remain for each processed video:

```text
<episode>/
  <episode>.summary.txt
  hope_25_0513/
    hope_25_0513.mp4
    hope_25_0513.orig.srt
    hope_25_0513.srt
  hope_25_0520/
    hope_25_0520.mp4
    hope_25_0520.orig.srt
    hope_25_0520.srt
  hope_25_0527/
    hope_25_0527.mp4
    hope_25_0527.orig.srt
    hope_25_0527.srt
```

Delete these after final subtitle and burned video are confirmed:

- `<stem>.deepseek.raw.srt`
- `<stem>.deepseek.polished.srt`
- `<stem>.qa.txt`
- per-video `<stem>.summary.txt` files after `<episode>.summary.txt` is confirmed
- DeepSeek chunk/cache folders
- Temporary burned files
- Screenshot check files

## Fallback

If DeepSeek is unavailable, use `split-srt` and `merge-srt` from `scripts/hooope_subtitles.py` for Codex chunk translation. This fallback costs more Codex tokens and should be used only when API translation is not available.
