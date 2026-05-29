# Translation And ASR Reference

Use this when creating source SRTs, running ASR comparison, running DeepSeek, or recovering failed translation/polish jobs. Pair it with `references/terms-glossary.md`, `references/deepseek-prompts.md`, and `references/review-policy.md` for production translation.

## Source Transcription

The production ASR baseline is local `Whisper large-v3-turbo + conservative Silero VAD + stable-whisper`. Use `model/large_v3_turbo/` and `model/silero_vad.onnx` by default. Legacy `model/large-v2/` remains an explicit fallback only.

Qwen3-ASR-1.7B is the default high-quality enhancement for risk-segment comparison. It writes `<stem>.asr.compare.txt` after `orig-audit`; it does not replace the Whisper-timed source SRT automatically.

`transcribe` extracts a temporary 16 kHz mono loudness-normalized WAV before ASR. It does not feed the MP4 directly to Whisper. Burning always uses the original MP4 audio.

Stable-whisper policy is Japanese transcription with VAD, silence suppression, `condition_on_previous_text=False`, temperature `0.0`, and the workflow regroup policy `clues` as implemented by the helper. Keep the ASR initial prompt enabled for HOOOOPE unless testing a non-HOOOOPE source or a visible prompt-bias issue. Hugging Face Whisper directories with `model*.safetensors` use the stable-whisper HF backend; CTranslate2 directories with `model.bin` use the faster-whisper backend.

Pipeline transcription preserves two source checkpoints: `<stem>.orig.raw.srt` is the direct ASR output, and `<stem>.orig.srt` is the smoothed source used downstream. Existing projects that only have `<stem>.orig.srt` remain valid resume targets.

ASR `initial_prompt` terms are ordered so ordinary glossary/reference terms come first and fixed core or CLI terms stay at the tail, where faster-whisper is least likely to drop them. Use `--verbose-prompt-sources` to print source counts, character count, and the final tail terms.

Optional audio preprocessing (`loudnorm`, `vocal-isolate`, `auto-ab`) may help noisy or BGM-heavy videos, but promote it only after comparing ASR output. Bad separation can damage laughter, breaths, reactions, or endings.

Always run `smooth-source` and `orig-audit` after transcription. In the default pipeline, also run `qwen-compare` on risk segments selected from `orig-audit`. Fix only obvious ASR source errors before translation; do not expand source audit into a full manual Japanese transcript review unless later QA shows a concrete defect.

Qwen enhancement modes:

- `--asr-enhancement qwen-risk` is the default. It creates a sidecar comparison report and skips gracefully if the `qwen_asr` runtime is not installed.
- `--asr-enhancement qwen-risk-required` fails when Qwen cannot run.
- `--asr-enhancement off` keeps the previous Whisper-only delivery path.

## DeepSeek Policy

Default translation chain:

1. DeepSeek V4-Pro translates 100% of the Japanese SRT.
2. DeepSeek V4-Pro self-polishes 100% of the initial Chinese translation against the Japanese source.
3. The polish stage writes a QA report for Codex.
4. Codex performs the final full-pass proofread using the only-corrections method.

Do not downgrade initial translation or polish to V4-Flash for cost savings. Avoid local MT models such as NLLB, MarianMT, OPUS-MT, or transformers pipelines unless the user explicitly asks for them.

The scripts load bundled split references first (`terms-glossary.md`, `deepseek-prompts.md`, and `review-policy.md` for translation/polish) and project glossary files after them, so project wording can override bundled wording. The preferred project glossary name is `hoooope_terms.txt`; `hooope_terms.txt` is only a compatibility fallback.

Pipeline initial translation defaults to `--workers 2 --context-blocks 20`, using read-only context chunks that are never emitted. `--workers 1` remains available as the legacy overlap-and-deduplicate fallback for manual recovery. Self-polish may use concurrent workers because it is still a full 100% second pass.

Translation cache validity depends on source and dependency hashes. Polish cache validity also depends on input and dependency hashes; the dependency hash covers prompt version, glossary text, model, temperature, chunk size, worker count, and polish strategy.

## Failure Recovery

If DeepSeek translation or polish fails:

1. Reuse existing cache and rerun the failed command.
2. For initial translation, reduce `--translate-workers` to `1` only if the concurrent context path is unstable.
3. Reduce polish chunk size, usually to `50`.
4. Reduce polish concurrency, usually to `2`.
5. Reduce chunk size further if structure errors persist.
6. Repair one specific chunk directly only after repeated smaller runs still produce changed timestamps, changed block counts, or missing subtitle lines.

Do not abandon the DeepSeek path because of an API reset or one bad chunk. Resume from cached chunks whenever possible.

## Advanced Comparison

Multiple transcripts may be used for premium checks, but keep one timestamp-friendly local source as the timing scaffold. Treat other ASR systems as text evidence only unless local episode-like tests prove their timestamps are reliable.
