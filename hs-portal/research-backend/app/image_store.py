"""포트폴리오 사진을 로컬 디스크에 저장한다.

이 서비스에는 파일 저장소가 전혀 없었다(유일한 업로드 처리는 은행 명세서
파싱인데, 그건 메모리에서만 다루고 디스크에 남기지 않는다). 그렇다고
S3 같은 새 클라우드 스토리지를 들이는 건 지금 규모(nginx+systemd로 직접
띄우는 단일 서버)에 과하므로, 서버 로컬 디스크에 저장하는 가장 단순한
방식을 쓴다 — `MEDIA_ROOT` 환경변수(기본값: 프로젝트 아래 `media/`)
밑에 학생 id별 폴더를 두고 원본·웹용·썸네일 세 장을 함께 관리한다.

파일은 정적 경로로 직접 노출하지 않는다. main.py의 스트리밍 엔드포인트가
"이 사진이 요청한 사람 것이 맞는지"를 DB로 확인한 뒤 내려주므로, 파일
이름을 안다고 남의 사진을 볼 수 없다.
"""

import os
import uuid
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, ImageOps

MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", str(Path(__file__).resolve().parent.parent / "media")))
WEB_MAX_SIDE = 1600     # 화면에 보여줄 웹 최적화본 최대 변 길이
THUMB_MAX_SIDE = 320    # 목록/갤러리용 썸네일 최대 변 길이
MAX_UPLOAD_BYTES = 12 * 1024 * 1024   # 12MB
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


def _student_dir(student_id: int) -> Path:
    d = MEDIA_ROOT / "portfolio" / str(student_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _flatten_to_rgb(im: Image.Image) -> Image.Image:
    """JPEG로 저장하므로 투명(알파) 정보는 반드시 없애야 한다 — PNG 스크린샷처럼
    투명 배경이 있는 파일을 그대로 두면 Pillow가 "cannot write mode RGBA as
    JPEG"로 저장을 거부해 업로드가 500으로 죽는다. 그냥 채널만 버리면 투명했던
    자리가 검게 나오므로, 흰 배경 위에 얹어(합성) 자연스럽게 만든다."""
    if im.mode == "RGB":
        return im
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        return bg
    return im.convert("RGB")


def _resize_copy(im: Image.Image, max_side: int) -> Image.Image:
    im = ImageOps.exif_transpose(im)  # 휴대폰 사진의 회전 정보를 실제 픽셀에 반영
    w, h = im.size
    if max(w, h) > max_side:
        scale = max_side / max(w, h)
        im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    return _flatten_to_rgb(im)


def save_image(student_id: int, data: bytes) -> Tuple[str, str, str, int, int]:
    """원본·웹용·썸네일 세 장을 저장하고 (storage_key, web_key, thumbnail_key, width, height)를 돌려준다.

    실패하면 ValueError를 던진다 — 손상된 파일이거나 이미지가 아닌 경우다.
    """
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError(f"파일이 너무 큽니다. {MAX_UPLOAD_BYTES // 1024 // 1024}MB 이하로 올려주세요.")

    import io
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:
        raise ValueError("이미지 파일이 아니거나 손상되었습니다.")

    width, height = im.size
    d = _student_dir(student_id)
    stem = uuid.uuid4().hex

    orig_name = f"{stem}_orig.jpg"
    web_name = f"{stem}_web.jpg"
    thumb_name = f"{stem}_thumb.jpg"

    # 여기서부터는 파일 형식이 특이하면(팔레트·CMYK·다중 프레임 등) Pillow가
    # 예상 못 한 오류를 던질 수 있다 — 그걸 그대로 두면 500(원인 불명)으로
    # 죽으므로, 여기서 잡아 화면에 뜨는 안내 문구로 바꾸고 서버 로그에
    # 실제 원인을 남긴다.
    try:
        orig_im = ImageOps.exif_transpose(im)
        _flatten_to_rgb(orig_im).save(d / orig_name, "JPEG", quality=92)
        _resize_copy(im, WEB_MAX_SIDE).save(d / web_name, "JPEG", quality=85)
        _resize_copy(im, THUMB_MAX_SIDE).save(d / thumb_name, "JPEG", quality=80)
    except Exception as exc:
        print(f"[포트폴리오 사진] 변환 실패: {exc!r}", flush=True)
        for name in (orig_name, web_name, thumb_name):
            (d / name).unlink(missing_ok=True)
        raise ValueError("이 사진은 저장할 수 없는 형식입니다. 다른 사진으로 다시 올려보세요.")

    rel = f"portfolio/{student_id}"
    return f"{rel}/{orig_name}", f"{rel}/{web_name}", f"{rel}/{thumb_name}", width, height


def read_variant(storage_key: str) -> Optional[bytes]:
    """저장된 파일을 읽는다. storage_key는 항상 DB에서 온 값이라 경로 탈출
    문자가 없어야 정상이지만, 방어적으로 한 번 더 확인한다."""
    if not storage_key or ".." in storage_key or storage_key.startswith("/"):
        return None
    path = MEDIA_ROOT / storage_key
    try:
        path = path.resolve()
        MEDIA_ROOT.resolve()
        if MEDIA_ROOT.resolve() not in path.parents and path != MEDIA_ROOT.resolve():
            return None
        return path.read_bytes()
    except (OSError, ValueError):
        return None


def delete_image(*storage_keys: str) -> None:
    for key in storage_keys:
        if not key:
            continue
        try:
            (MEDIA_ROOT / key).unlink(missing_ok=True)
        except OSError:
            pass
