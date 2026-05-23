from __future__ import annotations

import argparse
import concurrent.futures
import os
import re
import time
from pathlib import Path

import requests


TIME_RE = re.compile(r"^\d{2}:\d{2}:\d{2},\d{3}\s+-->\s+\d{2}:\d{2}:\d{2},\d{3}$")
JA_RE = re.compile(r"[\u3040-\u30ff]")


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


def block_number(block: str) -> int:
    return int(block.splitlines()[0].strip())


def block_text(block: str) -> str:
    return "\n".join(block.splitlines()[2:]).strip()


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


def read_blocks_from_text(text: str) -> list[str]:
    return [block.strip() for block in text.strip().split("\n\n") if block.strip()]


def chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def cached_polish_valid(cache_file: Path, zh_chunk: list[str]) -> list[str] | None:
    if not cache_file.exists():
        return None
    cached = read_blocks(cache_file)
    if len(cached) == len(zh_chunk) and not validate_blocks(cached, zh_chunk):
        return cached
    return None


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
    sample_numbers = sorted({1, 2, 3, total, max(1, total - 1), max(1, total // 4), max(1, total // 2), max(1, total * 3 // 4)})
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
        "HOOOOPE DeepSeek polished translation QA report",
        f"blocks={total}",
        f"issues={len(issue_numbers)}",
        f"samples={len(sample_numbers)}",
        "",
        "Codex final-inspector policy:",
        "- Review every issue block.",
        "- Review sampled blocks for tone and terminology.",
        "- Do not reduce review ratio because DeepSeek self-polish was used.",
        "- Do not re-read the full SRT unless the QA report shows systemic failure.",
        "",
    ]
    return "\n".join(header + issues + samples).strip() + "\n"


def polish_chunk(ja_blocks: list[str], zh_blocks: list[str], glossary: str, args: argparse.Namespace, chunk_index: int) -> list[str]:
    ja_text = "\n\n".join(ja_blocks)
    zh_text = "\n\n".join(zh_blocks)
    system_prompt = "你是专业的日语到简体中文字幕审校润色编辑。只输出有效 SRT，不要解释。"
    user_prompt = f"""你正在对照日语原文润色中文字幕。

输入包含同一批 SRT 的 JA 原文和 ZH 初翻。

任务：在不改变 SRT 编号和时间轴的前提下，润色 ZH 初翻。

要求：
1. 编号和时间轴必须与 ZH 初翻完全一致。
2. 只修改中文字幕正文。
3. 修正漏译、误译、硬译、日文残留和不自然中文。
4. 让中文更像自然口播字幕。
5. 保留听众来信语气和主持人反应。
6. 不要删减信息，不要合并字幕段，不要新增解释。
7. 节目名统一为 HOOOOPE，主持人统一为羊宫妃那。
8. 输出只能是完整 SRT，不要 Markdown，不要代码块，不要解释。

项目术语表：
{glossary or "(none)"}

JA 原文：
{ja_text}

ZH 初翻：
{zh_text}
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
            polished = read_blocks_from_text(strip_code_fence(content))
            if len(polished) != len(zh_blocks):
                raise ValueError(f"chunk {chunk_index}: block count changed {len(polished)} != {len(zh_blocks)}")
            errors = validate_blocks(polished, zh_blocks)
            if errors:
                raise ValueError("; ".join(errors[:5]))
            return polished
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            wait = min(args.retry_wait * attempt, 30)
            print(f"chunk {chunk_index}: attempt {attempt} failed: {exc}")
            if attempt < args.retries:
                time.sleep(wait)
    raise RuntimeError(f"chunk {chunk_index} failed after {args.retries} attempts: {last_error}")


def polish(args: argparse.Namespace) -> None:
    source = Path(args.input)
    translation = Path(args.translation)
    out = Path(args.output)
    if not args.api_key:
        raise SystemExit("Missing API key. Set DEEPSEEK_API_KEY or pass --api-key.")

    ja_blocks = read_blocks(source)
    zh_blocks = read_blocks(translation)
    if len(ja_blocks) != len(zh_blocks):
        raise SystemExit(f"Block count mismatch: {len(ja_blocks)} != {len(zh_blocks)}")
    source_errors = validate_blocks(ja_blocks)
    zh_errors = validate_blocks(zh_blocks, ja_blocks)
    if source_errors or zh_errors:
        raise SystemExit("Input validation failed:\n" + "\n".join((source_errors + zh_errors)[:20]))

    glossary = load_glossary([Path(p) for p in args.glossary])
    ja_chunks = chunks(ja_blocks, args.chunk_size)
    zh_chunks = chunks(zh_blocks, args.chunk_size)
    cache_dir = Path(args.cache_dir) if args.cache_dir else source.parent / "deepseek_polish_chunks" / source.stem
    cache_dir.mkdir(parents=True, exist_ok=True)

    chunk_count = len(ja_chunks)
    polished_results: list[list[str] | None] = [None] * chunk_count
    pending: list[tuple[int, list[str], list[str], Path]] = []
    for idx, (ja_chunk, zh_chunk) in enumerate(zip(ja_chunks, zh_chunks), start=1):
        cache_file = cache_dir / f"{source.stem}.part{idx:03d}.polished.srt"
        if not args.force:
            cached = cached_polish_valid(cache_file, zh_chunk)
            if cached is not None:
                print(f"chunk {idx}/{chunk_count}: using cache {cache_file.name}")
                polished_results[idx - 1] = cached
                continue
            if cache_file.exists():
                print(f"chunk {idx}/{chunk_count}: cache invalid, repolishing")
        pending.append((idx, ja_chunk, zh_chunk, cache_file))

    def run_polish(task: tuple[int, list[str], list[str], Path]) -> tuple[int, list[str]]:
        idx, ja_chunk, zh_chunk, cache_file = task
        print(f"chunk {idx}/{chunk_count}: polishing {len(zh_chunk)} blocks")
        polished = polish_chunk(ja_chunk, zh_chunk, glossary, args, idx)
        write_blocks(cache_file, polished)
        if args.sleep > 0:
            time.sleep(args.sleep)
        return idx, polished

    workers = max(1, args.workers)
    if pending and workers == 1:
        for task in pending:
            idx, polished = run_polish(task)
            polished_results[idx - 1] = polished
    elif pending:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_idx = {executor.submit(run_polish, task): task[0] for task in pending}
            for future in concurrent.futures.as_completed(future_to_idx):
                idx = future_to_idx[future]
                polished_results[idx - 1] = future.result()[1]

    polished_all: list[str] = []
    for idx, result in enumerate(polished_results, start=1):
        if result is None:
            raise SystemExit(f"Missing polished result for chunk {idx}")
        polished_all.extend(result)

    final_errors = validate_blocks(polished_all, ja_blocks)
    if final_errors:
        raise SystemExit("Final SRT validation failed:\n" + "\n".join(final_errors[:20]))
    write_blocks(out, polished_all)
    print(f"Wrote {out.resolve()} blocks={len(polished_all)}")

    if args.qa_output:
        report = qa_report(ja_blocks, polished_all, args.qa_sample_ratio)
        qa_path = Path(args.qa_output)
        qa_path.parent.mkdir(parents=True, exist_ok=True)
        qa_path.write_text(report, encoding="utf-8-sig")
        print(f"Wrote QA report {qa_path.resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Polish DeepSeek Chinese SRT against Japanese source SRT.")
    parser.add_argument("input", help="Input Japanese .srt")
    parser.add_argument("--translation", required=True, help="Initial Chinese .srt")
    parser.add_argument("--output", required=True, help="Output polished Chinese .srt")
    parser.add_argument("--api-key", default=os.environ.get("DEEPSEEK_API_KEY"))
    parser.add_argument("--base-url", default=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    parser.add_argument("--model", default=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro"))
    parser.add_argument("--chunk-size", type=int, default=70)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-wait", type=int, default=3)
    parser.add_argument("--sleep", type=float, default=0.0)
    parser.add_argument("--cache-dir")
    parser.add_argument("--qa-output")
    parser.add_argument("--qa-sample-ratio", type=float, default=0.28)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--workers", type=int, default=4, help="Concurrent polish workers")
    parser.add_argument("--polish-workers", dest="workers", type=int, default=argparse.SUPPRESS, help="Alias for --workers")
    parser.add_argument(
        "--glossary",
        action="append",
        default=["hooope_terms.txt", "model/hooope_terms.txt"],
    )
    args = parser.parse_args()
    polish(args)


if __name__ == "__main__":
    main()
