# yo_no_hoooope_skill

Codex skill for producing publish-ready Chinese subtitles and burned videos for *Yomiya Hina no HOOOOPE*.

This repository packages the `hoooope-subtitles` skill: a conservative production workflow for Japanese ASR, Chinese subtitle translation, final QA, MP4 burn-in validation, screenshot review, cleanup, and concise Chinese viewing notes. It is built for HOOOOPE episodes, not as a generic subtitle toy.

## What It Does

- Creates Japanese source SRTs from episode MP4s.
- Uses Whisper large-v3-turbo with local Silero VAD as the default timing-stable ASR backbone.
- Runs Qwen3-ASR-1.7B on high-risk source segments as a sidecar comparison report.
- Translates and self-polishes 100% of subtitles with DeepSeek V4-Pro.
- Keeps Codex responsible for final full-pass review, fixed-term correction, and only-changed-block subtitle edits.
- Runs local release gates for structure, line length, public subtitle readability, fixed terms, proper nouns, and review TODOs.
- Burns final Chinese SRTs into MP4s with duration validation.
- Generates screenshot contact sheets for visual subtitle QA before cleanup.
- Writes a concise episode-level Chinese viewing note from final subtitles.

## Why This Workflow

HOOOOPE subtitles have recurring production risks: member names, program corners, listener nicknames, brand names, jokes, self-corrections, long pauses, BGM-heavy segments, and Japanese ASR homophones. The skill treats those as production constraints:

- Whisper owns the timing scaffold.
- Qwen is review evidence, not an automatic replacement for Whisper timing.
- DeepSeek handles full translation and self-polish.
- Codex consumes QA artifacts and makes the final judgment.
- Cleanup is blocked until burned video, screenshot QA, and summary output are confirmed.

## Repository Layout

```text
.
├─ README.md
└─ hoooope-subtitles/
   ├─ SKILL.md
   ├─ test-checklist.json
   ├─ agents/
   │  └─ openai.yaml
   ├─ references/
   │  ├─ workflow.md
   │  ├─ translation-and-asr.md
   │  ├─ review-and-qa.md
   │  ├─ summary-and-tone.md
   │  ├─ terms-glossary.md
   │  ├─ deepseek-prompts.md
   │  ├─ note-style.md
   │  └─ review-policy.md
   └─ scripts/
      ├─ hoooope_subtitles.py
      ├─ deepseek_translate_srt.py
      ├─ deepseek_polish_srt.py
      ├─ deepseek_note_srt.py
      └─ hooope_lib/
```

## Requirements

- Python 3.11+
- `ffmpeg` and `ffprobe`
- `stable-whisper`, `faster-whisper`, `onnxruntime`, `torch`
- DeepSeek API key in `DEEPSEEK_API_KEY`
- Local ASR assets, usually under the workspace `model/` directory:
  - `model/large_v3_turbo`
  - `model/qwen-3-asr-1.7b`
  - `model/silero_vad.onnx`
  - `model/hoooope_terms.txt`
- Optional for Qwen comparison: `qwen-asr`

Install Qwen support when you want the default high-quality ASR comparison to run instead of writing a skipped sidecar:

```powershell
python -m pip install -U qwen-asr
```

## Install As A Codex Skill

Copy or clone `hoooope-subtitles/` into your Codex skills directory:

```powershell
Copy-Item -Recurse -Force .\hoooope-subtitles C:\Users\CHENG\.codex\skills\hoooope-subtitles
```

Validate the installed skill:

```powershell
python C:\Users\CHENG\.codex\skills\.system\skill-creator\scripts\quick_validate.py C:\Users\CHENG\.codex\skills\hoooope-subtitles
python C:\Users\CHENG\.codex\skills\hoooope-subtitles\scripts\hoooope_subtitles.py self-test
```

## Typical Usage

In Codex, ask for full production on an episode folder:

```text
Use $hoooope-subtitles to process D:\yo_no_hoooope\hope_25_0715
```

The staged helper can also be run directly:

```powershell
python C:\Users\CHENG\.codex\skills\hoooope-subtitles\scripts\hoooope_subtitles.py pipeline D:\yo_no_hoooope\hope_25_0715
python C:\Users\CHENG\.codex\skills\hoooope-subtitles\scripts\hoooope_subtitles.py pipeline D:\yo_no_hoooope\hope_25_0715 --stage post-review
python C:\Users\CHENG\.codex\skills\hoooope-subtitles\scripts\hoooope_subtitles.py pipeline D:\yo_no_hoooope\hope_25_0715 --stage burn-cleanup
```

Useful ASR switches:

```powershell
# Default: Whisper backbone + Qwen risk-segment sidecar
--asr-enhancement qwen-risk

# Require Qwen comparison and fail if qwen_asr is unavailable
--asr-enhancement qwen-risk-required

# Whisper-only path
--asr-enhancement off
```

For summary-only requests, the skill must not touch videos:

```powershell
python C:\Users\CHENG\.codex\skills\hoooope-subtitles\scripts\hoooope_subtitles.py pipeline D:\yo_no_hoooope\hope_25_0715 --stage post-review --summary-only
```

## Output Shape

Each root MP4 is organized into a same-stem work folder. The episode root keeps the combined summary:

```text
hope_25_0715/
├─ hope_25_0715.summary.txt
├─ hope_25_0715/
│  ├─ hope_25_0715.mp4
│  ├─ hope_25_0715.orig.raw.srt
│  ├─ hope_25_0715.orig.srt
│  ├─ hope_25_0715.asr.compare.txt
│  └─ hope_25_0715.srt
└─ hope_25_0715_member/
   ├─ hope_25_0715_member.mp4
   ├─ hope_25_0715_member.orig.raw.srt
   ├─ hope_25_0715_member.orig.srt
   ├─ hope_25_0715_member.asr.compare.txt
   └─ hope_25_0715_member.srt
```

Intermediate DeepSeek files, QA reports, chunk caches, screenshot-check files, and per-video summaries are workbench artifacts. Codex consumes them before final reporting; they are not user homework.

## Quality Policy

Default production is `public-release strict`:

- 100% DeepSeek initial translation.
- 100% DeepSeek self-polish.
- 100% Codex source/final subtitle proofread in manageable chunks.
- Only-corrections editing for final SRTs.
- Mandatory public-release gates before burn.
- Screenshot contact sheet inspection before cleanup.

Reduced review is only for explicit speed/cost tradeoffs.

## Development Checks

```powershell
python -m py_compile .\hoooope-subtitles\scripts\hoooope_subtitles.py
python .\hoooope-subtitles\scripts\hoooope_subtitles.py self-test
python .\hoooope-subtitles\scripts\hoooope_subtitles.py pipeline --help
```

The skill-level checklist lives in `hoooope-subtitles/test-checklist.json`.
