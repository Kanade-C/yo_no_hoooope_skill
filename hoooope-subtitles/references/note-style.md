# HOOOOPE Note Style

Use this when generating, editing, compressing, or combining `.summary.txt` files.

`.summary.txt` is a viewer-facing episode note, not a transcript, a formal minutes document, or a complete digest.

## Length And Selection

- DeepSeek automatic drafts can be slightly broad so later segments and hidden interesting moments are not lost.
- Codex final notes must be compressed and merged. The episode-level summary should usually be about 2,000 Chinese characters and must stay under 3,000 unless the user asks for a long note.
- Final notes should be short and evenly distributed across the episode. The goal is to help viewers decide which parts are worth rewatching.
- Prioritize moments related to Yomiya Hina herself: her thoughts, judgment, values, preferences, memories, recent state, distinctive reactions, humor, verbal habits, self-corrections, and staff interactions.
- Listener letters and fixed corners should be kept only when they draw out Yomiya's own thinking or a notable reaction. Routine announcements, product copy, mechanical rules, repeated letters, and generic transitions should be compressed or omitted.
- Cover opening, middle, late episode, and ending by selecting the best points, not by listing every segment.

## Structure

```text
[日期可选] 小羊 HOOOOPE 笔记

[用 1-2 句总述本期氛围和最值得回看的内容。]

————————————

『[话题/来信标题]』
[大致时间，例如 01:27左右] 这个片段为什么值得回看。重点写羊宫妃那的想法、反应、表达或和她本人有关的展开。写成自然段。

『[下一个话题/来信标题]』
[大致时间] 继续用自然段概括。可以根据节目内容添加更多话题段落。

#羊宫妃那
```

## Rules

- Use final Chinese `.srt` as the source.
- Use subtitle timings for approximate timestamps; do not extract extra timing from the video.
- Use `『topic title』` headings and natural paragraphs.
- Explain why the segment is worth rewatching; do not merely restate the listener letter.
- For 50-60 minute regular episodes, usually keep 7-10 topic sections. For short member videos, 2-3 compact sections is usually enough; dense short videos may use 4.
- Do not write the late episode as generic "后半场" or "来信集锦"; choose concrete segments when late content is worth keeping.
- Check major corners such as `HOOOOPE Battle`, `HOOOOPE Step Up`, `After Talk`, sponsor-copy areas, announcements, and monthly letter themes, but omit or compress them when they lack Yomiya-centered value.
- Any continuous 15-minute span of a regular episode should not be completely absent. If missing, replace weaker material elsewhere before adding length.
- Do not write a formal `本期要点：` bullet list unless the user explicitly requests it.
- The tone can be warm and fan-readable, but should stay concrete, neutral, and useful for deciding whether to watch. Reduce repeated praise such as “超级可爱”, “太好笑了”, “神企划”, or “任性又可爱”.
