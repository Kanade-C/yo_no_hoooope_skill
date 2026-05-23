from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path

import requests


TIME_RE = re.compile(r"^\d{2}:\d{2}:\d{2},\d{3}\s+-->\s+\d{2}:\d{2}:\d{2},\d{3}$")
JA_RE = re.compile(r"[\u3040-\u30ff]")


class BlockCountMismatch(ValueError):
    pass


def read_blocks(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8-sig")
    return [block.strip() for block in text.strip().split("\n\n") if block.strip()]


def write_blocks(path: Path, blocks: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n\n".join(blocks).strip() + "\n", encoding="utf-8-sig")


def block_header(block: str) -> tuple[str, str]:
    lines = block.splitlines()
    if len(lines) < 3:
        raise ValueError(f"Bad SRT block:\n{block}")
    return lines[0].strip(), lines[1].strip()


def validate_blocks(blocks: list[str], expected_blocks: list[str] | None = None) -> list[str]:
    errors: list[str] = []
    for idx, block in enumerate(blocks):
        lines = block.splitlines()
        if len(lines) < 3:
            errors.append(f"block {idx + 1}: too few lines")
            continue
        number = lines[0].strip()
        timing = lines[1].strip()
        if not number.isdigit():
            errors.append(f"block {idx + 1}: invalid number {number!r}")
        if not TIME_RE.match(timing):
            errors.append(f"block {idx + 1}: invalid timestamp {timing!r}")
        if expected_blocks is not None:
            exp_number, exp_timing = block_header(expected_blocks[idx])
            if number != exp_number:
                errors.append(f"block {idx + 1}: number changed {number!r} != {exp_number!r}")
            if timing != exp_timing:
                errors.append(f"block {idx + 1}: timestamp changed {timing!r} != {exp_timing!r}")
    return errors


def bundled_reference_path() -> Path:
    return Path(__file__).resolve().parents[1] / "references" / "terms-and-notes.md"


def load_glossary(paths: list[Path]) -> str:
    parts: list[str] = []
    all_paths = [bundled_reference_path(), *paths]
    seen: set[Path] = set()
    for path in all_paths:
        path = path.resolve()
        if path in seen:
            continue
        seen.add(path)
        if path.exists():
            parts.append(path.read_text(encoding="utf-8-sig").strip())
    return "\n\n".join(part for part in parts if part)


def strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def fix_timestamps(translated_blocks: list[str], source_blocks: list[str]) -> list[str]:
    if len(translated_blocks) != len(source_blocks):
        return translated_blocks

    fixed: list[str] = []
    for translated, source in zip(translated_blocks, source_blocks):
        translated_lines = translated.splitlines()
        source_lines = source.splitlines()
        if len(translated_lines) < 2 or len(source_lines) < 2:
            fixed.append(translated)
            continue
        translated_lines[1] = source_lines[1].strip()
        fixed.append("\n".join(translated_lines).strip())
    return fixed


def translate_chunk(
    blocks: list[str],
    glossary: str,
    args: argparse.Namespace,
    chunk_index: int,
    chunk_label: str | None = None,
    split_cache_dir: Path | None = None,
    split_cache_prefix: str | None = None,
) -> list[str]:
    source = "\n\n".join(blocks)
    label = chunk_label or str(chunk_index)
    system_prompt = "你是专业的日语到简体中文字幕译者。只输出有效 SRT，不要解释。如果你修改了任何一条时间轴的数字，整个翻译将被视为失败。"
    user_prompt = f"""你正在翻译声优广播节目《羊宫妃那的 HOOOOPE》。

任务：把下面的日语 SRT 分块翻译成自然、流畅的简体中文。

硬性要求：
1. 保留每一条 SRT 编号不变。
2. 时间轴是神圣不可修改的。每条字幕的时间轴必须原样复制，连一个数字、一个逗号、一个空格都不许改。修改时间轴是最严重的翻译错误。
3. 只翻译字幕正文，不要改编号、时间轴、空行结构。
4. 不要总结，不要省略，不要合并字幕段，不要新增字幕段。
5. 节目名统一为 HOOOOPE。
6. 主持人统一为羊宫妃那。
7. 听众来信要像中文投稿，主持人回应要像自然口播。
8. 不确定的节目固定词、广播名、昵称，优先保留原名或音译，不要乱译。
9. 日语接龙、双关、玩笑要让中文观众能理解，但不要写成长解释。
10. 输出只能是完整 SRT，不要 Markdown，不要代码块，不要解释。

项目术语表：
{glossary or "(none)"}

SRT 分块：
{source}
"""
    payload = {
        "model": args.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": args.temperature,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {args.api_key}",
        "Content-Type": "application/json",
    }
    url = args.base_url.rstrip("/") + "/chat/completions"

    last_error = None
    for attempt in range(1, args.retries + 1):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=args.timeout)
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            translated = read_blocks_from_text(strip_code_fence(content))

            if len(translated) != len(blocks):
                raise BlockCountMismatch(f"chunk {label}: block count changed {len(translated)} != {len(blocks)}")
            translated = fix_timestamps(translated, blocks)
            errors = validate_blocks(translated, blocks)
            if errors:
                raise ValueError("; ".join(errors[:5]))
            return translated
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if isinstance(exc, BlockCountMismatch) and attempt >= 2 and len(blocks) > 1:
                print(f"chunk {label}: splitting after repeated block count mismatch")
                return translate_split_chunk(
                    blocks,
                    glossary,
                    args,
                    chunk_index,
                    label,
                    split_cache_dir,
                    split_cache_prefix,
                )
            wait = min(args.retry_wait * attempt, 30)
            print(f"chunk {label}: attempt {attempt} failed: {exc}")
            if attempt < args.retries:
                time.sleep(wait)

    raise RuntimeError(f"chunk {label} failed after {args.retries} attempts: {last_error}")


def translate_split_chunk(
    blocks: list[str],
    glossary: str,
    args: argparse.Namespace,
    chunk_index: int,
    chunk_label: str,
    split_cache_dir: Path | None,
    split_cache_prefix: str | None,
) -> list[str]:
    mid = len(blocks) // 2
    if mid <= 0 or mid >= len(blocks):
        raise RuntimeError(f"chunk {chunk_label}: cannot split {len(blocks)} blocks")

    results: list[str] = []
    for suffix, sub_blocks in (("a", blocks[:mid]), ("b", blocks[mid:])):
        sub_label = f"{chunk_label}{suffix}"
        cache_file = None
        if split_cache_dir is not None and split_cache_prefix is not None:
            cache_file = split_cache_dir / f"{split_cache_prefix}.part{chunk_index:03d}.{sub_label}.zh.srt"
            if cache_file.exists() and not args.force:
                cached = read_blocks(cache_file)
                if len(cached) == len(sub_blocks) and not validate_blocks(cached, sub_blocks):
                    print(f"chunk {sub_label}: using split cache {cache_file.name}")
                    results.extend(cached)
                    continue
                print(f"chunk {sub_label}: split cache invalid, retranslating")

        translated = translate_chunk(
            sub_blocks,
            glossary,
            args,
            chunk_index,
            chunk_label=sub_label,
            split_cache_dir=split_cache_dir,
            split_cache_prefix=split_cache_prefix,
        )
        if cache_file is not None:
            write_blocks(cache_file, translated)
        results.extend(translated)

    return results


def read_blocks_from_text(text: str) -> list[str]:
    return [block.strip() for block in text.strip().split("\n\n") if block.strip()]


def chunks(items: list[str], size: int, overlap: int = 0) -> list[list[str]]:
    if size <= 0:
        raise ValueError("chunk size must be greater than 0")
    if overlap < 0:
        raise ValueError("overlap must be greater than or equal to 0")
    if overlap >= size:
        raise ValueError("overlap must be smaller than chunk size")
    step = size - overlap
    return [items[i : i + size] for i in range(0, len(items), step)]


def block_number(block: str) -> int:
    return int(block.splitlines()[0].strip())


def append_new_blocks(target: list[str], blocks: list[str]) -> None:
    if not target:
        target.extend(blocks)
        return
    last_number = block_number(target[-1])
    target.extend(block for block in blocks if block_number(block) > last_number)


def block_text(block: str) -> str:
    return "\n".join(block.splitlines()[2:]).strip()


def qa_report(source_blocks: list[str], zh_blocks: list[str], sample_ratio: float) -> str:
    issues: list[str] = []
    issue_numbers: set[int] = set()

    def add_issue(title: str, number: int, ja: str, zh: str, detail: str = "") -> None:
        issue_numbers.add(number)
        issues.append(
            "\n".join(
                [
                    f"[{title}] #{number}" + (f" - {detail}" if detail else ""),
                    "JA: " + block_text(ja).replace("\n", " / "),
                    "ZH: " + block_text(zh).replace("\n", " / "),
                    "",
                ]
            )
        )

    for ja, zh in zip(source_blocks, zh_blocks):
        num = block_number(ja)
        ztext = block_text(zh)
        if not ztext:
            add_issue("空字幕", num, ja, zh)
        if JA_RE.search(ztext):
            add_issue("疑似日文残留", num, ja, zh)
        if "HOPE" in ztext and "HOOOOPE" not in ztext:
            add_issue("节目名疑似错误", num, ja, zh)
        for bad in ("阳宫", "雏乃", "陽宮", "ひなの"):
            if bad in ztext:
                add_issue("人名疑似错误", num, ja, zh, bad)
                break
        if len(ztext.replace("\n", "")) > 48:
            add_issue("字幕偏长", num, ja, zh, f"{len(ztext.replace(chr(10), ''))} chars")

    total = len(source_blocks)
    sample_count = max(12, int(total * sample_ratio))
    sample_numbers = sorted(
        {
            1,
            2,
            3,
            total,
            max(1, total - 1),
            max(1, total // 4),
            max(1, total // 2),
            max(1, total * 3 // 4),
        }
    )
    if sample_count > len(sample_numbers):
        step = max(1, total // max(1, sample_count - len(sample_numbers)))
        sample_numbers.extend(range(1, total + 1, step))
    sample_numbers = sorted(set(n for n in sample_numbers if 1 <= n <= total and n not in issue_numbers))
    sample_numbers = sample_numbers[:sample_count]

    samples: list[str] = []
    for number in sample_numbers:
        ja = source_blocks[number - 1]
        zh = zh_blocks[number - 1]
        samples.append(
            "\n".join(
                [
                    f"[抽样审核] #{number}",
                    "JA: " + block_text(ja).replace("\n", " / "),
                    "ZH: " + block_text(zh).replace("\n", " / "),
                    "",
                ]
            )
        )

    header = [
        "HOOOOPE DeepSeek translation QA report",
        f"blocks={total}",
        f"issues={len(issue_numbers)}",
        f"samples={len(sample_numbers)}",
        "",
        "Codex review policy:",
        "- Review every issue block.",
        "- Review sampled blocks for tone and terminology.",
        "- Do not re-read the full SRT unless the QA report shows systemic failure.",
        "",
    ]
    return "\n".join(header + issues + samples).strip() + "\n"


def translate(args: argparse.Namespace) -> None:
    src = Path(args.input)
    out = Path(args.output)
    if not args.api_key:
        raise SystemExit("Missing API key. Set DEEPSEEK_API_KEY or pass --api-key.")

    blocks = read_blocks(src)
    source_errors = validate_blocks(blocks)
    if source_errors:
        raise SystemExit("Source SRT validation failed:\n" + "\n".join(source_errors[:20]))

    glossary_paths = [Path(p) for p in args.glossary]
    glossary = load_glossary(glossary_paths)
    overlap = 10
    chunk_list = chunks(blocks, args.chunk_size, overlap=overlap)

    cache_dir = Path(args.cache_dir) if args.cache_dir else src.parent / "deepseek_chunks" / src.stem
    cache_dir.mkdir(parents=True, exist_ok=True)

    translated_all: list[str] = []
    for idx, chunk_blocks in enumerate(chunk_list, start=1):
        cache_file = cache_dir / f"{src.stem}.part{idx:03d}.o{overlap}.zh.srt"
        if cache_file.exists() and not args.force:
            cached = read_blocks(cache_file)
            if len(cached) == len(chunk_blocks) and not validate_blocks(cached, chunk_blocks):
                print(f"chunk {idx}/{len(chunk_list)}: using cache {cache_file.name}")
                append_new_blocks(translated_all, cached)
                continue
            print(f"chunk {idx}/{len(chunk_list)}: cache invalid, retranslating")

        print(f"chunk {idx}/{len(chunk_list)}: translating {len(chunk_blocks)} blocks")
        translated = translate_chunk(
            chunk_blocks,
            glossary,
            args,
            idx,
            split_cache_dir=cache_dir,
            split_cache_prefix=f"{src.stem}.o{overlap}",
        )
        write_blocks(cache_file, translated)
        append_new_blocks(translated_all, translated)
        if args.sleep > 0:
            time.sleep(args.sleep)

    if len(translated_all) != len(blocks):
        raise SystemExit(f"Final block count mismatch: {len(translated_all)} != {len(blocks)}")
    final_errors = validate_blocks(translated_all, blocks)
    if final_errors:
        raise SystemExit("Final SRT validation failed:\n" + "\n".join(final_errors[:20]))

    write_blocks(out, translated_all)
    print(f"Wrote {out.resolve()} blocks={len(translated_all)}")

    if args.qa_output:
        report = qa_report(blocks, translated_all, args.qa_sample_ratio)
        qa_path = Path(args.qa_output)
        qa_path.parent.mkdir(parents=True, exist_ok=True)
        qa_path.write_text(report, encoding="utf-8-sig")
        print(f"Wrote QA report {qa_path.resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Translate Japanese SRT to Chinese via DeepSeek chat completions.")
    parser.add_argument("input", help="Input Japanese .srt")
    parser.add_argument("--output", required=True, help="Output Chinese .srt")
    parser.add_argument("--api-key", default=os.environ.get("DEEPSEEK_API_KEY"))
    parser.add_argument("--base-url", default=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    parser.add_argument("--model", default=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro"))
    parser.add_argument("--chunk-size", type=int, default=70)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-wait", type=int, default=3)
    parser.add_argument("--sleep", type=float, default=0.0, help="Seconds to sleep between successful chunks")
    parser.add_argument("--cache-dir")
    parser.add_argument("--qa-output", help="Write a QA report for targeted Codex review")
    parser.add_argument("--qa-sample-ratio", type=float, default=0.28)
    parser.add_argument("--force", action="store_true", help="Retranslate cached chunks")
    parser.add_argument(
        "--glossary",
        action="append",
        default=["hooope_terms.txt", "model/hooope_terms.txt"],
        help="Glossary file. Can be passed multiple times.",
    )
    args = parser.parse_args()
    translate(args)


if __name__ == "__main__":
    main()
