#  Review And QA Reference

Use this when Codex is inspecting final subtitles, consuming QA artifacts, or validating burned video.

## Final Proofread

Start from `<stem>.deepseek.polished.srt` copied to `<stem>.srt`. Read `<stem>.qa.txt` as priority context, but still cover 100% of the Japanese source against the Chinese final SRT in manageable chunks. This is the default `public-release strict` mode described in `references/review-policy.md`.

Use only-corrections editing:

- Patch only blocks that need changes.
- Preserve stable blocks exactly.
- Preserve numbering and timestamps unless a separate timing fix is required.
- Do not rewrite the full SRT, neighboring blocks, or the whole chunk for style.
- Apply corrections directly to `<stem>.srt`; do not leave review suggestions as deliverables.

Prefer natural Chinese subtitle rhythm over literal Japanese order, but do not add unsupported softeners, cuteness, jokes, facts, or explanations. Keep hesitation, teasing, self-correction, laughter, and staff interaction when they carry meaning or humor.

After the full proofread is complete, run `python <skill_dir>\scripts\hoooope_subtitles.py mark-proofread <episode>` to write the hash-anchored proofread receipt. If any final SRT changes after that, rerun the proofread check and `mark-proofread`; `burn-cleanup` rejects stale receipt hashes by default.

## Local Gates

After proofread and before burn, run and consume:

```powershell
python <skill_dir>\scripts\hoooope_subtitles.py normalize-punctuation <stem>.srt
python <skill_dir>\scripts\hoooope_subtitles.py review-todo --orig <stem>.orig.srt --final <stem>.srt
python <skill_dir>\scripts\hoooope_subtitles.py wrap-final <stem>.srt
python <skill_dir>\scripts\hoooope_subtitles.py validate <stem>.srt
python <skill_dir>\scripts\hoooope_subtitles.py baseline-report <stem>.srt
python <skill_dir>\scripts\hoooope_subtitles.py lint-final <stem>.srt --strict-public
python <skill_dir>\scripts\hoooope_subtitles.py terms-audit <stem>.srt
python <skill_dir>\scripts\hoooope_subtitles.py proper-noun-candidates <stem>.orig.srt
python <skill_dir>\scripts\hoooope_subtitles.py final-ready <episode>
```

Run `review-todo` before `wrap-final` so its block-number comparison still reflects the unsplit DeepSeek/Codex final SRT. Fix high-risk issues, then rerun validation. QA artifacts are Codex inputs, not user homework.

Use helper commands over ad hoc recursive globs when scanning episode folders; they exclude workbench directories by default.

## Line And Timing Rules

For overlong lines, split Chinese text into at most two readable lines while preserving numbering and timestamps. Do not retranslate a block just because the line is too long.

`wrap-final` should prefer punctuation, clause boundaries, connectives, particles, and dependency/token boundaries when available. Protect official titles, names, English terms, numbers, and fixed glossary spans.

Long subtitle durations are not automatically acceptable. For short spoken text over 30 seconds, shorten the display interval or split/adjust the subtitle unless it is clearly a silent visual segment such as drawing, cooking, crafting, prop inspection, or gameplay.

Consecutive repeated subtitles can be correct when the source repeats the same reaction. If accepted, mention it as a residual lint item in the final report.

## Fixed-Term Review

Use `references/terms-glossary.md`, project glossary entries, `terms-audit`, `proper-noun-candidates`, and `review-todo` for HOOOOPE-specific fixed-term traps. Do not keep Japanese residue in public subtitles unless the original form is meaningful to the segment.

Listener nicknames in kana or mixed Japanese are usually romanized or transliterated for public Chinese subtitles unless an established Chinese spelling exists or the Japanese form itself is the point.

## Burn And Screenshot QA

Burn with:

```powershell
python <skill_dir>\scripts\hoooope_subtitles.py burn <stem>.mp4 --subtitle <stem>.srt --encoder auto --replace-source
python <skill_dir>\scripts\hoooope_subtitles.py screenshot-check <stem>.mp4 --subtitle <stem>.srt
```

The burn helper writes a temporary file, prefers NVENC, falls back to libx264, compares source/output durations, and replaces the original only if duration difference is within 1 second.

Open and inspect the contact sheet before cleanup. Check readability, contrast, lower-safe-area placement, two-line wrapping, mixed-width overflow, and overlap with faces, hands, props, game boards, product labels, or on-screen text. Reburn after fixing text, line breaks, or burn style if the sheet fails. Only run `cleanup` after this visual QA has passed.
