"""연구 참고자료 첨부파일(논문 PDF·한글 파일 등)을 로컬 디스크에 저장한다.

image_store.py와 같은 이유로 로컬 디스크를 쓴다(이 서비스 규모에 별도
클라우드 스토리지는 과하다). 사진과 달리 리사이즈·썸네일이 필요 없어
원본 그대로만 보관하는 훨씬 단순한 버전이다.
"""

import os
import uuid
from pathlib import Path
from typing import Optional, Tuple

MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", str(Path(__file__).resolve().parent.parent / "media")))
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20MB

# 브라우저가 hwp/hwpx 같은 형식은 content-type을 제각각으로(또는
# application/octet-stream으로) 보내는 경우가 많아, content-type이
# 아니라 파일 확장자로 판단한다.
ALLOWED_EXTENSIONS = {".pdf", ".hwp", ".hwpx", ".doc", ".docx", ".jpg", ".jpeg", ".png"}
CONTENT_TYPE_BY_EXT = {
    ".pdf": "application/pdf", ".hwp": "application/x-hwp",
    ".hwpx": "application/haansofthwp", ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
}


def _student_dir(student_id: int) -> Path:
    d = MEDIA_ROOT / "research_literature" / str(student_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_document(student_id: int, filename: str, data: bytes) -> Tuple[str, str]:
    """파일을 저장하고 (storage_key, 화면에 보여줄 파일명)을 돌려준다.

    지원하지 않는 형식이거나 너무 크면 ValueError를 던진다.
    """
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError(f"파일이 너무 큽니다. {MAX_UPLOAD_BYTES // 1024 // 1024}MB 이하로 올려주세요.")
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError("이 형식의 파일은 첨부할 수 없습니다. PDF/HWP/DOC/이미지 파일만 가능합니다.")

    d = _student_dir(student_id)
    name = f"{uuid.uuid4().hex}{ext}"
    (d / name).write_bytes(data)
    safe_name = (Path(filename or "").name or f"첨부파일{ext}")[:150]
    return f"research_literature/{student_id}/{name}", safe_name


def read_document(storage_key: str) -> Optional[bytes]:
    if not storage_key or ".." in storage_key or storage_key.startswith("/"):
        return None
    path = MEDIA_ROOT / storage_key
    try:
        path = path.resolve()
        if MEDIA_ROOT.resolve() not in path.parents and path != MEDIA_ROOT.resolve():
            return None
        return path.read_bytes()
    except (OSError, ValueError):
        return None


def delete_document(storage_key: str) -> None:
    if not storage_key:
        return
    try:
        (MEDIA_ROOT / storage_key).unlink(missing_ok=True)
    except OSError:
        pass


def guess_media_type(storage_key: str) -> str:
    return CONTENT_TYPE_BY_EXT.get(Path(storage_key or "").suffix.lower(), "application/octet-stream")
