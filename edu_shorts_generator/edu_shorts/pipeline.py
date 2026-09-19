"""전체 파이프라인 오케스트레이션: 전사 → AI 분석 → 선정 → 렌더링.

GUI(gui.py)는 이 모듈의 run_pipeline()만 스레드에서 호출하면 된다.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import time
from typing import Any, Callable, Optional

from .analyzer import analyze_transcript
from .config import CONFIG_PATH
from .models import ShortResult, Transcript
from .selector import select_final_shorts
from .transcriber import Transcriber
from .utils import fmt_mmss
from .video_editor import render_short

logger = logging.getLogger(__name__)

ProgressCallback = Optional[Callable[[str, float], None]]  # (메시지, 0~1 진행률 또는 -1=불명)


@dataclasses.dataclass
class PipelineOptions:
    video_path: str
    shorts_count: int
    max_length_seconds: int
    subtitles_enabled: bool
    vertical_enabled: bool


@dataclasses.dataclass
class PipelineResult:
    shorts: list[ShortResult]
    output_dir: str
    content_type_info: dict[str, str]
    transcript_duration: float
    candidates_found: int


def run_pipeline(options: PipelineOptions, cfg: dict[str, Any], progress: ProgressCallback = None) -> PipelineResult:
    def report(msg: str, pct: float = -1.0):
        logger.info(msg)
        if progress:
            progress(msg, pct)

    video_path = options.video_path
    video_name = os.path.splitext(os.path.basename(video_path))[0]
    output_root = cfg.get("output_dir", "output")
    if not os.path.isabs(output_root):
        output_root = os.path.join(os.path.dirname(CONFIG_PATH), output_root)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    output_dir = os.path.join(output_root, f"{video_name}_{timestamp}")
    os.makedirs(output_dir, exist_ok=True)

    # 1) 전사
    report("1/4 단계: 음성 인식(전사) 시작", 0.05)
    transcriber = Transcriber(model_name=cfg["whisper_model"], language=cfg.get("whisper_language"))
    transcript: Transcript = transcriber.transcribe(video_path, progress=lambda m: report(m, 0.1))
    report(f"전사 완료: 총 {fmt_mmss(transcript.duration)}, {len(transcript.segments)}개 구간", 0.35)

    # 2) AI 분석 (교육적 가치 평가)
    report("2/4 단계: AI 교육 콘텐츠 분석 시작", 0.4)
    candidates, content_type_info = analyze_transcript(
        transcript, cfg, options.max_length_seconds, progress=lambda m: report(m, 0.55)
    )
    report(f"AI 분석 완료: 후보 {len(candidates)}개 발견", 0.65)

    # 3) 최종 선정 (점수 계산 + 개수 제한 + 겹침 제거 + 최대 길이 강제)
    report("3/4 단계: 상위 후보 선정 중", 0.68)
    final_candidates = select_final_shorts(
        candidates, transcript, cfg, options.shorts_count, options.max_length_seconds
    )
    if not final_candidates:
        report("교육적 가치 기준을 만족하는 후보를 찾지 못했습니다.", 1.0)
        return PipelineResult(
            shorts=[], output_dir=output_dir, content_type_info=content_type_info,
            transcript_duration=transcript.duration, candidates_found=len(candidates),
        )
    report(f"최종 선정: {len(final_candidates)}개 (요청 {options.shorts_count}개)", 0.7)

    # 4) 렌더링
    results: list[ShortResult] = []
    total = len(final_candidates)
    for i, cand in enumerate(final_candidates, start=1):
        report(f"4/4 단계: 쇼츠 렌더링 중 ({i}/{total}) - {cand.title}", 0.7 + 0.3 * (i - 1) / total)
        render = render_short(
            video_path, transcript, cand, i, output_dir, cfg,
            subtitles_enabled=options.subtitles_enabled,
            vertical_enabled=options.vertical_enabled,
        )
        results.append(
            ShortResult(
                index=i,
                candidate=cand,
                output_path=render["output_path"],
                subtitle_path=render["subtitle_path"],
                actual_duration=render["actual_duration"],
            )
        )

    _write_metadata(results, output_dir, content_type_info, options)
    report(f"완료: 총 {len(results)}개 쇼츠 생성", 1.0)

    return PipelineResult(
        shorts=results, output_dir=output_dir, content_type_info=content_type_info,
        transcript_duration=transcript.duration, candidates_found=len(candidates),
    )


def _write_metadata(
    results: list[ShortResult], output_dir: str, content_type_info: dict[str, str], options: PipelineOptions
) -> None:
    data = {
        "source_video": options.video_path,
        "content_type_info": content_type_info,
        "shorts_count_requested": options.shorts_count,
        "max_length_seconds": options.max_length_seconds,
        "shorts": [],
    }
    for r in results:
        c = r.candidate
        data["shorts"].append(
            {
                "번호": r.index,
                "제목": c.title,
                "시작": fmt_mmss(c.start_time),
                "종료": fmt_mmss(c.end_time),
                "길이_초": round(r.actual_duration, 1),
                "교육_콘텐츠_유형": c.content_type,
                "과목": c.subject,
                "핵심_학습_개념": c.key_concept,
                "학습_목표": c.learning_objective,
                "선정_이유": c.reason,
                "shorts_score": round(c.shorts_score, 1),
                "키워드": c.keywords,
                "구조": c.structure_tags,
                "세부_점수": dataclasses.asdict(c.scores),
                "파일": os.path.basename(r.output_path),
            }
        )
    with open(os.path.join(output_dir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
