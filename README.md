# yo_no_hoooope_skill

给 Codex 使用的《羊宫妃那的 HOOOOPE》半自动字幕烧录 skill。

这是一个基于 DeepSeek + Codex 双模型协作的声优广播字幕工作流，覆盖日语转写、中文字幕翻译、字幕润色、质量审计、视频烧录、截图验收和中文观看笔记生成。它的目标不是“一条 prompt 跑到底”，而是把机器翻译、自动检查和 Codex 最终判断拆成稳定可复用的生产流程。

## 主要功能

- 本地 faster-whisper 转写日语语音，生成 `.orig.srt`。
- DeepSeek V4-Pro 完整翻译日语 SRT。
- DeepSeek V4-Pro 二次自我润色，并输出 QA 检查文件。
- Codex 对高风险段落、抽样段落、固定术语、人名和机翻腔做最终审计。
- 自动校验 SRT 编号、时间轴、行长、术语和疑似专有名词。
- 使用 ffmpeg 烧录中文字幕，并通过 ffprobe 做时长熔断，避免音画不同步文件覆盖源视频。
- 生成截图 contact sheet，检查字幕位置、遮挡、对比度和中日英混排行宽。
- 根据最终中文字幕生成中文观看笔记，并合并为单集摘要。
- 清理中间产物，只保留最终视频、原文 SRT、中文字幕 SRT 和单集笔记。

## 仓库结构

```text
.
├─ README.md
└─ hoooope-subtitles/
   ├─ SKILL.md
   ├─ agents/
   │  └─ openai.yaml
   ├─ references/
   │  └─ terms-and-notes.md
   └─ scripts/
      ├─ hooope_subtitles.py
      ├─ deepseek_translate_srt.py
      ├─ deepseek_polish_srt.py
      └─ deepseek_note_srt.py
```

## 输入约定

推荐使用日期型文件名，便于区分 regular 和 member 视频。

```text
project/
├─ model/
├─ hooope_terms.txt
└─ hope_25_0513/
   ├─ hope_25_0513.mp4
   └─ hope_25_0513_member.mp4
```

旧格式 `hoooope_<episode>.mp4` 和 `hoooope_<episode>_member*.mp4` 仍然兼容。

## 输出示例

处理完成后，每个视频会被放入自己的工作目录，最终只保留核心文件。

```text
hope_25_0513/
├─ hope_25_0513.summary.txt
├─ hope_25_0513/
│  ├─ hope_25_0513.mp4
│  ├─ hope_25_0513.orig.srt
│  └─ hope_25_0513.srt
└─ hope_25_0513_member/
   ├─ hope_25_0513_member.mp4
   ├─ hope_25_0513_member.orig.srt
   └─ hope_25_0513_member.srt
```

## 环境需求

- Python 3
- `ffmpeg` / `ffprobe`
- 本地 faster-whisper 模型目录，默认使用 `model/`
- DeepSeek V4-Pro API，用于翻译、润色和摘要生成
- 可选项目术语表：`hooope_terms.txt`

## 使用方式

在 Codex 中调用 skill：

```text
Use $hoooope-subtitles to process ./hope_25_0513
```

主脚本也可以直接查看命令：

```powershell
python .\hoooope-subtitles\scripts\hooope_subtitles.py --help
```

常用命令包括：

- `transcribe`
- `validate`
- `lint-final`
- `terms-audit`
- `review-todo`
- `proper-noun-candidates`
- `split-srt`
- `merge-srt`
- `burn`
- `screenshot-check`
- `cleanup`
- `combine-summaries`

## 字幕风格

最终字幕以“自然、好读、对中文观众成立”为优先目标，而不是机械贴合日语语序。

工作流会保留羊宫妃那说话中的犹豫、吐槽、自我修正和轻微口癖，但会压掉没有信息量的填充语、机器翻译腔、过长字幕和不自然直译。固定术语、人名、栏目名和常见 ASR 误识别由 `references/terms-and-notes.md` 维护，项目级 `hooope_terms.txt` 可以进一步补充或覆盖。

## 设计取向

这个项目比较保守，也比较偏生产导向。DeepSeek 负责完整覆盖和二次润色，Codex 负责最终判断和人工式质检；这样速度不一定最快，但更适合需要稳定输出、术语一致、可发布视频字幕的场景。
