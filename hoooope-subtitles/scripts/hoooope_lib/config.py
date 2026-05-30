from __future__ import annotations

import re

MEDIA_EXTS = {".ts", ".mp4", ".mkv", ".mov", ".webm", ".m4a", ".mp3", ".wav", ".flac"}

DEFAULT_TRANSCRIBE_MODEL_DIR = "model/large_v3_turbo_ct2"
DEFAULT_QWEN_ASR_MODEL_DIR = "model/qwen-3-asr-1.7b"
DEFAULT_STABLE_REGROUP = "clues"

PIPELINE_TRANSLATION_MODEL = "deepseek-v4-pro"
PIPELINE_TRANSLATE_CHUNK_SIZE = 100
PIPELINE_TRANSLATE_WORKERS = 2
PIPELINE_TRANSLATE_CONTEXT_BLOCKS = 20
PIPELINE_POLISH_CHUNK_SIZE = 50
PIPELINE_POLISH_WORKERS = 2
PIPELINE_DEEPSEEK_QA_SAMPLE_RATIO = 0.28
PIPELINE_DEEPSEEK_MAX_RETRIES = 3
PIPELINE_DEEPSEEK_RETRY_DELAY = 10.0
PIPELINE_MIN_SUMMARY_CHARS = 1500
PIPELINE_MAX_SUMMARY_CHARS = 3000
PIPELINE_DEFAULT_VAD_ONNX = "model/silero_vad.onnx"

CLEANUP_SENTINEL = ".screenshot_qa_passed"
PROOFREAD_RECEIPT = ".hoooope_proofread_receipt.json"
MANIFEST_SCHEMA = "hoooope-run-manifest-v2"
STRICT_REVIEW_MODE = "public-release strict"

IGNORED_WORKBENCH_DIRS = {
    "deepseek_chunks",
    "deepseek_polish_chunks",
    "screenshot_check",
}

FINAL_SRT_EXCLUDED_SUFFIXES = (
    ".orig.raw.srt",
    ".orig.srt",
    ".deepseek.raw.srt",
    ".deepseek.polished.srt",
)

PREFERRED_GLOSSARY_CANDIDATES = (
    "hoooope_terms.txt",
    "model/hoooope_terms.txt",
)

LEGACY_GLOSSARY_CANDIDATES = (
    "hooope_terms.txt",
    "model/hooope_terms.txt",
)

BAD_FIXED_TERMS: dict[str, str] = {
    "AGVIOT": "AVIOT",
    "ＡＶＩＯＴ": "AVIOT",
    "生驹ゆりえ": "伊驹百合绘",
    "生驹百合绘": "伊驹百合绘",
    "伊驹小百合": "伊驹百合绘",
    "水野サク": "水野咲",
    "水野佐久": "水野咲",
    "村上真夏酱": "村上真夏",
    "HOOOPE": "HOOOOPE",
    "HOOOOOP": "HOOOOPE",
    "Sheepッチ": "咩咩吉 or Sheeputchi, depending on context",
    "シープッチ": "咩咩吉 or Sheeputchi, depending on context",
    "赞助播出村上真夏": "Supported by 村上真夏",
    "由村上真夏赞助": "Supported by 村上真夏",
}

SUSPICIOUS_TERMS: tuple[str, ...] = (
    "AGVIOT",
    "ＡＶＩＯＴ",
    "陽宮",
    "ひなの",
    "生驹",
    "水野サク",
    "水野さく",
    "Open",
    "OPEN",
    "サポーテッドバイ",
    "シープッチ",
    "Sheepッチ",
)

# --- Show-specific detection data (HOOOOPE) -----------------------------------
# Swapping these reconfigures the engine for another program without code edits.
JA_RE = re.compile(r"[぀-ヿ]")
HOOPE_RE = re.compile(r"\bHO+PE\b", re.IGNORECASE)
ASCII_PUNCT_RE = re.compile(r"[,!?:;]")
KATAKANA_TERM_RE = re.compile(r"[ァ-ヿー]{3,}")
LATIN_TERM_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9&'./+-]{2,}\b")
TITLE_LIKE_RE = re.compile(r"[「『《](.*?)[」』》]")
KANA_NICKNAME_RE = re.compile(r"[ぁ-ゟァ-ヿー]{2,}")
ASR_SUSPICIOUS_OPEN_RE = re.compile(r"(Open|OPEN|オープン|おーぷん)")

BAD_HOST_TERMS = ("阳宫", "雏乃", "陽宮", "ひなの")
TONE_MARKERS = (
    "我觉得", "可能", "或许", "谢谢", "抱歉", "不好意思",
    "开心", "高兴", "喜欢", "怎么办", "真的", "感觉",
)

HOOOOPE_OPENING_MISHEAR_RE = re.compile(
    r"(?:エ\s*クステンド|ネクスト|ステップ|STEP|Step).*"
    r"(?:陽宮|羊宮|ようみや|ヨ[ーォ]?ミヤ|小宮|神谷).*"
    r"(?:オープン|おーぷん|ポープ|ホップ|Open|OPEN|新)"
)
HOOOOPE_TITLE_MISHEAR_RE = re.compile(
    r"(?:陽宮|羊宮|ようみや|ヨ[ーォ]?ミヤ|小宮|神谷).{0,8}"
    r"(?:ポープ|ホップ|Open|OPEN|オープン|おーぷん)"
)
HOOOOPE_ACCOUNT_MISHEAR_RE = re.compile(
    r"(?:番組公式|公式).{0,12}(?:x|X|エックス).{0,12}"
    r"(?:アカウント).{0,16}(?:bx\s*ホープ|ex\s*hope|exhope|ホープ)"
)
AIUEO_COMPOSITION_MISHEAR_RE = re.compile(
    r"(?:み[、,\s]*ず[、,\s]*の|水野).{0,12}"
    r"(?:相植え|藍植え|愛植え|あいうえ|アイウエ|作文)"
)

SUMMARY_TEMPLATE = """[日期可选] 小羊 HOOOOPE 笔记

[根据 {subtitle_name} 的润色中文字幕，用 1-2 句总述本期氛围和主要内容。]

----------

『[话题/来信标题]』
[大致时间] 听众来信或节目话题讲了什么，羊宫妃那怎么回应，有什么有趣的展开。写成自然段，不要写成要点列表。

『[下一个话题/来信标题]』
[大致时间] 继续用自然段概括。可以根据节目内容添加更多话题段落。

#羊宫妃那
"""
