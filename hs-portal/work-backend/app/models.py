"""우리업무의 표. 이 서비스가 아는 표는 이게 전부다.

**왜 계정을 따로 두나.** 우리동네 직업계고의 `users` 표는 학생·학교·선생님의
것이다. 거기에 협업기업 직원을 섞으면, 권한 검사 한 줄만 빠뜨려도 남의 회사
사람이 학생 개인정보가 있는 화면에 닿는다. 표를 나누면 그 사고가 **구조적으로
불가능**해진다 — 이 프로세스는 그 표의 존재조차 모른다.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from .database import Base


class WorkOrg(Base):
    """협업기업. 이 회사에 속한 계정들이 요청사항을 올린다."""

    __tablename__ = "work_orgs"

    id = Column(Integer, primary_key=True)
    name = Column(String(80), nullable=False, unique=True)
    contact = Column(String(120), default="")     # 담당자·연락처 메모
    is_active = Column(Boolean, nullable=False, default=True)
    # 이 기업이 볼 수 있는 방문 통계 사이트. 쉼표로 잇는다.
    #   None(비어 있음) = 집계하는 사이트 전부 / "" = 아무것도 안 보임
    # 방문자 수는 영업 자료가 될 수 있어서 관리자가 기업마다 좁힐 수 있게 둔다.
    visit_sites = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class WorkUser(Base):
    """업무 시스템 계정. 관리자가 만들어서 나눠 준다.

    가입 화면은 두지 않는다. 아무나 만들 수 있으면 그 순간 사내 시스템이
    아니게 된다.
    """

    __tablename__ = "work_users"

    id = Column(Integer, primary_key=True)
    login_id = Column(String(40), nullable=False, unique=True, index=True)
    name = Column(String(40), nullable=False)
    password_hash = Column(String(255), nullable=False)
    # admin(관리자) / staff(직원) / partner(협업기업)
    role = Column(String(10), nullable=False, default="staff", index=True)
    # role=partner 인 계정만 채워진다.
    org_id = Column(Integer, ForeignKey("work_orgs.id"), nullable=True, index=True)

    phone = Column(String(30), default="")
    email = Column(String(120), default="")
    memo = Column(String(200), default="")        # 직책·부서 등

    is_active = Column(Boolean, nullable=False, default=True)
    # 관리자가 준 초기 비밀번호를 아직 안 바꾼 상태
    must_change_password = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    last_login_at = Column(DateTime, nullable=True)


class WorkAttendance(Base):
    """출근 기록. 버튼을 누르는 게 아니라 **접속으로 자동 판단**한다.

    그날 처음 시스템을 쓴 시각이 출근이고, 마지막으로 쓴 시각이 마지막 활동이다.
    누르는 수고가 없고 "출근 체크를 깜빡했다"가 생기지 않는다. 반면 **퇴근은
    버튼을 눌러야** 남는다 — 접속만 봐서는 잠깐 자리를 비운 것과 일을 마친
    것이 똑같아 보이기 때문이다. 하루 한 사람 한 줄이다.

    work_date 는 **한국 날짜**다. UTC 로 끊으면 오전 9시 출근이 전날로 기록된다.
    """

    __tablename__ = "work_attendance"
    __table_args__ = (
        UniqueConstraint("user_id", "work_date", name="uq_work_attendance_day"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("work_users.id"), nullable=False, index=True)
    work_date = Column(Date, nullable=False, index=True)

    first_seen_at = Column(DateTime, nullable=False)   # 그날 첫 접속 = 출근
    last_seen_at = Column(DateTime, nullable=False)    # 마지막 활동
    # 퇴근은 **누를 때만** 남는다. 접속으로는 "지금 안 쓰고 있다"와 "오늘 일을
    # 마쳤다"를 구분할 수 없기 때문이다. 자리를 비운 것과 퇴근은 다른 얘기다.
    left_at = Column(DateTime, nullable=True)
    # 퇴근을 안 누른 채 날이 바뀌면 마지막 활동 시각으로 대신 닫는다.
    # **추측한 값이라는 표시를 반드시 남긴다** — 본인이 찍은 시각과 섞이면
    # 나중에 근태를 따질 때 어느 쪽이 진짜인지 알 수 없게 된다.
    auto_closed = Column(Boolean, nullable=False, default=False)
    # 관리자가 손으로 고쳤으면 누가 고쳤는지 남긴다.
    edited_by = Column(Integer, ForeignKey("work_users.id"), nullable=True)
    edited_at = Column(DateTime, nullable=True)
    # 기록 시점의 접속 흔적. 나중에 "정말 사무실에서 썼나"를 따질 근거가 된다.
    ip = Column(String(45), default="")
    user_agent = Column(String(200), default="")


class WorkTask(Base):
    """관리자가 직원에게 내리는 업무 지시."""

    __tablename__ = "work_tasks"

    id = Column(Integer, primary_key=True)
    title = Column(String(160), nullable=False)
    body = Column(Text, default="")

    assignee_id = Column(Integer, ForeignKey("work_users.id"), nullable=False, index=True)
    created_by = Column(Integer, ForeignKey("work_users.id"), nullable=True)

    # todo(할 일) / doing(진행 중) / done(완료) / hold(보류)
    status = Column(String(8), nullable=False, default="todo", index=True)
    # 0 보통 / 1 중요 / 2 급함
    priority = Column(Integer, nullable=False, default=0)
    due_at = Column(DateTime, nullable=True, index=True)

    # 직원이 남기는 진행 메모. 관리자가 물어보지 않아도 상황을 알 수 있게.
    progress_note = Column(String(400), default="")

    # 협업기업 요청에서 만들어진 업무면 그 요청을 가리킨다.
    request_id = Column(Integer, ForeignKey("work_requests.id"), nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    done_at = Column(DateTime, nullable=True)


class WorkRequest(Base):
    """협업기업이 올리는 요청사항·지시사항. 관리자가 받아서 처리한다."""

    __tablename__ = "work_requests"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("work_orgs.id"), nullable=False, index=True)
    created_by = Column(Integer, ForeignKey("work_users.id"), nullable=True)

    title = Column(String(160), nullable=False)
    body = Column(Text, default="")
    # 0 보통 / 1 중요 / 2 급함
    priority = Column(Integer, nullable=False, default=0)

    # new(미확인) / reading(확인함) / answered(답변함) / closed(종료)
    status = Column(String(10), nullable=False, default="new", index=True)
    admin_note = Column(Text, default="")          # 관리자 답변
    handled_by = Column(Integer, ForeignKey("work_users.id"), nullable=True)
    handled_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WorkVisitDaily(Base):
    """사이트별·날짜별 방문 집계. 하루 한 사이트 한 줄.

    **왜 따로 쌓나.** 방문 기록의 원본은 nginx 로그인데, 로그는 매일 회전되고
    2주쯤 지나면 지워진다. 원본만 보면 "전체" 기간을 영영 못 낸다. 그래서
    하루치를 숫자로 접어서 여기에 남긴다 — 로그가 지워져도 숫자는 남는다.

    **방문자(visitors)는 그날 안에서 중복을 뺀 사람 수**다. 여러 날을 합칠 때는
    날마다의 방문자를 더한다(월요일에도 오고 화요일에도 온 사람은 두 번 센다).
    기간 전체에서 중복을 빼려면 사람마다 흔적을 계속 들고 있어야 하는데,
    그러면 개인을 추적하는 기록이 된다. 그건 안 하기로 한다.
    """

    __tablename__ = "work_visit_daily"
    __table_args__ = (
        UniqueConstraint("site", "day", name="uq_work_visit_daily"),
    )

    id = Column(Integer, primary_key=True)
    site = Column(String(40), nullable=False, index=True)
    day = Column(Date, nullable=False, index=True)          # 한국 날짜

    visitors = Column(Integer, nullable=False, default=0)   # 그날 중복 뺀 사람 수
    pageviews = Column(Integer, nullable=False, default=0)  # 페이지를 연 횟수
    peak_5m = Column(Integer, nullable=False, default=0)    # 5분 동안 가장 많이 몰린 사람 수
    bot_hits = Column(Integer, nullable=False, default=0)   # 검색엔진·자동화 요청
    # 요청은 했지만 페이지를 실제로 연 흔적이 없어 뺀 사람(스캐너 등)
    excluded = Column(Integer, nullable=False, default=0)
    # 어느 규칙으로 센 숫자인가. 규칙이 바뀌면 다시 센 값으로 덮기 위해 남긴다.
    rule = Column(Integer, nullable=False, default=1)

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WorkSetting(Base):
    """관리자가 화면에서 바꾸는 설정 값. 배분 비율·인센티브 조건 같은 것."""

    __tablename__ = "work_settings"

    key = Column(String(60), primary_key=True)
    value = Column(Text, default="")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WorkLedgerEntry(Base):
    """결제 기록에 안 잡히는 매출·환불을 관리자가 직접 적는 줄.

    계좌이체 계약, 결제 칸이 없는 환불, 잘못 잡힌 금액 바로잡기 같은 것.
    금액은 늘 양수로 적고, 매출인지 환불인지는 kind 로 가른다 — 음수를 섞으면
    화면에서 부호 하나 잘못 읽는 순간 돈 계산이 뒤집힌다.
    """

    __tablename__ = "work_ledger_entries"

    id = Column(Integer, primary_key=True)
    month = Column(String(7), nullable=False, index=True)     # "2026-09"
    day = Column(Date, nullable=True)                          # 실제 발생일(참고)
    site = Column(String(40), nullable=False, default="기타")
    kind = Column(String(8), nullable=False, default="sale")   # sale / refund
    # 결제 유형(settlement.PAYMENT_TYPES). 예전 줄은 기타로 본다.
    payment_type = Column(String(12), nullable=False, default="other")
    amount = Column(Integer, nullable=False, default=0)        # 원, 양수
    memo = Column(String(200), default="")
    created_by = Column(Integer, ForeignKey("work_users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class WorkSettlement(Base):
    """마감한 달의 정산표. 마감하면 그 순간의 계산을 통째로 얼려 둔다.

    **왜 얼리나.** 마감 뒤에도 결제 기록은 바뀔 수 있다(늦게 확인된 입금, 설정
    비율 변경). 이미 돈을 보낸 달의 숫자가 나중에 저절로 바뀌면 무엇을 근거로
    보냈는지 알 수 없게 된다. 그래서 마감한 달은 저장해 둔 표만 보여 준다.
    """

    __tablename__ = "work_settlements"

    id = Column(Integer, primary_key=True)
    month = Column(String(7), nullable=False, unique=True, index=True)
    data = Column(Text, nullable=False)                 # 계산 결과 JSON
    paid = Column(Text, default="{}")                   # 지급 완료 표시 JSON
    locked_by = Column(Integer, ForeignKey("work_users.id"), nullable=True)
    locked_at = Column(DateTime, default=datetime.utcnow)


class WorkPayProfile(Base):
    """직원별 급여 기본값. 매달 명세서를 만들 때 여기서 채워 온다."""

    __tablename__ = "work_pay_profiles"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("work_users.id"), nullable=False, unique=True, index=True)
    # employee(근로자: 4대보험·근로소득세) / freelancer(사업소득 3.3%)
    employment = Column(String(12), nullable=False, default="employee")
    # 시급제. 기본급은 출퇴근 기록의 근무시간 × 시급으로 매달 계산한다.
    hourly_wage = Column(Integer, nullable=False, default=0)       # 시급(원)
    meal_allowance = Column(Integer, nullable=False, default=0)    # 식대(비과세 한도까지)
    fixed_allowance = Column(Integer, nullable=False, default=0)   # 고정 수당(과세)
    fixed_allowance_name = Column(String(30), default="직책수당")
    employee_no = Column(String(30), default="")                  # 사번(명세서 식별용)
    department = Column(String(40), default="")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WorkPayslip(Base):
    """한 사람의 한 달 급여 명세.

    정산을 완료하기 전에는 초안(draft)이라 출퇴근 기록·기본값·인센티브가 바뀌면
    따라 바뀐다.
    **정산 완료를 누르는 순간 확정(final)되어 더는 바뀌지 않는다** — 직원에게
    교부한 명세서가 나중에 저절로 달라지면 안 되기 때문이다.
    """

    __tablename__ = "work_payslips"
    __table_args__ = (UniqueConstraint("user_id", "month", name="uq_work_payslip"),)

    id = Column(Integer, primary_key=True)
    month = Column(String(7), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("work_users.id"), nullable=True, index=True)
    name = Column(String(40), nullable=False, default="")       # 계정이 지워져도 남게 복사
    employment = Column(String(12), nullable=False, default="employee")

    # 명세서의 나머지(기본급·주휴·인센티브)는 출퇴근 기록과 정산에서 매번 계산한다.
    # 여기에는 **관리자가 그 달에만 넣은 값**만 둔다.
    extras = Column(Text, default="[]")       # 그 달 추가 지급·조정 항목 JSON
    income_tax = Column(Integer, nullable=False, default=0)   # 근로소득세(관리자 입력)
    overrides = Column(Text, default="{}")    # 자동 공제를 손으로 바꾼 값
    note = Column(String(300), default="")

    # 확정 시점의 계산 결과 전체(명세서 그대로)
    snapshot = Column(Text, nullable=True)
    status = Column(String(8), nullable=False, default="draft", index=True)   # draft / final
    finalized_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
