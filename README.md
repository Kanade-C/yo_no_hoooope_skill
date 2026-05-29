# yo_no_hoooope_skill

面向 Codex 的《羊宫妃那的 HOOOOPE》中文字幕生产 skill，用于生成可发布的中文字幕、烧录 MP4 和中文观看笔记。

这个仓库打包的是 `hoooope-subtitles` skill：一套偏保守、偏生产质量的 HOOOOPE 字幕工作流，覆盖日语 ASR、中文字幕翻译、最终审校、MP4 烧录校验、截图检查、清理和单集中文笔记。它不是通用字幕玩具，而是针对 HOOOOPE 节目长期使用的发布流程。

## 主要能力

- 从 episode MP4 生成日文源字幕 SRT。
- 默认使用 Whisper large-v3-turbo + 本地 Silero VAD 作为时间轴稳定的 ASR 主干。
- 对高风险源字幕片段运行 Qwen3-ASR-1.7B，对照结果写入 sidecar 报告。
- 使用 DeepSeek V4-Pro 完整初翻并进行 100% 自润色。
- 由 Codex 负责最终 full-pass 审校、固定术语修正和 only-corrections 字幕编辑。
- 运行本地发布门禁：结构、行长、公开字幕可读性、固定术语、专有名词和 review TODO。
- 用 ffmpeg 烧录最终中文字幕，并用时长校验保护源视频。
- 生成截图 contact sheet，在清理前检查字幕位置、遮挡和可读性。
- 根据最终中文字幕生成简洁的单集中文观看笔记。

## 为什么这样设计

HOOOOPE 字幕的风险集中在成员名、栏目名、听众昵称、品牌名、笑点、自我修正、长停顿、BGM 段落和日语 ASR 同音误识别。这个 skill 把这些风险当成生产约束处理：

- Whisper 负责主时间轴。
- Qwen 只提供复核证据，不自动替换 Whisper 时间轴。
- DeepSeek 负责完整翻译和自润色。
- Codex 消化 QA 产物并做最终判断。
- 只有在最终视频、截图 QA 和 summary 都确认后才允许 cleanup。

## 仓库结构

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

## 环境需求

- Python 3.11+
- `ffmpeg` 和 `ffprobe`
- `stable-whisper`、`faster-whisper`、`onnxruntime`、`torch`
- DeepSeek API key：`DEEPSEEK_API_KEY`
- 本地 ASR 资源，通常放在工作区 `model/` 目录：
  - `model/large_v3_turbo`
  - `model/qwen-3-asr-1.7b`
  - `model/silero_vad.onnx`
  - `model/hoooope_terms.txt`
- Qwen 对照可选依赖：`qwen-asr`

如果希望默认高质量 ASR 对照真正运行，而不是只写 skipped sidecar：

```powershell
python -m pip install -U qwen-asr
```

## 安装为 Codex Skill

把 `hoooope-subtitles/` 复制或克隆到 Codex skills 目录：

```powershell
Copy-Item -Recurse -Force .\hoooope-subtitles C:\Users\CHENG\.codex\skills\hoooope-subtitles
```

验证安装：

```powershell
python C:\Users\CHENG\.codex\skills\.system\skill-creator\scripts\quick_validate.py C:\Users\CHENG\.codex\skills\hoooope-subtitles
python C:\Users\CHENG\.codex\skills\hoooope-subtitles\scripts\hoooope_subtitles.py self-test
```

## 使用方式

在 Codex 中直接让 skill 处理 episode 文件夹：

```text
Use $hoooope-subtitles to process D:\yo_no_hoooope\hope_25_0715
```

也可以直接运行 staged helper：

```powershell
python C:\Users\CHENG\.codex\skills\hoooope-subtitles\scripts\hoooope_subtitles.py pipeline D:\yo_no_hoooope\hope_25_0715
python C:\Users\CHENG\.codex\skills\hoooope-subtitles\scripts\hoooope_subtitles.py pipeline D:\yo_no_hoooope\hope_25_0715 --stage post-review
python C:\Users\CHENG\.codex\skills\hoooope-subtitles\scripts\hoooope_subtitles.py pipeline D:\yo_no_hoooope\hope_25_0715 --stage burn-cleanup
```

常用 ASR 选项：

```powershell
# 默认：Whisper 主干 + Qwen 风险片段 sidecar
--asr-enhancement qwen-risk

# 强制要求 Qwen 对照，qwen_asr 不可用时失败
--asr-enhancement qwen-risk-required

# 只走 Whisper
--asr-enhancement off
```

summary-only 请求必须不碰视频：

```powershell
python C:\Users\CHENG\.codex\skills\hoooope-subtitles\scripts\hoooope_subtitles.py pipeline D:\yo_no_hoooope\hope_25_0715 --stage post-review --summary-only
```

## 输出结构

每个根目录 MP4 会被整理到同名工作目录，episode 根目录保留合并后的 summary：

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

DeepSeek 中间文件、QA 报告、chunk cache、截图检查文件和分视频 summary 都是工作台产物。Codex 会在最终报告前消化这些文件，不把它们交给用户当作手工检查作业。

## 质量策略

默认生产模式是 `public-release strict`：

- DeepSeek 初翻覆盖 100% 字幕。
- DeepSeek 自润色覆盖 100% 字幕。
- Codex 对源字幕和最终中文字幕做 100% 分块审校。
- 最终 SRT 使用 only-corrections 编辑方式。
- 烧录前必须通过公开发布门禁。
- cleanup 前必须检查截图 contact sheet。

只有用户明确要求用速度或成本换质量时，才使用 reduced review。

## 开发检查

```powershell
python -m py_compile .\hoooope-subtitles\scripts\hoooope_subtitles.py
python .\hoooope-subtitles\scripts\hoooope_subtitles.py self-test
python .\hoooope-subtitles\scripts\hoooope_subtitles.py pipeline --help
```

skill 级别评测清单在 `hoooope-subtitles/test-checklist.json`。
