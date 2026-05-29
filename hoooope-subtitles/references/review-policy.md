# HOOOOPE Review Policy

Use this when deciding Codex final-review depth, consuming QA artifacts, or preparing public-release outputs.

## Public-Release Strict Default

For normal HOOOOPE production, default to `public-release strict`.

- DeepSeek initial translation and self-polish process 100% of subtitles.
- Codex final proofread covers 100% of the Japanese source against the Chinese final SRT in manageable chunks.
- Codex uses only-corrections editing: patch changed blocks, preserve stable blocks, and do not regenerate the whole SRT as a review output.
- Full coverage does not mean full retranslation. It means every block is compared for fidelity, natural Chinese, timing/readability risk, and fixed-term risk.
- QA artifacts are required inputs, not substitutes for full coverage.

## Reduced-Review Mode

Use reduced review only when the user explicitly asks to trade quality for speed or cost.

- Minimum reduced mode: all QA-hit blocks plus a targeted 35%-40% sample of high-risk non-hit blocks.
- High-risk blocks include listener-letter openings, host reactions, jokes, self-corrections, nicknames, titles, works, brands, long lines, and dense game/corner rules.
- Escalate back to full coverage when QA reports many Japanese residues, fixed-term mistakes, timing anomalies, heavy proper nouns, dense jokes, or game rules.
- State the reduced-review tradeoff in the final report.

## QA Gates

Before burn, run and consume `lint-final --strict-public`, `terms-audit`, `proper-noun-candidates`, `review-todo`, `baseline-report`, and `final-ready`.

Codex must fix high-risk issues and rerun the relevant checks. These artifacts are internal workbench inputs and should not be handed to the user as homework.

## Tone Priority

Tone review priority is:

1. Faithfulness to the Japanese source.
2. Natural Chinese subtitle rhythm.
3. Yomiya Hina tone.

Use `celebrity-yomiya-hina` only as optional calibration to avoid overly stiff, slangy, promotional, artificially cute, over-assertive, or emotionally flattened Chinese. Never add facts, mood, persona traits, SNS wording, or fan-copy style.
