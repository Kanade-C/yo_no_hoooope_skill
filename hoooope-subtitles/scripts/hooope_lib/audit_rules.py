from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ASR_PROMPT_SEED_TERMS = (
    "羊宫妃那", "陽宮妃那", "ひなの", "HOOOOPE", "Extend Step HOOOOPE",
    "村上真夏", "村上まなつ", "伊驹百合绘", "伊駒ゆりえ", "水野咲", "水野朔",
    "AVIOT", "HOOOOPE Battle", "HOOOOPE Step Up", "After Talk",
    "HOOOOPE Room", "Sheeputchi", "シープッチ",
)

ASR_HOMOPHONE_CONTEXT_RULES = (
    {
        "pattern": re.compile(r"某人間"),
        "reason": "possible homophone ASR error in drawing/illustration context; verify against surrounding context",
        "context": ("イラスト", "描", "書", "絵", "画", "鬼", "投稿", "棒人間", "落書き"),
    },
)


def builtin_audit_rules(bad_fixed_terms: dict[str, str], suspicious_terms: tuple[str, ...]) -> dict[str, object]:
    return {
        "asr_seed_terms": list(ASR_PROMPT_SEED_TERMS),
        "bad_fixed_terms": dict(bad_fixed_terms),
        "suspicious_terms": list(suspicious_terms),
        "homophone_context_rules": [
            {
                "id": f"homophone-{idx}",
                "priority": 100 + idx,
                "pattern": rule["pattern"].pattern,
                "reason": rule["reason"],
                "context": list(rule["context"]),
                "enabled": True,
            }
            for idx, rule in enumerate(ASR_HOMOPHONE_CONTEXT_RULES, start=1)
        ],
        "source_regex_rules": [],
    }


def deep_merge_rules(base: dict[str, object], incoming: dict[str, object]) -> dict[str, object]:
    if incoming.get("override") is True:
        fallback_bad = dict(base.get("bad_fixed_terms", {}))
        fallback_suspicious = tuple(str(item) for item in base.get("suspicious_terms", []))
        base = builtin_audit_rules(fallback_bad, fallback_suspicious)
        for key in ("asr_seed_terms", "bad_fixed_terms", "suspicious_terms", "homophone_context_rules", "source_regex_rules"):
            if key in incoming:
                base[key] = [] if isinstance(base.get(key), list) else {}
    for key, value in incoming.items():
        if key == "override":
            continue
        if key == "bad_fixed_terms" and isinstance(value, dict):
            merged = dict(base.get(key, {}))
            merged.update({str(k): str(v) for k, v in value.items()})
            base[key] = merged
        elif key in {"asr_seed_terms", "suspicious_terms"} and isinstance(value, list):
            merged = list(base.get(key, []))
            for item in value:
                text = str(item).strip()
                if text and text not in merged:
                    merged.append(text)
            base[key] = merged
        elif key in {"homophone_context_rules", "source_regex_rules"} and isinstance(value, list):
            merged = list(base.get(key, []))
            merged.extend(item for item in value if isinstance(item, dict))
            base[key] = merged
    return base


def load_json_rules(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid audit rules JSON {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"Invalid audit rules JSON {path}: top-level value must be an object")
    return data


def default_audit_rule_paths(anchor: Path | None = None) -> list[Path]:
    candidates = [
        Path.cwd() / "audit_rules.json",
        Path.cwd() / "model" / "audit_rules.json",
    ]
    if anchor is not None:
        parent = anchor.parent if anchor.is_file() else anchor
        candidates.extend([parent / "audit_rules.json", parent.parent / "audit_rules.json"])
    return candidates


def load_audit_rules(
    args: argparse.Namespace | None = None,
    anchor: Path | None = None,
    *,
    bad_fixed_terms: dict[str, str],
    suspicious_terms: tuple[str, ...],
) -> dict[str, object]:
    rules = builtin_audit_rules(bad_fixed_terms, suspicious_terms)
    paths: list[Path] = []
    seen: set[Path] = set()
    for raw in default_audit_rule_paths(anchor):
        path = raw.resolve()
        if path.exists() and path not in seen:
            paths.append(path)
            seen.add(path)
    for raw in getattr(args, "audit_rules", None) or []:
        path = Path(raw).resolve()
        if path.exists() and path not in seen:
            paths.append(path)
            seen.add(path)
    for path in paths:
        rules = deep_merge_rules(rules, load_json_rules(path))
    rules["_paths"] = [str(path) for path in paths]
    return rules


def ordered_rule_items(rules: dict[str, object], key: str) -> list[dict[str, object]]:
    items = [item for item in rules.get(key, []) if isinstance(item, dict) and item.get("enabled", True)]
    return [item for _idx, item in sorted(enumerate(items), key=lambda pair: (int(pair[1].get("priority", 1000)), pair[0]))]
