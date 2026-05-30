from __future__ import annotations

import argparse
from dataclasses import dataclass, field

from . import config


@dataclass(frozen=True)
class PipelineConfig:
    episode_dir: str
    stage: str = "prepare-review"
    dry_run: bool = False
    summary_only: bool = False
    skip_asr: bool = False
    force_deepseek: bool = False
    model_dir: str = config.DEFAULT_TRANSCRIBE_MODEL_DIR
    vad_onnx: str = config.PIPELINE_DEFAULT_VAD_ONNX
    asr_enhancement: str = "qwen-risk"
    qwen_model_dir: str = config.DEFAULT_QWEN_ASR_MODEL_DIR
    qwen_max_segments: int = 24
    force_asr_compare: bool = False
    glossary: list[str] = field(default_factory=list)
    translate_workers: int = config.PIPELINE_TRANSLATE_WORKERS
    translate_context_blocks: int = config.PIPELINE_TRANSLATE_CONTEXT_BLOCKS
    encoder: str = "auto"
    cleanup: bool = False
    cleanup_confirmed: bool = False
    require_proofread_evidence: bool = True

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> "PipelineConfig":
        return cls(
            episode_dir=args.episode_dir,
            stage=args.stage,
            dry_run=args.dry_run,
            summary_only=args.summary_only,
            skip_asr=args.skip_asr,
            force_deepseek=args.force_deepseek,
            model_dir=args.model_dir,
            vad_onnx=args.vad_onnx,
            asr_enhancement=args.asr_enhancement,
            qwen_model_dir=args.qwen_model_dir,
            qwen_max_segments=args.qwen_max_segments,
            force_asr_compare=args.force_asr_compare,
            glossary=list(args.glossary or []),
            translate_workers=args.translate_workers,
            translate_context_blocks=args.translate_context_blocks,
            encoder=args.encoder,
            cleanup=args.cleanup,
            cleanup_confirmed=args.cleanup_confirmed,
            require_proofread_evidence=args.require_proofread_evidence,
        )
