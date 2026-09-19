"""학교 이름 검색 검사.

정식 명칭을 그대로 치는 사람은 드물다. 줄임말·머리글자·한글 음차로 쳐도
찾아지는지, 그리고 **엉뚱한 학교까지 딸려 나오지는 않는지**를 함께 본다.
느슨한 매칭은 잘 찾는 것보다 헛것을 안 내놓는 게 더 어렵다.
"""
import os
import sys

os.environ["DATABASE_URL"] = "sqlite:////tmp/school_search.db"
os.environ["SECRET_KEY"] = "x"
if os.path.exists("/tmp/school_search.db"):
    os.remove("/tmp/school_search.db")

sys.path.insert(0, ".")
from fastapi.testclient import TestClient          # noqa: E402
from app.main import app, school_name_matches      # noqa: E402
from app.database import SessionLocal              # noqa: E402
from app.models import Coed, School                # noqa: E402

OK = []


def chk(name, cond, extra=""):
    OK.append(bool(cond))
    print(("  OK  " if cond else "  FAIL") + f"  {name}" + (f"  {extra}" if not cond and extra else ""))


SCHOOLS = [
    "경화여자English Business고등학교",
    "이화여자대학교병설미디어고등학교",
    "안양공업고등학교",
    "부산정보고등학교",
    "선일빅데이터고등학교",
    "서울로봇고등학교",
    "경기관광고등학교",
    "한국애니메이션고등학교",
    "충북비즈니스고등학교",
    "예일메디텍고등학교",
    # 아래 둘은 자모 하나 차이라 서로 헷갈리기 쉽다. 오타 보정이 이 둘을
    # 뭉뚱그리지 않는지 보려고 일부러 같이 둔다.
    "서울여자상업고등학교",
    "서울영상고등학교",
]

db = SessionLocal()
for i, nm in enumerate(SCHOOLS):
    db.add(School(name=nm, category="특성화고", region="서울",
                  address=f"서울 어딘가 {i}", coed=Coed.coed, phone="0"))
db.commit()
db.close()
c = TestClient(app)


def search(term):
    return [x["name"] for x in c.get(f"/api/schools?name={term}&size=20").json()["items"]]


print("=== 1. 영문 머리글자 (English Business → EB) ===")
chk("경화EB고등학교", search("경화EB고등학교") == ["경화여자English Business고등학교"],
    str(search("경화EB고등학교")))
chk("경화EB고", search("경화EB고") == ["경화여자English Business고등학교"], str(search("경화EB고")))

print("=== 2. 머리글자를 한글로 읽기 (EB → 이비) ===")
chk("경화이비고", search("경화이비고") == ["경화여자English Business고등학교"], str(search("경화이비고")))
chk("경화이비고등학교", search("경화이비고등학교") == ["경화여자English Business고등학교"],
    str(search("경화이비고등학교")))

print("=== 3. 긴 이름의 앞머리 + 특징어 줄임 ===")
chk("이화미디어고", search("이화미디어고") == ["이화여자대학교병설미디어고등학교"],
    str(search("이화미디어고")))
chk("이화미디어", search("이화미디어") == ["이화여자대학교병설미디어고등학교"],
    str(search("이화미디어")))

print("=== 4. 기존 줄임말(~업고등학교)도 그대로 ===")
chk("안양공고", search("안양공고") == ["안양공업고등학교"], str(search("안양공고")))

print("=== 5. 정식 명칭·부분 일치는 그대로 ===")
chk("부산정보", search("부산정보") == ["부산정보고등학교"], str(search("부산정보")))
chk("선일빅데이터고등학교", search("선일빅데이터고등학교") == ["선일빅데이터고등학교"],
    str(search("선일빅데이터고등학교")))

print("=== 6. 헛것이 나오지 않는가 (이게 핵심) ===")
# 아래 몇 개는 SQL 부분 일치로 정상적으로 잡히는 것들이라(이름 안에 그
# 글자가 실제로 들어 있다) 느슨한 매칭까지 가지도 않는다. 그래서 여기서는
# 느슨한 매칭 함수가 그것들을 스스로 거절하는지를 본다 — 부분 일치가
# 0건일 때 이 함수가 대신 나서기 때문이다.
chk("없는 학교는 0건", search("없는학교이름고") == [], str(search("없는학교이름고")))
chk("느슨한 매칭: 한 글자 '고' 는 거절", not school_name_matches("고", "부산정보고등학교"))
chk("느슨한 매칭: 두 글자 '고등' 도 거절", not school_name_matches("고등", "부산정보고등학교"))
# '여자미디어고' 는 이름 안에 그대로 들어 있지는 않고 글자 순서만 맞는다.
# 앞머리(이화)가 빠졌으므로 이런 건 받아주지 않는다.
# ('미디어고' 처럼 이름에 통째로 들어 있는 말은 정상적인 부분 일치라 걸린다.)
chk("느슨한 매칭: 앞머리가 빠지면 거절('여자미디어고')",
    not school_name_matches("여자미디어고", "이화여자대학교병설미디어고등학교"))
chk("느슨한 매칭: 다른 학교를 부르지 않는다",
    not school_name_matches("경화이비고", "경기관광고등학교")
    and not school_name_matches("이화미디어고", "부산정보고등학교")
    and not school_name_matches("안양공고", "서울로봇고등학교"))
chk("'정보고' 로 엉뚱한 학교가 딸려오지 않는다",
    all("정보고" in n for n in search("정보고")), str(search("정보고")))

print("=== 7. 오타를 견디는가 ===")
chk("애→에 오타: 한국에니고", search("한국에니고") == ["한국애니메이션고등학교"],
    str(search("한국에니고")))
chk("텍→택 오타: 예일메디택고", search("예일메디택고") == ["예일메디텍고등학교"],
    str(search("예일메디택고")))
chk("즈→지 오타: 충북비지니스고", search("충북비지니스고") == ["충북비즈니스고등학교"],
    str(search("충북비지니스고")))
chk("제대로 친 것도 그대로", search("한국애니고") == ["한국애니메이션고등학교"],
    str(search("한국애니고")))

print("=== 8. 오타 보정이 멀쩡한 검색을 망치지 않는가 ===")
# '서울여상' 과 '서울영상고' 는 자모 하나 차이다. 오타 보정을 늘 켜두면
# 서울여자상업고를 찾는 사람에게 서울영상고가 함께 나온다.
chk("서울여상 → 서울여자상업고만", search("서울여상") == ["서울여자상업고등학교"],
    str(search("서울여상")))
chk("서울영상고 → 서울영상고만", search("서울영상고") == ["서울영상고등학교"],
    str(search("서울영상고")))
chk("오타 보정을 끄면 서울영상고는 서울여상을 안 부른다",
    not school_name_matches("서울여상", "서울영상고등학교", allow_typo=False))

print("=== 9. 함수 단위 확인 ===")
chk("별칭도 같이 본다",
    school_name_matches("경화이비", "경화여자English Business고등학교", "경화EB고등학교"))
chk("두 글자는 무조건 거절", not school_name_matches("경화", "경화여자English Business고등학교"))
chk("첫 글자 다르면 거절", not school_name_matches("여자대학교미디어고", "이화여자대학교병설미디어고등학교"))

print("=== 10. 학교 종류만 쳐도 그 종류 전부가 나오는가 ===")
# '상고'·'공고'는 특정 학교의 앞머리가 아니라 **종류**다. 앞머리가 같아야
# 한다는 규칙에서 빼되, 이름이 실제로 그 종류로 끝날 때만 걸어야 한다.
chk("상고 → 상업고", school_name_matches("상고", "서울여자상업고등학교"))
chk("상고 → 상업계고도", school_name_matches("상고", "경기상업계고등학교"))
chk("공고 → 공업고", school_name_matches("공고", "안양공업고등학교"))
chk("여상 → 여자상업고", school_name_matches("여상", "서울여자상업고등학교"))
for short, full in [("농고", "전남농업고등학교"), ("수고", "완도수산고등학교"),
                    ("실고", "서울실업고등학교"), ("종고", "충남종합고등학교"),
                    ("과고", "대전과학고등학교"), ("외고", "명덕외국어고등학교"),
                    ("예고", "서울예술고등학교"), ("여고", "인천여자고등학교"),
                    ("해양고", "포항해양고등학교"), ("정보고", "부산정보고등학교"),
                    ("전산고", "대구전산고등학교")]:
    chk(f"{short} → {full}", school_name_matches(short, full))
chk("줄이지 않은 '상업고'도 같은 결과", school_name_matches("상업고", "부산상업고등학교"))

print("=== 11. 종류 검색이 엉뚱한 학교를 부르지 않는가 ===")
# '서울영상고'는 끝 두 글자가 우연히 '상고'다. 끝 글자만 보고 맞히면 여기서 걸린다.
chk("상고 ↛ 서울영상고", not school_name_matches("상고", "서울영상고등학교"))
chk("공고 ↛ 상업고", not school_name_matches("공고", "서울여자상업고등학교"))
chk("여상 ↛ 영상고", not school_name_matches("여상", "서울영상고등학교"))
chk("과고 ↛ 관광고", not school_name_matches("과고", "경기관광고등학교"))
chk("정보고 ↛ 로봇고", not school_name_matches("정보고", "서울로봇고등학교"))

print("=== 12. 종류 검색은 목록 API 에서도 그대로 나오는가 ===")
# 이게 실제 증상이었다. '상고'는 이름에 통째로 들어있지 않아 부분 일치로는
# 정작 상업고가 안 나오고 '서울영상고'만 나왔다.
chk("상고 → 서울여자상업고만", search("상고") == ["서울여자상업고등학교"], str(search("상고")))
chk("공고 → 안양공업고만", search("공고") == ["안양공업고등학교"], str(search("공고")))
chk("여상 → 서울여자상업고만", search("여상") == ["서울여자상업고등학교"], str(search("여상")))

print("\n" + "=" * 5 + f" {sum(OK)}/{len(OK)} 통과 " + "=" * 5)
if not all(OK):
    sys.exit(1)
