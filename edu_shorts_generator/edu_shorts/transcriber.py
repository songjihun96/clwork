"""로컬 Whisper를 이용한 영상 → 텍스트(자막/대본) 전사.

AI가 "어느 구간이 교육적으로 중요한지" 판단하려면 타임스탬프가 붙은 텍스트가
필요하다(지시서 근거). openai-whisper를 로컬에서 실행해 무료로 처리하고,
문장(세그먼트) 단위 타임스탬프와 단어 단위 타임스탬프를 함께 뽑아 둔다.
- 세그먼트 타임스탬프: AI 후보 구간의 시작/끝을 "자연스러운 문장 경계"에
  맞추는 데 사용 (지시서 §8).
- 단어 타임스탬프: 자막(SRT/ASS) 생성 시 자연스러운 줄바꿈에 사용.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from .models import Transcript, TranscriptSegment, Word

logger = logging.getLogger(__name__)

ProgressCallback = Optional[Callable[[str], None]]


class Transcriber:
    def __init__(self, model_name: str = "medium", language: Optional[str] = None):
        self.model_name = model_name
        self.language = language
        self._model = None

    def _load_model(self, progress: ProgressCallback = None):
        if self._model is not None:
            return self._model
        try:
            import whisper  # openai-whisper
        except ImportError as e:
            raise RuntimeError(
                "openai-whisper 패키지가 설치되어 있지 않습니다. "
                "먼저 `pip install -r requirements.txt` 를 실행하세요."
            ) from e

        if progress:
            progress(f"Whisper 모델('{self.model_name}') 로딩 중... (처음 실행 시 모델 다운로드로 시간이 걸릴 수 있습니다)")
        self._model = whisper.load_model(self.model_name)
        return self._model

    def transcribe(self, video_path: str, progress: ProgressCallback = None) -> Transcript:
        """영상 파일을 전사한다. ffmpeg가 PATH에 있어야 whisper가 오디오를 추출할 수 있다."""
        model = self._load_model(progress)

        if progress:
            progress("음성 인식(전사) 진행 중... 영상 길이에 따라 수 분~수십 분 소요될 수 있습니다.")

        result = model.transcribe(
            video_path,
            language=self.language,
            word_timestamps=True,
            verbose=False,
            condition_on_previous_text=True,
        )

        segments: list[TranscriptSegment] = []
        for i, seg in enumerate(result.get("segments", [])):
            words = [
                Word(start=w.get("start", seg["start"]), end=w.get("end", seg["end"]), text=w.get("word", "").strip())
                for w in seg.get("words", []) or []
            ]
            segments.append(
                TranscriptSegment(
                    index=i,
                    start=float(seg["start"]),
                    end=float(seg["end"]),
                    text=seg["text"].strip(),
                    words=words,
                )
            )

        duration = segments[-1].end if segments else 0.0
        language = result.get("language", self.language or "unknown")

        if progress:
            progress(f"전사 완료: {len(segments)}개 구간, 총 {duration/60:.1f}분")

        return Transcript(segments=segments, language=language, duration=duration)
