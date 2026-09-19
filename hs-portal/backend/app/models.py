import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    LargeBinary,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .database import Base


class Role(str, enum.Enum):
    student = "student"
    teacher = "teacher"   # 학교 계정이 만들어주는 선생님 계정
    school = "school"
    cs = "cs"             # 상담 직원. udjcs.ggm.kr 에서만 쓰며 권한이 제한된다.
    admin = "admin"


class Plan(str, enum.Enum):
    free = "free"
    basic = "basic"
    premium = "premium"
    platinum = "platinum"


# 플랜 등급이 높을수록 검색 결과 상단에 노출된다.
PLAN_RANK = {Plan.platinum: 3, Plan.premium: 2, Plan.basic: 1, Plan.free: 0}

# 월 단위 가격(원)
PLAN_PRICE = {Plan.free: 0, Plan.basic: 99000, Plan.premium: 249000, Plan.platinum: 499000}


class OrderStatus(str, enum.Enum):
    pending = "pending"      # 입금 대기
    paid = "paid"            # 입금 확인됨 (승인 전)
    approved = "approved"    # 승인 — 플랜 적용
    rejected = "rejected"    # 거절
    expired = "expired"      # 기한 내 미입금으로 만료

ORDER_STATUS_LABEL = {
    "pending": "입금 대기",
    "paid": "입금 확인",
    "approved": "승인 완료",
    "rejected": "거절",
    "expired": "만료",
}


class Coed(str, enum.Enum):
    coed = "남녀공학"
    boys = "남고"
    girls = "여고"


class InquiryStatus(str, enum.Enum):
    pending = "pending"  # 학교가 아직 답변하지 않음
    answered = "answered"  # 답변 완료


class DeliveryStatus(str, enum.Enum):
    """답변 이메일 발송 상태."""

    pending = "pending"  # 아직 답변 전
    sent = "sent"  # 발송 성공
    failed = "failed"  # 발송 시도했으나 실패
    not_configured = "not_configured"  # 메일 서버 미설정


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(120), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(60), nullable=False)
    role = Column(Enum(Role), nullable=False, default=Role.student)
    # role=school 인 계정만 채워진다. 관리자가 계정을 만들 때 학교를 연결한다.
    school_id = Column(Integer, ForeignKey("schools.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    # 계정 찾기(아이디 찾기)의 2차 식별 수단. 선택 입력.
    # 본인확인·계정찾기에 쓰므로 조회가 잦다. 인덱스를 둔다.
    phone = Column(String(30), default="", index=True)
    # role=teacher 인 계정의 담당 학급 (예: "2학년 3반")
    class_name = Column(String(40), default="")
    # 학생이 다니는 학과·학년. 일지의 과목 목록을 좁히는 데 쓴다.
    department = Column(String(60), default="")
    grade = Column(Integer, nullable=True)
    # 학교가 정한 초기 비밀번호를 아직 안 바꾼 상태면 True
    must_change_password = Column(Boolean, default=False)
    # 개인정보 수집·이용에 동의한 시각(동의 이력 보관).
    privacy_consent_at = Column(DateTime, nullable=True)

    # 개인정보 보호법 제22조의2(만 14세 미만 아동) 대응
    birth_date = Column(Date, nullable=True)            # 연령 확인용
    guardian_email = Column(String(120), default="")    # 만 14세 미만일 때 법정대리인 주소
    guardian_consent_at = Column(DateTime, nullable=True)  # 법정대리인 동의 시각

    created_at = Column(DateTime, default=datetime.utcnow)

    school = relationship("School", back_populates="accounts")
    favorites = relationship("Favorite", back_populates="user", cascade="all, delete-orphan")


class School(Base):
    __tablename__ = "schools"
    __table_args__ = (
        UniqueConstraint("atpt_code", "school_code", name="uq_neis_school"),
    )

    id = Column(Integer, primary_key=True)

    # --- NEIS 원본 식별자. 재수집 시 갱신 기준이 된다. ---
    atpt_code = Column(String(10), nullable=True, index=True)  # 시도교육청코드
    school_code = Column(String(20), nullable=True, index=True)  # 표준학교코드

    # --- 검색 목록에 항상 노출되는 기본 정보 ---
    name = Column(String(80), nullable=False, index=True)
    # 정식 명칭 말고 실제로 통용되는 이름. 쉼표로 구분해 여러 개 둘 수 있다.
    # (예: '경화여자English Business고등학교' → '경화EB고등학교,경화여자EB고')
    # 이름 검색은 정식 명칭과 이 값을 함께 본다.
    search_aliases = Column(String(300), default="")
    category = Column(String(30), nullable=False, index=True)  # 특성화고, 마이스터고, 과학고 ...
    region = Column(String(20), nullable=False, index=True)  # 서울, 경기 ...
    address = Column(String(200), nullable=False)
    coed = Column(Enum(Coed), nullable=False, default=Coed.coed)
    # NEIS에 기숙사 항목이 없다. None = 미확인, 학교 계정이 직접 채운다.
    dormitory = Column(Boolean, nullable=True, default=None)
    foundation = Column(String(10), default="")  # 공립 / 사립
    phone = Column(String(30), nullable=False, default="")
    website = Column(String(200), default="")
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    # --- 학교 계정이 직접 채우는 상세 정보 ---
    slogan = Column(String(120), default="")
    intro = Column(Text, default="")
    departments = Column(Text, default="")  # 줄바꿈으로 구분된 학과 목록
    # departments 를 계열로 분류해 캐시한 값. ",it,design," 형태로 저장한다.
    # 검색에서 LIKE 로 걸러쓰며, 학과가 바뀔 때마다 다시 계산한다.
    dept_fields = Column(String(200), default="", index=True)
    facilities = Column(Text, default="")
    admission_info = Column(Text, default="")   # 화면 표기: '학교 상세 안내'
    # 학교 소개 영상(유튜브) 주소. 줄바꿈으로 구분해 최대 4개까지 담는다.
    # departments 와 같은 방식이라 새 테이블 없이 한 칸으로 끝난다.
    youtube_urls = Column(Text, default="")

    # 문의가 들어왔을 때 알림을 받을 주소. 로그인 계정 메일과 일부러 따로 둔다
    # — 로그인은 학교 대표 계정으로 하고 알림은 담당 선생님이 받는 경우가
    # 대부분이다. 비어 있으면 알림을 보내지 않는다(기본 꺼짐).
    inquiry_notify_email = Column(String(120), default="")
    employment_rate = Column(Float, nullable=True)  # 취업률(%)
    student_count = Column(Integer, nullable=True)
    established_year = Column(Integer, nullable=True)
    hero_image = Column(String(300), default="")

    # --- 문의 답변을 보낼 학교 자체 메일 계정(SMTP) ---
    # 비밀번호는 평문으로 두지 않고 Fernet으로 암호화해 저장한다(mail_password_enc).
    mail_host = Column(String(120), default="")
    mail_port = Column(Integer, default=587)
    mail_username = Column(String(120), default="")
    mail_password_enc = Column(Text, default="")  # 암호화된 비밀번호
    mail_from = Column(String(120), default="")  # 보내는 주소(보통 mail_username과 동일)
    mail_ssl = Column(Boolean, default=False)  # 465(SSL)=True, 587(STARTTLS)=False

    # --- 노출/과금 ---
    plan = Column(Enum(Plan), nullable=False, default=Plan.free)
    plan_expires_at = Column(Date, nullable=True)
    # 플랜이 끝나면 무료로 되돌리면서 이 두 칸에 흔적을 남긴다. 안 남기면
    # 되돌리는 순간 "언제 무엇이 끝났는지"가 통째로 사라져서, 연장을 놓친
    # 학교를 나중에 찾아낼 방법이 없다.
    plan_expired_at = Column(Date, nullable=True)      # 끝난 날
    plan_expired_from = Column(String(20), default="")  # 끝나기 전 플랜
    # 관리자가 사용자에게 학교를 보이거나 숨길 수 있다. 기본은 노출.
    is_visible = Column(Boolean, nullable=False, default=True)
    # 플랜 일시정지: 승인된 플랜을 잠시 멈춘다(플랜은 유지하되 혜택만 정지).
    plan_paused = Column(Boolean, nullable=False, default=False)
    # 관리자가 무상으로 준 플랜인지. 결제로 받은 것과 구분해 화면에 알린다.
    # 만료 안내 문구가 달라야 하고, 매출 집계에도 들어가면 안 된다.
    plan_is_free_trial = Column(Boolean, nullable=False, default=False)
    plan_granted_note = Column(String(200), default="")
    view_count = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)

    accounts = relationship("User", back_populates="school")
    favorites = relationship("Favorite", back_populates="school", cascade="all, delete-orphan")
    events = relationship(
        "AdmissionEvent", back_populates="school", cascade="all, delete-orphan"
    )
    orders = relationship("PlanOrder", back_populates="school", cascade="all, delete-orphan")
    inquiries = relationship(
        "Inquiry", back_populates="school", cascade="all, delete-orphan"
    )

    @property
    def plan_rank(self) -> int:
        return PLAN_RANK.get(self.plan, 0)


class Favorite(Base):
    __tablename__ = "favorites"
    __table_args__ = (UniqueConstraint("user_id", "school_id", name="uq_user_school"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    school_id = Column(Integer, ForeignKey("schools.id"), nullable=False)
    memo = Column(String(200), default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="favorites")
    school = relationship("School", back_populates="favorites")


# 학교 일정 종류. "briefing"=학교 설명회, "admission"=참가 행사.
# ("admission" 은 원래 '입시 일정' 이었다. 학교가 여는 중학생 참가 행사로
#  뜻을 바꾸면서 표시 문구만 갈아끼웠다 — 이미 쌓인 일정 행을 그대로 쓰려고
#  저장 값은 건드리지 않았다. 값 자체엔 의미를 두지 말고 이 표만 볼 것.)
EVENT_KINDS = ("briefing", "admission")
EVENT_KIND_LABEL = {"briefing": "학교 설명회", "admission": "참가 행사"}


class AdmissionEvent(Base):
    __tablename__ = "admission_events"

    id = Column(Integer, primary_key=True)
    school_id = Column(Integer, ForeignKey("schools.id"), nullable=False)
    # 학교 설명회("briefing")인지 참가 행사("admission")인지 구분한다.
    kind = Column(String(20), nullable=False, default="briefing")
    title = Column(String(120), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
    start_time = Column(String(5), nullable=True)   # "14:00" 형식, 없으면 시간 미정
    end_time = Column(String(5), nullable=True)
    location = Column(String(200), default="")
    registration_url = Column(String(500), default="")
    description = Column(Text, default="")

    school = relationship("School", back_populates="events")


class JournalEntry(Base):
    """학생이 쓰는 수업 일지 / 학교생활 일지.
    content에는 항목별 답변을 JSON 문자열로 저장한다(양식이 바뀌어도 스키마 변경 불필요)."""

    __tablename__ = "journal_entries"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    kind = Column(String(10), nullable=False, default="diary")  # lesson/diary
    entry_date = Column(Date, nullable=False)

    # 수업 일지 전용(일기는 비워둠)
    subject = Column(String(60), default="")       # 교과명
    teacher_name = Column(String(60), default="")  # 교사명

    content = Column(Text, default="{}")           # {필드키: 답변} JSON
    resume_tags = Column(String(200), default="")  # 자소서 항목 키(쉼표 구분)

    # 선생님 공유
    teacher_email = Column(String(255), default="")
    share_token = Column(String(64), unique=True, index=True, nullable=True)
    sent_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User")


class QuizTaken(Base):
    """진로 적성 테스트 참여 기록. 참여자 수 집계에 쓴다.
    비로그인도 이용할 수 있으므로 user_id는 비어 있을 수 있다."""

    __tablename__ = "quiz_taken"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    top_axis = Column(String(30), default="")   # 가장 높게 나온 성향
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class SchoolVerification(Base):
    """재학생 인증. 선생님이 학급에 학생을 등록하면 승인(approved) 상태로 만들어진다.
    승인된 학생만 그 학교 선생님의 학급 명단(재학생)으로 잡힌다."""

    __tablename__ = "school_verifications"
    __table_args__ = (
        UniqueConstraint("user_id", "school_id", name="uq_verification_once"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    school_id = Column(Integer, ForeignKey("schools.id"), nullable=False)
    status = Column(String(10), nullable=False, default="pending")  # pending/approved/rejected
    note = Column(String(200), default="")  # 학생이 남기는 소개(학번/학년 등)
    # 선생님이 학급에 등록한 경우 채워진다
    class_name = Column(String(40), default="")
    teacher_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    decided_at = Column(DateTime, nullable=True)

    user = relationship("User", foreign_keys=[user_id])
    teacher = relationship("User", foreign_keys=[teacher_id])
    school = relationship("School")


class PlanGrant(Base):
    """관리자가 학교에 무상으로 준 플랜 이력.

    누가 언제 어느 학교에 무엇을 줬는지 남긴다. 무상 제공은 매출로 잡히지
    않으므로, 나중에 "왜 이 학교가 유료 기능을 쓰고 있지" 를 확인할 근거가 된다.
    """

    __tablename__ = "plan_grants"

    id = Column(Integer, primary_key=True)
    school_id = Column(Integer, ForeignKey("schools.id"), nullable=False, index=True)
    school_name = Column(String(120), default="")     # 학교가 지워져도 남도록 복사
    plan = Column(Enum(Plan), nullable=False)
    months = Column(Integer, nullable=False, default=1)
    starts_on = Column(Date, nullable=False)
    expires_on = Column(Date, nullable=False)
    reason = Column(String(200), default="")          # 지급 사유(영업·체험 등)
    granted_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    granted_by_email = Column(String(120), default="")
    revoked_at = Column(DateTime, nullable=True)      # 중간에 회수한 경우
    created_at = Column(DateTime, default=datetime.utcnow)

    school = relationship("School")


class PlanOrder(Base):
    __tablename__ = "plan_orders"

    id = Column(Integer, primary_key=True)
    school_id = Column(Integer, ForeignKey("schools.id"), nullable=False)
    requested_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    plan = Column(Enum(Plan), nullable=False)
    months = Column(Integer, nullable=False, default=1)
    amount = Column(Integer, nullable=False, default=0)
    status = Column(Enum(OrderStatus), nullable=False, default=OrderStatus.pending)
    note = Column(String(200), default="")
    # 입금자명에 적어달라고 안내하는 고유 코드 (예: UDJ-3F7K)
    deposit_code = Column(String(30), default="", index=True)
    # 세금계산서 발행용 정보
    tax_email = Column(String(255), default="")
    tax_manager = Column(String(60), default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    due_at = Column(DateTime, nullable=True)     # 입금 기한
    paid_at = Column(DateTime, nullable=True)    # 입금 확인 시각
    handled_at = Column(DateTime, nullable=True)

    school = relationship("School", back_populates="orders")


class Inquiry(Base):
    """방문자가 특정 학교에 남긴 질문과, 학교가 다는 답변.

    개인정보보호법에 따라 이메일 등 개인정보는 '답변 발송'이라는 명시된 목적으로만
    수집하며, 수집·이용 동의(privacy_consent)를 받아야 한다. 보유기간이 지나면
    자동 파기한다(main.py의 purge_old_inquiries 참고).
    """

    __tablename__ = "inquiries"

    id = Column(Integer, primary_key=True)
    school_id = Column(Integer, ForeignKey("schools.id"), nullable=False, index=True)

    # --- 수집하는 개인정보 (최소수집 원칙) ---
    asker_name = Column(String(60), default="")  # 선택
    contact_email = Column(String(120), nullable=False)  # 답변을 받을 주소(필수)
    contact_phone = Column(String(30), default="")  # 선택

    question = Column(Text, nullable=False)

    # --- 동의 기록 (개인정보 수집·이용 동의 여부) ---
    privacy_consent = Column(Boolean, nullable=False, default=False)

    # --- 답변 ---
    status = Column(Enum(InquiryStatus), nullable=False, default=InquiryStatus.pending)
    answer = Column(Text, default="")
    answered_at = Column(DateTime, nullable=True)
    answered_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # --- 답변 이메일 발송 결과 ---
    delivery_status = Column(
        Enum(DeliveryStatus), nullable=False, default=DeliveryStatus.pending
    )
    delivery_error = Column(String(300), default="")

    created_at = Column(DateTime, default=datetime.utcnow)

    school = relationship("School", back_populates="inquiries")


class PasswordReset(Base):
    """비밀번호 재설정 인증코드. 코드는 해시로만 저장하고 만료·사용여부를 관리한다."""

    __tablename__ = "password_resets"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    code_hash = Column(String(64), nullable=False)  # 6자리 코드의 sha256
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False)
    attempts = Column(Integer, default=0)  # 코드 입력 시도 횟수(무차별 대입 방지)
    created_at = Column(DateTime, default=datetime.utcnow)


class SchoolView(Base):
    """조회 로그. 학교 대시보드의 일자별 조회수 그래프에 쓰인다."""

    __tablename__ = "school_views"

    id = Column(Integer, primary_key=True)
    school_id = Column(Integer, ForeignKey("schools.id"), nullable=False)
    viewed_on = Column(Date, nullable=False, default=lambda: datetime.utcnow().date())
    count = Column(Integer, default=1)


class Article(Base):
    """특성화고신문 기사. 자동 크롤링 또는 수동 등록으로 쌓인다.

    같은 곳/협력 관계라 저작권 문제는 없으나, 출처를 '특성화고신문 제공'으로
    명시하고 원문 링크를 함께 둔다. 학교는 제목의 학교명 매칭 또는 수동 지정으로
    연결한다(school_id가 있으면 그 학교 상세페이지에 표시).
    """

    __tablename__ = "articles"

    id = Column(Integer, primary_key=True)
    # 특성화고신문 원문 식별자(view.html?...&no=N 의 no). 중복 수집 방지용.
    source_no = Column(Integer, nullable=True, index=True)
    url = Column(String(500), nullable=False)
    title = Column(String(300), nullable=False)
    summary = Column(Text, default="")
    thumbnail = Column(String(500), default="")
    published_at = Column(Date, nullable=True)

    # 연결된 학교(있으면). 제목 매칭 또는 수동 지정.
    school_id = Column(Integer, ForeignKey("schools.id"), nullable=True, index=True)
    # 수동 등록인지 자동 크롤링인지
    source = Column(String(20), default="crawl")  # "crawl" | "manual"

    created_at = Column(DateTime, default=datetime.utcnow)

    school = relationship("School", backref="articles")


class Notice(Base):
    """공지·알림. 대상 범위(scope)에 따라 누구에게 보일지 결정된다.

      all      : 사이트 전체 (관리자만 작성, 팝업 가능)
      school   : 특정 학교의 학교 계정·선생님 (관리자가 작성)
      teachers : 우리 학교 선생님들 (학교 계정이 작성)
    """

    __tablename__ = "notices"

    id = Column(Integer, primary_key=True)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    scope = Column(String(10), nullable=False, default="all")
    school_id = Column(Integer, ForeignKey("schools.id"), nullable=True, index=True)

    title = Column(String(150), nullable=False)
    body = Column(Text, default="")
    # 첨부 이미지 URL (/api/uploads/xxx.png)
    image_url = Column(String(300), default="")
    # 전체 공지를 화면 가운데 팝업으로 띄울지
    is_popup = Column(Boolean, nullable=False, default=False)
    # 중요 표시(빨간 배지)
    is_important = Column(Boolean, nullable=False, default=False)

    starts_at = Column(DateTime, nullable=True)   # 비우면 즉시
    ends_at = Column(DateTime, nullable=True)     # 비우면 무기한
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    author = relationship("User")
    school = relationship("School")


class NoticeRead(Base):
    """공지 읽음 기록. 팝업을 한 번만 띄우고 안 읽은 개수를 세는 데 쓴다."""

    __tablename__ = "notice_reads"
    __table_args__ = (
        UniqueConstraint("notice_id", "user_id", name="uq_notice_read"),
    )

    id = Column(Integer, primary_key=True)
    notice_id = Column(Integer, ForeignKey("notices.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    read_at = Column(DateTime, default=datetime.utcnow)


class SchoolViewHit(Base):
    """조회수 중복 집계를 막기 위한 열람 기록.

    같은 사람이 같은 학교를 짧은 시간에 여러 번 열어도 1회만 센다.
    viewer_key 는 로그인 사용자면 계정 기준, 아니면 IP+브라우저를 해시한 값이라
    개인정보를 그대로 남기지 않는다. 창이 지나면 자동으로 지운다.
    """

    __tablename__ = "school_view_hits"

    id = Column(Integer, primary_key=True)
    school_id = Column(Integer, ForeignKey("schools.id"), nullable=False, index=True)
    viewer_key = Column(String(64), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class SchoolSubject(Base):
    """학교·학과·학년별 개설 과목.

    NEIS 시간표에서 모아둔다. 일지를 쓸 때 과목명을 직접 타이핑하지 않고
    고를 수 있게 하려는 것이다. 학교마다 과목 이름이 제각각이라 미리 받아둔다.
    """

    __tablename__ = "school_subjects"
    __table_args__ = (
        UniqueConstraint("school_id", "department", "grade", "name",
                         name="uq_school_subject"),
    )

    id = Column(Integer, primary_key=True)
    school_id = Column(Integer, ForeignKey("schools.id"), nullable=False, index=True)
    department = Column(String(60), default="")   # 빈 값이면 학과 구분 없음
    grade = Column(Integer, nullable=True)
    name = Column(String(80), nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Subscription(Base):
    """개인 구독.

    학교 연계(일지를 교사에게 제출)는 무료다. 학교와 무관하게 본인이 따로
    자기소개서를 쓰는 기능만 구독 대상이다.
    한 사람당 한 행만 두고, 연장할 때 expires_at 을 뒤로 민다.
    """

    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False, index=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User")


class SubscriptionOrder(Base):
    """구독 결제 주문. 학교 플랜과 같은 무통장 입금 방식을 쓴다."""

    __tablename__ = "subscription_orders"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    # 계정이 지워져도 정산 근거가 남도록 값으로 복사해 둔다.
    user_email = Column(String(120), default="")
    months = Column(Integer, nullable=False, default=1)
    amount = Column(Integer, nullable=False, default=0)
    status = Column(Enum(OrderStatus), nullable=False, default=OrderStatus.pending)
    deposit_code = Column(String(30), default="", index=True)
    note = Column(String(200), default="")

    # 카드 결제(토스페이먼츠)
    order_uid = Column(String(64), unique=True, index=True, nullable=True)  # 토스에 넘기는 주문번호
    payment_key = Column(String(200), default="")   # 승인 후 토스가 주는 키(취소에 필요)
    pay_method = Column(String(30), default="")     # 카드/간편결제 등
    receipt_url = Column(String(300), default="")   # 영수증 링크
    refunded_at = Column(DateTime, nullable=True)

    # 미성년자 결제 보호(민법 제5조): 결제 시점의 법정대리인 동의 여부
    minor_consent = Column(Boolean, default=False)
    guardian_contact = Column(String(120), default="")

    created_at = Column(DateTime, default=datetime.utcnow)
    due_at = Column(DateTime, nullable=True)
    paid_at = Column(DateTime, nullable=True)
    handled_at = Column(DateTime, nullable=True)

    user = relationship("User")


class CoverLetter(Base):
    """개인 자기소개서. 구독한 이용자만 만들 수 있다."""

    __tablename__ = "cover_letters"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(120), default="")
    template = Column(String(40), default="")      # 자소서 항목 키
    content = Column(Text, default="{}")           # {항목키: 본문} JSON
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User")


class PhoneVerification(Base):
    """휴대폰 본인확인(SMS 인증번호).

    회원가입·아이디 찾기·비밀번호 재설정·비밀번호 변경에서 공통으로 쓴다.
    인증번호는 평문으로 두지 않고 해시로 저장하며, 확인에 성공하면 짧게 유효한
    일회용 토큰을 발급해 그 토큰으로 실제 작업을 진행한다.
    """

    __tablename__ = "phone_verifications"

    id = Column(Integer, primary_key=True)
    phone = Column(String(20), nullable=False, index=True)   # 숫자만 저장
    purpose = Column(String(20), nullable=False)             # signup/find_id/reset_pw/change_pw
    code_hash = Column(String(64), nullable=False)
    attempts = Column(Integer, default=0)                    # 인증번호 확인 시도 횟수
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    expires_at = Column(DateTime, nullable=False)
    verified_at = Column(DateTime, nullable=True)
    token = Column(String(64), unique=True, index=True, nullable=True)  # 확인 성공 시 발급
    token_used = Column(Boolean, default=False)              # 일회용
    ip = Column(String(45), default="")


class GuardianConsent(Base):
    """만 14세 미만 아동 가입 시 법정대리인 동의 요청.

    개인정보 보호법 시행령 제17조의2가 인정하는 방법 중 '법정대리인의
    전자우편을 통한 동의'에 해당한다. 동의 전까지 계정은 비활성 상태다.
    """

    __tablename__ = "guardian_consents"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    guardian_email = Column(String(120), nullable=False)
    token = Column(String(64), unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    consented_at = Column(DateTime, nullable=True)
    consent_ip = Column(String(45), default="")

    user = relationship("User")


class AdminAuditLog(Base):
    """관리자 활동 기록.

    개인정보의 안전성 확보조치 기준 제8조에 따라 개인정보취급자의 처리 이력을
    남긴다. 최소 1년 보관하며, 계정이 지워져도 누가 했는지 알 수 있도록
    이메일과 권한을 값으로 함께 복사해 둔다.
    """

    __tablename__ = "admin_audit_logs"

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


class CsDevice(Base):
    """상담 사이트(udjcs.ggm.kr)에 접속을 허용한 기기.

    사무실 밖에서 들어오는 기기는 관리자가 승인해야 쓸 수 있다. 기기 자체를
    확실히 식별할 방법은 없으므로(브라우저가 알려주는 값은 위조된다) 서버가
    발급한 긴 무작위 토큰을 기기에 저장하고 그것으로 구분한다. 토큰은 복사될
    수 있으니 원본을 두지 않고 해시만 저장하며, 언제든 끊을 수 있게 한다.
    """

    __tablename__ = "cs_devices"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    # 발급한 토큰의 sha256. 원본은 기기에만 있다.
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    # 승인 화면에서 어느 기기인지 짚어주기 위한 짧은 표시용 코드(예: 4F7K9C)
    code = Column(String(12), nullable=False, default="")
    label = Column(String(60), default="")           # 상담원이 붙이는 이름(사무실 노트북 등)
    status = Column(String(10), nullable=False, default="pending")  # pending/approved/revoked
    user_agent = Column(String(200), default="")
    first_ip = Column(String(45), default="")
    last_ip = Column(String(45), default="")
    last_seen_at = Column(DateTime, nullable=True)
    decided_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    decided_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", foreign_keys=[user_id])


class Setting(Base):
    """관리자가 바꿀 수 있는 운영 설정을 key-value로 저장한다.
    예) 플랜 가격(plan_price_basic 등). 값은 문자열로 저장하고 필요 시 형변환한다."""

    __tablename__ = "settings"

    key = Column(String(60), primary_key=True)
    value = Column(Text, default="")


class SchoolExposure(Base):
    """검색 목록에 뜬 횟수와 진로 테스트에 추천된 횟수.

    조회수(SchoolView)만으로는 '아무도 안 본다'와 '보여줬는데 안 눌린다'를
    가릴 수 없다. 둘은 할 말이 다르다.
      · 노출도 적다      → 검색에 안 걸린다. 학과·지역 정보가 부실하다.
      · 노출은 많은데 안 눌린다 → 목록에서 매력이 없다. 소개·사진이 없다.

    영업할 때 이 구분이 그대로 근거가 된다.

    SchoolView 와 같이 날짜별로 세어 둔다. 한 줄씩 쌓으면 금방 수백만 줄이
    되고, 우리는 '며칠에 몇 번'만 알면 된다.
    """

    __tablename__ = "school_exposures"
    __table_args__ = (
        UniqueConstraint("school_id", "shown_on", name="uq_exposure_day"),
    )

    id = Column(Integer, primary_key=True)
    school_id = Column(Integer, ForeignKey("schools.id"), nullable=False, index=True)
    shown_on = Column(Date, nullable=False, default=lambda: datetime.utcnow().date(),
                      index=True)
    # 검색 목록에 뜬 횟수
    search_count = Column(Integer, default=0)
    # 진로 테스트 결과에 추천된 횟수
    quiz_count = Column(Integer, default=0)


class QuizDemand(Base):
    """진로 테스트에서 '어느 지역의 학생이 어떤 계열을 원했는가'.

    수요와 공급을 견주려고 남긴다. 양주에서 IT 계열을 찾는 학생이 많은데
    그 지역 IT 학교가 적다면, 그 학교에는 강한 영업 근거가 된다.

    개인을 알아볼 수 있는 것은 남기지 않는다. 좌표 대신 시·군 이름만 둔다.
    """

    __tablename__ = "quiz_demands"
    __table_args__ = (
        UniqueConstraint("region", "axis", "asked_on", name="uq_demand_day"),
    )

    id = Column(Integer, primary_key=True)
    region = Column(String(40), nullable=False, index=True)   # 시·도 또는 시·군
    axis = Column(String(30), nullable=False)                 # 계열 (TECH, IT ...)
    asked_on = Column(Date, nullable=False,
                      default=lambda: datetime.utcnow().date(), index=True)
    count = Column(Integer, default=0)


# ══════════════════════════════════════════════════════════════
#  전화 상담(콜센터)
#
#  기존 CS 콘솔 위에 전화 응대를 얹기 위한 표들이다. 전부 새 표이고
#  기존 표의 컬럼은 건드리지 않는다.
#
#  상태값은 Enum 컬럼 대신 문자열로 둔다. PostgreSQL 은 이미 만들어진 ENUM
#  타입에 값을 자동으로 추가하지 않아서(main.py 의 _ensure_enum_values 참고),
#  운영 중에 상태 하나 늘리는 일이 배포 사고가 되기 때문이다. 값의 목록은
#  아래 상수로 못 박고, 검증은 API 스키마에서 한다.
# ══════════════════════════════════════════════════════════════

CUSTOMER_TYPES = ("STUDENT", "TEACHER", "SCHOOL", "OTHER")

CALL_DIRECTIONS = ("INBOUND", "OUTBOUND")

# RINGING   상담원을 부르는 중
# QUEUED    받을 사람이 없어 대기열에 있음
# ANSWERED  통화 중
# MISSED    아무도 받지 않음
# REJECTED  상담원이 거절
# FAILED    회선 오류
# COMPLETED 정상 종료
CALL_STATUSES = ("RINGING", "QUEUED", "ANSWERED", "MISSED", "REJECTED", "FAILED", "COMPLETED")

# 통화가 끝났다고 볼 수 있는 상태. 목록·통계에서 되풀이해 쓴다.
CALL_CLOSED_STATUSES = ("MISSED", "REJECTED", "FAILED", "COMPLETED")

CONSULTATION_CHANNELS = ("PHONE", "HOMEPAGE", "EMAIL", "OTHER")

CONSULTATION_STATUSES = (
    "NEW", "RECEIVED", "IN_PROGRESS", "WAITING", "PROCESSING", "COMPLETED", "HOLD",
)

# 아직 손이 더 가야 하는 상담. 대시보드의 미처리 건수가 이걸 센다.
CONSULTATION_OPEN_STATUSES = ("NEW", "RECEIVED", "IN_PROGRESS", "WAITING", "PROCESSING", "HOLD")

CONSULTATION_PRIORITIES = ("LOW", "NORMAL", "HIGH", "URGENT")

AVAILABILITY_STATUSES = ("AVAILABLE", "BUSY", "AWAY", "OFFLINE")


class CsCustomer(Base):
    """상담 고객.

    포털 회원(User)과는 다르다. 전화를 건 사람이 회원이 아닐 수 있고,
    회원이어도 상담 맥락은 따로 쌓이기 때문이다. 회원이면 user_id 로 잇는다.

    전화번호는 반드시 정규화된 형태(01012345678)로 넣는다. 걸려온 번호를
    그대로 담으면 010-1234-5678 과 +821012345678 이 다른 고객이 된다.
    정규화는 callcenter/phones.py 의 normalize_phone 하나만 쓴다.
    """

    __tablename__ = "cs_customers"

    id = Column(Integer, primary_key=True)
    name = Column(String(60), default="")
    # 전화가 오면 이 번호로 찾는다. 조회가 가장 잦은 컬럼이다.
    phone_number = Column(String(20), nullable=False, index=True)
    email = Column(String(120), default="")
    customer_type = Column(String(10), nullable=False, default="OTHER")
    school_name = Column(String(120), default="")
    school_id = Column(Integer, ForeignKey("schools.id"), nullable=True, index=True)
    # 포털 계정이 있으면 이어둔다. 없어도 상담은 된다.
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    memo = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CsCallLog(Base):
    """통화 한 건의 이력. 끝난 통화도 남는다.

    provider 와 external_call_id 를 같이 남긴다. 나중에 사업자를 바꿔도
    예전 기록이 어느 망에서 온 것인지 알아야 대조가 되기 때문이다.
    """

    __tablename__ = "cs_call_logs"

    id = Column(Integer, primary_key=True)
    provider = Column(String(20), nullable=False, default="mock")
    # 사업자가 부르는 통화 ID. 웹훅이 이 값으로 우리 기록을 찾는다.
    external_call_id = Column(String(80), default="", index=True)

    customer_id = Column(Integer, ForeignKey("cs_customers.id"), nullable=True, index=True)
    counselor_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    phone_number = Column(String(20), nullable=False, default="", index=True)
    direction = Column(String(10), nullable=False, default="INBOUND")
    status = Column(String(12), nullable=False, default="RINGING", index=True)

    started_at = Column(DateTime, default=datetime.utcnow, index=True)
    answered_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer, default=0)
    # 녹취는 파일을 직접 들고 있지 않는다. 사업자가 준 주소만 적어둔다.
    recording_url = Column(String(500), default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class CsInquiryType(Base):
    """문의 유형. 관리자가 늘리고 줄인다.

    통계의 축이 되므로 지우지 않고 is_active 로 감춘다. 지워버리면 지난
    상담의 유형이 사라져 예전 통계를 다시 그릴 수 없다.
    """

    __tablename__ = "cs_inquiry_types"

    id = Column(Integer, primary_key=True)
    name = Column(String(60), nullable=False, unique=True)
    sort_order = Column(Integer, nullable=False, default=100)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class CsConsultation(Base):
    """상담 한 건.

    전화든 홈페이지 문의든 여기로 모인다. 채널이 달라도 상담원이 보는 화면과
    통계는 같아야 하기 때문이다.
    """

    __tablename__ = "cs_consultations"

    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("cs_customers.id"), nullable=True, index=True)
    counselor_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    # 전화 상담이면 어느 통화에서 나온 상담인지 이어둔다.
    call_log_id = Column(Integer, ForeignKey("cs_call_logs.id"), nullable=True, index=True)

    channel = Column(String(10), nullable=False, default="PHONE")
    inquiry_type_id = Column(Integer, ForeignKey("cs_inquiry_types.id"), nullable=True)
    subject = Column(String(200), default="")
    content = Column(Text, default="")
    result = Column(Text, default="")
    status = Column(String(20), nullable=False, default="NEW", index=True)
    priority = Column(String(10), nullable=False, default="NORMAL")

    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CsCallSession(Base):
    """진행 중인 콜의 분배 상태.

    운영은 gunicorn 워커 3개다. 이 상태를 파이썬 메모리에 두면 웹훅을 받은
    워커와 상담원이 붙어 있는 워커가 달라 화면에 전화가 뜨지 않는다.
    그래서 DB 에 둔다.

    ring_step 은 낙관적 잠금 열쇠이기도 하다. 타임아웃을 넘길 때
    UPDATE ... WHERE ring_step = 현재값 조건으로 바꾸므로, 세 워커가 동시에
    깨어나도 한 번만 넘어간다.
    """

    __tablename__ = "cs_call_sessions"

    id = Column(Integer, primary_key=True)
    call_log_id = Column(Integer, ForeignKey("cs_call_logs.id"), nullable=False,
                         unique=True, index=True)
    # RINGING / QUEUED / ANSWERED / ENDED
    state = Column(String(10), nullable=False, default="RINGING", index=True)
    # 지금 벨이 울리고 있는 상담원
    current_counselor_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    ring_step = Column(Integer, nullable=False, default=0)
    # 이 시각이 지나면 다음 상담원으로 넘긴다.
    ring_deadline = Column(DateTime, nullable=True, index=True)
    # 이번 콜에서 이미 부른 상담원 id 들. 쉼표로 잇는다. 큐에서 다시 돌 때
    # 같은 사람을 두 번 부르지 않기 위해서다.
    tried_ids = Column(String(200), default="")
    queued_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CsCallEvent(Base):
    """상담원 화면으로 내보낼 이벤트 아웃박스.

    WebSocket 은 워커마다 따로 붙는다. 어느 워커에서 만든 이벤트든 모든
    상담원에게 가야 하므로, 브로드캐스트를 메모리가 아니라 이 표로 한다.
    각 연결은 자기가 마지막으로 보낸 id 뒤부터 읽어 간다.

    개인정보를 평문으로 오래 들고 있지 않도록, payload 에는 화면에 필요한
    최소한만 담고 오래된 행은 주기적으로 지운다.
    """

    __tablename__ = "cs_call_events"

    id = Column(Integer, primary_key=True)
    type = Column(String(30), nullable=False)
    call_log_id = Column(Integer, ForeignKey("cs_call_logs.id"), nullable=True, index=True)
    # 특정 상담원에게만 보낼 이벤트면 채운다. 비어 있으면 전체 방송.
    target_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    payload = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class CsCounselorProfile(Base):
    """상담원의 전화 설정. 계정 자체는 기존 users 를 그대로 쓴다.

    상담원 표를 따로 만들면 계정이 두 벌이 되어 비밀번호·권한·기기승인이
    갈라진다. 전화에만 필요한 값들만 여기에 딸려 둔다.
    """

    __tablename__ = "cs_counselor_profiles"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    # 순차분배 순서. 작을수록 먼저 받는다. 관리자가 바꾼다.
    ring_order = Column(Integer, nullable=False, default=100)
    availability_status = Column(String(10), nullable=False, default="OFFLINE", index=True)
    # 전화를 아예 안 받는 계정(관리자 등)은 False 로 두어 분배에서 뺀다.
    accepts_calls = Column(Boolean, nullable=False, default=True)
    extension = Column(String(20), default="")       # 내선
    phone_number = Column(String(20), default="")    # 상담원 개인 착신번호(선택)

    # 브라우저로 전화를 받을 때 쓰는 임시 SIP 주소.
    # 전화 사업자가 주는 토큰의 수명이 5~7분이라 주소가 계속 바뀐다. 그래서
    # 상담원이 정하는 값이 아니라, 서버가 토큰을 발급할 때마다 여기에 덮어쓴다.
    # 만료된 주소로 전화를 돌리면 아무 데도 울리지 않으므로 만료시각을 함께 둔다.
    sip_uri = Column(String(200), default="")
    sip_uri_expires_at = Column(DateTime, nullable=True)
    department = Column(String(60), default="")
    position = Column(String(40), default="")
    last_status_at = Column(DateTime, default=datetime.utcnow)
    last_login_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ============================================================
# 영상 (롱폼 · 숏츠) — 숏츠는 롱폼의 한 구간에서 잘려 나온 것으로 본다
# ============================================================
VIDEO_KINDS = ("longform", "shorts")

# 숏츠↔롱폼 연결의 상태.
#   pending      아직 분석 안 함
#   processing   분석 중
#   completed    AI 가 구간을 찾음(신뢰도 높음)
#   needs_review 찾긴 했으나 관리자 확인이 필요하거나, 못 찾음
#   failed       분석 자체가 터짐(대본 없음·STT 실패 등)
#   confirmed    관리자가 확정함
MATCH_STATUSES = ("pending", "processing", "completed", "needs_review", "failed", "confirmed")


class Video(Base):
    """포털이 직접 들고 있는 영상.

    학교 상세의 유튜브 링크(School.youtube_urls)와는 다른 것이다. 그쪽은
    학교가 자기 채널 영상을 걸어 두는 자리고, 이건 포털이 올려서 직접
    서빙하는 영상이다. 숏츠에서 롱폼의 정확한 초로 이동하려면 재생을
    우리가 쥐고 있어야 해서 따로 둔다.
    """

    __tablename__ = "videos"

    id = Column(Integer, primary_key=True)
    kind = Column(String(12), nullable=False, default="longform", index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, default="")

    # /api/media/... 로 서빙하는 경로. 업로드본은 이 서버 디스크에 있다.
    file_path = Column(String(300), default="")
    thumbnail = Column(String(300), default="")
    duration_sec = Column(Float, nullable=True)     # ffprobe 로 잰 실제 길이
    size_bytes = Column(Integer, nullable=True)

    category = Column(String(40), default="", index=True)
    is_public = Column(Boolean, nullable=False, default=False)
    view_count = Column(Integer, nullable=False, default=0)

    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ServiceApplication(Base):
    """유료 서비스 신청(컨설팅·상담·영상)과 설명회 시청 신청.

    폼마다 테이블을 따로 파지 않는다 — 물어보는 항목이 거의 같고, 관리자가
    볼 때도 한 화면에서 처리하는 편이 낫다. 폼마다 다른 항목만 extra_json 에
    담는다.

    **금액을 신청 행에 박아 둔다.** 가격표(applications.py 의 KINDS)를 나중에
    올리면, 예전 신청까지 새 가격으로 보이게 된다. 그때 얼마로 신청했는지가
    입금 대조의 기준이므로 신청 시점의 값을 그대로 남긴다.
    """

    __tablename__ = "service_applications"

    id = Column(Integer, primary_key=True)
    kind = Column(String(30), nullable=False, index=True)

    name = Column(String(40), nullable=False)
    phone = Column(String(30), nullable=False)
    email = Column(String(120), default="")

    found_path = Column(String(20), default="")    # 소개 / 검색 / 기타
    found_etc = Column(String(100), default="")    # 기타일 때 직접 입력
    applicant = Column(String(20), default="")     # 본인 / 학부모 · 학생 / 교원
    message = Column(Text, default="")             # 문의 및 요청사항
    extra_json = Column(Text, default="{}")        # 폼마다 다른 항목

    amount = Column(Integer, default=0)
    status = Column(String(12), nullable=False, default="received", index=True)
    admin_note = Column(Text, default="")

    # 신청한 계정. 대부분의 폼은 로그인 없이 받으므로 보통 비어 있다.
    # 산 사람에게 무언가를 열어 줘야 하는 신청(합격생 영상)만 로그인을
    # 요구하고 여기에 누구인지 남긴다 — 열어 줄 상대가 있어야 열 수 있다.
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class VideoTranscript(Base):
    """영상 하나의 STT 결과. **더 이상 쓰지 않는다.**

    구간 찾기는 소리 지문(fingerprint.py)만 쓰도록 바뀌었다. 받아 적기는
    외부 업체 할당량에 매번 걸렸고, 받아 적어도 시각이 문장 단위라 정밀도가
    지문보다 한 자릿수 떨어졌다.

    표 정의만 남겨 둔 것은 **운영 DB 에 이미 만들어진 표와 예전 행이 있어서**다.
    여기서 클래스를 지우면 SQLAlchemy 가 그 표를 모르게 될 뿐 표가 사라지지는
    않는다. 새로 쓰지 않으니 그대로 두고, 나중에 정리할 때 함께 지운다.
    """

    __tablename__ = "video_transcripts"

    id = Column(Integer, primary_key=True)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=False, unique=True)
    provider = Column(String(20), default="")       # whisper / clova / manual ...
    language = Column(String(10), default="ko")

    # 전체 텍스트. 사람이 눈으로 확인하거나 검색할 때 쓴다.
    text = Column(Text, default="")
    # [{start, end, text, words:[{text,start,end}]}] 를 JSON 문자열로.
    # 낱말 단위 시각이 여기 있어야 03:24.12 같은 보정이 가능하다.
    segments_json = Column(Text, default="[]")

    status = Column(String(12), nullable=False, default="pending", index=True)
    # 어디까지 갔는지. STT 업체가 진행률(%)을 주지 않으므로 단계로 알린다 —
    # 1시간 영상은 몇 분이 걸려서, 아무 표시가 없으면 멈춘 줄 알고 새로고침한다.
    #   extracting(오디오 뽑는 중) / transcribing(받아 적는 중) / saving(저장 중)
    stage = Column(String(16), default="")
    started_at = Column(DateTime, nullable=True)   # 경과 시간을 재는 기준
    error = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class VideoFingerprint(Base):
    """영상 하나의 오디오 지문 색인. 영상당 한 벌.

    대본과 같은 이유로 저장해 둔다 — 숏츠 30개를 맞춘다고 롱폼 지문을
    30번 다시 만들면 30배가 걸린다. 원본 파일을 지워도 이 색인은 남아서
    나중에 붙는 숏츠도 계속 맞출 수 있다.
    """

    __tablename__ = "video_fingerprints"

    id = Column(Integer, primary_key=True)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=False, unique=True)
    # numpy 배열 두 개(해시·시각)를 압축해 담는다. 1시간 영상이 몇 MB 쯤.
    data = Column(LargeBinary, nullable=True)
    hash_count = Column(Integer, nullable=False, default=0)
    frames = Column(Integer, nullable=False, default=0)
    status = Column(String(12), nullable=False, default="pending", index=True)
    error = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ShortsMatch(Base):
    """숏츠가 롱폼의 어느 구간에서 나왔는지.

    숏츠 하나는 롱폼 하나에만 붙는다(unique). 롱폼 하나에는 숏츠가 여럿
    붙는다.
    """

    __tablename__ = "shorts_matches"

    id = Column(Integer, primary_key=True)
    shorts_id = Column(Integer, ForeignKey("videos.id"), nullable=False, unique=True)
    longform_id = Column(Integer, ForeignKey("videos.id"), nullable=False, index=True)

    # 초 단위. 소수점을 살린다 — 문장 중간에서 잘린 숏츠는 1초만 어긋나도
    # 엉뚱한 말부터 재생된다.
    source_start_time = Column(Float, nullable=True)
    source_end_time = Column(Float, nullable=True)

    status = Column(String(14), nullable=False, default="pending", index=True)
    confidence = Column(Float, nullable=True)
    method = Column(String(20), default="")          # text / text+audio ...

    # 각 점수를 따로 남긴다. 신뢰도가 낮게 나왔을 때 텍스트가 문제인지
    # 오디오가 문제인지 봐야 임계값을 어디로 옮길지 판단할 수 있다.
    text_score = Column(Float, nullable=True)
    sequence_score = Column(Float, nullable=True)
    audio_score = Column(Float, nullable=True)
    visual_score = Column(Float, nullable=True)

    # 관리자가 손댄 값은 AI 재분석이 덮어쓰지 않는다. 이 두 칸이 그 근거다.
    manually_verified = Column(Boolean, nullable=False, default=False)
    manually_modified = Column(Boolean, nullable=False, default=False)

    note = Column(Text, default="")
    analyzed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MonitorSample(Base):
    """서버 상태를 1분마다 한 줄씩 남긴 시계열.

    **왜 DB에 두나.** 지금 값만 보면 "CPU 62%"가 높은 건지 평소인지 알 수가
    없다. 사고는 절대값이 아니라 변화로 드러난다 — 어제 이 시각엔 12% 였다는
    사실이 있어야 판단이 된다. 디스크도 마찬가지여서, 남은 용량보다 "이 속도면
    며칠 남았다"가 훨씬 쓸모 있는데 그건 과거 표본이 있어야만 낼 수 있다.

    **왜 파이썬 메모리가 아닌가.** 운영은 gunicorn 워커 3개다. 메모리에 쌓으면
    워커마다 다른 그래프를 들고 있게 되고, 배포 때마다 통째로 날아간다.

    한 줄이 1분이므로 30일이면 43,200 줄. 자주 쓰는 값만 칸으로 빼서 그래프를
    바로 그릴 수 있게 하고, 나머지 잡다한 내역은 payload(JSON)에 넣는다.
    """

    __tablename__ = "monitor_samples"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    cpu_percent = Column(Float, default=0.0)
    mem_percent = Column(Float, default=0.0)
    disk_percent = Column(Float, default=0.0)
    disk_used_mb = Column(Integer, default=0)
    load1 = Column(Float, default=0.0)

    # 최근 5분 기준. nginx 로그에서 센다.
    visitors_5m = Column(Integer, default=0)
    requests_per_min = Column(Float, default=0.0)
    error_5xx = Column(Integer, default=0)

    # 서비스가 전부 살아 있었으면 True. 월간 가동률(uptime %)은 이 칸을 센다.
    all_up = Column(Boolean, default=True)

    payload = Column(Text, default="{}")
