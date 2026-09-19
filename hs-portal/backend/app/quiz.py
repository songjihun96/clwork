"""진로 적성 테스트 로직."""

from . import quiz_bank

AXES = ["TECH", "IT", "DESIGN", "BIZ", "CARE", "AGRI"]

AXIS_LABEL = {
    "TECH": "제작·기계",
    "IT": "IT·소프트웨어",
    "DESIGN": "디자인·콘텐츠",
    "BIZ": "경영·비즈니스",
    "CARE": "서비스·보건",
    "AGRI": "농생명·바이오",
}

SUBSCALE_LABEL = {
    "TECH": ["기계·문제해결", "설계·정밀성", "제작·실습", "현장·장비", "품질·검증", "유지관리"],
    "IT": ["논리·문제해결", "디지털 탐색", "데이터·분석", "집중·개발", "자기주도 학습", "구조화·설계"],
    "DESIGN": ["시각·감각", "창의·아이디어", "콘텐츠·표현", "표현·공개", "완성도·수정", "자유·규칙"],
    "BIZ": ["기획·관리", "마케팅·고객", "금융·수치", "소통·설득", "목표·성과관리", "도전·리스크"],
    "CARE": ["돌봄·공감", "대인·소통", "보건·안전", "현장·서비스", "공감·정서", "협력·팀워크"],
    "AGRI": ["생명·관찰", "환경·지속가능성", "농업·바이오", "현장·자연", "탐구·연구", "실내·실외"],
}

QUESTIONS = quiz_bank.BANK


def questions_for(seed=None) -> list:
    return quiz_bank.build_quiz(seed)


def score_answers(answers: list, seed=None) -> dict:
    """5점 척도 답변을 축별 0~100 점수와 세부 점수로 환산한다."""
    items = questions_for(seed)
    raw = {ax: 0.0 for ax in AXES}
    counts = {ax: 0 for ax in AXES}
    sub_raw = {}
    sub_counts = {}

    for i, answer in enumerate(answers):
        if i >= len(items):
            break
        item = items[i]
        try:
            value = int(answer)
        except (TypeError, ValueError):
            continue
        value = max(1, min(5, value))
        points = value - 1  # 1~5 -> 0~4
        if item.get("reverse"):
            points = 4 - points
        axis = item["axis"]
        raw[axis] += points
        counts[axis] += 1
        sub = item["subscale"]
        sub_raw[sub] = sub_raw.get(sub, 0.0) + points
        sub_counts[sub] = sub_counts.get(sub, 0) + 1

    scores = {}
    for ax in AXES:
        scores[ax] = round((raw[ax] / (max(counts[ax], 1) * 4)) * 100)

    sub_scores = {}
    for ax in AXES:
        sub_scores[ax] = {}
        for sub in SUBSCALE_LABEL[ax]:
            n = max(sub_counts.get(sub, 0), 1)
            sub_scores[ax][sub] = round((sub_raw.get(sub, 0.0) / (n * 4)) * 100)

    return {"axis_scores": scores, "sub_scores": sub_scores, "quality": response_quality(answers)}


def response_quality(answers: list) -> dict:
    """응답 패턴을 간단히 점검해 결과를 얼마나 믿을 수 있는지 알려준다.

    문항이 늘어난 만큼, 전부 같은 번호만 고르거나 편차 없이 답한 경우를
    걸러내지 않으면 "정확해 보이는 점수"가 실제로는 무의미할 수 있다.
    """
    values = []
    for a in answers:
        try:
            values.append(int(a))
        except (TypeError, ValueError):
            continue

    if len(values) < 2:
        return {"reliable": True, "note": ""}

    distinct = len(set(values))
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)

    if distinct == 1:
        return {"reliable": False, "note": "모든 문항에 같은 번호만 선택해 결과의 신뢰도가 낮습니다."}
    if variance < 0.3:
        return {"reliable": False, "note": "응답 편차가 매우 작아 실제 성향과 다르게 나왔을 수 있습니다."}
    return {"reliable": True, "note": ""}


def top_axes(scores: dict, n: int = 3) -> list[str]:
    return sorted(AXES, key=lambda ax: (-scores.get(ax, 0), AXES.index(ax)))[:n]


def score_confidence(scores: dict, tops: list[str]) -> str:
    """1위와 2위 축의 점수 차이로 추천이 얼마나 뚜렷한지 가늠한다.

    차이가 작으면 두 계열이 비슷하게 어울린다는 뜻이라, 하나로 단정하기보다
    "비슷하다"고 알려주는 편이 더 정직하다.
    """
    if len(tops) < 2:
        return "high"
    gap = scores.get(tops[0], 0) - scores.get(tops[1], 0)
    return "high" if gap >= 10 else "close"


def recommended_departments(scores: dict, limit: int = 3) -> list[dict]:
    groups = []
    for axis in AXES:
        for group in DEPARTMENT_GROUPS.get(axis, []):
            groups.append({**group, "axis": axis, "axis_score": scores.get(axis, 0)})
    groups.sort(key=lambda g: (-g["axis_score"], AXES.index(g["axis"])))
    positive = [g for g in groups if g["axis_score"] > 0]
    return (positive or groups)[:limit]


def department_matches(school_departments: list[str], keywords: list[str]) -> list[str]:
    hits = []
    for dept in school_departments:
        for kw in keywords:
            if kw.lower() in dept.lower():
                hits.append(dept)
                break
    return hits

# 축 -> 추천 학과 계열. label은 사용자에게 보여줄 이름,
# keywords는 NEIS 학과명에서 이 계열을 찾아낼 검색어.
#
# jobs 는 진로 챗봇 정보표(career_data.DEFAULT_GUIDE)의 직업 이름과 **같아야
# 한다.** 카드에 뜬 이름과 챗봇이 말하는 이름이 다르면 학생은 다른 직업인 줄
# 안다. (예전 목록의 '전기기사'는 자격증 이름이었고 '창업'은 직업이 아니었다.)
DEPARTMENT_GROUPS = {
    "TECH": [
        {
            "label": "기계·자동차",
            "keywords": ["기계", "자동차", "메카트로", "금형", "설비", "조선", "항공정비", "로봇",
            # 요즘 새로 생기는 이름들. 뜻은 같은데 말이 바뀐 것뿐이다.
            "모빌리티", "모터스", "스마트팩토리", "자동화", "드론", "정밀",
            "용접", "배관", "건설", "건축", "토목", "소방", "플랜트", "산업설비", "오토", "정비", "도장", "배터리", "차체"],
            "desc": "부품을 설계하고 조립해 실제로 움직이는 것을 만드는 분야",
            "jobs": ["기계설계원", "CNC 가공원", "자동차정비원", "생산설비 운용원"],
        },
        {
            "label": "전기·전자",
            "keywords": ["전기", "전자", "반도체", "제어", "통신", "에너지", "정보통신",
            "전자기계", "스마트전기", "신재생", "이차전지", "디스플레이", "나노", "신소재", "융합소재"],
            "desc": "전기·전자 회로와 반도체, 자동제어를 다루는 분야",
            "jobs": ["전기 설비 기술자", "반도체 장비 기술자", "전자회로 기술자", "자동제어 기술자"],
        },
    ],
    "IT": [
        {
            "label": "소프트웨어·정보",
            "keywords": ["소프트웨어", "정보", "인터넷", "컴퓨터", "프로그래", "코딩", "네트워크", "보안", "게임", "빅데이터", "인공지능", "AI", "SW", "데이터", "클라우드", "메타버스", "가상현실", "VR", "IT", "디지털", "스마트소프트", "융합소프트", "정보처리"],
            "desc": "프로그래밍, 앱·웹 개발, 데이터와 보안을 다루는 분야",
            "jobs": ["앱 개발자", "웹 개발자", "데이터 분석원", "정보보안 담당자"],
        },
    ],
    "DESIGN": [
        {
            "label": "디자인·콘텐츠",
            "keywords": ["디자인", "콘텐츠", "미디어", "영상", "만화", "애니", "웹툰", "방송", "광고", "시각", "패션", "미용", "뷰티", "메이커", "창작", "공예", "사진", "음악", "실용음악", "연기", "예술", "출판", "편집", "의상", "주얼리", "스타일", "도예", "도자", "목공", "섬유"],
            "desc": "시각 디자인, 영상·콘텐츠 제작, 패션·뷰티 분야",
            "jobs": ["그래픽 디자이너", "영상 편집자", "콘텐츠 기획자", "화면 디자이너"],
        },
    ],
    "BIZ": [
        {
            "label": "경영·금융·유통",
            "keywords": ["경영", "회계", "금융", "유통", "마케팅", "무역", "사무", "비즈니스", "물류", "e비즈", "세무", "상경", "행정", "창업", "경제", "부동산", "보험", "스마트경영", "글로벌비즈", "커머스", "자영", "판매", "유통관리"],
            "desc": "회계·마케팅·유통·창업 등 비즈니스 전반을 배우는 분야",
            "jobs": ["회계 사무원", "금융 사무원", "마케터", "유통 관리원"],
        },
    ],
    "CARE": [
        {
            "label": "보건·조리·서비스",
            "keywords": ["조리", "제과", "제빵", "외식", "관광", "호텔", "간호", "보건", "복지", "항공서비스", "승무", "치위생", "반려동물", "카페", "의료", "헬스", "케어", "요양", "재활", "보육", "유아", "아동", "서비스", "바리스타", "커피", "식음료", "레저", "스포츠", "부사관", "국방", "군사", "경호", "소방안전", "안전관리"],
            "desc": "조리·제과, 보건·간호, 관광·서비스처럼 사람을 응대하고 돌보는 분야",
            "jobs": ["조리사", "제과제빵사", "간호조무사", "호텔·관광 서비스원"],
        },
    ],
    "AGRI": [
        {
            "label": "농생명·바이오·환경",
            "keywords": ["농업", "원예", "축산", "식품", "바이오", "환경", "해양", "수산", "생명", "동물", "산림", "조경", "화훼", "농생명", "스마트팜", "양식", "운항", "항해", "기관", "어업", "농기계", "그린", "자원", "화학", "제약", "말산업", "승마", "경마", "종축"],
            "desc": "농생명·식품가공·바이오·환경·해양을 다루는 분야",
            "jobs": ["식품가공원", "바이오 실험원", "스마트팜 농업인", "환경 관리원"],
        },
    ],
}



# 위 함수들은 상단에서 정의한 점수 로직을 사용한다.