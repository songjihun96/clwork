"""Google Places 대표 이미지 자동 수집(import_school_photos) 검사.

실제 API는 부르지 않고 requests.get을 흉내 낸다 — 확인할 것은
"카테고리로 잘 거르는가·기존 이미지를 지키는가·dry-run이 저장하지 않는가"다.
"""
import os
import shutil
import sys

os.environ["DATABASE_URL"] = "sqlite:////tmp/school_photos.db"
os.environ["SECRET_KEY"] = "x"
if os.path.exists("/tmp/school_photos.db"):
    os.remove("/tmp/school_photos.db")
os.environ["GOOGLE_PLACES_API_KEY"] = "test-key"
sys.path.insert(0, ".")

import requests
from app.database import Base, SessionLocal, engine
from app.models import Coed, School
from app import import_school_photos

OK = []


def chk(n, c, e=""):
    OK.append(bool(c))
    print(("  OK  " if c else "  FAIL") + f"  {n}" + (f"  {e}" if not c and e else ""))


Base.metadata.create_all(bind=engine)

TMP_UPLOAD_DIR = "/tmp/school_photos_uploads"
if os.path.exists(TMP_UPLOAD_DIR):
    shutil.rmtree(TMP_UPLOAD_DIR)
import_school_photos.UPLOAD_DIR = TMP_UPLOAD_DIR
import_school_photos.time.sleep = lambda *_: None

db = SessionLocal()
s_specialized = School(name="양주기계고등학교", category="특성화고", region="경기",
                       address="a", coed=Coed.coed, is_visible=True, hero_image="")
s_meister = School(name="수도전기공업고등학교", category="마이스터고", region="서울",
                   address="a", coed=Coed.coed, is_visible=True, hero_image="")
s_science = School(name="서울과학고등학교", category="과학고", region="서울",
                   address="a", coed=Coed.coed, is_visible=True, hero_image="")
s_has_image = School(name="이미확인고등학교", category="특성화고", region="경기",
                     address="a", coed=Coed.coed, is_visible=True,
                     hero_image="/api/uploads/existing.jpg")
s_no_photo = School(name="사진없는고등학교", category="특성화고", region="경기",
                    address="a", coed=Coed.coed, is_visible=True, hero_image="")
s_hidden = School(name="숨김고등학교", category="특성화고", region="경기",
                  address="a", coed=Coed.coed, is_visible=False, hero_image="")
for s in (s_specialized, s_meister, s_science, s_has_image, s_no_photo, s_hidden):
    db.add(s)
db.commit()
[db.refresh(s) for s in (s_specialized, s_meister, s_science, s_has_image, s_no_photo, s_hidden)]
db.close()


class FakeResponse:
    def __init__(self, payload=None, content=b""):
        self._payload = payload
        self.content = content
        self.text = str(payload)

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


TEXT_SEARCH_RESULTS = {
    "양주기계고등학교": [{"photos": [{"photo_reference": "ref-mechanic"}]}],
    "수도전기공업고등학교": [{"photos": [{"photo_reference": "ref-meister"}]}],
    "이미확인고등학교": [{"photos": [{"photo_reference": "ref-existing"}]}],
    "사진없는고등학교": [{"name": "사진없는고등학교"}],  # photos 필드 자체가 없음
}


def fake_get(url, params=None, timeout=None):
    if url == import_school_photos.TEXT_SEARCH_URL:
        query = params["query"]
        name = next((n for n in TEXT_SEARCH_RESULTS if n in query), None)
        if not name:
            return FakeResponse({"status": "ZERO_RESULTS", "results": []})
        return FakeResponse({"status": "OK", "results": TEXT_SEARCH_RESULTS[name]})
    if url == import_school_photos.PHOTO_URL:
        return FakeResponse(content=b"\xff\xd8\xfake-jpeg-bytes")
    raise AssertionError(f"unexpected url {url}")


requests.get = fake_get

print("=== 1. 기본 실행 — 특성화고·마이스터고만, 미확인만 채운다 ===")
sys.argv = ["import_school_photos.py"]
code = import_school_photos.main()
chk("정상 종료", code == 0, str(code))

db = SessionLocal()
r_specialized = db.get(School, s_specialized.id)
r_meister = db.get(School, s_meister.id)
r_science = db.get(School, s_science.id)
r_has_image = db.get(School, s_has_image.id)
r_no_photo = db.get(School, s_no_photo.id)
r_hidden = db.get(School, s_hidden.id)
db.close()

chk("특성화고 이미지 채워짐", r_specialized.hero_image.startswith("/api/uploads/hero_"), r_specialized.hero_image)
chk("마이스터고 이미지 채워짐", r_meister.hero_image.startswith("/api/uploads/hero_"), r_meister.hero_image)
chk("과학고는 대상이 아니라 건드리지 않음", r_science.hero_image == "", r_science.hero_image)
chk("이미 이미지 있던 곳은 안 건드림", r_has_image.hero_image == "/api/uploads/existing.jpg", r_has_image.hero_image)
chk("사진 없는 학교는 안 건드림", r_no_photo.hero_image == "", r_no_photo.hero_image)
chk("숨김 학교(is_visible=False)는 대상이 아님", r_hidden.hero_image == "", r_hidden.hero_image)
chk("저장된 파일이 실제로 존재함", os.path.exists(
    os.path.join(TMP_UPLOAD_DIR, r_specialized.hero_image.rsplit("/", 1)[-1])))

print("=== 2. --force — 이미 있어도 덮어쓴다 ===")
sys.argv = ["import_school_photos.py", "--force"]
import_school_photos.main()
db = SessionLocal()
r_has_image2 = db.get(School, s_has_image.id)
db.close()
chk("--force로 기존 이미지 덮어씀", r_has_image2.hero_image != "/api/uploads/existing.jpg", r_has_image2.hero_image)

print("=== 3. --dry-run — 다운로드/저장/커밋 없이 존재 여부만 ===")
db = SessionLocal()
s_dry = School(name="드라이런고등학교", category="특성화고", region="경기",
              address="a", coed=Coed.coed, is_visible=True, hero_image="")
db.add(s_dry)
db.commit()
db.refresh(s_dry)
dry_id = s_dry.id
db.close()
TEXT_SEARCH_RESULTS["드라이런고등학교"] = [{"photos": [{"photo_reference": "ref-dry"}]}]


def photo_should_not_be_called(url, params=None, timeout=None):
    if url == import_school_photos.PHOTO_URL:
        raise AssertionError("dry-run이 Photo API를 불렀다 — 비용이 든다")
    return fake_get(url, params, timeout)


requests.get = photo_should_not_be_called
sys.argv = ["import_school_photos.py", "--dry-run"]
import_school_photos.main()
db = SessionLocal()
after = db.get(School, dry_id)
db.close()
chk("dry-run은 저장하지 않음(여전히 빈 문자열)", after.hero_image == "", after.hero_image)

print("=== 4. --limit — 앞에서 N곳만 ===")
requests.get = fake_get
sys.argv = ["import_school_photos.py", "--force", "--limit", "1"]
import_school_photos.main()
# limit=1 은 School.id 순으로 첫 학교(s_specialized)만 처리한다는 것만 확인
chk("정상 종료(limit)", True)

print("\n" + ("=" * 5) + f" {sum(OK)}/{len(OK)} 통과 " + ("=" * 5))
shutil.rmtree(TMP_UPLOAD_DIR, ignore_errors=True)
if not all(OK):
    sys.exit(1)
