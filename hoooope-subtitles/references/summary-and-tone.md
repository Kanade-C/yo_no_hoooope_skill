# Summary And Tone Reference

Use this when generating episode notes or doing the Yomiya tone micro-review.

## Auto Note

Generate each `<stem>.summary.txt` from the final Chinese `<stem>.srt`, not from the video. Use:

```powershell
python <skill_dir>\scripts\deepseek_note_srt.py <stem>.srt --output <stem>.summary.txt --model deepseek-v4-pro
```

The script extracts candidate topic boundaries, asks DeepSeek for a draft, and uses `references/note-style.md` plus `references/terms-glossary.md` for note style and fixed terms. Treat the result as a draft. Codex must inspect and edit it for topic coverage, factual consistency, time accuracy, tone, and length.

Before combining summaries, verify viewer-relevant facts: dates, event titles, performers, brands, product names, work titles, corner names, and `Supported by` title text.

Combine after all per-video notes pass inspection:

```powershell
python <skill_dir>\scripts\hoooope_subtitles.py combine-summaries <episode>
```

The combined note lives directly under the episode folder as `<episode>/<episode>.summary.txt`. Per-video summaries are deleted after successful combination unless `--keep-parts` is explicitly used for debugging.

## Compression Policy

The episode summary is a concise viewing note, not a full digest or promotional copy. The combined episode-level summary should usually be about 2,000 Chinese characters and must stay under 3,000 unless the user asks for a long note.

Allocate length by content value, not file count. For a 50-60 minute regular episode, aim for about 7-10 topic sections. For short member videos, 2-3 compact sections is usually enough.

Prioritize moments where Yomiya Hina expresses her thoughts, judgment, values, preferences, memories, or recent state; distinctive reactions, humor, verbal habits, self-corrections, and staff interactions; listener letters that reveal something about her.

Compress or omit routine announcements, product copy, mechanical corner rules, repeated letters with the same point, and generic transitions unless Yomiya adds notable reaction or interpretation.

Check coverage near 0%, 25%, 50%, 75%, and the final 5 minutes, plus obvious segment markers. If any continuous 15-minute span of a regular episode is absent, find the strongest Yomiya-centered moment in that span and replace weaker material elsewhere before expanding length.

If the draft reads like hype, fan copy, or transcript outline, rewrite it into concrete replayable viewing-note style with fewer adjectives and clearer timestamps.

## Yomiya Tone Micro-Review

Do this after final Chinese SRT passes basic validation and before generating the summary. It is a targeted micro-review, not a rewrite stage.

Priority order:

1. Faithfulness to the Japanese source.
2. Natural Chinese subtitle rhythm.
3. Yomiya Hina tone.

Use `celebrity-yomiya-hina` only as optional calibration. It must not change facts, dates, names, event information, product information, or segment rules. Do not make subtitles sound like a fictional persona, fan imitation, or composed SNS post.

Review only tone-bearing blocks: first-person feelings, reactions, self-corrections, hesitation, uncertainty, embarrassment, laughter, listener-letter responses, thanks, announcements, submission requests, closing remarks, and moments where she is carefully choosing words.

Edit only when the current Chinese is clearly too stiff, promotional, internet-slangy, artificially cute, assertive compared with the source, or emotionally flattened. Keep lines unchanged when already faithful and natural.
