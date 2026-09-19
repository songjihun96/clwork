import re
from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import (BaseModel, EmailStr, Field, TypeAdapter, ValidationError,
                      field_validator)

from .models import Coed, DeliveryStatus, InquiryStatus, OrderStatus, Plan, Role


# 유튜브 주소에서 영상 id 만 뽑는다. watch?v=, youtu.be/, embed/, shorts/,
# live/ 다섯 가지 꼴을 모두 받는다. 학교가 어디서 복사해 오든 통하게 하려는 것.
_YT_HOSTS = ("youtube.com", "www.youtube.com", "m.youtube.com",
             "youtu.be", "www.youtu.be", "youtube-nocookie.com",
             "www.youtube-nocookie.com")
_YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def youtube_video_id(url: str) -> str:
    """유튜브 영상 id. 유튜브 주소가 아니면 빈 문자열."""
    from urllib.parse import parse_qs, urlparse

    try:
        u = urlparse((url or "").strip())
    except ValueError:
        return ""
    if u.scheme not in ("http", "https") or u.hostname not in _YT_HOSTS:
        return ""
    if u.hostname in ("youtu.be", "www.youtu.be"):
        cand = u.path.lstrip("/").split("/")[0]
    elif u.path == "/watch":
        cand = (parse_qs(u.query).get("v") or [""])[0]
    else:
        parts = [p for p in u.path.split("/") if p]
        if len(parts) >= 2 and parts[0] in ("embed", "shorts", "live", "v"):
            cand = parts[1]
        else:
            return ""
    return cand if _YT_ID_RE.match(cand) else ""


def youtube_videos(raw: str) -> List[dict]:
    """저장된 줄바꿈 목록을 화면에서 바로 쓸 수 있는 꼴로 바꾼다."""
    out = []
    for line in (raw or "").splitlines():
        vid = youtube_video_id(line)
        if not vid:
            continue
        out.append({
            "video_id": vid,
            "url": line.strip(),
            # 개인정보 보호 모드 도메인으로 띄운다(학생이 보는 화면이라).
            "embed_url": f"https://www.youtube-nocookie.com/embed/{vid}",
            "thumbnail": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
        })
        if len(out) == 4:
            break
    return out


class YoutubeVideoOut(BaseModel):
    video_id: str
    url: str
    embed_url: str
    thumbnail: str


# ---------- 인증 ----------
class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    name: str = Field(min_length=1, max_length=60)
    # 본인확인·계정찾기에 쓰는 휴대폰번호(필수). SMS 인증을 마쳐야 한다.
    phone: str = Field(min_length=10, max_length=30)
    phone_verification_token: str = Field(min_length=1)
    # 연령 확인용(필수). 만 14세 미만이면 법정대리인 동의 절차로 넘어간다.
    birth_date: date
    # 만 14세 미만일 때만 필요한 법정대리인 이메일.
    guardian_email: Optional[EmailStr] = None
    # 개인정보 수집·이용 동의(필수). True 여야 가입된다.
    privacy_consent: bool = False
    # 이용약관 동의(필수).
    terms_consent: bool = False

    @field_validator("privacy_consent")
    @classmethod
    def must_consent(cls, v: bool) -> bool:
        if not v:
            raise ValueError("개인정보 수집·이용에 동의해야 가입할 수 있습니다.")
        return v

    @field_validator("terms_consent")
    @classmethod
    def must_agree_terms(cls, v: bool) -> bool:
        if not v:
            raise ValueError("이용약관에 동의해야 가입할 수 있습니다.")
        return v


class LoginIn(BaseModel):
    email: EmailStr
    password: str


# ---------- 아이디/비밀번호 찾기·변경 ----------
class PhoneCodeIn(BaseModel):
    phone: str = Field(min_length=10, max_length=30)
    purpose: Literal["signup", "find_id", "reset_pw", "change_pw", "change_phone"]
    # 인증 채널이 이메일일 때 인증번호를 받을 주소(가입·재설정 단계에서 필요).
    email: Optional[EmailStr] = None


class PhoneVerifyIn(PhoneCodeIn):
    code: str = Field(min_length=6, max_length=6)


class FindIdIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    phone: str = Field(min_length=1, max_length=30)  # 동명이인 구분을 위한 2차 식별
    # 문자 채널일 때만 필수. 메일 채널에서는 아이디 찾기 인증이 불가능하다.
    phone_verification_token: Optional[str] = None


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6)
    new_password: str = Field(min_length=8, max_length=200)


class ResetPasswordByPhoneIn(BaseModel):
    """휴대폰 인증으로 비밀번호를 재설정한다(메일을 못 쓰는 경우)."""
    email: EmailStr
    phone: str = Field(min_length=10, max_length=30)
    phone_verification_token: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=200)


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=200)
    # 휴대폰번호가 등록된 계정만 필수. 미등록 계정은 비밀번호 확인만으로 변경한다.
    phone_verification_token: Optional[str] = None


class DeleteAccountIn(BaseModel):
    password: str  # 본인 확인용 현재 비밀번호


class AdminResetPasswordIn(BaseModel):
    new_password: str = Field(min_length=8, max_length=200)


class UserOut(BaseModel):
    id: int
    email: EmailStr
    name: str
    role: Role
    school_id: Optional[int] = None
    school_name: Optional[str] = None
    phone: str = ""   # 미등록 안내를 띄우기 위해 함께 내려준다
    # 학교 계정이 상단에서 남은 기간을 보는 데 쓴다. 무료·무기한이면 비어 있다.
    plan: Optional[str] = None
    plan_expires_at: Optional[datetime] = None
    plan_days_left: Optional[int] = None
    plan_paused: bool = False

    class Config:
        from_attributes = True


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ---------- 학교 ----------
class SchoolBase(BaseModel):
    name: str
    category: str
    region: str
    address: str
    coed: Coed
    dormitory: Optional[bool] = None
    foundation: str = ""
    phone: str = ""
    website: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class SchoolCreate(SchoolBase):
    pass


class SchoolAdminUpdate(BaseModel):
    """관리자만 바꿀 수 있는 항목."""

    name: Optional[str] = None
    category: Optional[str] = None
    region: Optional[str] = None
    address: Optional[str] = None
    coed: Optional[Coed] = None
    dormitory: Optional[bool] = None
    foundation: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    plan: Optional[Plan] = None
    plan_expires_at: Optional[date] = None


class SchoolProfileUpdate(BaseModel):
    """학교 계정이 스스로 채우는 상세 정보."""

    slogan: Optional[str] = None
    intro: Optional[str] = None
    departments: Optional[str] = None
    facilities: Optional[str] = None
    admission_info: Optional[str] = None      # 화면 표기: '학교 상세 안내'
    youtube_urls: Optional[str] = None        # 줄바꿈으로 구분, 최대 4개
    inquiry_notify_email: Optional[str] = None   # 문의 알림 받을 주소(비우면 끔)
    employment_rate: Optional[float] = None
    student_count: Optional[int] = None
    established_year: Optional[int] = None
    hero_image: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    dormitory: Optional[bool] = None

    @field_validator("inquiry_notify_email")
    @classmethod
    def check_notify_email(cls, v):
        """비우면 알림을 끄는 뜻이라 빈 값도 받는다. 값이 있으면 형식을 본다."""
        v = (v or "").strip()
        if not v:
            return ""
        try:
            return str(TypeAdapter(EmailStr).validate_python(v))
        except ValidationError:
            raise ValueError("알림 받을 이메일 주소 형식이 올바르지 않습니다.")

    @field_validator("youtube_urls")
    @classmethod
    def check_youtube(cls, v: Optional[str]) -> Optional[str]:
        """유튜브 주소만, 최대 3개까지 받는다.

        상세 페이지에서 iframe 으로 그대로 트는 값이라, 여기서 막지 않으면
        아무 사이트나 학교 페이지 안에 끼워 넣을 수 있게 된다.
        """
        if v is None:
            return v
        lines = [x.strip() for x in v.replace(",", "\n").splitlines() if x.strip()]
        if len(lines) > 4:
            raise ValueError("영상은 최대 4개까지 등록할 수 있습니다.")
        clean = []
        for line in lines:
            if not youtube_video_id(line):
                raise ValueError(f"유튜브 주소가 아닙니다: {line}")
            clean.append(line)
        return "\n".join(clean)

    @field_validator("hero_image", "website")
    @classmethod
    def safe_url(cls, v: Optional[str]) -> Optional[str]:
        """javascript:, data: 같은 위험한 스킴을 막고 http/https만 허용한다(XSS 방어)."""
        if not v:
            return v
        v = v.strip()
        if not v:
            return v
        low = v.lower()
        if low.startswith("http://") or low.startswith("https://"):
            return v
        # 업로드 API가 돌려주는 우리 서버 자체 경로(/api/uploads/...)도 허용한다.
        if v.startswith("/api/uploads/"):
            return v
        raise ValueError("이미지·웹사이트 주소는 http:// 또는 https:// 로 시작해야 합니다.")


class SchoolListItem(BaseModel):
    """검색 결과 목록에 기본으로 노출되는 정보."""

    id: int
    name: str
    category: str
    region: str
    address: str
    coed: Coed
    dormitory: Optional[bool]
    foundation: str
    phone: str
    website: str
    latitude: Optional[float]
    longitude: Optional[float]
    slogan: str
    hero_image: str
    plan: Plan
    actual_plan: Optional[Plan] = None
    plan_paused: bool = False
    is_visible: bool = True
    is_favorite: bool = False
    # 학교 계정 + SMTP 등록이 되어 '빠른 문의'(이메일 답변)가 가능한 상태인지.
    can_quick_inquiry: bool = False

    class Config:
        from_attributes = True


class SchoolListOut(BaseModel):
    total: int
    page: int
    size: int
    items: List[SchoolListItem]


class EventOut(BaseModel):
    id: int
    kind: str = "admission"  # "admission"=입시 일정, "briefing"=학교 설명회
    title: str
    start_date: date
    end_date: Optional[date]
    start_time: Optional[str] = None  # "14:00"
    end_time: Optional[str] = None
    location: str = ""
    registration_url: str = ""
    description: str
    d_day: int  # 오늘 기준 남은 일수(음수면 지남)

    class Config:
        from_attributes = True


class SchoolDetailOut(SchoolListItem):
    """상세 페이지. 기본 정보 + 학교 계정이 추가한 정보."""

    intro: str
    departments: List[str]
    facilities: str
    admission_info: str
    youtube_videos: List["YoutubeVideoOut"] = []
    employment_rate: Optional[float]
    student_count: Optional[int]
    established_year: Optional[int]
    view_count: int
    events: List[EventOut] = []
    # 관리자에게만 채워 보낸다(main.py 참고). 응답 모형에 없으면 pydantic 이
    # 통째로 걸러 버려서, 서버가 담아도 화면에 도착하지 않는다.
    plan_expires_at: Optional[datetime] = None
    plan_days_left: Optional[int] = None


# ---------- 즐겨찾기 ----------
class FavoriteIn(BaseModel):
    school_id: int
    memo: str = ""


class FavoriteOut(BaseModel):
    school: SchoolListItem
    memo: str
    created_at: datetime


# ---------- 학교 일정(입시 일정 · 학교 설명회) ----------
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class EventIn(BaseModel):
    kind: Literal["admission", "briefing"] = "admission"
    title: str
    start_date: date
    end_date: Optional[date] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    location: str = Field(default="", max_length=200)
    registration_url: str = Field(default="", max_length=500)
    description: str = ""

    @field_validator("start_time", "end_time")
    @classmethod
    def check_time(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return None
        if not _TIME_RE.match(v):
            raise ValueError("시간은 HH:MM 형식이어야 합니다.")
        return v

    @field_validator("registration_url")
    @classmethod
    def check_registration_url(cls, v: str) -> str:
        v = (v or "").strip()
        if v and not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("신청 링크는 http:// 또는 https:// 로 시작해야 합니다.")
        return v


class EventDateSlot(BaseModel):
    """일정 하나를 여러 날짜에 걸쳐 등록할 때, 날짜별 칸 하나.

    장소는 날짜마다 다를 수 있다(1회차는 본관 강당, 2회차는 실습동 등).
    비워두면 공통 장소(EventBatchIn.location)를 쓴다.
    """
    start_date: date
    end_date: Optional[date] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    location: str = Field(default="", max_length=200)

    @field_validator("start_time", "end_time")
    @classmethod
    def check_time(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return None
        if not _TIME_RE.match(v):
            raise ValueError("시간은 HH:MM 형식이어야 합니다.")
        return v


class EventBatchIn(BaseModel):
    """제목·설명 등은 공통으로 두고, 날짜만 여러 개 한 번에 등록한다
    (같은 설명회를 여러 날짜에 걸쳐 진행하는 경우).

    location 은 날짜 칸에 장소를 안 적었을 때만 쓰는 기본값이다."""
    kind: Literal["admission", "briefing"] = "admission"
    title: str
    location: str = Field(default="", max_length=200)
    registration_url: str = Field(default="", max_length=500)
    description: str = ""
    dates: List[EventDateSlot] = Field(min_length=1, max_length=30)

    @field_validator("registration_url")
    @classmethod
    def check_registration_url(cls, v: str) -> str:
        v = (v or "").strip()
        if v and not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("신청 링크는 http:// 또는 https:// 로 시작해야 합니다.")
        return v


class EventUpdate(BaseModel):
    """일정 수정. 준 필드만 바꾼다(부분 수정)."""
    kind: Optional[Literal["admission", "briefing"]] = None
    title: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    location: Optional[str] = Field(default=None, max_length=200)
    registration_url: Optional[str] = Field(default=None, max_length=500)
    description: Optional[str] = None

    @field_validator("start_time", "end_time")
    @classmethod
    def check_time(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return None
        if not _TIME_RE.match(v):
            raise ValueError("시간은 HH:MM 형식이어야 합니다.")
        return v

    @field_validator("registration_url")
    @classmethod
    def check_registration_url(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        if v and not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("신청 링크는 http:// 또는 https:// 로 시작해야 합니다.")
        return v


# ---------- 플랜 ----------
class PlanInfo(BaseModel):
    plan: Plan
    label: str
    price_per_month: int
    rank: int
    perks: List[str]


class OrderIn(BaseModel):
    tax_email: str = ""      # 세금계산서 받을 이메일
    tax_manager: str = ""    # 담당자명
    plan: Plan
    months: int = Field(ge=1, le=36)
    note: str = ""


class OrderOut(BaseModel):
    id: int
    school_id: int
    school_name: str
    plan: Plan
    months: int
    amount: int
    status: OrderStatus
    status_label: str = ""
    note: str
    deposit_code: str = ""
    tax_email: str = ""
    tax_manager: str = ""
    created_at: datetime
    due_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None
    handled_at: Optional[datetime]

    class Config:
        from_attributes = True


# ---------- 학교 문의 (Q&A) ----------
class InquiryCreate(BaseModel):
    """방문자가 학교에 남기는 질문. 로그인 없이도 남길 수 있다."""

    asker_name: str = Field(default="", max_length=60)
    contact_email: EmailStr  # 답변을 받을 이메일(필수)
    # 메일이 반송되거나 주소를 잘못 적는 일이 잦아, 학교가 연락할 길을
    # 하나 더 받아 둔다.
    contact_phone: str = Field(min_length=9, max_length=30)
    question: str = Field(min_length=5, max_length=2000)
    # 개인정보 수집·이용 동의. 반드시 True 여야 접수된다.
    privacy_consent: bool

    @field_validator("privacy_consent")
    @classmethod
    def must_consent(cls, v: bool) -> bool:
        if not v:
            raise ValueError("개인정보 수집·이용에 동의해야 문의를 남길 수 있습니다.")
        return v


class InquiryOut(BaseModel):
    """학교 계정이 보는 문의 상세. 답변하려면 연락처가 보여야 한다."""

    id: int
    asker_name: str
    contact_email: EmailStr
    contact_phone: str
    question: str
    status: InquiryStatus
    answer: str
    answered_at: Optional[datetime]
    delivery_status: DeliveryStatus
    delivery_error: str
    created_at: datetime

    class Config:
        from_attributes = True


class InquiryAnswer(BaseModel):
    answer: str = Field(min_length=1, max_length=4000)


# ---------- 학교 계정 생성(관리자 전용) ----------
class SchoolAccountIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    name: str
    school_id: int


# ---------- 통계 ----------
class DailyPoint(BaseModel):
    day: str
    count: int


class SchoolStatsOut(BaseModel):
    view_count: int
    favorite_count: int
    plan: Plan
    plan_expires_at: Optional[date]
    search_rank_hint: int
    daily_views: List[DailyPoint]


class AdminStatsOut(BaseModel):
    school_count: int
    student_count: int
    school_account_count: int
    pending_orders: int
    monthly_revenue: int          # 이번 달 결제 완료 순매출(매출 − 환불)
    revenue: dict = {}            # 이번 달·지난달·전체 결제 완료 명세
    plan_distribution: dict
    region_distribution: dict
    top_viewed: List[dict]
    quiz_stats: dict = {}


# ---------- 진로 적성 테스트 ----------
class GeocodeOut(BaseModel):
    lat: float
    lng: float
    address: str


class QuizSubmit(BaseModel):
    answers: List[str] = Field(description="문항별 1~5 점 척도 문자열")
    # 어떤 문항을 보고 답했는지. 회차마다 문항이 달라지므로 이 값으로
    # 학생이 본 문항을 되살려 채점한다. 없으면 예전 고정 문항으로 본다.
    seed: Optional[int] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    location_label: str = ""
    commute_time: str = Field(description="TIME_OPTIONS의 key (30m/1h/1h30/2h/any)")


class QuizDeptOut(BaseModel):
    label: str
    axis: str
    axis_label: str
    desc: str
    jobs: List[str]


class QuizSchoolOut(BaseModel):
    id: int
    name: str
    region: str
    address: str
    category: str
    coed: str
    dormitory: Optional[bool]
    plan: str
    matched_departments: List[str]
    distance_km: Optional[float]
    distance_approx: bool


class QuizResultOut(BaseModel):
    scores: dict
    sub_scores: dict
    top_axes: List[str]
    quality: dict
    confidence: str
    axis_labels: dict
    departments: List[QuizDeptOut]
    schools: List[QuizSchoolOut]
    location_label: str
    has_location: bool
    shows_distance: bool
    commute_label: str
    matched_count: int


# ---------- 기사 ----------
class ArticleOut(BaseModel):
    id: int
    url: str
    title: str
    summary: str
    thumbnail: str
    published_at: Optional[date]
    school_id: Optional[int]
    school_name: Optional[str] = None
    source: str

    class Config:
        from_attributes = True


class ArticleManualCreate(BaseModel):
    url: str = Field(min_length=8)
    title: str = Field(min_length=2, max_length=300)
    summary: str = ""
    thumbnail: str = ""
    school_id: Optional[int] = None


# ---------- 학교생활 일지 / 수업 일지 ----------
class JournalIn(BaseModel):
    kind: Literal["lesson", "diary"] = "diary"
    entry_date: Optional[date] = None
    subject: str = ""
    teacher_name: str = ""
    content: dict = {}
    resume_tags: List[str] = []


class ResumeRequest(BaseModel):
    template: str = "school_life"


class JournalSend(BaseModel):
    teacher_email: EmailStr


# ---------- 선생님 계정 ----------
class TeacherRegisterStudent(BaseModel):
    user_id: int
    class_name: str = ""


class VerifyApprove(BaseModel):
    class_name: str = ""


class PlanPerksIn(BaseModel):
    """플랜에서 켤 혜택 항목의 키 목록. reset=True 면 기본값으로 되돌린다."""
    keys: List[str] = []
    reset: bool = False


class BankInfoIn(BaseModel):
    bank_name: Optional[str] = None
    bank_account: Optional[str] = None
    bank_holder: Optional[str] = None
    payment_note: Optional[str] = None
    due_days: Optional[str] = None


# ---------- 공지 ----------
class NoticeIn(BaseModel):
    scope: str = "all"                 # all | school | teachers
    school_id: Optional[int] = None
    title: str
    body: str = ""
    image_url: str = ""
    is_popup: bool = False
    is_important: bool = False
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None


class SubscriptionOrderIn(BaseModel):
    """구독 주문 생성. 금액은 서버가 정하므로 받지 않는다."""
    months: int = Field(default=1, ge=1, le=12)
    # 만 19세 미만일 때 필요한 법정대리인 동의(민법 제5조)
    minor_consent: bool = False
    guardian_contact: str = Field(default="", max_length=120)


class PaymentConfirmIn(BaseModel):
    """토스 결제창 성공 후 서버 승인 요청."""
    payment_key: str = Field(min_length=1, max_length=200)
    order_id: str = Field(min_length=1, max_length=64)
    amount: int = Field(ge=0)


class SpellCheckIn(BaseModel):
    """맞춤법 검사 요청. 항목별로 한꺼번에 보낼 수도 있다."""
    text: str = Field(default="", max_length=20000)
    fields: dict = Field(default_factory=dict)


class CoverLetterIn(BaseModel):
    """개인 자기소개서 저장."""
    title: str = Field(default="", max_length=120)
    template: str = Field(default="", max_length=40)
    content: dict = Field(default_factory=dict)


class MyAccountIn(BaseModel):
    """마이페이지에서 본인이 고칠 수 있는 항목.

    휴대폰번호는 본인확인 수단이라 여기서 바꿀 수 없다.
    ChangePhoneIn(POST /api/me/change-phone)으로만 변경한다.
    """
    name: str


class ChangePhoneIn(BaseModel):
    """등록된 휴대폰번호 변경. 현재 비밀번호 + 새 번호 SMS 인증이 모두 필요하다."""
    current_password: str
    new_phone: str = Field(min_length=10, max_length=30)
    phone_verification_token: str = Field(min_length=1)


class FloatingButtonIn(BaseModel):
    """오른쪽 아래 플로팅 버튼 설정."""
    enabled: bool = False
    url: str = ""
    label: str = "바로가기"
    roles: List[str] = ["school", "teacher"]
    # "link"(주소 열기) 또는 "inquiry"(교육·컨설팅 문의 폼 띄우기)
    action: str = "link"
