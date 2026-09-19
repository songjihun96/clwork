"""기록해 자체 데이터 모델.

계정의 원본은 UDJ 다. 이곳의 User 는 그 사본이며, 로그인할 때마다 UDJ 에서
받은 값으로 갱신된다. 비밀번호 해시는 두지 않는다 — 한 곳에만 있어야
비밀번호를 바꿨을 때 어긋나지 않는다.
"""

import enum
from datetime import date, datetime

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Enum, ForeignKey, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .database import Base


class Role(str, enum.Enum):
    student = "student"
    teacher = "teacher"
    school = "school"
    admin = "admin"


class OrderStatus(str, enum.Enum):
    pending = "pending"
    paid = "paid"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"


ORDER_STATUS_LABEL = {
    "pending": "입금 대기",
    "paid": "입금 확인",
    "approved": "승인 완료",
    "rejected": "거절·환불",
    "expired": "기간 만료",
}


class User(Base):
    """UDJ 계정의 사본.

    udj_user_id 가 진짜 식별자다. 이메일은 바뀔 수 있으므로 기준으로 삼지 않는다.
    소속(학교·담당 교사·학급)은 로그인할 때마다 새로 받아 덮어쓴다. 그래야 UDJ
    에서 재학생 인증을 받거나 학년이 바뀌어도 여기 자동으로 반영된다.
    """

    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    udj_user_id = Column(Integer, unique=True, nullable=False, index=True)
    email = Column(String(120), nullable=False, index=True)
    name = Column(String(60), default="")
    role = Column(Enum(Role), nullable=False, default=Role.student)

    # UDJ 에서 받아오는 소속 정보
    school_id = Column(Integer, nullable=True, index=True)     # UDJ 의 학교 ID
    school_name = Column(String(120), default="")
    department = Column(String(60), default="")
    grade = Column(Integer, nullable=True)
    verified = Column(Boolean, default=False)                  # 재학생 인증 완료 여부
    teacher_udj_id = Column(Integer, nullable=True, index=True)  # 담당 교사(UDJ ID)
    class_name = Column(String(40), default="")

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login_at = Column(DateTime, nullable=True)

    def apply_profile(self, p: dict) -> None:
        """UDJ 가 준 프로필로 갱신한다.

        학년·반·학과는 조심해서 다룬다. 학생이 이용권 코드를 넣으면
        코드를 만든 선생님의 반으로 옮겨 담는데, 여기서 UDJ 값으로
        덮어쓰면 다음 로그인 때 되돌아간다.

        그래서 UDJ 가 값을 준 경우에만 바꾼다. UDJ 에 그 정보가 없으면
        (직업계고는 대개 없다) 기록해에서 정한 것을 그대로 둔다.
        """
        self.email = (p.get("email") or "")[:120]
        self.name = (p.get("name") or "")[:60]
        self.role = Role(p.get("role") or "student")
        self.school_id = p.get("school_id")
        self.school_name = (p.get("school_name") or "")[:120]
        self.verified = bool(p.get("verified"))
        self.teacher_udj_id = p.get("teacher_udj_id")
        self.is_active = bool(p.get("is_active", True))

        if p.get("department"):
            self.department = p["department"][:60]
        if p.get("grade") is not None:
            self.grade = p["grade"]
        if p.get("class_name"):
            self.class_name = p["class_name"][:40]


class JournalEntry(Base):
    """학교생활 일기 · 수업 일지."""

    __tablename__ = "journal_entries"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    kind = Column(String(20), nullable=False, default="diary")   # diary / lesson
    entry_date = Column(Date, nullable=False, index=True)
    title = Column(String(120), default="")          # 예전 글은 비어 있을 수 있다
    subject = Column(String(80), default="")        # 수업 일지의 교과명(자유문자열, 예전 글 호환)
    # lesson 일지가 가리키는 과목. 세특을 과목별로 완전히 분리하는 열쇠다.
    # 예전 글은 비어 있어 subject 문자열만으로 화면에 보인다.
    subject_id = Column(Integer, ForeignKey("school_subjects.id"), nullable=True)
    teacher_name = Column(String(60), default="")
    content = Column(Text, default="{}")            # {항목키: 본문} JSON
    # 제출한 시점. 값이 있으면 선생님이 볼 수 있다.
    sent_at = Column(DateTime, nullable=True, index=True)
    share_token = Column(String(64), unique=True, index=True, nullable=True)

    # 선생님이 남긴 한마디. 학생 화면에 그대로 보인다.
    # 누가 썼는지 이름을 값으로 복사해 두는 이유는, 그 선생님 계정이 나중에
    # 사라지거나 학교를 옮겨도 학생에게는 계속 보여야 하기 때문이다.
    feedback = Column(Text, default="")
    feedback_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    feedback_by_name = Column(String(60), default="")
    feedback_at = Column(DateTime, nullable=True)
    # 학생이 피드백을 확인한 시점. 선생님 화면에서 읽었는지 알 수 있다.
    feedback_read_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", foreign_keys=[user_id])


class CoverLetter(Base):
    """개인 자기소개서. 구독한 이용자만 만들 수 있다."""

    __tablename__ = "cover_letters"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(120), default="")
    content = Column(Text, default="{}")            # {항목키: 본문} JSON
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User")


class Subscription(Base):
    """개인 구독. 학교 제출용 일지는 무료, 자기소개서만 구독 대상이다."""

    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False, index=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User")


class SubscriptionOrder(Base):
    """구독 결제 주문."""

    __tablename__ = "subscription_orders"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    # 계정이 지워져도 정산 근거가 남도록 값으로 복사해 둔다.
    user_email = Column(String(120), default="")
    months = Column(Integer, nullable=False, default=1)
    amount = Column(Integer, nullable=False, default=0)
    status = Column(Enum(OrderStatus), nullable=False, default=OrderStatus.pending)

    deposit_code = Column(String(30), default="", index=True)
    # 실제로 입금할 사람 이름. 통장에 찍히는 이름과 신청자 이름이 다른 경우가
    # 많아(부모님이 대신 넣는 등) 미리 받아두면 대조가 훨씬 쉬워진다.
    depositor_name = Column(String(40), default="")
    # 이 주문에 안내한 입금 계좌. 계좌를 여러 개 쓸 때 어디로 오기로 했는지 남긴다.
    # 실제로 다른 계좌에 들어와도 확인은 되지만, 안내한 곳을 알아야 대조가 쉽다.
    bank_key = Column(String(20), default="")
    order_uid = Column(String(64), unique=True, index=True, nullable=True)
    payment_key = Column(String(200), default="")
    pay_method = Column(String(30), default="")
    receipt_url = Column(String(300), default="")
    refunded_at = Column(DateTime, nullable=True)
    # 실제로 돌려준 금액과 사유. 부분 환불이 있으므로 amount 와 별도로 남긴다.
    refund_amount = Column(Integer, default=0)
    refund_reason = Column(String(200), default="")
    # 계좌이체로 받은 건은 사람이 직접 돌려줘야 한다. 어디로 보낼지 받아둔다.
    refund_bank = Column(String(40), default="")
    refund_account = Column(String(60), default="")
    refund_holder = Column(String(40), default="")
    # 실제로 송금을 마친 시점. 이 값이 있어야 환불이 끝난 것이다.
    refund_paid_at = Column(DateTime, nullable=True)
    # 환불을 거절한 경우. 부정 이용이나 약관 위반 같은 제한 사유에만 쓴다.
    # 7일 이내 청약철회는 법이 준 권리라 거절할 수 없다.
    refund_denied_at = Column(DateTime, nullable=True)
    refund_denied_reason = Column(String(300), default="")
    # 계좌가 틀려 송금하지 못했을 때. 이용자가 고칠 때까지 남는다.
    refund_account_issue = Column(String(200), default="")
    # 환불을 거절한 경우. 부정 이용이나 약관 위반에만 쓴다.
    # 7일 이내 청약철회는 법이 준 권리라 거절할 수 없다.
    refund_denied_at = Column(DateTime, nullable=True)
    refund_denied_reason = Column(String(300), default="")

    # 미성년자 결제 보호(민법 제5조)
    minor_consent = Column(Boolean, default=False)
    guardian_contact = Column(String(120), default="")

    note = Column(String(200), default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    due_at = Column(DateTime, nullable=True)
    paid_at = Column(DateTime, nullable=True)
    handled_at = Column(DateTime, nullable=True)

    user = relationship("User")


class SchoolSubject(Base):
    """학교·학과·학년별 개설 과목. UDJ 에서 수집한 결과를 복사해 둔다."""

    __tablename__ = "school_subjects"
    __table_args__ = (
        UniqueConstraint("school_id", "department", "grade", "name",
                         name="uq_diary_school_subject"),
    )

    id = Column(Integer, primary_key=True)
    school_id = Column(Integer, nullable=False, index=True)   # UDJ 의 학교 ID
    department = Column(String(60), default="")
    grade = Column(Integer, nullable=True)
    name = Column(String(80), nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AuditLog(Base):
    """관리자·학교 계정의 활동 기록.

    학생 일기는 민감한 개인정보다. 담당 교사가 아닌 계정의 열람은 누가 무엇을
    보았는지 남겨야 한다. 안전성 확보조치 기준 제8조에 따라 1년 보관한다.
    """

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    actor_email = Column(String(120), default="")
    actor_role = Column(String(20), default="")
    action = Column(String(60), nullable=False, index=True)
    target_type = Column(String(40), default="")
    target_id = Column(String(40), default="")
    detail = Column(String(300), default="")
    ip = Column(String(45), default="")
    user_agent = Column(String(200), default="")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class Setting(Base):
    """운영 설정(구독 가격, 계좌 정보 등)."""

    __tablename__ = "settings"

    key = Column(String(60), primary_key=True)
    value = Column(Text, default="")


class UnmatchedDeposit(Base):
    """어느 주문에도 붙지 않은 입금 내역.

    계좌를 여러 개 쓰면 안내한 곳이 아닌 계좌로 들어오는 일이 생긴다.
    금액이 틀렸거나, 아예 모르는 입금일 수도 있다. 그런 것들을 계좌를 가리지
    않고 한곳에 모아 두고 사람이 판단한다.

    같은 내역을 두 번 붙여넣어도 쌓이지 않도록 지문(fingerprint)으로 막는다.
    """

    __tablename__ = "unmatched_deposits"

    id = Column(Integer, primary_key=True)
    # 계좌 + 원문 줄의 해시. 중복 등록을 막는 열쇠다.
    fingerprint = Column(String(64), unique=True, index=True, nullable=False)
    bank_key = Column(String(20), default="")     # 어느 계좌 내역에서 나왔는지
    line = Column(String(200), default="")        # 붙여넣은 원문 그대로
    amount = Column(Integer, default=0)
    name = Column(String(40), default="")
    reason = Column(String(120), default="")      # 왜 못 붙였는지
    status = Column(String(12), default="open")   # open/linked/ignored
    linked_order_id = Column(Integer, nullable=True)
    note = Column(String(200), default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)


class SchoolSeat(Base):
    """학교가 사 둔 좌석.

    결제 주체가 학생에서 학교로 바뀌었다. 학교가 인원수를 정해 결제하면
    그만큼의 좌석이 생기고, 학교가 학생에게 나눠준다.

    학년별로 파는 구조라 한 학교가 여러 번 살 수 있다. 그때는 좌석 수를
    더하고 기간을 뒤로 민다.

    상품(product)마다 별도 풀이다 — 자기소개서 좌석과 연구 좌석은 서로 다른
    풀이라, 학교가 하나만 사거나 둘 다 살 수 있다. 기존 행은 전부
    "essay"(자기소개서)로 채워져 있다(연구 좌석 개념이 나오기 전에는 이것
    하나뿐이었으므로).
    """

    __tablename__ = "school_seats"
    __table_args__ = (
        UniqueConstraint("school_id", "product", name="uq_school_seat_product"),
    )

    id = Column(Integer, primary_key=True)
    school_id = Column(Integer, nullable=False, index=True)
    product = Column(String(20), nullable=False, default="essay", index=True)  # essay/research
    seats = Column(Integer, nullable=False, default=0)
    started_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SeatHolder(Base):
    """좌석을 받은 학생.

    학교가 산 좌석을 누구에게 줄지는 학교가 정한다. 좌석 수보다 많이
    줄 수 없고, 회수하면 다른 학생에게 넘길 수 있다.
    """

    __tablename__ = "seat_holders"
    __table_args__ = (
        UniqueConstraint("school_id", "user_id", "product", name="uq_seat_once"),
    )

    id = Column(Integer, primary_key=True)
    school_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    product = Column(String(20), nullable=False, default="essay", index=True)  # essay/research
    granted_at = Column(DateTime, default=datetime.utcnow)
    granted_by = Column(Integer, nullable=True)

    user = relationship("User")


class SeatOrder(Base):
    """학교가 넣은 좌석 주문.

    학교가 인원수를 적어 신청하면, 관리자가 실제 인원을 확인한 뒤 승인한다.
    확인 과정에서 인원이 달라질 수 있어 신청 인원과 확정 인원을 따로 둔다.
    """

    __tablename__ = "seat_orders"

    id = Column(Integer, primary_key=True)
    school_id = Column(Integer, nullable=False, index=True)
    school_name = Column(String(120), default="")
    product = Column(String(20), nullable=False, default="essay", index=True)  # essay/research
    requested_by = Column(Integer, nullable=True)      # 신청한 학교 계정
    requester_email = Column(String(255), default="")

    seats = Column(Integer, nullable=False)            # 학교가 적은 인원
    approved_seats = Column(Integer, nullable=True)    # 관리자가 확인한 인원
    unit_price = Column(Integer, nullable=False)       # 1명당 금액
    discount_percent = Column(Integer, default=0)      # 인원 구간 할인율(%)
    months = Column(Integer, nullable=False, default=12)
    amount = Column(Integer, nullable=False)           # 인원 x 단가

    note = Column(String(300), default="")             # 학년 등 메모
    status = Column(Enum(OrderStatus), nullable=False, default=OrderStatus.pending)
    deposit_code = Column(String(30), default="", index=True)
    depositor_name = Column(String(40), default="")
    bank_key = Column(String(20), default="")

    created_at = Column(DateTime, default=datetime.utcnow)
    due_at = Column(DateTime, nullable=True)
    paid_at = Column(DateTime, nullable=True)
    handled_at = Column(DateTime, nullable=True)
    admin_note = Column(String(300), default="")


class SeatCode(Base):
    """학교가 학생에게 나눠주는 등록 코드.

    학생 목록에서 한 명씩 체크하는 것은 200명이 넘어가면 쓸 수 없다.
    학교가 코드를 만들어 종이나 안내문으로 나눠주고, 학생이 직접 입력해
    좌석을 받게 한다.

    코드마다 쓸 수 있는 횟수를 정한다. 학급별로 다른 코드를 만들면
    누가 어디서 등록했는지도 구분된다.
    """

    __tablename__ = "seat_codes"

    id = Column(Integer, primary_key=True)
    school_id = Column(Integer, nullable=False, index=True)
    code = Column(String(20), nullable=False, unique=True, index=True)
    product = Column(String(20), nullable=False, default="essay", index=True)  # essay/research
    label = Column(String(60), default="")        # 2학년 3반 등

    # 코드를 만든 선생님의 학년·반·학과. 학생이 이 코드를 넣으면
    # 그대로 옮겨 담는다.
    #
    # 예전에는 학생이 직접 골랐다. 그러면 오타가 나고, 반을 잘못 고르면
    # 담당 선생님과 이어지지 않는다. 코드에 딸려 오게 하면 그 문제가
    # 사라진다. 코드를 만든 사람이 곧 그 반의 담당이기 때문이다.
    grade = Column(Integer, nullable=True)
    class_no = Column(String(20), default="")     # 3반
    department = Column(String(60), default="")   # 기계과

    max_uses = Column(Integer, nullable=False, default=1)
    used_count = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, default=True)
    expires_at = Column(DateTime, nullable=True)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AiConsent(Base):
    """AI 기능 이용 동의.

    학생이 쓴 글이 분석을 위해 외부로 나간다. 개인정보 보호법상
    국외 이전은 별도 동의를 받아야 하고, 개인정보처리방침 제7조에도
    "이용자가 별도로 동의하고 직접 요청한 경우에만" 이라고 적어 두었다.

    철회한 기록도 남긴다. 언제 동의했고 언제 거뒀는지 확인할 수 있어야
    나중에 다툼이 생겼을 때 근거가 된다.
    """

    __tablename__ = "ai_consents"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False,
                     unique=True, index=True)
    agreed = Column(Boolean, default=False)
    # 동의를 받을 때 보여준 방침의 시행일. 방침이 바뀌면 다시 받아야 한다.
    policy_date = Column(String(20), default="")
    agreed_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User")


class JournalAnalysis(Base):
    """일지를 AI 로 분석한 결과.

    같은 일지를 다시 분석하지 않으려고 남긴다. 부를 때마다 돈이 나가고
    시간도 걸리므로, 글이 바뀌지 않았으면 저장해 둔 것을 그대로 쓴다.

    글이 바뀌었는지는 내용의 지문(SHA-256)으로 가린다. 원문 자체는
    여기에 두지 않는다. 원문은 JournalEntry 에만 있고, 이 표는
    분석 결과만 갖는다.
    """

    __tablename__ = "journal_analyses"
    __table_args__ = (
        UniqueConstraint("journal_id", "content_hash", name="uq_analysis_once"),
    )

    id = Column(Integer, primary_key=True)
    journal_id = Column(Integer, ForeignKey("journal_entries.id"),
                        nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    # 분석할 때의 글 지문. 글이 바뀌면 값이 달라져 다시 분석하게 된다.
    content_hash = Column(String(64), nullable=False, index=True)
    model_name = Column(String(60), default="")

    cleaned_content = Column(Text, default="")     # 다듬은 글
    analysis_json = Column(Text, default="{}")     # 경험·역량·키워드

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AiJob(Base):
    """AI 작업 하나.

    AI 는 몇 초에서 수십 초가 걸린다. 그동안 웹 요청을 붙들고 있으면
    gunicorn 워커가 묶여, 자소서와 상관없는 다른 학생의 일지 저장까지
    멈춘다. 그래서 요청을 여기 적어 두고 바로 응답한 뒤,
    뒤에서 하나씩 처리한다.
    """

    __tablename__ = "ai_jobs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    kind = Column(String(30), nullable=False)      # analyze / generate / verify / ...
    status = Column(String(20), default="queued", index=True)
    # queued(기다리는 중) → running(도는 중) → done(끝) / failed(실패)

    # 같은 요청을 연타해도 작업이 중복 생기지 않게 막는 열쇠(kind+무엇에
    # 대한 것인지). main.py가 enqueue 전에 이 값으로 진행 중인 작업이
    # 있는지 먼저 찾는다.
    dedup_key = Column(String(200), nullable=True, index=True)

    payload_json = Column(Text, default="{}")      # 무엇을 처리할지
    result_json = Column(Text, default="{}")       # 결과
    error = Column(String(300), default="")        # 화면에 보여줄 말

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)


class TeacherSubjectAssignment(Base):
    """교사가 담당하는 과목.

    담당 학급(User.class_name, 담임 한 명)과는 별개 개념이다. 한 교사가
    여러 과목을 가르칠 수 있어 여러 행을 가질 수 있다. 세특을 만들 때
    이 표에 없는 과목의 기록은 절대 쓰지 않는다.
    """

    __tablename__ = "teacher_subject_assignments"
    __table_args__ = (
        UniqueConstraint("teacher_id", "subject_id", name="uq_teacher_subject"),
    )

    id = Column(Integer, primary_key=True)
    teacher_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    school_id = Column(Integer, nullable=False, index=True)
    subject_id = Column(Integer, ForeignKey("school_subjects.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    teacher = relationship("User")
    subject = relationship("SchoolSubject")


class StudentEnrollment(Base):
    """학년도별 학생 소속(학년·반·번호·학과).

    User 의 grade/class_name/department 는 "지금" 스냅샷이라 학년이
    바뀌면 지난 기록의 소속도 함께 바뀐 것처럼 보인다. 학년도를 못박아
    이력을 남기면 지난 학년도 기록은 그대로 남는다.

    student_no 가 비어 있는 행(과거 호환용으로 좌석코드만 쓰고 번호는
    안 정한 경우)은 유일성 제약에서 자동으로 빠진다 — NULL 은 서로
    다른 값으로 취급되는 표준 SQL 규칙을 그대로 이용한다.
    """

    __tablename__ = "student_enrollments"
    __table_args__ = (
        UniqueConstraint("school_id", "academic_year", "grade", "class_no",
                         "student_no", name="uq_enrollment_seat"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    school_id = Column(Integer, nullable=False, index=True)
    academic_year = Column(Integer, nullable=False)
    grade = Column(Integer, nullable=True)
    class_no = Column(String(20), default="")
    student_no = Column(Integer, nullable=True)
    department = Column(String(60), default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User")


class StudentRecordAiDraft(Base):
    """AI 세특·행동특성 초안.

    AI 는 확정하지 않는다. 만든 결과는 항상 draft 로 저장되고, 교사가
    검토·수정한 뒤 confirmed 로 바꿔야 생기부에 쓸 수 있는 상태가 된다.

    이미 confirmed 된 행이 있는데 다시 생성을 누르면, 그 행을 덮어쓰지
    않고 새 draft 행을 추가한다. 확정본은 교사가 스스로 지우기 전까지
    항상 남아 있어야 한다.
    """

    __tablename__ = "student_record_ai_drafts"

    id = Column(Integer, primary_key=True)
    school_id = Column(Integer, nullable=False, index=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    teacher_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    type = Column(String(30), nullable=False)   # subject_special_note / behavioral_characteristics
    subject_id = Column(Integer, ForeignKey("school_subjects.id"), nullable=True)

    content = Column(Text, default="")          # 교사가 고칠 수 있는 현재 본문
    ai_original = Column(Text, default="")      # AI 가 처음 만든 원문(비교용, 고치지 않음)
    source_journal_ids = Column(Text, default="[]")   # 근거로 쓴 일지/관찰 기록 id 목록(JSON)
    source_kind = Column(String(20), default="journal")  # journal(수업일지) / observation(누가기록)
    status = Column(String(12), default="draft", index=True)  # draft/reviewed/confirmed
    model_name = Column(String(60), default="")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    confirmed_at = Column(DateTime, nullable=True)

    student = relationship("User", foreign_keys=[student_id])
    teacher = relationship("User", foreign_keys=[teacher_id])
    subject = relationship("SchoolSubject")


class TeacherObservation(Base):
    """교사 관찰 기록.

    NEIS 누가기록이나 학교생활기록부를 대신하는 기능이 아니다 — 수업·학교
    생활에서 교사가 직접 관찰한 내용을 날짜별로 개인적으로 쌓아 두는,
    이 서비스만의 독립적인 기록이다. 세특·행동특성 문장을 이걸로 자동
    생성하는 기능도 만들지 않는다.

    JournalEntry.feedback("선생님 한마디")와는 완전히 다른 것이다 — feedback은
    학생에게 보이라고 남기는 것이고, 이것은 그 반대로 교사 본인만 보는
    비공개 기록이다. 학생 포트폴리오 생성에도 이 데이터는 절대 쓰지
    않는다(학생 원본 기록만 근거로 삼는다). 특정 일지에 달 수도, 학생
    전체에 대한 기록으로 남길 수도 있다. 작성한 교사 본인 외에는(다른
    교사·학교·관리자·학생 누구도) API 단에서 절대 조회할 수 없다 — UI에서
    숨기는 것으로 끝내지 않는다.
    """

    __tablename__ = "teacher_observations"

    id = Column(Integer, primary_key=True)
    teacher_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    journal_id = Column(Integer, ForeignKey("journal_entries.id"), nullable=True, index=True)
    subject_id = Column(Integer, ForeignKey("school_subjects.id"), nullable=True)
    # 관찰이 실제로 있었던 날짜. 입력한 시점(created_at)과 다를 수 있다
    # (예: 지난주 관찰한 것을 오늘 정리해 적는 경우).
    observed_at = Column(Date, nullable=False, default=date.today)
    title = Column(String(120), default="")
    content = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    subject = relationship("SchoolSubject")


class TeacherObservationTemplate(Base):
    """교사가 자주 쓰는 관찰 문구를 저장해 둔 것.

    관찰 기록을 쓸 때 눌러서 바로 넣는 초안일 뿐이다 — AI가 학생 행동을
    지어내는 기능이 아니라, 교사가 미리 등록해 둔 정해진 문구를 다시
    꺼내 쓰는 것뿐이다. 작성한 교사 본인에게만 보인다.
    """

    __tablename__ = "teacher_observation_templates"

    id = Column(Integer, primary_key=True)
    teacher_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(60), nullable=False)
    content = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Portfolio(Base):
    """학생 포트폴리오 한 편.

    학교생활 기록을 취업·진학용으로 재구성한 결과물이다. 원본 JournalEntry는
    여기서 절대 고치지 않는다 — 편집한 내용은 전부 PortfolioBlock 쪽에
    따로 쌓인다(원본과 편집본을 분리해야 나중에 "이 내용의 근거"를 보여줄
    수 있고, 학생이 마음대로 고쳐도 원래 일지는 안전하다).
    """

    __tablename__ = "portfolios"

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(120), default="")
    description = Column(Text, default="")
    purpose = Column(String(20), default="free")        # growth/university/employment/interview/school_life/free
    theme_type = Column(String(30), default="custom")
    career_goal = Column(String(120), default="")
    cover_image_id = Column(Integer, ForeignKey("portfolio_images.id"), nullable=True)
    visibility = Column(String(10), default="private")   # private/shared
    status = Column(String(10), default="draft")         # draft/published
    share_token = Column(String(64), unique=True, index=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    student = relationship("User")


class PortfolioPage(Base):
    """포트폴리오 안의 페이지 한 장(표지, 프로젝트 소개 등)."""

    __tablename__ = "portfolio_pages"

    id = Column(Integer, primary_key=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False, index=True)
    title = Column(String(120), default="")
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PortfolioBlock(Base):
    """페이지 안의 블록 하나(제목·글·사진·타임라인 등).

    content_json/style_json 은 block_type 마다 모양이 다른 자유 JSON이다.
    허용된 block_type 이 아니면 main.py 가 저장을 거부한다.
    """

    __tablename__ = "portfolio_blocks"

    id = Column(Integer, primary_key=True)
    page_id = Column(Integer, ForeignKey("portfolio_pages.id"), nullable=False, index=True)
    block_type = Column(String(20), nullable=False)
    sort_order = Column(Integer, default=0)
    content_json = Column(Text, default="{}")
    style_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PortfolioImage(Base):
    """포트폴리오에 올린 사진 한 장.

    원본은 그대로 두고, 화면에 빠르게 보여줄 웹 최적화본과 목록용
    썸네일을 함께 만들어 둔다. storage_key 들은 로컬 디스크 상의
    상대 경로이며, 실제 파일은 /api/portfolio-images/{id}(?variant=) 로
    스트리밍한다 — 정적 파일 서버를 직접 노출하지 않아야 다른 학생의
    사진 id를 추측해 접근하는 것을 막을 수 있다(스트리밍 엔드포인트에서
    소유자를 확인한다).
    """

    __tablename__ = "portfolio_images"

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=True, index=True)
    page_id = Column(Integer, ForeignKey("portfolio_pages.id"), nullable=True)
    block_id = Column(Integer, ForeignKey("portfolio_blocks.id"), nullable=True)
    storage_key = Column(String(200), nullable=False)
    web_key = Column(String(200), default="")
    thumbnail_key = Column(String(200), default="")
    title = Column(String(120), default="")
    caption = Column(Text, default="")
    sort_order = Column(Integer, default=0)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PortfolioSource(Base):
    """포트폴리오(또는 그 페이지·블록)가 어느 원본 기록에서 나왔는지.

    "이 내용의 근거 보기" 기능을 위한 것이다. AI가 만든 내용일 때
    반드시 채워 넣어, 학생이 원본 일지로 되짚어 갈 수 있게 한다.
    """

    __tablename__ = "portfolio_sources"

    id = Column(Integer, primary_key=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False, index=True)
    page_id = Column(Integer, ForeignKey("portfolio_pages.id"), nullable=True)
    block_id = Column(Integer, ForeignKey("portfolio_blocks.id"), nullable=True)
    journal_id = Column(Integer, ForeignKey("journal_entries.id"), nullable=True)
    experience_id = Column(Integer, ForeignKey("experiences.id"), nullable=True)
    source_type = Column(String(20), default="journal")
    created_at = Column(DateTime, default=datetime.utcnow)


class Experience(Base):
    """학생 기록에서 추출한 경험 한 건(문제해결/협업/성장 등).

    자소서 기능의 "경험 재료"와 같은 개념을 포트폴리오에도 쓴다.
    content_json 에 상황/문제/행동/결과/배운 점을 담는다.
    """

    __tablename__ = "experiences"

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(120), default="")
    type = Column(String(30), default="")
    summary = Column(Text, default="")
    content_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    student = relationship("User")


class ExperienceSource(Base):
    """Experience 가 어느 JournalEntry 에서 나왔는지."""

    __tablename__ = "experience_sources"

    id = Column(Integer, primary_key=True)
    experience_id = Column(Integer, ForeignKey("experiences.id"), nullable=False, index=True)
    journal_id = Column(Integer, ForeignKey("journal_entries.id"), nullable=False)


class PortfolioThemeRecommendation(Base):
    """테마 추천 결과 캐시.

    학생 기록이 그대로면 같은 추천을 반복해서 AI로 다시 만들지 않는다.
    source_snapshot 은 "추천에 쓴 재료가 그때와 같은지" 가리는 지문이다.
    """

    __tablename__ = "portfolio_theme_recommendations"

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    theme_type = Column(String(30), nullable=False)
    title = Column(String(120), default="")
    reason = Column(Text, default="")
    source_count = Column(Integer, default=0)
    score = Column(Integer, default=0)
    source_snapshot = Column(String(64), default="")
    created_at = Column(DateTime, default=datetime.utcnow)


# ── 연구 플랫폼 ──────────────────────────────────────────────
# "기록해"의 새 핵심 기능. 학생이 관심 키워드에서 출발해 AI 코치와
# 대화하며 연구 주제를 좁히고, 장기간에 걸쳐 연구를 진행한다.
# 기존 일지·포트폴리오와는 별개 데이터라 삭제하거나 뒤섞지 않는다.
























# ── 최종 논문 / 연구 포트폴리오 ────────────────────────────────
# 둘 다 같은 연구 데이터를 쓰지만 표현 방식이 다르다(§41) — 논문은 학술
# 형식, 포트폴리오는 시각적으로 읽기 쉬운 형식. AI는 원본 데이터(연구
# 질문·확인된 참고자료·실제 분석 결과·연구심사 결과)만 근거로 초안을
# 만들고, 학생이 반드시 직접 검토·수정한다.







# ── 공동 연구(팀) ────────────────────────────────────────────
# 기존 ResearchProject 는 손대지 않는다. "이 연구가 팀 연구인가"는
# ResearchTeam 행이 있는지로만 판단한다 — 개인 연구 51개 엔드포인트가
# 전부 그대로 동작하게 하기 위해서다(main.py._own_research_or_404 참고).














# ── 외부 교사 질문 ────────────────────────────────────────────
# 담임도 같은 학교도 아닌 교사와 이어지는 완전히 별도 경로다 — 기존
# viewable_students/assert_is_homeroom 스코프를 전혀 쓰지 않는다.
# 학생↔교사 양방향으로 신원을 가린다(교사 정보는 지시서 §17이 명시한
# 요구사항이고, 학생 정보도 같은 수준으로 보호한다 — 낯선 교사에게
# 이름·학교가 노출될 이유가 없다).












