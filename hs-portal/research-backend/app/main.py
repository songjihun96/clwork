"""기록해(diary.ggm.kr) 백엔드.

UDJ 와 별개의 서비스다. 자체 DB 에 일지·자기소개서·구독을 저장하고,
계정만 UDJ 에 맡긴다.

  - 학생   : 일지·일기 작성, 선생님께 제출, 자기소개서(구독)
  - 선생님 : 담당 학급 학생이 제출한 기록 열람
  - 학교   : 우리 학교 학생의 제출 기록 열람
  - 관리자 : 구독 결제 승인, 이용 현황, 감사 로그
"""

import hashlib
import json
import os
import random
import re
import secrets
import statistics
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, File, Form, UploadFile
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import and_, func, inspect as sa_inspect, or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import (ai, ai_jobs, ai_service, dept_fields, doc_store, fonts, image_store,
               llm, mailer, research_ai, research_export)
from .auth import (
    create_access_token, get_current_user, get_current_user_optional,
    hash_password, require_admin, require_journal_viewer, require_roles,
    require_student, verify_password,
)
from .database import Base, SessionLocal, engine, get_db
from .models import (
    ORDER_STATUS_LABEL, AuditLog, CoverLetter, JournalEntry, OrderStatus, Role,
    AiConsent, AiJob, JournalAnalysis,
    SchoolSeat, SchoolSubject, SeatCode, SeatHolder, SeatOrder, Setting, Subscription,
    SubscriptionOrder, UnmatchedDeposit, User,
    TeacherSubjectAssignment, StudentEnrollment, StudentRecordAiDraft,
    TeacherObservation, TeacherObservationTemplate, Portfolio, PortfolioPage, PortfolioBlock, PortfolioImage,
    PortfolioSource, Experience, ExperienceSource, PortfolioThemeRecommendation,
    ResearchProject, ResearchDialogueTurn, ResearchTopicSuggestion,
    ResearchRoadmapStep, ResearchTask,
    ResearchLiterature, ResearchData, ResearchAnalysis, ResearchReview,
    ResearchReport, ResearchFeedback,
    ResearchPaper, ResearchPortfolio, PAPER_SECTION_KEYS, PORTFOLIO_SECTION_KEYS,
    ResearchTeam, ResearchTeamMember, ResearchTeamRoleHistory, ResearchTeamInvite,
    ResearchTeamLeaveRequest, ResearchBoardPost,
    ExternalQuestion, ExternalAnswer, ExternalAnswerFeedback, ExternalAnswerNote,
    TeacherFieldTag, ExternalAnswerSeen,
)

Base.metadata.create_all(bind=engine)


def _ensure_columns() -> None:
    """이미 만들어진 표에 새 칸을 채워 넣는다.

    create_all 은 없는 표만 만들고, 기존 표에 칸을 더하지는 않는다.
    운영 중인 DB 에 배포할 때 여기서 메운다. 이미 있으면 건너뛴다.
    """
    wanted = {
        "journal_entries": {
            "feedback": "TEXT DEFAULT ''",
            "feedback_by": "INTEGER",
            "feedback_by_name": "VARCHAR(60) DEFAULT ''",
            "feedback_at": "TIMESTAMP",
            "feedback_read_at": "TIMESTAMP",
            # lesson 일지가 가리키는 과목. 세특을 과목별로 완전히 분리하는 열쇠다.
            # 예전 글은 비어 있고, 그때는 자유문자열 subject 만으로 화면에 보인다.
            "subject_id": "INTEGER",
            "title": "VARCHAR(120) DEFAULT ''",
        },
        "seat_orders": {
            "discount_percent": "INTEGER DEFAULT 0",
            "product": "VARCHAR(20) DEFAULT 'essay'",
        },
        "seat_codes": {
            # 코드를 만든 선생님의 학급. 학생이 코드를 넣으면 그대로 배정된다.
            "grade": "INTEGER",
            "class_no": "VARCHAR(20) DEFAULT ''",
            "department": "VARCHAR(60) DEFAULT ''",
            "product": "VARCHAR(20) DEFAULT 'essay'",
        },
        "ai_jobs": {
            # 같은 학생이 같은 요청을 연타해도 작업이 중복 생기지 않도록
            # 막는 열쇠. kind+무엇에 대한 것인지(테마/포트폴리오/기록 id 등)를
            # 묶어 만든다. None이면(예전 작업) 중복 검사에서 그냥 빠진다.
            "dedup_key": "VARCHAR(200)",
        },
        "student_record_ai_drafts": {
            # 세특 초안이 수업일지에서 나왔는지 교사 관찰 기록에서 나왔는지.
            # 예전 행은 전부 수업일지 기반이었으므로 기본값을 journal로 둔다.
            "source_kind": "VARCHAR(20) DEFAULT 'journal'",
        },
        "subscription_orders": {
            "depositor_name": "VARCHAR(40) DEFAULT ''",
            "bank_key": "VARCHAR(20) DEFAULT ''",
            "refund_amount": "INTEGER DEFAULT 0",
            "refund_bank": "VARCHAR(40) DEFAULT ''",
            "refund_account": "VARCHAR(60) DEFAULT ''",
            "refund_holder": "VARCHAR(40) DEFAULT ''",
            "refund_paid_at": "TIMESTAMP",
            "refund_denied_at": "TIMESTAMP",
            "refund_denied_reason": "VARCHAR(300) DEFAULT ''",
            "refund_account_issue": "VARCHAR(200) DEFAULT ''",
            "refund_reason": "VARCHAR(200) DEFAULT ''",
        },
        "research_literature": {
            # 학생이 직접 올린 첨부파일(논문 PDF 등). M5 이후 배포에 추가됐다.
            "file_key": "VARCHAR(300) DEFAULT ''",
            "file_name": "VARCHAR(200) DEFAULT ''",
        },
        "research_projects": {
            # 날짜 계산 대신 학생이 직접 넘기는 주차. 기존 행은 1주차로 시작한다.
            "current_week": "INTEGER DEFAULT 1",
            # 학생이 쉬운 말로 쓴 계획을 전문 연구 구조로 번역해 둔 것(학생 비노출).
            "structure_json": "TEXT DEFAULT '{}'",
            "difficulty_level": "VARCHAR(10) DEFAULT 'easy'",
        },
        "research_tasks": {
            "guide": "TEXT DEFAULT ''",
        },
        # 좌석을 상품별(자기소개서/연구)로 나눈다. 기존 행은 전부 이 상품
        # 개념이 생기기 전이라 "essay"로 채운다 — 지금까지의 자소서 좌석과
        # 정확히 같은 뜻이라 동작이 그대로 유지된다.
        # 주의: school_seats.school_id 단일 유니크 제약은 옛 배포 DB에
        # 그대로 남아 있어(ALTER TABLE로는 제약을 못 바꾼다), 같은 학교가
        # research 좌석을 새로 만들려는 순간 충돌한다. 그 전에 운영 DB에서
        # 수동으로 `ALTER TABLE school_seats DROP CONSTRAINT school_seats_school_id_key,
        # ADD CONSTRAINT uq_school_seat_product UNIQUE (school_id, product);`
        # (seat_holders 의 uq_seat_once 도 동일하게) 를 한 번 실행해야 한다 —
        # 지금은 실사용자가 0명이라 이 문서에만 남겨 둔다.
        "school_seats": {"product": "VARCHAR(20) DEFAULT 'essay'"},
        "seat_holders": {"product": "VARCHAR(20) DEFAULT 'essay'"},
    }
    insp = sa_inspect(engine)
    with engine.begin() as conn:
        for table, cols in wanted.items():
            if not insp.has_table(table):
                continue
            have = {c["name"] for c in insp.get_columns(table)}
            for col, ddl in cols.items():
                if col in have:
                    continue
                try:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
                    print(f"[기록해] {table}.{col} 추가", flush=True)
                except Exception as exc:
                    print(f"[기록해] {table}.{col} 추가 실패: {exc}", flush=True)


def _fix_seat_unique_constraints() -> None:
    """좌석을 상품별(essay/research)로 나누면서 유니크 제약도 함께 넓어져야
    하는데, ALTER TABLE ADD COLUMN 만으로는 기존 제약이 그대로 남는다 —
    운영 DB에 이미 essay 좌석이 있는 학교가 research 좌석을 만들려는 순간
    이 옛 제약에 막혀 500 이 난다(실제로 겪은 문제).

    처음엔 information_schema.table_constraints 만 봤는데, 실제 운영 DB를
    열어보니 school_seats.school_id 쪽은 SQLAlchemy가 `unique=True,
    index=True`를 함께 준 컬럼이라 이름 있는 제약이 아니라 그냥 유니크
    "인덱스"(ix_school_seats_school_id)로 만들어져 있었다 — 이런 건
    table_constraints 에 안 잡힌다. 그래서 pg_index/pg_constraint 를 직접
    봐서, 제약이든 이름 없는 유니크 인덱스든 전부 찾는다.

    여러 워커가 동시에 시작하면서 같은 걸 동시에 고치려 들면 한쪽이
    "이미 있음" 에러를 내고 그 안에서 트랜잭션이 통째로 막히는 걸 실제로
    봤다(에러 자체는 걸러지니 서버가 죽지는 않지만 지저분하다) —
    advisory lock 으로 한 번에 한 워커만 고치게 한다.

    Postgres 에서만 의미가 있다(운영 DB). SQLite(로컬/테스트)는 매번 새로
    만드는 파일이라 손댈 필요가 없다.
    """
    if engine.dialect.name != "postgresql":
        return

    # (table, 옛 제약/인덱스가 걸려 있던 컬럼 집합, 새로 있어야 하는 컬럼 목록)
    wanted = [
        ("school_seats", {"school_id"}, ["school_id", "product"]),
        ("seat_holders", {"school_id", "user_id"}, ["school_id", "user_id", "product"]),
    ]
    # 같은 서버 안의 여러 gunicorn 워커가 동시에 시작해도 이 번호로 한
    # 워커만 실제로 고치고 나머지는 끝날 때까지 기다렸다가 이미 됐음을
    # 보고 조용히 넘어간다(임의로 고른 상수 — 다른 잠금과 안 겹치면 된다).
    LOCK_KEY = 727271
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": LOCK_KEY})
        for table, old_cols, new_cols in wanted:
            try:
                rows = conn.execute(text("""
                    SELECT i.relname AS index_name, con.conname AS constraint_name,
                           array_agg(a.attname ORDER BY k.ord) AS cols
                    FROM pg_class t
                    JOIN pg_index ix ON t.oid = ix.indrelid
                    JOIN pg_class i ON i.oid = ix.indexrelid
                    JOIN unnest(ix.indkey) WITH ORDINALITY AS k(attnum, ord) ON true
                    JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum
                    LEFT JOIN pg_constraint con ON con.conindid = ix.indexrelid
                    WHERE t.relname = :table AND ix.indisunique AND NOT ix.indisprimary
                    GROUP BY i.relname, con.conname
                """), {"table": table}).fetchall()
            except Exception as exc:
                print(f"[기록해] {table} 인덱스 조회 실패: {exc}", flush=True)
                continue

            has_new = False
            for index_name, constraint_name, cols in rows:
                cols_set = set(cols)
                label = constraint_name or index_name
                if cols_set == old_cols:
                    try:
                        if constraint_name:
                            conn.execute(text(f'ALTER TABLE {table} DROP CONSTRAINT "{constraint_name}"'))
                        else:
                            conn.execute(text(f'DROP INDEX "{index_name}"'))
                        print(f"[기록해] {table}.{label} 옛 제약/인덱스 제거", flush=True)
                    except Exception as exc:
                        print(f"[기록해] {table}.{label} 제거 실패: {exc}", flush=True)
                elif cols_set == set(new_cols):
                    has_new = True

            if not has_new:
                col_list = ", ".join(new_cols)
                try:
                    conn.execute(text(
                        f"ALTER TABLE {table} ADD CONSTRAINT uq_{table}_{'_'.join(new_cols)} "
                        f"UNIQUE ({col_list})"))
                    print(f"[기록해] {table} 새 제약 추가({col_list})", flush=True)
                except Exception as exc:
                    print(f"[기록해] {table} 새 제약 추가 실패: {exc}", flush=True)


def _fix_research_teams_schema() -> None:
    """research_teams 표가 이번 공동연구 기능 코드보다 먼저(이름이 다른
    이전 시도로) 운영 DB에 만들어져 있던 적이 있다 — leader_id/updated_at
    라는, 지금 코드 어디에서도 안 쓰는 컬럼이 있고 정작 지금 모델이 쓰는
    created_by 는 없었다(실제로 겪은 문제 1: 팀 초대 목록 조회가 이 컬럼이
    없어서 500). 컬럼을 추가하는 것만으론 안 끝난다 — leader_id 가 옛날
    그대로 NOT NULL 이라, 지금 코드는 이 컬럼을 채우지 않으니 팀 연구를
    새로 만들 때마다 이 제약에 막혀 또 500 이 났다(실제로 겪은 문제 2).
    이 컬럼은 이제 아무도 안 읽으니 지우는 대신 NULL 을 허용하도록만
    고친다(굳이 지울 필요 없는 데이터라 더 안전한 쪽을 택한다).
    research_id 유니크 제약(연구 하나에 팀은 하나)도 옛 표에는 없었다.
    """
    insp = sa_inspect(engine)
    if not insp.has_table("research_teams"):
        return
    have = {c["name"] for c in insp.get_columns("research_teams")}

    with engine.begin() as conn:
        if "created_by" not in have:
            try:
                conn.execute(text("ALTER TABLE research_teams ADD COLUMN created_by INTEGER"))
                if "leader_id" in have:
                    conn.execute(text(
                        "UPDATE research_teams SET created_by = leader_id WHERE created_by IS NULL"))
                print("[기록해] research_teams.created_by 추가(옛 leader_id 값 이어받음)", flush=True)
            except Exception as exc:
                print(f"[기록해] research_teams.created_by 추가 실패: {exc}", flush=True)

        if "leader_id" in have and engine.dialect.name == "postgresql":
            try:
                is_nullable = next(
                    (c.get("nullable", True) for c in insp.get_columns("research_teams")
                     if c["name"] == "leader_id"), True)
                if not is_nullable:
                    conn.execute(text("ALTER TABLE research_teams ALTER COLUMN leader_id DROP NOT NULL"))
                    print("[기록해] research_teams.leader_id NOT NULL 해제(안 쓰는 옛 컬럼)", flush=True)
            except Exception as exc:
                print(f"[기록해] research_teams.leader_id NOT NULL 해제 실패: {exc}", flush=True)

        if engine.dialect.name == "postgresql":
            try:
                existing = conn.execute(text(
                    "SELECT 1 FROM pg_constraint WHERE conrelid = 'research_teams'::regclass "
                    "AND contype = 'u'")).first()
                if not existing:
                    conn.execute(text(
                        "ALTER TABLE research_teams ADD CONSTRAINT uq_research_teams_research_id "
                        "UNIQUE (research_id)"))
                    print("[기록해] research_teams.research_id 유니크 제약 추가", flush=True)
            except Exception as exc:
                print(f"[기록해] research_teams.research_id 유니크 제약 추가 실패: {exc}", flush=True)


_ensure_columns()
_fix_seat_unique_constraints()
_fix_research_teams_schema()

# 자소서 PDF 는 서버가 글자를 직접 그려서 한글 글꼴이 있어야 한다.
# 없으면 PDF 만 조용히 실패하므로, 시작할 때 미리 확인해 로그에 남긴다.
# 학생이 눌러 보고 나서야 아는 것보다 낫다.
fonts.find_font()

app = FastAPI(title="기록해 API", version="1.0.0")

_allowed = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]

_cors_kwargs = dict(
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
if _allowed:
    _cors_kwargs["allow_origins"] = _allowed
else:
    _cors_kwargs["allow_origin_regex"] = (
        r"http://(localhost|127\.0\.0\.1|192\.168\.\d{1,3}\.\d{1,3}|"
        r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
        r"172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}):(5173|5174|5175|4173)"
    )

app.add_middleware(CORSMiddleware, **_cors_kwargs)


# ══════════════════════════════════════════════════════════
# 스키마
# ══════════════════════════════════════════════════════════
class LoginIn(BaseModel):
    email: EmailStr
    password: str


class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    name: str = Field(min_length=2, max_length=60)
    phone: str = Field(min_length=10, max_length=30)
    phone_verification_token: str = Field(min_length=1)
    birth_date: date
    guardian_email: Optional[EmailStr] = None
    privacy_consent: bool
    terms_consent: bool


class ProfileIn(BaseModel):
    name: Optional[str] = Field(default=None, max_length=60)
    department: Optional[str] = Field(default=None, max_length=60)
    grade: Optional[int] = Field(default=None, ge=1, le=3)


class PasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=200)


class DeleteIn(BaseModel):
    password: str


class JournalIn(BaseModel):
    kind: str = Field(default="diary", pattern="^(diary|lesson)$")
    entry_date: date
    title: str = Field(default="", max_length=120)
    subject: str = Field(default="", max_length=80)
    teacher_name: str = Field(default="", max_length=60)
    content: dict = Field(default_factory=dict)


class CoverLetterIn(BaseModel):
    title: str = Field(default="", max_length=120)
    content: dict = Field(default_factory=dict)


class WritingReviewIn(BaseModel):
    """자기소개서 점검 요청."""
    fields: dict = Field(default_factory=dict)
    limit: int = Field(default=1000, ge=100, le=5000)


class SpellCheckIn(BaseModel):
    text: str = Field(default="", max_length=20000)
    fields: dict = Field(default_factory=dict)


# ── 포트폴리오 ────────────────────────────────────────────
class PortfolioIn(BaseModel):
    title: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=1000)
    purpose: str = Field(default="free")
    theme_type: str = Field(default="custom")
    career_goal: str = Field(default="", max_length=120)


class PortfolioPatchIn(BaseModel):
    title: Optional[str] = Field(default=None, max_length=120)
    description: Optional[str] = Field(default=None, max_length=1000)
    purpose: Optional[str] = None
    theme_type: Optional[str] = None
    career_goal: Optional[str] = Field(default=None, max_length=120)
    visibility: Optional[str] = None
    status: Optional[str] = None
    cover_image_id: Optional[int] = None


class PortfolioPageIn(BaseModel):
    title: str = Field(default="새 페이지", max_length=120)


class PortfolioBlockIn(BaseModel):
    block_type: str
    content: dict = Field(default_factory=dict)
    style: dict = Field(default_factory=dict)


class MoveIn(BaseModel):
    direction: str = Field(pattern="^(up|down)$")


class ThemeRecommendIn(BaseModel):
    pass


class PortfolioGenerateIn(BaseModel):
    theme_type: str
    purpose: str = Field(default="free")
    journal_ids: List[int] = Field(default_factory=list)


class ExperienceExtractIn(BaseModel):
    journal_id: int


class ExperienceIn(BaseModel):
    title: str = Field(default="", max_length=120)
    type: str = Field(default="", max_length=30)
    situation: str = Field(default="", max_length=1000)
    problem: str = Field(default="", max_length=1000)
    action: str = Field(default="", max_length=1000)
    result: str = Field(default="", max_length=1000)
    lesson: str = Field(default="", max_length=1000)


class ProofreadIn(BaseModel):
    text: str = Field(max_length=3000)
    action: str = Field(pattern="^(TEXT_EDIT|TEXT_SHORTEN|TEXT_EXPAND|TEXT_PROOFREAD|TITLE_SUGGEST)$")


class TeacherObservationIn(BaseModel):
    student_id: int
    observed_at: Optional[date] = None   # 안 주면 오늘 날짜
    title: str = Field(default="", max_length=120)
    journal_id: Optional[int] = None
    subject_id: Optional[int] = None
    content: str = Field(min_length=1, max_length=2000)


class TeacherObservationPatchIn(BaseModel):
    observed_at: Optional[date] = None
    title: Optional[str] = Field(default=None, max_length=120)
    journal_id: Optional[int] = None
    subject_id: Optional[int] = None
    content: str = Field(min_length=1, max_length=2000)


class ObservationTemplateIn(BaseModel):
    title: str = Field(min_length=1, max_length=60)
    content: str = Field(min_length=1, max_length=500)


# ══════════════════════════════════════════════════════════
# 공통
# ══════════════════════════════════════════════════════════
def upsert_user(db: Session, profile: dict) -> User:
    """UDJ 가 준 프로필로 사본을 만들거나 갱신한다.

    udj_user_id 를 기준으로 찾는다. 이메일은 바뀔 수 있어 기준이 될 수 없다.
    """
    user = db.query(User).filter(User.udj_user_id == profile["udj_user_id"]).first()
    if not user:
        user = User(udj_user_id=profile["udj_user_id"])
        db.add(user)
    user.apply_profile(profile)
    user.last_login_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return user


def user_out(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role.value,
        "school_name": user.school_name or "",
        "department": user.department or "",
        "grade": user.grade,
        "class_name": user.class_name or "",
        "teacher_id": user.teacher_id,
    }


def write_audit(db: Session, request: Optional[Request], actor: Optional[User],
                action: str, target_type: str = "", target_id="", detail: str = "") -> None:
    """기록 실패가 본 기능을 막지 않도록 예외를 삼킨다."""
    try:
        ip, agent = "", ""
        if request is not None:
            ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
                  or (request.client.host if request.client else ""))
            agent = request.headers.get("user-agent", "")[:200]
        db.add(AuditLog(
            actor_id=actor.id if actor else None,
            actor_email=(actor.email if actor else "")[:120],
            actor_role=(actor.role.value if actor and actor.role else "")[:20],
            action=action[:60], target_type=target_type[:40],
            target_id=str(target_id)[:40], detail=detail[:300],
            ip=ip[:45], user_agent=agent,
        ))
        db.commit()
    except Exception as exc:
        db.rollback()
        print(f"[감사로그] 기록 실패: {exc}", flush=True)


def journal_content(e: JournalEntry) -> dict:
    try:
        data = json.loads(e.content or "{}")
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


# ══════════════════════════════════════════════════════════
# 계정 — 이 서비스가 직접 만들고 확인한다
#
# 기록해는 UDJ 에 계정 확인을 맡겼지만, 여기는 별도 사이트라 기댈 곳이 없다.
# 가입·로그인·비밀번호를 모두 여기서 다룬다.
# ══════════════════════════════════════════════════════════
class LocalSignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    name: str = Field(min_length=1, max_length=60)
    role: str = Field(default="student", pattern="^(student|teacher)$")
    school_name: str = Field(default="", max_length=120)
    privacy_consent: bool = False
    terms_consent: bool = False


class LocalLoginIn(BaseModel):
    email: EmailStr
    password: str


class LocalProfileIn(BaseModel):
    name: Optional[str] = Field(default=None, max_length=60)
    school_name: Optional[str] = Field(default=None, max_length=120)
    department: Optional[str] = Field(default=None, max_length=60)
    grade: Optional[int] = None
    class_name: Optional[str] = Field(default=None, max_length=40)


class LocalPasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=72)


@app.post("/api/auth/signup")
def signup(payload: LocalSignupIn, db: Session = Depends(get_db)):
    if not (payload.privacy_consent and payload.terms_consent):
        raise HTTPException(status_code=400, detail="약관과 개인정보 수집에 동의해야 합니다.")
    email = str(payload.email).strip().lower()
    if db.query(User).filter(func.lower(User.email) == email).first():
        raise HTTPException(status_code=400, detail="이미 가입된 이메일입니다.")
    user = User(
        email=email, password_hash=hash_password(payload.password),
        name=payload.name.strip(),
        role=Role.teacher if payload.role == "teacher" else Role.student,
        school_name=payload.school_name.strip(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"access_token": create_access_token(user), "user": user_out(user)}


@app.post("/api/auth/login")
def login(payload: LocalLoginIn, db: Session = Depends(get_db)):
    email = str(payload.email).strip().lower()
    user = db.query(User).filter(func.lower(User.email) == email).first()
    # 이메일이 없는 경우와 비밀번호가 틀린 경우를 구분해 알려주지 않는다 —
    # 구분해 주면 어떤 이메일이 가입돼 있는지 훑어볼 수 있다.
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 맞지 않습니다.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="정지된 계정입니다.")
    user.last_login_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return {"access_token": create_access_token(user), "user": user_out(user)}


@app.get("/api/auth/me")
def me(user: User = Depends(get_current_user)):
    return user_out(user)


@app.patch("/api/me")
def update_me(payload: LocalProfileIn, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(user, key, value)
    db.commit()
    db.refresh(user)
    return user_out(user)


@app.post("/api/me/change-password")
def change_password(payload: LocalPasswordIn, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="지금 비밀번호가 맞지 않습니다.")
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"ok": True}


@app.delete("/api/me")
def delete_me(payload: LocalLoginIn = None, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    """계정을 지운다. 연구 자료는 함께 사라진다."""
    user.is_active = False
    user.email = f"deleted-{user.id}@removed.local"
    user.password_hash = ""
    db.commit()
    return {"ok": True}


@app.patch("/api/me/class")
def update_my_class(payload: dict, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """선생님이 자기 담당 학급을 적는다.

    이 값은 기록해에만 둔다. UDJ 로 보내지 않는다.
    담당 학급은 학교마다 부르는 법이 다르고 해마다 바뀌는데,
    UDJ 는 여러 서비스가 함께 쓰는 곳이라 그런 것을 담기에 맞지 않다.

    학생은 이 화면을 쓰지 않는다. 이용권 코드를 넣으면 코드에 담긴
    학급으로 저절로 옮겨진다.
    """
    if user.role not in (Role.teacher, Role.school, Role.admin):
        raise HTTPException(status_code=403,
                            detail="선생님과 학교 계정만 쓸 수 있습니다.")

    if "grade" in payload:
        raw = payload.get("grade")
        try:
            g = int(raw) if str(raw or "").strip() else None
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="학년은 숫자로 적어주세요.")
        if g is not None and not (1 <= g <= 3):
            raise HTTPException(status_code=400, detail="학년은 1~3 사이로 적어주세요.")
        user.grade = g

    if "class_name" in payload:
        user.class_name = str(payload.get("class_name") or "").strip()[:40]
    if "department" in payload:
        user.department = str(payload.get("department") or "").strip()[:60]

    db.commit()
    db.refresh(user)
    write_audit(db, request, user, action="me.class_update", target_type="user",
                target_id=user.id,
                detail=f"{user.grade or ''} {user.class_name} {user.department}".strip())
    return user_out(user)






# ══════════════════════════════════════════════════════════
# 일지 · 일기
# ══════════════════════════════════════════════════════════










def _resolve_subject_id(db: Session, user: User, subject_name: str) -> Optional[int]:
    """학생이 고른 과목 이름을 SchoolSubject id 로 잇는다.

    세특을 과목별로 완전히 가르는 열쇠라, 알 수 있으면 채워 둔다. 같은
    이름이 학과·학년마다 겹치면 학생의 학과·학년에 맞는 쪽을 고른다.
    """
    name = (subject_name or "").strip()
    if not name or not user.school_id:
        return None
    rows = db.query(SchoolSubject).filter(
        SchoolSubject.school_id == user.school_id, SchoolSubject.name == name).all()
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0].id
    for r in rows:
        if r.department == (user.department or "") and r.grade == user.grade:
            return r.id
    for r in rows:
        if r.department == (user.department or ""):
            return r.id
    return rows[0].id
















# ══════════════════════════════════════════════════════════
# 선생님 · 학교 · 관리자 — 제출된 기록 열람
# ══════════════════════════════════════════════════════════
def viewable_students(db: Session, user: User, school_id: Optional[int], scope: str) -> List[int]:
    """이 계정이 볼 수 있는 학생의 내부 ID 목록."""
    if user.role == Role.admin:
        if not school_id:
            raise HTTPException(status_code=400, detail="관리자는 학교를 지정해야 합니다. (school_id)")
        target = school_id
    else:
        if not user.school_id:
            raise HTTPException(status_code=400, detail="소속 학교가 연결되지 않은 계정입니다.")
        target = user.school_id

    q = db.query(User.id).filter(
        User.school_id == target,
        User.role == Role.student,
        User.verified.is_(True),
    )
    if user.role == Role.teacher and scope == "mine":
        # 담임 학급 학생은 당연히 보이고, 담임이 아니어도 담당 과목으로
        # 이미 수업일지를 제출받은 학생은 그 과목만큼 볼 수 있어야 한다 —
        # '담당 과목'을 담임과 별개 개념으로 둔 취지가 그래서다.
        cond = User.teacher_udj_id == user.udj_user_id
        subject_ids = teacher_subject_ids(db, user)
        if subject_ids:
            taught = db.query(JournalEntry.user_id).filter(
                JournalEntry.kind == "lesson",
                JournalEntry.subject_id.in_(subject_ids),
                JournalEntry.sent_at.isnot(None),
            )
            cond = or_(cond, User.id.in_(taught))
        q = q.filter(cond)
    return [row[0] for row in q.all()]


def teacher_subject_ids(db: Session, teacher: User) -> set:
    """이 교사가 담당하는 과목 id 모음. AI 세특을 만들 때 이 안에 없으면 막는다."""
    return {
        r[0] for r in
        db.query(TeacherSubjectAssignment.subject_id)
        .filter(TeacherSubjectAssignment.teacher_id == teacher.id).all()
    }


def assert_can_view_lesson(db: Session, teacher: User, student: User, subject_id: int) -> None:
    """교사가 이 학생의 이 과목 수업일지를 볼 수 있는지 확인한다.

    학급 담당(viewable_students)과 과목 담당(teacher_subject_ids) 둘 다
    맞아야 한다. 담임이라도 담당하지 않는 과목의 세특은 만들 수 없다 —
    과목 기록이 섞이면 안 되기 때문이다.
    """
    if teacher.role == Role.admin:
        return
    if student.id not in viewable_students(db, teacher, None, "mine"):
        raise HTTPException(status_code=403, detail="볼 수 없는 학생입니다.")
    if subject_id not in teacher_subject_ids(db, teacher):
        raise HTTPException(status_code=403, detail="담당 과목이 아닙니다.")


def assert_is_homeroom(db: Session, teacher: User, student: User) -> None:
    """교사가 이 학생의 담임인지 확인한다. 학교생활일지·행동특성은 담임만 다룬다."""
    if teacher.role == Role.admin:
        return
    if teacher.role != Role.teacher or student.teacher_udj_id != teacher.udj_user_id:
        raise HTTPException(status_code=403, detail="담당 학급 학생이 아닙니다.")


def _require_valid_observation_subject(db: Session, teacher: User, subject_id: Optional[int]) -> None:
    """관찰 기록(누가기록)에 붙일 과목을 확인한다.

    담당 과목이 하나라도 배정된 교사는 반드시 그중 하나를 골라야 한다 —
    그래야 나중에 '이 과목 기록만 모아 AI 결과물 도출'이 정확히 그
    과목 것만 쓴다. 아직 담당 과목이 하나도 없는 교사(순수 담임 역할이거나
    배정 전)는 예전처럼 과목 없이도 쓸 수 있게 둔다.
    """
    allowed = teacher_subject_ids(db, teacher)
    if not allowed:
        return
    if subject_id is None:
        raise HTTPException(status_code=400, detail="과목을 선택해주세요.")
    if subject_id not in allowed:
        raise HTTPException(status_code=403, detail="담당 과목이 아닙니다.")






class FeedbackIn(BaseModel):
    text: str = Field(..., max_length=1000)






# ══════════════════════════════════════════════════════════
# 구독
# ══════════════════════════════════════════════════════════
SUBSCRIPTION_DEFAULT_PRICE = int(os.getenv("SUBSCRIPTION_PRICE", "5900") or 5900)
SUBSCRIPTION_DUE_DAYS = 3
ADULT_AGE = 19


def subscription_price(db: Session) -> int:
    row = db.query(Setting).filter(Setting.key == "subscription_price").first()
    if row and str(row.value).isdigit():
        return int(row.value)
    return SUBSCRIPTION_DEFAULT_PRICE


def bank_info(db: Session) -> dict:
    keys = ["bank_name", "bank_account", "bank_holder", "payment_note"]
    rows = {r.key: r.value for r in db.query(Setting).filter(Setting.key.in_(keys)).all()}
    return {k: rows.get(k, "") for k in keys}


def bank_accounts(db: Session) -> List[dict]:
    """등록된 입금 계좌 목록.

    계좌를 여러 개 두면 한도를 나눌 수 있고, 신청이 몰릴 때 서로 다른 곳으로
    안내해 대조가 쉬워진다. 예전처럼 계좌가 하나뿐인 설정도 그대로 쓸 수
    있도록, 목록이 비어 있으면 기존 단일 계좌를 1번 계좌로 본다.
    """
    row = db.get(Setting, "bank_accounts")
    raw = (row.value if row else "") or ""
    if raw.strip():
        try:
            items = json.loads(raw)
            out = []
            for i, it in enumerate(items):
                key = str(it.get("key") or f"acc{i + 1}")[:20]
                out.append({
                    "key": key,
                    "bank_name": str(it.get("bank_name") or "")[:40],
                    "bank_account": str(it.get("bank_account") or "")[:60],
                    "bank_holder": str(it.get("bank_holder") or "")[:40],
                })
            ready = [a for a in out if a["bank_name"] and a["bank_account"] and a["bank_holder"]]
            if ready:
                return ready
        except Exception as exc:
            print(f"[계좌] 목록을 읽지 못했습니다: {exc}", flush=True)

    info = bank_info(db)
    if all(info.get(k, "").strip() for k in ("bank_name", "bank_account", "bank_holder")):
        return [{
            "key": "acc1",
            "bank_name": info["bank_name"],
            "bank_account": info["bank_account"],
            "bank_holder": info["bank_holder"],
        }]
    return []


def find_bank(db: Session, key: str) -> Optional[dict]:
    for a in bank_accounts(db):
        if a["key"] == key:
            return a
    return None


def assign_bank(db: Session) -> str:
    """새 주문에 안내할 계좌를 고른다.

    지금 입금을 기다리는 주문이 적게 몰린 계좌를 준다. 같은 금액이 같은
    계좌에 겹치는 일을 줄이기 위해서다. 다만 이용자가 다른 계좌로 보낼 수도
    있으므로, 이것만으로 구분이 끝났다고 보지는 않는다.
    """
    accounts = bank_accounts(db)
    if not accounts:
        return ""
    if len(accounts) == 1:
        return accounts[0]["key"]

    pending = (db.query(SubscriptionOrder)
               .filter(SubscriptionOrder.status == OrderStatus.pending).all())
    load = {a["key"]: 0 for a in accounts}
    for o in pending:
        if o.bank_key in load:
            load[o.bank_key] += 1

    # 대기 건수가 모두 같으면 min() 은 늘 첫 계좌를 고른다. 그러면 계좌를
    # 여러 개 둔 뜻이 없어지므로, 직전에 배정한 계좌의 다음 것부터 본다.
    last = db.get(Setting, "bank_last_key")
    order = [a["key"] for a in accounts]
    if last and last.value in order:
        i = order.index(last.value)
        order = order[i + 1:] + order[: i + 1]

    chosen = min(order, key=lambda k: load[k])
    if last is None:
        db.add(Setting(key="bank_last_key", value=chosen))
    else:
        last.value = chosen
    db.commit()
    return chosen


def bank_ready(db: Session) -> bool:
    """입금할 곳을 안내할 수 있는 상태인가.

    안내 문구는 없어도 되지만 은행·계좌번호·예금주가 하나라도 비면
    이용자가 어디로 보내야 할지 알 수 없다.
    """
    return bool(bank_accounts(db))


# 결제 방식. 관리자 화면에서 고른다.
#   auto  — 토스 키가 있으면 카드, 없으면 무통장 (예전과 같은 동작)
#   bank  — 토스 키가 있어도 무통장만 쓴다
#   toss  — 카드만 쓴다
PAYMENT_METHODS = ("auto", "bank", "toss")


def payment_method(db: Session) -> str:
    row = db.get(Setting, "payment_method")
    value = (row.value if row else "") or "auto"
    return value if value in PAYMENT_METHODS else "auto"




def seat_price(db: Session) -> int:
    """1명당 금액. 학년별로 파는 구조라 인원수에 곱한다."""
    row = db.get(Setting, "seat_price")
    try:
        return max(0, int((row.value if row else "") or SEAT_PRICE_DEFAULT))
    except ValueError:
        return SEAT_PRICE_DEFAULT


# 인원이 많을수록 깎아주는 구간. 관리자가 설정에서 켜고 끄며 수치를 정한다.
DEFAULT_TIERS = [{"min": 50, "percent": 5},
                 {"min": 100, "percent": 10},
                 {"min": 300, "percent": 15}]


def discount_tiers(db: Session) -> List[dict]:
    row = db.get(Setting, "seat_discount_tiers")
    raw = (row.value if row else "") or ""
    if not raw.strip():
        return list(DEFAULT_TIERS)
    try:
        items = json.loads(raw)
        out = []
        for it in items:
            m = int(it.get("min") or 0)
            p = int(it.get("percent") or 0)
            if m > 0 and 0 < p < 100:
                out.append({"min": m, "percent": p})
        return sorted(out, key=lambda x: x["min"])
    except Exception:
        return list(DEFAULT_TIERS)


def discount_on(db: Session) -> bool:
    row = db.get(Setting, "seat_discount_enabled")
    # 설정한 적이 없으면 꺼진 것으로 본다. 모르는 사이에 값이 깎이면 안 된다.
    return bool(row and (row.value or "").strip() == "on")


def seat_quote(db: Session, seats: int) -> dict:
    """인원수로 금액을 계산한다.

    화면의 미리보기와 실제 주문이 같은 함수를 쓰게 했다. 두 곳에 따로
    적으면 언젠가 어긋나고, 그러면 보여준 금액과 청구액이 달라진다.
    """
    price = seat_price(db)
    subtotal = seats * price
    percent = 0
    if discount_on(db):
        for t in discount_tiers(db):
            if seats >= t["min"]:
                percent = t["percent"]
    # 원 단위 미만은 버려 이용자에게 유리하게 둔다.
    discount = (subtotal * percent) // 100
    return {
        "seats": seats, "unit_price": price, "subtotal": subtotal,
        "discount_percent": percent, "discount_amount": discount,
        "amount": subtotal - discount,
        "tiers": discount_tiers(db) if discount_on(db) else [],
    }


SEAT_PRODUCT_LABEL = {"essay": "자기소개서", "research": "연구"}


def school_seat(db: Session, school_id: Optional[int], product: str = "essay") -> Optional[SchoolSeat]:
    if not school_id:
        return None
    return db.query(SchoolSeat).filter(SchoolSeat.school_id == school_id,
                                       SchoolSeat.product == product).first()


def subscription_active(db: Session, user: User, product: str = "essay") -> bool:
    """이 상품(자기소개서/연구)을 쓸 수 있는가.

    결제 주체가 학교로 바뀌었다. 학교가 좌석을 사고, 그 좌석을 받은
    학생만 쓸 수 있다. 좌석이 있어도 학교의 이용 기간이 지나면 막힌다.
    상품마다 좌석 풀이 따로다 — 자기소개서 좌석이 있어도 연구 좌석이
    없으면 연구는 못 쓴다.

    예전에 개인이 결제한 구독은 기간이 남아 있는 동안 그대로 인정한다
    (자기소개서에만 있던 레거시라 다른 상품에는 적용하지 않는다 —
    돈을 받아 놓고 갑자기 끊을 수는 없기 때문이다).
    """
    now = datetime.utcnow()

    if product == "essay":
        old_sub = db.query(Subscription).filter(Subscription.user_id == user.id).first()
        if old_sub and old_sub.expires_at > now:
            return True

    seat = school_seat(db, user.school_id, product)
    if not seat or seat.expires_at <= now:
        return False
    holder = db.query(SeatHolder).filter(
        SeatHolder.school_id == user.school_id,
        SeatHolder.user_id == user.id,
        SeatHolder.product == product).first()
    return holder is not None


def _require_product_seat(product: str):
    """이용권 확인 — **이 서비스에는 아직 없다.**

    기록해에서는 학교가 좌석을 사고 그 좌석을 받은 학생만 쓸 수 있었다.
    여기는 별도 사이트로 새로 여는 것이라 결제도 좌석도 아직 없다. 그래서
    로그인만 확인하고 통과시킨다.

    자리를 없애지 않고 남겨 둔 이유는, 연구 엔드포인트 쉰 몇 개가 이
    의존성을 물고 있어서다. 나중에 이 서비스에 맞는 이용권을 붙일 때
    여기 한 곳만 채우면 전부에 걸린다.
    """
    def dependency(user: User = Depends(get_current_user)) -> User:
        return user
    return dependency


require_subscription = _require_product_seat("essay")
require_research_seat = _require_product_seat("research")


def make_deposit_code(db: Session) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    for _ in range(30):
        code = "SUB-" + "".join(random.choices(alphabet, k=4))
        if not db.query(SubscriptionOrder).filter(SubscriptionOrder.deposit_code == code).first():
            return code
    return "SUB-" + secrets.token_hex(3).upper()




def apply_subscription(db: Session, user: User, months: int) -> datetime:
    now = datetime.utcnow()
    sub = db.query(Subscription).filter(Subscription.user_id == user.id).first()
    base = sub.expires_at if (sub and sub.expires_at > now) else now
    expires = base + timedelta(days=30 * months)
    if sub:
        sub.expires_at = expires
    else:
        db.add(Subscription(user_id=user.id, started_at=now, expires_at=expires))
    return expires


# ── 학교 좌석 결제 ─────────────────────────────────────────
#
# 학년별로 영업하는 구조라, 학교가 인원수를 적어 신청하면 그만큼 좌석을
# 산다. 인원은 학교가 스스로 적고 관리자가 확인한 뒤 확정한다. 확인 없이
# 그대로 받으면 인원을 줄여 적는 일을 막을 수 없다.


def require_school_account(user: User = Depends(get_current_user)) -> User:
    if user.role not in (Role.school, Role.admin):
        raise HTTPException(status_code=403, detail="학교 계정만 이용할 수 있습니다.")
    if not user.school_id:
        raise HTTPException(status_code=400, detail="소속 학교가 연결되지 않은 계정입니다.")
    return user


def require_seat_manager(user: User = Depends(get_current_user)) -> User:
    """등록 코드를 다룰 수 있는 계정.

    코드 발급은 학급 단위 업무라 담임 선생님이 직접 하는 편이 빠르다.
    다만 결제(신청)는 학교 계정만 할 수 있게 그대로 둔다.
    """
    if user.role not in (Role.school, Role.teacher, Role.admin):
        raise HTTPException(status_code=403, detail="학교 또는 선생님 계정만 이용할 수 있습니다.")
    if not user.school_id:
        raise HTTPException(status_code=400, detail="소속 학교가 연결되지 않은 계정입니다.")
    return user


# ══════════════════════════════════════════════════════════
# 담당 과목 — 담당 학급(User.class_name, 한 명)과 별개로 교사가 여러 개 가진다.
# ══════════════════════════════════════════════════════════
def subject_assignment_out(a: TeacherSubjectAssignment) -> dict:
    s = a.subject
    return {
        "id": a.id,
        "subject_id": a.subject_id,
        "subject_name": s.name if s else "",
        "department": s.department if s else "",
        "grade": s.grade if s else None,
    }












# ══════════════════════════════════════════════════════════
# 선생님 계정 — 검색·권한부여·해제 (예전에는 UDJ 화면에 있던 기능, 이동해 옴)
# 계정 원본은 여전히 UDJ 뿐이라, 여기서는 매 요청마다 UDJ를 그대로 불러
# 대신 처리한다(partner API, X-Partner-Secret 인증). 담당 과목 배정용
# /api/school/teachers(위, 기록해 로컬 사본)와는 다른 목적이라 경로를
# teacher-accounts 로 분리했다 — 아직 기록해에 한 번도 로그인 안 한
# 선생님도 여기서는 검색·부여가 가능해야 하기 때문이다.












def seat_summary(db: Session, school_id: int, product: str = "essay") -> dict:
    seat = school_seat(db, school_id, product)
    used = db.query(func.count(SeatHolder.id)).filter(
        SeatHolder.school_id == school_id, SeatHolder.product == product).scalar() or 0
    now = datetime.utcnow()
    total = seat.seats if seat else 0
    return {
        "seats": total,
        "used": used,
        "left": max(0, total - used),
        "expires_at": seat.expires_at if seat else None,
        "active": bool(seat and seat.expires_at > now),
        "unit_price": seat_price(db),
    }














# ── 등록 코드 ──────────────────────────────────────────────
#
# 학생 목록에서 한 명씩 체크하는 방식은 200명이 넘어가면 쓸 수 없다.
# 학교가 코드를 만들어 나눠주고 학생이 직접 입력해 좌석을 받게 한다.

# 헷갈리는 글자(0/O, 1/I/L)를 뺐다. 종이로 나눠주면 잘못 읽는 일이 잦다.
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def make_seat_code(db: Session) -> str:
    for _ in range(30):
        body = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        code = f"{body[:4]}-{body[4:]}"
        if not db.query(SeatCode).filter(SeatCode.code == code).first():
            return code
    raise HTTPException(status_code=500, detail="코드를 만들지 못했습니다. 다시 시도해주세요.")


def code_out(x: SeatCode) -> dict:
    return {
        "id": x.id, "code": x.code, "label": x.label or "",
        "product": x.product or "essay",
        "grade": x.grade, "class_no": x.class_no or "",
        "department": x.department or "",
        "max_uses": x.max_uses, "used_count": x.used_count,
        "left": max(0, x.max_uses - x.used_count),
        "is_active": bool(x.is_active),
        "expires_at": x.expires_at, "created_at": x.created_at,
    }












def seat_order_out(db: Session, o: SeatOrder) -> dict:
    return {
        "id": o.id, "product": o.product or "essay",
        "seats": o.seats, "approved_seats": o.approved_seats,
        "unit_price": o.unit_price, "months": o.months, "amount": o.amount,
        "discount_percent": o.discount_percent or 0,
        "note": o.note or "", "status": o.status.value,
        "status_label": ORDER_STATUS_LABEL.get(o.status.value, ""),
        "deposit_code": o.deposit_code, "depositor_name": o.depositor_name or "",
        "bank": find_bank(db, o.bank_key) or bank_info(db),
        "payment_note": bank_info(db).get("payment_note", ""),
        "created_at": o.created_at, "due_at": o.due_at, "paid_at": o.paid_at,
        "admin_note": o.admin_note or "",
        "can_cancel": o.status == OrderStatus.pending,
    }








# ── 관리자: 좌석 주문 확인 ──────────────────────────────────










# ── 취소와 환불 ────────────────────────────────────────────
#
# 전자상거래법 제17조는 디지털 콘텐츠도 7일 안에 청약철회를 할 수 있게 한다.
# 다만 이미 써 버린 콘텐츠는 되돌릴 수 없으므로, 실제로는 두 갈래로 나뉜다.
#
#   1) 7일 안 + 아직 안 씀   → 전액 돌려준다
#   2) 그 밖                  → 남은 기간만큼 일할로 돌려준다
#
# 여기서 '썼다'의 기준은 자기소개서를 하나라도 만들었는지다. 구독의 값어치가
# 거기에 있기 때문이다. 애매하면 이용자에게 유리한 쪽으로 계산한다.

SEAT_PRICE_DEFAULT = 15000     # 1명당 기본 금액
SEAT_MONTHS_DEFAULT = 12       # 한 번 사면 1년
SEAT_DAYS_PER_YEAR = 365       # 연 단위로 판다. 30일*12 로 세면 5일이 모자란다

REFUND_WITHDRAW_DAYS = 7      # 청약철회 기간
DAYS_PER_MONTH = 30           # 구독 1개월을 30일로 셈한다


# 환불 규정 원문.
#
# 위의 두 상수가 뜻하는 기준을 그대로 옮겨 적은 것이다. 분쟁이 생기면
# 화면에 적힌 문구가 기준이 되므로, 계산 규칙을 고칠 때는 이 글도 함께
# 고쳐야 한다. 한쪽만 바꾸면 규정과 다르게 돈이 오간다.
REFUND_POLICY = {
    "service_name": "기록해",
    "effective_date": "2026-08-21",
    "summary": [
        "자기소개서 이용권은 학교가 인원수만큼 신청합니다. 개인은 결제하지 않습니다.",
        "승인 전에 취소하시면 전액 환불됩니다.",
        "이용이 시작된 뒤에는 남은 기간만큼 일할 계산하여 환불합니다.",
        "일지 작성과 선생님께 제출은 무료이며 환불 대상이 아닙니다.",
    ],
    "articles": [
        {
            "title": "제1조 (목적)",
            "body": "이 규정은 기록해(이하 '서비스')가 학교에 제공하는 자기소개서 이용권의 "
                    "청약철회, 계약 해지, 대금 환급의 조건과 절차를 정함을 목적으로 합니다. "
                    "학교가 신청하는 노출 플랜은 이 규정이 아니라 우리동네 직업계고의 "
                    "환불 규정을 따릅니다.",
        },
        {
            "title": "제2조 (이용권의 성격)",
            "body": "① 일지·일기 작성, 선생님께 제출하는 기능, 맞춤법 살펴보기는 무료로 "
                    "제공되며 결제 대상이 아닙니다.\n"
                    "② 유료 결제가 필요한 기능은 자기소개서 작성과 AI 첨삭에 한합니다.\n"
                    "③ 이용권은 학교가 이용 인원수를 정해 신청하며, 요금은 "
                    "'1명당 단가 × 인원수'로 산정합니다. 단가는 서비스 화면에 표시된 금액을 "
                    "따릅니다. 인원수에 따라 단체 할인이 적용될 수 있으며, 적용 여부와 "
                    "할인율은 신청 화면에 표시됩니다.\n"
                    "④ 학교는 확보한 인원수 범위에서 소속 학생에게 이용 권한을 배정하며, "
                    "배정과 회수는 학교가 정합니다.",
        },
        {
            "title": "제3조 (인원 확인과 계약의 성립)",
            "body": "학교가 신청한 인원은 운영자가 확인한 뒤 확정됩니다. 확인 과정에서 "
                    "실제 이용 인원과 차이가 있는 경우 인원과 금액이 조정될 수 있으며, "
                    "조정 사유는 학교에 안내합니다. 계약은 입금이 확인되고 운영자가 승인한 "
                    "시점에 성립하며, 그때부터 이용 기간이 시작됩니다.",
        },
        {
            "title": "제4조 (이용 시작 전 취소)",
            "body": "입금 전 신청은 서비스 화면에서 별도 절차 없이 취소하실 수 있으며, "
                    "입금 기한이 지나면 자동으로 만료됩니다. 입금 후 승인 전에 취소를 "
                    "요청하시면 결제하신 금액 전액을 환불합니다.",
        },
        {
            "title": "제5조 (이용 시작 후 중도 해지)",
            "body": "이용이 시작된 뒤 해지를 요청하시면, 이미 제공된 기간을 제외하고 남은 "
                    "일수에 대해 일할 계산하여 환불합니다. 환불액은 '결제금액 × "
                    "(남은 일수 ÷ 전체 이용일수)'로 계산하며, 원 단위 미만은 버림 "
                    "처리합니다. 별도의 위약금이나 수수료는 받지 않습니다. 이미 제공된 "
                    "기간은 환불 대상이 아닙니다.",
        },
        {
            "title": "제6조 (인원 변경)",
            "body": "이용 기간 중 인원을 늘리시려면 추가로 신청하시면 되며, 좌석이 더해지고 "
                    "이용 기간이 조정됩니다. 인원을 줄이는 경우에는 제5조에 따라 줄어든 "
                    "인원분의 남은 기간을 일할 계산하여 환불합니다. 학생 개인의 "
                    "배정·회수는 학교가 자유롭게 할 수 있으며, 그 자체로는 환불 사유가 "
                    "되지 않습니다.",
        },
        {
            "title": "제7조 (환불 절차)",
            "body": "환불은 학교 담당자가 news@sinmoon.net 또는 070-7867-7970 으로 "
                    "요청하시면 접수됩니다. 접수 후 영업일 기준 7일 이내에 결제하신 계좌 "
                    "또는 학교가 지정한 계좌로 입금해 드립니다. 세금계산서가 이미 발행된 "
                    "경우에는 수정세금계산서를 함께 발행합니다.",
        },
        {
            "title": "제8조 (환불 후 이용)",
            "body": "환불이 처리되면 해당 인원의 이용권이 종료됩니다. 학생이 이미 작성한 "
                    "자기소개서는 삭제되지 않으며 계속 열람할 수 있으나, 새로 작성하거나 "
                    "수정할 수 없습니다. 일지 작성과 선생님께 제출하는 기능은 환불과 "
                    "관계없이 계속 이용하실 수 있습니다.",
        },
        {
            "title": "제9조 (환불이 제한되는 경우)",
            "body": "학교 또는 소속 이용자가 약관을 위반하거나 서비스를 부정하게 이용하여 "
                    "이용이 정지된 경우, 이미 제공된 기간에 대한 환불은 제한될 수 있습니다. "
                    "이 경우 사유를 사전에 서면(이메일)으로 안내합니다.",
        },
        {
            "title": "제10조 (서비스 장애에 따른 보상)",
            "body": "운영자의 귀책사유로 서비스가 연속 24시간 이상 중단된 경우, 중단된 "
                    "기간의 2배에 해당하는 기간을 무상 연장하거나 그에 상응하는 금액을 "
                    "환불합니다. 다만 천재지변이나 사전에 공지한 정기 점검으로 인한 중단은 "
                    "제외합니다.",
        },
        {
            "title": "제11조 (AI 첨삭 결과에 관하여)",
            "body": "자기소개서 첨삭은 AI가 제안하는 참고 자료이며, 진학이나 취업의 결과를 "
                    "보장하지 않습니다. 첨삭 결과에 대한 주관적인 불만족은 환불 사유에 "
                    "해당하지 않으나, 기능이 정상적으로 동작하지 않은 경우에는 제10조에 "
                    "따라 보상해 드립니다.",
        },
        {
            "title": "제12조 (개인이 결제한 기존 이용권)",
            "body": "2026년 8월 21일 이전에 학생 개인이 결제한 이용권은 남은 기간 동안 "
                    "그대로 이용하실 수 있으며, 결제 당시의 규정에 따라 환불합니다. "
                    "해당 이용권의 환불은 서비스 화면의 신청 내역에서 직접 신청하실 수 "
                    "있습니다.",
        },
        {
            "title": "제13조 (규정의 변경)",
            "body": "이 규정은 시행일부터 적용되며, 변경되는 경우 시행 7일 전에 서비스 "
                    "화면에 공지합니다. 이미 결제하신 건에 대해서는 결제 당시의 규정을 "
                    "적용합니다. 문의는 news@sinmoon.net 또는 070-7867-7970 으로 "
                    "연락해 주시기 바랍니다.",
        },
    ],
}






















# ══════════════════════════════════════════════════════════
# 학생 포트폴리오
#
# 학교생활 기록 → AI 테마 추천 → 학생이 테마를 고름 → 관련 기록 연결
# → AI 초안 → 학생이 직접 편집(블록 단위) → 사진 추가 → 완성.
#
# 원본 JournalEntry는 여기서 절대 고치지 않는다. AI가 만들거나 학생이
# 편집한 내용은 전부 PortfolioBlock에 따로 쌓인다 — 원본과 편집본을
# 분리해야 나중에 "이 내용의 근거"를 보여줄 수 있다.
#
# 포트폴리오 만들기·편집·사진 추가는 일지 작성처럼 무료다. AI로 돕는
# 기능(테마 추천·자동 생성·경험 추출·첨삭·사진 설명)만 자기소개서와
# 같은 이용권(require_subscription)이 필요하다 — 이 서비스가 실제로
# 돈을 받는 지점이 AI 보조라는 기존 틀을 그대로 잇는다.
# ══════════════════════════════════════════════════════════




def get_own_portfolio(db: Session, user: User, portfolio_id: int) -> Portfolio:
    p = db.get(Portfolio, portfolio_id)
    if not p or p.student_id != user.id:
        raise HTTPException(status_code=404, detail="포트폴리오를 찾을 수 없습니다.")
    return p


def get_own_page(db: Session, user: User, page_id: int) -> PortfolioPage:
    page = db.get(PortfolioPage, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="페이지를 찾을 수 없습니다.")
    get_own_portfolio(db, user, page.portfolio_id)
    return page


def get_own_block(db: Session, user: User, block_id: int) -> PortfolioBlock:
    block = db.get(PortfolioBlock, block_id)
    if not block:
        raise HTTPException(status_code=404, detail="블록을 찾을 수 없습니다.")
    get_own_page(db, user, block.page_id)
    return block


def page_out(pg: PortfolioPage, blocks: List[PortfolioBlock] = None) -> dict:
    out = {"id": pg.id, "portfolio_id": pg.portfolio_id, "title": pg.title,
           "sort_order": pg.sort_order}
    if blocks is not None:
        out["blocks"] = [block_out(b) for b in blocks]
    return out


def block_out(b: PortfolioBlock) -> dict:
    try:
        content = json.loads(b.content_json or "{}")
    except (ValueError, TypeError):
        content = {}
    try:
        style = json.loads(b.style_json or "{}")
    except (ValueError, TypeError):
        style = {}
    return {"id": b.id, "page_id": b.page_id, "block_type": b.block_type,
           "sort_order": b.sort_order, "content": content, "style": style}


def _reorder(db: Session, rows: List, row) -> None:
    """direction 은 이미 위치를 바꿔 넣은 뒤라고 가정하고, sort_order를
    현재 나열 순서에 맞게 다시 매긴다. 값이 겹치거나 비는 것을 막는다."""
    for i, r in enumerate(rows):
        r.sort_order = i
    db.commit()


@app.get("/api/dept-fields")
def list_dept_fields():
    """학과 계열 선택지. 학생 정보(학과 계열+학과+희망 진로)를 위한 것이다."""
    return {"fields": dept_fields.options()}




















# ── 페이지 ──────────────────────────────────────────────────











# ── 블록 ────────────────────────────────────────────────────











# ── 사진 ────────────────────────────────────────────────────

def image_out(img: PortfolioImage) -> dict:
    return {"id": img.id, "portfolio_id": img.portfolio_id, "page_id": img.page_id,
           "block_id": img.block_id, "title": img.title, "caption": img.caption,
           "sort_order": img.sort_order, "width": img.width, "height": img.height,
           "url": f"/api/portfolio-images/{img.id}",
           "thumbnail_url": f"/api/portfolio-images/{img.id}?variant=thumbnail",
           "created_at": img.created_at}












# ── 경험 ────────────────────────────────────────────────────

def experience_out(e: Experience) -> dict:
    try:
        content = json.loads(e.content_json or "{}")
    except (ValueError, TypeError):
        content = {}
    return {"id": e.id, "title": e.title, "type": e.type, "summary": e.summary,
           **content, "created_at": e.created_at, "updated_at": e.updated_at}














# ── 테마 추천 · 포트폴리오 생성 · 첨삭 ──────────────────────









# ══════════════════════════════════════════════════════════
# 교사 관찰 기록(TeacherObservation)
#
# NEIS 누가기록이나 학교생활기록부를 대신하는 기능이 아니다 — 수업·학교
# 생활에서 교사가 실제로 관찰한 내용을 날짜별로 개인적으로 쌓아 두는,
# 이 서비스만의 독립된 기록이다. JournalEntry.feedback("선생님 한마디")와는
# 완전히 다르다 — feedback은 학생에게 보이라고 남기는 것이고, 이것은
# 정반대로 작성한 교사 본인만 볼 수 있는 기록이다. 다른 교사·학교·관리자·
# 학생 전부 여기 접근할 수 없다. UI에서 숨기는 게 아니라 아래 각 API가
# teacher_id를 직접 대조한다. 학생 포트폴리오 AI 생성에도 이 데이터는
# 절대 재료로 쓰지 않는다(포트폴리오 쪽 코드는 JournalEntry만 조회한다).
# ══════════════════════════════════════════════════════════

def observation_out(n: TeacherObservation) -> dict:
    return {"id": n.id, "student_id": n.student_id, "journal_id": n.journal_id,
           "subject_id": n.subject_id, "subject_name": n.subject.name if n.subject else "",
           "title": n.title or "", "observed_at": n.observed_at, "content": n.content,
           "created_at": n.created_at, "updated_at": n.updated_at}


def _own_observation_or_403(db: Session, user: User, observation_id: int) -> TeacherObservation:
    n = db.get(TeacherObservation, observation_id)
    if not n:
        raise HTTPException(status_code=404, detail="기록을 찾을 수 없습니다.")
    if n.teacher_id != user.id:
        raise HTTPException(status_code=403, detail="본인이 작성한 기록만 다룰 수 있습니다.")
    return n
















# ── 교사 개인 문구 템플릿 ────────────────────────────────────
# "자주 쓰는 표현"을 눌러 바로 넣는 초안일 뿐이다. AI가 학생 행동을 지어
# 내는 것이 아니라, 교사가 미리 등록해 둔 정해진 문구를 다시 꺼내 쓰는
# 것뿐이라 AI 동의·이용권과 무관하게 아무 때나 쓸 수 있다.

def template_out(t: TeacherObservationTemplate) -> dict:
    return {"id": t.id, "title": t.title, "content": t.content}








# ── AI 기능 ────────────────────────────────────────────────
#
# 학생이 쓴 글이 분석을 위해 외부로 나간다. 개인정보처리방침 제7조에
# "이용자가 별도로 동의하고 직접 요청한 경우에만" 이라고 적어 두었으므로,
# 동의 없이는 어떤 글도 밖으로 보내지 않는다.
#
# 무거운 일은 뒤로 미룬다. AI 는 몇 초에서 수십 초가 걸리는데 그동안
# 웹 요청을 붙들면 다른 학생의 일지 저장까지 멈춘다.

# 동의를 받을 때 보여준 방침의 시행일. 방침이 바뀌면 이 값을 올린다.
# 그러면 학생에게 다시 동의를 받게 된다.
AI_POLICY_DATE = "2026-09-07"


def ai_consent_of(db: Session, user: User) -> Optional[AiConsent]:
    return db.query(AiConsent).filter(AiConsent.user_id == user.id).first()


def has_ai_consent(db: Session, user: User) -> bool:
    """지금 방침에 대해 동의한 상태인가.

    방침이 바뀌었으면 예전 동의는 인정하지 않는다. 무엇에 동의했는지가
    달라졌기 때문이다.
    """
    c = ai_consent_of(db, user)
    return bool(c and c.agreed and c.policy_date == AI_POLICY_DATE)


def require_ai(db: Session, user: User) -> None:
    """AI 를 쓸 수 있는 상태인지 확인한다. 아니면 이유를 알려준다."""
    if not llm.available():
        raise HTTPException(status_code=503,
                            detail="AI 기능이 아직 준비되지 않았습니다.")
    if not has_ai_consent(db, user):
        raise HTTPException(
            status_code=403,
            detail="AI 기능을 쓰려면 먼저 동의가 필요합니다. 내 정보에서 동의해주세요.",
        )


def require_ai_for_student(db: Session, student: User) -> None:
    """세특·행동특성은 교사가 부르지만, 개인정보 주체는 학생이다.

    호출한 교사가 아니라 대상 학생 본인이 AI 이용에 동의했는지를 본다.
    """
    if not llm.available():
        raise HTTPException(status_code=503, detail="AI 기능이 아직 준비되지 않았습니다.")
    if not has_ai_consent(db, student):
        raise HTTPException(
            status_code=403,
            detail="학생이 아직 AI 이용에 동의하지 않았습니다. 학생에게 동의를 요청해주세요.",
        )


# ══════════════════════════════════════════════════════════
# AI 생기부 초안 — 세부능력 및 특기사항(세특) · 행동특성 및 종합의견
# ══════════════════════════════════════════════════════════
def _lesson_journal_ids(db: Session, student_id: int, subject_id: int) -> List[int]:
    return [r[0] for r in db.query(JournalEntry.id).filter(
        JournalEntry.user_id == student_id, JournalEntry.kind == "lesson",
        JournalEntry.subject_id == subject_id,
        JournalEntry.sent_at.isnot(None)).all()]


def _diary_journal_ids(db: Session, student_id: int) -> List[int]:
    return [r[0] for r in db.query(JournalEntry.id).filter(
        JournalEntry.user_id == student_id, JournalEntry.kind == "diary",
        JournalEntry.sent_at.isnot(None)).all()]


def _observation_ids(db: Session, teacher_id: int, student_id: int, subject_id: int) -> List[int]:
    """이 교사가 이 학생·이 과목에 남긴 관찰 기록(누가기록) id 모음.

    반드시 teacher_id 로 좁힌다 — 다른 교사가 같은 과목·학생에 남긴
    기록이 섞여 들어가면 안 된다(관찰 기록은 작성자 개인 것이다)."""
    return [r[0] for r in db.query(TeacherObservation.id).filter(
        TeacherObservation.teacher_id == teacher_id,
        TeacherObservation.student_id == student_id,
        TeacherObservation.subject_id == subject_id).all()]


def _observation_records(db: Session, ids: List[int], teacher_id: int, student_id: int,
                         subject_id: int) -> List[dict]:
    """id 로 다시 하나씩 조회하며 조건을 다시 확인한다(비동기 작업이라
    요청 시점과 실행 시점 사이에 상태가 바뀔 수 있어 재검증한다)."""
    out = []
    for oid in ids:
        n = db.get(TeacherObservation, oid)
        if (not n or n.teacher_id != teacher_id or n.student_id != student_id
                or n.subject_id != subject_id):
            continue
        text = n.content or ""
        if n.title:
            text = f"{n.title}\n{text}"
        out.append({
            "observation_id": n.id,
            "entry_date": n.observed_at.isoformat() if n.observed_at else "",
            "content": text,
        })
    return out


def _journal_records(db: Session, ids: List[int], student_id: int, kind: str,
                     subject_id: Optional[int] = None) -> List[dict]:
    """id 로 다시 하나씩 조회하며 조건을 다시 확인한다.

    비동기 작업은 API 요청의 권한 검사와 떨어져 실행되므로, 여기서
    한 번 더 user_id·kind·subject_id·제출 여부를 확인해야 다른 학생이나
    다른 과목의 글이 섞여 들어오지 않는다.
    """
    out = []
    for jid in ids:
        e = db.get(JournalEntry, jid)
        if not e or e.user_id != student_id or e.kind != kind or not e.sent_at:
            continue
        if kind == "lesson" and e.subject_id != subject_id:
            continue
        content = journal_content(e)
        out.append({
            "journal_id": e.id,
            "entry_date": e.entry_date.isoformat() if e.entry_date else "",
            "content": ai_service.journal_text(e, content),
        })
    return out


def ai_draft_out(d: StudentRecordAiDraft) -> dict:
    return {
        "id": d.id,
        "type": d.type,
        "subject_id": d.subject_id,
        "subject_name": d.subject.name if d.subject else "",
        "content": d.content,
        "ai_original": d.ai_original,
        "status": d.status,
        "source_kind": d.source_kind or "journal",
        "source_journal_ids": json.loads(d.source_journal_ids or "[]"),
        "created_at": d.created_at,
        "updated_at": d.updated_at,
        "confirmed_at": d.confirmed_at,
    }














@app.get("/api/ai/status")
def ai_status(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """AI 를 쓸 수 있는지, 동의했는지 알려준다."""
    c = ai_consent_of(db, user)
    return {
        **llm.status(),
        "consented": has_ai_consent(db, user),
        # 방침이 바뀌어 다시 받아야 하는 경우를 화면이 구분할 수 있게 한다.
        "consent_outdated": bool(c and c.agreed and c.policy_date != AI_POLICY_DATE),
        "policy_date": AI_POLICY_DATE,
    }


@app.post("/api/ai/consent")
def set_ai_consent(payload: dict, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """AI 기능 이용에 동의하거나 철회한다.

    철회한 기록도 남긴다. 언제 동의했고 언제 거뒀는지 확인할 수 있어야
    나중에 다툼이 생겼을 때 근거가 된다.
    """
    agree = bool(payload.get("agreed"))
    now = datetime.utcnow()

    c = ai_consent_of(db, user)
    if c is None:
        c = AiConsent(user_id=user.id)
        db.add(c)

    c.agreed = agree
    if agree:
        c.policy_date = AI_POLICY_DATE
        c.agreed_at = now
        c.revoked_at = None
    else:
        c.revoked_at = now
    db.commit()

    write_audit(db, request, user,
                action="ai.consent" if agree else "ai.consent_revoke",
                target_type="user", target_id=user.id, detail=AI_POLICY_DATE)
    return {
        "ok": True,
        "consented": agree,
        "message": ("AI 기능을 쓸 수 있습니다." if agree
                    else "동의를 거뒀습니다. AI 기능은 더 이상 쓰이지 않습니다."),
    }




def _job_visible_to_team(db: Session, job: AiJob, user: User) -> bool:
    """이 작업이 팀 연구용이면, 요청한 사람이 아니어도 같은 팀원이면 보게 한다.
    (§4 위험 요소 2번 — enqueue 자체는 요청자 user_id 로 등록되므로, 조회
    시점에 팀 멤버십으로 한 번 더 넓혀 준다. 연구가 아닌 작업(자소서 등)은
    원래대로 본인 것만 보인다.)"""
    if not job.kind.startswith("research_"):
        return False
    try:
        payload = json.loads(job.payload_json) if job.payload_json else {}
    except (ValueError, TypeError):
        return False
    research_id = payload.get("research_id")
    if not research_id:
        return False
    try:
        _own_research_or_404(db, user, int(research_id))
    except (HTTPException, TypeError, ValueError):
        return False
    return True


@app.get("/api/ai/jobs/{job_id}")
def get_ai_job(job_id: int, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    """맡긴 일이 끝났는지 확인한다. 화면이 몇 초마다 물어본다."""
    job = db.get(AiJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="요청을 찾을 수 없습니다.")
    if job.user_id != user.id and not _job_visible_to_team(db, job, user):
        raise HTTPException(status_code=404, detail="요청을 찾을 수 없습니다.")
    return ai_jobs.job_out(job, db)


# ── 연구 플랫폼 ──────────────────────────────────────────────
# M1: 관심 키워드 → AI 심화 대화 → 주제 5개 추천 → 선택/수정.
# 아직 헤더 메뉴에 링크가 없다 — 전체 기능이 완성되면 한 번에 노출한다.

RESEARCH_DIALOGUE_HISTORY_LIMIT = 20  # AI에 보낼 최근 대화 턴 수(§49 입력 최소화)


def _get_research_team(db: Session, research_id: int) -> Optional[ResearchTeam]:
    return db.query(ResearchTeam).filter(ResearchTeam.research_id == research_id).first()


def _team_member_or_none(db: Session, team_id: int, user_id: int) -> Optional[ResearchTeamMember]:
    return db.query(ResearchTeamMember).filter(
        ResearchTeamMember.team_id == team_id, ResearchTeamMember.user_id == user_id).first()


def _own_research_or_404(db: Session, user: User, research_id: int) -> ResearchProject:
    """이 연구를 볼 수 있는가 — 개인 연구면 본인, 팀 연구면 팀원 전원.

    팀 연구도 데이터 자체(로드맵·문헌·데이터·분석·논문 등)는 팀 전체가 함께
    보고 고치는 공용 자료로 다룬다 — 그래야 실제로 협업이 된다. 팀장만 할 수
    있게 남겨 둔 것은 초대 발송·연구 종료 요청·교사 검토 요청 세 가지뿐이고,
    그 세 곳은 이 함수 대신(또는 이 함수 다음에) _require_team_leader 를 쓴다."""
    r = db.get(ResearchProject, research_id)
    if not r:
        raise HTTPException(status_code=404, detail="연구를 찾을 수 없습니다.")
    if r.student_id == user.id:
        return r
    team = _get_research_team(db, r.id)
    if team and _team_member_or_none(db, team.id, user.id):
        return r
    raise HTTPException(status_code=404, detail="연구를 찾을 수 없습니다.")


def _job_research_authorized(db: Session, research: ResearchProject, user_id: int) -> bool:
    """AI 작업(_job_research_*)이 실제로 실행되는 시점에 다시 검사한다 — 요청
    시점과 처리 시점 사이에 팀 구성이 바뀌었을 수 있다. 개인 연구면 본인,
    팀 연구면 팀원 전원 허용(엔드포인트의 _own_research_or_404 와 같은 규칙)."""
    if research.student_id == user_id:
        return True
    team = _get_research_team(db, research.id)
    return bool(team and _team_member_or_none(db, team.id, user_id))


def _require_team_leader(db: Session, research_id: int, user: User) -> ResearchTeam:
    """팀장 전용 작업 앞에서 부른다. 팀 연구가 아니면 애초에 쓸 일이 없는
    엔드포인트이므로 400으로 알려준다."""
    team = _get_research_team(db, research_id)
    if not team:
        raise HTTPException(status_code=400, detail="팀 연구가 아닙니다.")
    member = _team_member_or_none(db, team.id, user.id)
    if not member or not member.is_leader:
        raise HTTPException(status_code=403, detail="팀장만 할 수 있습니다.")
    return team


def _team_out(db: Session, team: Optional[ResearchTeam]) -> Optional[dict]:
    if not team:
        return None
    members = (db.query(ResearchTeamMember, User)
               .join(User, ResearchTeamMember.user_id == User.id)
               .filter(ResearchTeamMember.team_id == team.id)
               .order_by(ResearchTeamMember.joined_at.asc()).all())
    return {
        "id": team.id, "status": team.status, "created_by": team.created_by,
        "members": [{
            "user_id": u.id, "name": u.name, "is_leader": m.is_leader,
            "research_role": m.research_role or "", "joined_at": m.joined_at,
        } for m, u in members],
    }


def research_out(db: Session, r: ResearchProject) -> dict:
    return {
        "id": r.id,
        "interest_keyword": r.interest_keyword,
        "title": r.title,
        "short_description": r.short_description,
        "research_type": r.research_type,
        "research_question": r.research_question,
        "hypothesis": r.hypothesis,
        "variables": r.variables,
        "target_sample": r.target_sample,
        "method_detail": r.method_detail,
        "expected_limitations": r.expected_limitations,
        "follow_up_ideas": r.follow_up_ideas,
        "difficulty_level": r.difficulty_level or "easy",
        "duration_weeks": r.duration_weeks,
        "start_date": r.start_date.isoformat() if r.start_date else None,
        "target_end_date": r.target_end_date.isoformat() if r.target_end_date else None,
        "status": r.status,
        "current_stage": r.current_stage,
        "progress": r.progress,
        "current_week": r.current_week or 1,
        "created_at": r.created_at,
        "updated_at": r.updated_at,
        "completed_at": r.completed_at,
        "team": _team_out(db, _get_research_team(db, r.id)),
        **_display_stage(db, r),
    }


def _dialogue_turn_out(t: ResearchDialogueTurn) -> dict:
    return {"id": t.id, "role": t.role, "stage": t.stage, "content": t.content,
            "created_at": t.created_at}


def _topic_out(t: ResearchTopicSuggestion) -> dict:
    return {
        "id": t.id, "title": t.title, "research_question": t.research_question,
        "research_type": t.research_type,
        "feasibility_note": t.feasibility_note, "expected_duration": t.expected_duration,
        "required_materials": t.required_materials, "method_summary": t.method_summary,
        "difficulty": t.difficulty, "extensibility": t.extensibility,
        "is_selected": t.is_selected,
    }


def _roadmap_step_out(s: ResearchRoadmapStep, tasks: List[ResearchTask]) -> dict:
    return {
        "id": s.id, "week_number": s.week_number, "title": s.title, "goal": s.goal,
        "expected_hours": s.expected_hours, "completion_criteria": s.completion_criteria,
        "tasks": [_task_out(t) for t in tasks],
    }


def _task_out(t: ResearchTask) -> dict:
    try:
        guide = json.loads(t.guide) if t.guide else None
    except (ValueError, TypeError):
        guide = None
    return {"id": t.id, "title": t.title, "status": t.status,
            "roadmap_step_id": t.roadmap_step_id, "completed_at": t.completed_at, "guide": guide}


def _recent_dialogue_turns(db: Session, research_id: int) -> List[dict]:
    rows = (db.query(ResearchDialogueTurn)
            .filter(ResearchDialogueTurn.research_id == research_id)
            .order_by(ResearchDialogueTurn.created_at.desc())
            .limit(RESEARCH_DIALOGUE_HISTORY_LIMIT).all())
    rows.reverse()
    return [{"role": t.role, "content": t.content} for t in rows]


def _own_topic_or_404(db: Session, research_id: int, topic_id: int) -> ResearchTopicSuggestion:
    t = db.get(ResearchTopicSuggestion, topic_id)
    if not t or t.research_id != research_id:
        raise HTTPException(status_code=404, detail="주제를 찾을 수 없습니다.")
    return t


@app.post("/api/research")
def start_research(payload: dict, db: Session = Depends(get_db),
                   user: User = Depends(require_student),
                   _seat: User = Depends(require_research_seat)):
    """새 연구를 시작한다. 학생은 관심 키워드와 기간만 정하면 된다.

    mode="team" 이면 이 연구에 딸린 팀을 함께 만들고 본인을 팀장으로 넣는다
    (지시서 §5 — "누구와 함께 연구할까요?"를 주제보다 먼저 정한다).
    ResearchProject 자체는 개인 연구와 완전히 같은 모양이다 — 팀 여부는
    ResearchTeam 존재로만 판단한다."""
    keyword = str(payload.get("interest_keyword") or "").strip()
    mode = str(payload.get("mode") or "solo").strip()
    if mode not in ("solo", "team"):
        mode = "solo"
    # 팀 연구는 팀부터 꾸리고 주제는 팀원이 모인 뒤 함께 정한다 — 그래서
    # 키워드 없이 만드는 걸 허용한다. 나중에 POST .../keyword 로 채운다.
    if not keyword and mode != "team":
        raise HTTPException(status_code=400, detail="관심 있는 주제를 입력해주세요.")
    try:
        weeks = int(payload.get("duration_weeks") or 4)
    except (TypeError, ValueError):
        weeks = 4
    weeks = min(max(weeks, 1), 52)
    difficulty = str(payload.get("difficulty_level") or "easy").strip()
    if difficulty not in ("easy", "normal", "deep"):
        difficulty = "easy"

    r = ResearchProject(student_id=user.id, interest_keyword=keyword[:80],
                        duration_weeks=weeks, status="planning", current_stage="interest",
                        difficulty_level=difficulty)
    db.add(r)
    db.commit()
    db.refresh(r)

    if mode == "team":
        team = ResearchTeam(research_id=r.id, created_by=user.id)
        db.add(team)
        db.commit()
        db.refresh(team)
        db.add(ResearchTeamMember(team_id=team.id, user_id=user.id, is_leader=True))
        db.commit()

    return research_out(db, r)


@app.post("/api/research/{research_id}/keyword")
def set_research_keyword(research_id: int, payload: dict, db: Session = Depends(get_db),
                         user: User = Depends(require_student),
                         _seat: User = Depends(require_research_seat)):
    """관심 키워드를 (다시) 정한다. 팀 연구는 팀부터 꾸리고 주제를 나중에
    비워둔 채 시작하므로(start_research), 팀원이 모인 뒤 이 엔드포인트로
    채운다. 대화가 이미 시작된 뒤에는 못 바꾼다 — 그 키워드로 이미 AI
    코치와 이야기를 시작했기 때문이다."""
    r = _own_research_or_404(db, user, research_id)
    has_turns = db.query(ResearchDialogueTurn.id).filter(
        ResearchDialogueTurn.research_id == r.id).first() is not None
    if r.current_stage != "interest" or has_turns:
        raise HTTPException(status_code=400, detail="이미 연구가 시작되어 주제를 바꿀 수 없습니다.")
    keyword = str(payload.get("interest_keyword") or "").strip()
    if not keyword:
        raise HTTPException(status_code=400, detail="관심 있는 주제를 입력해주세요.")
    r.interest_keyword = keyword[:80]
    if payload.get("duration_weeks") is not None:
        try:
            r.duration_weeks = min(max(int(payload.get("duration_weeks")), 1), 52)
        except (TypeError, ValueError):
            pass
    difficulty = str(payload.get("difficulty_level") or "").strip()
    if difficulty in ("easy", "normal", "deep"):
        r.difficulty_level = difficulty
    db.commit()
    db.refresh(r)
    return research_out(db, r)


@app.get("/api/research")
def list_research(db: Session = Depends(get_db), user: User = Depends(require_student),
    _seat: User = Depends(require_research_seat)):
    """내 연구 목록 — 내가 시작한 것 + 팀원으로 참여 중인 것. 최근 것부터."""
    team_research_ids = (
        db.query(ResearchTeam.research_id)
        .join(ResearchTeamMember, ResearchTeamMember.team_id == ResearchTeam.id)
        .filter(ResearchTeamMember.user_id == user.id)
    )
    rows = (db.query(ResearchProject)
            .filter(or_(ResearchProject.student_id == user.id,
                       ResearchProject.id.in_(team_research_ids)))
            .order_by(ResearchProject.created_at.desc()).all())
    return {"items": [research_out(db, r) for r in rows]}


@app.get("/api/research/{research_id}")
def get_research(research_id: int, db: Session = Depends(get_db),
                 user: User = Depends(require_student),
                 _seat: User = Depends(require_research_seat)):
    r = _own_research_or_404(db, user, research_id)
    return research_out(db, r)


def _delete_research_cascade(db: Session, r: ResearchProject) -> None:
    """연구 하나와 거기 딸린 모든 자식 행을 지운다. FK 제약(research_projects,
    research_teams, external_questions) 때문에 자식부터 순서대로 지워야 한다
    — cleanup_load_test.py 의 정리 스크립트와 같은 순서다."""
    question_ids = [q.id for q in db.query(ExternalQuestion.id).filter(
        ExternalQuestion.research_id == r.id).all()]
    answer_ids = [a.id for a in db.query(ExternalAnswer.id).filter(
        ExternalAnswer.question_id.in_(question_ids)).all()]
    db.query(ExternalAnswerFeedback).filter(
        ExternalAnswerFeedback.answer_id.in_(answer_ids)).delete(synchronize_session=False)
    db.query(ExternalAnswerNote).filter(
        or_(ExternalAnswerNote.research_id == r.id,
            ExternalAnswerNote.answer_id.in_(answer_ids))
    ).delete(synchronize_session=False)
    db.query(ExternalAnswer).filter(ExternalAnswer.id.in_(answer_ids)).delete(synchronize_session=False)
    db.query(ExternalQuestion).filter(ExternalQuestion.id.in_(question_ids)).delete(synchronize_session=False)
    db.query(ExternalAnswerSeen).filter(
        ExternalAnswerSeen.research_id == r.id).delete(synchronize_session=False)

    team = _get_research_team(db, r.id)
    if team:
        db.query(ResearchBoardPost).filter(ResearchBoardPost.team_id == team.id).delete(synchronize_session=False)
        db.query(ResearchTeamRoleHistory).filter(
            ResearchTeamRoleHistory.team_id == team.id).delete(synchronize_session=False)
        db.query(ResearchTeamInvite).filter(
            ResearchTeamInvite.team_id == team.id).delete(synchronize_session=False)
        db.query(ResearchTeamLeaveRequest).filter(
            ResearchTeamLeaveRequest.team_id == team.id).delete(synchronize_session=False)
        db.query(ResearchTeamMember).filter(
            ResearchTeamMember.team_id == team.id).delete(synchronize_session=False)
        # db.delete(team) 대신 즉시 실행되는 벌크 삭제를 쓴다 — ResearchTeam과
        # ResearchProject 사이엔 ORM relationship()이 없어서, db.delete()로
        # 큐에 쌓으면 SQLAlchemy가 둘 중 뭘 먼저 지울지 보장을 못 하고(실제로
        # research_projects를 먼저 지우려다 FK 위반이 났다), 벌크 삭제는 이
        # 자리에서 바로 실행되므로 아래 db.delete(r)보다 항상 먼저 끝난다.
        db.query(ResearchTeam).filter(ResearchTeam.id == team.id).delete(synchronize_session=False)

    # 순서 중요: ResearchTask.roadmap_step_id → ResearchRoadmapStep,
    # ResearchPortfolio.cover_data_id → ResearchData 를 참조하므로(둘 다
    # research_projects 말고 이 목록 안의 다른 표를 가리키는 FK), 그 자식들을
    # 먼저 지워야 한다. 나머지는 전부 research_id 로만 research_projects 를
    # 가리켜서 순서가 상관없다.
    for model in (ResearchDialogueTurn, ResearchTopicSuggestion,
                  ResearchTask, ResearchRoadmapStep,
                  ResearchPortfolio, ResearchData,
                  ResearchLiterature, ResearchAnalysis, ResearchReview, ResearchReport,
                  ResearchFeedback, ResearchPaper):
        db.query(model).filter(model.research_id == r.id).delete(synchronize_session=False)

    # ai_jobs 는 research_id 컬럼이 없어(payload_json 안에만 있음) FK 제약도
    # 없다 — 지운 연구를 가리키는 옛 작업 기록이 남아도 조회 시 조용히
    # 못 찾을 뿐 오류가 안 나므로, 여기서 굳이 안 지운다.
    db.delete(r)


@app.delete("/api/research/{research_id}")
def delete_research(research_id: int, db: Session = Depends(get_db),
                    user: User = Depends(require_student)):
    """연구를 완전히 지운다. 되돌릴 수 없다 — 확인은 프론트에서 받는다.

    개인 연구는 본인만. 팀 연구는 팀장만 지울 수 있다 — 팀원 전체가 함께
    쌓은 자료를 한 명이 마음대로 없앨 수 없어야 한다(초대·팀 관련 다른
    팀장 전용 작업과 같은 원칙). 이용권이 끊긴 뒤에도(만료된 연구를
    정리하고 싶을 수 있으니) 지울 수 있게 좌석 검사는 안 건다."""
    r = db.get(ResearchProject, research_id)
    if not r:
        raise HTTPException(status_code=404, detail="연구를 찾을 수 없습니다.")

    # 원래 만든 사람(student_id)은 항상 지울 수 있다 — 팀 멤버십이 어떤
    # 이유로든 비어버린 경우(정상적으로는 탈퇴 시 혼자 남은 팀은 막아
    # 두었지만, 방어적으로) 그 사람마저 막히면 아무도 못 지우는 상태가
    # 되기 때문이다. 그 외 사람은 팀장이어야만 지울 수 있다.
    if r.student_id != user.id:
        team = _get_research_team(db, r.id)
        if not team:
            raise HTTPException(status_code=404, detail="연구를 찾을 수 없습니다.")
        member = _team_member_or_none(db, team.id, user.id)
        if not member:
            raise HTTPException(status_code=404, detail="연구를 찾을 수 없습니다.")
        if not member.is_leader:
            raise HTTPException(status_code=403, detail="팀장만 지울 수 있습니다.")

    _delete_research_cascade(db, r)
    db.commit()
    return {"ok": True}


@app.post("/api/research/{research_id}/dialogue")
def send_research_dialogue(research_id: int, payload: dict, db: Session = Depends(get_db),
                           user: User = Depends(require_student),
                           _seat: User = Depends(require_research_seat)):
    """학생의 메시지를 기록하고, AI의 다음 질문을 만들어 달라고 맡긴다.

    아직 대화가 하나도 없는 상태에서 빈 메시지로 부르면, 화면이 채팅처럼
    보이도록 AI가 관심 키워드만 보고 먼저 첫 질문을 던진다(학생 발화로
    남기지 않는다 — 학생이 실제로 아무 말도 안 했으니까)."""
    r = _own_research_or_404(db, user, research_id)
    require_ai(db, user)

    message = str(payload.get("message") or "").strip()
    has_turns = db.query(ResearchDialogueTurn.id).filter(
        ResearchDialogueTurn.research_id == r.id).first() is not None
    if not message and has_turns:
        raise HTTPException(status_code=400, detail="내용을 입력해주세요.")

    if message:
        db.add(ResearchDialogueTurn(research_id=r.id, role="student",
                                    stage=r.current_stage, content=message))
        db.commit()

    job = ai_jobs.enqueue(db, user.id, "research_dialogue", {
        "research_id": r.id,
        "interest_keyword": r.interest_keyword,
        "turns": _recent_dialogue_turns(db, r.id),
        "message": message,
    })
    return {"job_id": job.id}


@app.get("/api/research/{research_id}/dialogue")
def list_research_dialogue(research_id: int, db: Session = Depends(get_db),
                           user: User = Depends(require_student),
                           _seat: User = Depends(require_research_seat)):
    r = _own_research_or_404(db, user, research_id)
    rows = (db.query(ResearchDialogueTurn)
            .filter(ResearchDialogueTurn.research_id == r.id)
            .order_by(ResearchDialogueTurn.created_at.asc()).all())
    return {"items": [_dialogue_turn_out(t) for t in rows]}


@app.post("/api/research/{research_id}/topics")
def request_research_topics(research_id: int, db: Session = Depends(get_db),
                            user: User = Depends(require_student),
                            _seat: User = Depends(require_research_seat)):
    """지금까지의 대화를 바탕으로 주제 후보를 만들어 달라고 맡긴다."""
    r = _own_research_or_404(db, user, research_id)
    require_ai(db, user)

    turns = _recent_dialogue_turns(db, r.id)
    if not turns:
        raise HTTPException(status_code=400, detail="먼저 AI와 몇 마디 나눠주세요.")

    job = ai_jobs.enqueue(db, user.id, "research_topics", {
        "research_id": r.id, "interest_keyword": r.interest_keyword, "turns": turns,
    }, dedup_key=f"topics:{r.id}:{len(turns)}")
    return {"job_id": job.id}


@app.get("/api/research/{research_id}/topics")
def list_research_topics(research_id: int, db: Session = Depends(get_db),
                         user: User = Depends(require_student),
                         _seat: User = Depends(require_research_seat)):
    r = _own_research_or_404(db, user, research_id)
    rows = (db.query(ResearchTopicSuggestion)
            .filter(ResearchTopicSuggestion.research_id == r.id)
            .order_by(ResearchTopicSuggestion.created_at.asc()).all())
    return {"items": [_topic_out(t) for t in rows]}


@app.put("/api/research/{research_id}/topics/{topic_id}")
def edit_research_topic(research_id: int, topic_id: int, payload: dict,
                        db: Session = Depends(get_db), user: User = Depends(require_student),
                        _seat: User = Depends(require_research_seat)):
    """학생이 AI가 제안한 주제를 직접 수정한다."""
    r = _own_research_or_404(db, user, research_id)
    t = _own_topic_or_404(db, r.id, topic_id)
    if "title" in payload:
        t.title = str(payload.get("title") or "").strip()[:200]
    if "research_question" in payload:
        t.research_question = str(payload.get("research_question") or "").strip()
    db.commit()
    return _topic_out(t)


@app.post("/api/research/{research_id}/topics/{topic_id}/review")
def review_research_topic(research_id: int, topic_id: int, db: Session = Depends(get_db),
                          user: User = Depends(require_student),
                          _seat: User = Depends(require_research_seat)):
    """학생이 수정한 주제를 AI에게 검토해 달라고 맡긴다."""
    r = _own_research_or_404(db, user, research_id)
    t = _own_topic_or_404(db, r.id, topic_id)
    require_ai(db, user)

    job = ai_jobs.enqueue(db, user.id, "research_topic_review", {
        "research_id": r.id, "topic_id": t.id, "interest_keyword": r.interest_keyword,
        "title": t.title, "research_question": t.research_question,
    })
    return {"job_id": job.id}


@app.post("/api/research/{research_id}/topics/{topic_id}/select")
def select_research_topic(research_id: int, topic_id: int, db: Session = Depends(get_db),
                          user: User = Depends(require_student),
                          _seat: User = Depends(require_research_seat)):
    """이 주제로 연구를 확정한다."""
    r = _own_research_or_404(db, user, research_id)
    t = _own_topic_or_404(db, r.id, topic_id)

    (db.query(ResearchTopicSuggestion)
     .filter(ResearchTopicSuggestion.research_id == r.id)
     .update({"is_selected": False}, synchronize_session=False))
    t.is_selected = True

    r.title = t.title
    r.research_question = t.research_question
    r.research_type = t.research_type
    r.current_stage = "question"
    db.commit()
    return research_out(db, r)


@app.put("/api/research/{research_id}")
def update_research(research_id: int, payload: dict, db: Session = Depends(get_db),
                    user: User = Depends(require_student),
                    _seat: User = Depends(require_research_seat)):
    """학생이 연구 계획 필드를 직접 수정한다. AI 초안은 시작점일 뿐이다."""
    r = _own_research_or_404(db, user, research_id)
    for field in ("title", "short_description", "research_type", "research_question",
                  "hypothesis", "variables", "target_sample", "method_detail",
                  "expected_limitations", "follow_up_ideas"):
        if field in payload:
            setattr(r, field, str(payload.get(field) or ""))
    db.commit()
    return research_out(db, r)


@app.post("/api/research/{research_id}/plan")
def request_research_plan(research_id: int, db: Session = Depends(get_db),
                          user: User = Depends(require_student),
                          _seat: User = Depends(require_research_seat)):
    """확정된 주제로 연구 계획 초안을 만들어 달라고 맡긴다."""
    r = _own_research_or_404(db, user, research_id)
    if not r.research_question:
        raise HTTPException(status_code=400, detail="먼저 연구 주제를 확정해주세요.")
    require_ai(db, user)

    job = ai_jobs.enqueue(db, user.id, "research_plan", {"research_id": r.id})
    return {"job_id": job.id}


@app.post("/api/research/{research_id}/confirm-plan")
def confirm_research_plan(research_id: int, db: Session = Depends(get_db),
                          user: User = Depends(require_student),
                          _seat: User = Depends(require_research_seat)):
    """계획을 다 다듬었다고 확정한다. 로드맵을 만들 수 있게 된다."""
    r = _own_research_or_404(db, user, research_id)
    r.current_stage = "plan"
    db.commit()
    # 학생이 쉬운 말로 쓴 계획을 전문 연구 구조로 번역해 둔다(학생에겐 안 보임,
    # 논문·심사·교사 화면에서 씀). AI 동의가 없으면 조용히 건너뛴다 — 계획
    # 확정 자체는 이미 끝났으니 학생 흐름을 막을 이유가 없다.
    if llm.available() and has_ai_consent(db, user):
        ai_jobs.enqueue(db, user.id, "research_structure", {"research_id": r.id})
    return research_out(db, r)


@app.post("/api/research/{research_id}/roadmap")
def request_research_roadmap(research_id: int, db: Session = Depends(get_db),
                             user: User = Depends(require_student),
                             _seat: User = Depends(require_research_seat)):
    """연구 기간을 주차별 로드맵으로 나눠 달라고 맡긴다. 다시 요청하면
    기존 로드맵을 새로 만든 것으로 바꾼다."""
    r = _own_research_or_404(db, user, research_id)
    if not r.research_question:
        raise HTTPException(status_code=400, detail="먼저 연구 주제를 확정해주세요.")
    require_ai(db, user)

    job = ai_jobs.enqueue(db, user.id, "research_roadmap", {"research_id": r.id})
    return {"job_id": job.id}


@app.get("/api/research/{research_id}/roadmap")
def list_research_roadmap(research_id: int, db: Session = Depends(get_db),
                          user: User = Depends(require_student),
                          _seat: User = Depends(require_research_seat)):
    r = _own_research_or_404(db, user, research_id)
    steps = (db.query(ResearchRoadmapStep)
             .filter(ResearchRoadmapStep.research_id == r.id)
             .order_by(ResearchRoadmapStep.week_number.asc()).all())
    tasks = (db.query(ResearchTask)
             .filter(ResearchTask.research_id == r.id)
             .order_by(ResearchTask.created_at.asc()).all())
    by_step: Dict[int, List[ResearchTask]] = {}
    for t in tasks:
        by_step.setdefault(t.roadmap_step_id, []).append(t)
    return {"items": [_roadmap_step_out(s, by_step.get(s.id, [])) for s in steps]}


@app.patch("/api/research/{research_id}/tasks/{task_id}")
def update_research_task(research_id: int, task_id: int, payload: dict,
                         db: Session = Depends(get_db), user: User = Depends(require_student),
                         _seat: User = Depends(require_research_seat)):
    """학생이 할 일을 체크하거나 되돌린다."""
    r = _own_research_or_404(db, user, research_id)
    t = db.get(ResearchTask, task_id)
    if not t or t.research_id != r.id:
        raise HTTPException(status_code=404, detail="할 일을 찾을 수 없습니다.")
    status = str(payload.get("status") or "").strip()
    if status not in ("todo", "in_progress", "completed", "skipped"):
        raise HTTPException(status_code=400, detail="상태 값이 올바르지 않습니다.")
    t.status = status
    t.completed_at = datetime.utcnow() if status == "completed" else None
    db.flush()  # 세션이 autoflush=False라서, 방금 바꾼 상태를 집계 쿼리가 보려면 직접 흘려보내야 한다
    _recompute_progress(db, r)
    db.commit()
    return _task_out(t)


@app.post("/api/research/{research_id}/advance-week")
def advance_research_week(research_id: int, db: Session = Depends(get_db),
                          user: User = Depends(require_student),
                          _seat: User = Depends(require_research_seat)):
    """이번 주차 할 일을 다 끝냈을 때, 학생이 직접 다음 주차로 넘어간다.

    날짜가 지났다고 자동으로 넘기지 않는다 — 방학이나 늦어진 진행 때문에
    실제 진도와 달력이 어긋날 수 있어서다.
    """
    r = _own_research_or_404(db, user, research_id)
    week = r.current_week or 1
    if week >= r.duration_weeks:
        raise HTTPException(status_code=400, detail="이미 마지막 주차입니다.")

    step = (db.query(ResearchRoadmapStep)
           .filter(ResearchRoadmapStep.research_id == r.id, ResearchRoadmapStep.week_number == week)
           .first())
    if step:
        tasks = db.query(ResearchTask).filter(ResearchTask.roadmap_step_id == step.id).all()
        if tasks and any(t.status != "completed" for t in tasks):
            raise HTTPException(status_code=400, detail="이번 주차 할 일을 모두 완료해야 다음 주차로 넘어갈 수 있습니다.")

    r.current_week = week + 1
    db.commit()
    return research_out(db, r)


@app.post("/api/research/{research_id}/tasks/{task_id}/guide")
def request_task_guide(research_id: int, task_id: int, db: Session = Depends(get_db),
                       user: User = Depends(require_student),
                       _seat: User = Depends(require_research_seat)):
    """이 할 일을 실제로 어떻게 하면 되는지 AI에게 단계별 안내를 맡긴다."""
    r = _own_research_or_404(db, user, research_id)
    t = db.get(ResearchTask, task_id)
    if not t or t.research_id != r.id:
        raise HTTPException(status_code=404, detail="할 일을 찾을 수 없습니다.")
    require_ai(db, user)
    job = ai_jobs.enqueue(db, user.id, "research_task_guide", {"research_id": r.id, "task_id": t.id})
    return {"job_id": job.id}


def _recompute_progress(db: Session, r: ResearchProject) -> None:
    """전체 할 일 중 완료 비율로 진행률을 다시 계산한다(0~100)."""
    total = db.query(func.count(ResearchTask.id)).filter(ResearchTask.research_id == r.id).scalar() or 0
    if total == 0:
        return
    done = (db.query(func.count(ResearchTask.id))
           .filter(ResearchTask.research_id == r.id, ResearchTask.status == "completed").scalar() or 0)
    r.progress = round(done / total * 100)


# ── 문헌/참고자료 ─────────────────────────────────────────────

_HANGUL_RE = re.compile(r"[가-힣]")


def _format_citation(l: ResearchLiterature, index: Optional[int] = None) -> str:
    """참고문헌 한 줄을 "[번호] 저자, 「제목」, 출처, 연도." 형식으로 만든다
    (한글이 아닌 제목은 「」 대신 큰따옴표). 확인된 자료만 대상이라 AI가
    지어낼 여지가 없다 — 서버가 학생이 적어 둔 값을 그대로 조합만 한다.
    index를 안 주면(참고 자료 화면에서 낱개로 "인용 복사"할 때처럼, 최종
    번호가 아직 정해지지 않은 경우) 번호 없이 만든다."""
    title = (l.title or "").strip()
    lq, rq = ("「", "」") if _HANGUL_RE.search(title) else ('"', '"')
    quoted_title = f"{lq}{title}{rq}" if title else ""

    bits = []
    if l.author:
        bits.append(l.author.strip())
    if quoted_title:
        bits.append(quoted_title)
    if l.source:
        bits.append(l.source.strip())
    if l.year:
        bits.append(l.year.strip())
    body = ", ".join(bits) or title
    prefix = f"[{index}] " if index is not None else ""
    return f"{prefix}{body}.".strip()


def _literature_out(l: ResearchLiterature) -> dict:
    return {
        "id": l.id, "title": l.title, "author": l.author, "year": l.year,
        "source": l.source, "url": l.url, "summary": l.summary, "relevance": l.relevance,
        "student_note": l.student_note, "stance": l.stance, "verified": l.verified,
        "ai_suggested": l.ai_suggested, "sort_order": l.sort_order,
        "file_name": l.file_name,
        "file_url": f"/api/research-literature/{l.id}/attachment" if l.file_key else "",
        "citation": _format_citation(l),
    }


@app.post("/api/research/{research_id}/literature")
def add_research_literature(research_id: int, payload: dict, db: Session = Depends(get_db),
                            user: User = Depends(require_student),
                            _seat: User = Depends(require_research_seat)):
    """학생이 직접 찾은 자료를 등록한다. 직접 등록한 자료는 처음부터 확인됨 상태다."""
    r = _own_research_or_404(db, user, research_id)
    title = str(payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="제목을 입력해주세요.")
    last = (db.query(func.max(ResearchLiterature.sort_order))
           .filter(ResearchLiterature.research_id == r.id).scalar())
    lit = ResearchLiterature(
        research_id=r.id, title=title[:300], author=str(payload.get("author") or "")[:200],
        year=str(payload.get("year") or "")[:10], source=str(payload.get("source") or "")[:200],
        url=str(payload.get("url") or "")[:500], summary=str(payload.get("summary") or ""),
        relevance=str(payload.get("relevance") or ""), student_note=str(payload.get("student_note") or ""),
        stance=str(payload.get("stance") or "uncertain"), verified=True, ai_suggested=False,
        sort_order=(last + 1) if last is not None else 0)
    db.add(lit)
    db.commit()
    db.refresh(lit)
    return _literature_out(lit)


@app.get("/api/research/{research_id}/literature")
def list_research_literature(research_id: int, db: Session = Depends(get_db),
                             user: User = Depends(require_student),
                             _seat: User = Depends(require_research_seat)):
    r = _own_research_or_404(db, user, research_id)
    rows = (db.query(ResearchLiterature).filter(ResearchLiterature.research_id == r.id)
           .order_by(ResearchLiterature.sort_order.asc(), ResearchLiterature.created_at.asc()).all())
    return {"items": [_literature_out(l) for l in rows]}


def _own_literature_or_404(db: Session, research_id: int, literature_id: int) -> ResearchLiterature:
    l = db.get(ResearchLiterature, literature_id)
    if not l or l.research_id != research_id:
        raise HTTPException(status_code=404, detail="자료를 찾을 수 없습니다.")
    return l


@app.put("/api/research/{research_id}/literature/{literature_id}")
def update_research_literature(research_id: int, literature_id: int, payload: dict,
                               db: Session = Depends(get_db), user: User = Depends(require_student),
                               _seat: User = Depends(require_research_seat)):
    r = _own_research_or_404(db, user, research_id)
    l = _own_literature_or_404(db, r.id, literature_id)
    for field in ("title", "author", "year", "source", "url", "summary", "relevance",
                  "student_note", "stance"):
        if field in payload:
            setattr(l, field, str(payload.get(field) or ""))
    db.commit()
    return _literature_out(l)


@app.post("/api/research/{research_id}/literature/{literature_id}/verify")
def verify_research_literature(research_id: int, literature_id: int, db: Session = Depends(get_db),
                               user: User = Depends(require_student),
                               _seat: User = Depends(require_research_seat)):
    """학생이 직접 실제로 찾아 확인했다고 표시한다. AI가 자동으로 확인 처리하지 않는다."""
    r = _own_research_or_404(db, user, research_id)
    l = _own_literature_or_404(db, r.id, literature_id)
    l.verified = True
    db.commit()
    return _literature_out(l)


@app.delete("/api/research/{research_id}/literature/{literature_id}")
def delete_research_literature(research_id: int, literature_id: int, db: Session = Depends(get_db),
                               user: User = Depends(require_student),
                               _seat: User = Depends(require_research_seat)):
    r = _own_research_or_404(db, user, research_id)
    l = _own_literature_or_404(db, r.id, literature_id)
    doc_store.delete_document(l.file_key)
    db.delete(l)
    db.commit()
    return {"ok": True}


@app.post("/api/research/{research_id}/literature/{literature_id}/attachment")
async def attach_research_literature_file(
    research_id: int, literature_id: int, file: UploadFile = File(...),
    db: Session = Depends(get_db), user: User = Depends(require_student),
    _seat: User = Depends(require_research_seat),
):
    """학생이 직접 찾은 논문 파일(PDF/HWP/DOC/이미지)을 첨부한다."""
    r = _own_research_or_404(db, user, research_id)
    l = _own_literature_or_404(db, r.id, literature_id)
    data = await file.read()
    try:
        storage_key, safe_name = doc_store.save_document(user.id, file.filename, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    doc_store.delete_document(l.file_key)
    l.file_key = storage_key
    l.file_name = safe_name
    db.commit()
    return _literature_out(l)


@app.delete("/api/research/{research_id}/literature/{literature_id}/attachment")
def remove_research_literature_file(research_id: int, literature_id: int,
                                    db: Session = Depends(get_db), user: User = Depends(require_student),
                                    _seat: User = Depends(require_research_seat)):
    r = _own_research_or_404(db, user, research_id)
    l = _own_literature_or_404(db, r.id, literature_id)
    doc_store.delete_document(l.file_key)
    l.file_key = ""
    l.file_name = ""
    db.commit()
    return _literature_out(l)


@app.get("/api/research-literature/{literature_id}/attachment")
def get_research_literature_file(literature_id: int, db: Session = Depends(get_db),
                                 user: User = Depends(require_student),
                                 _seat: User = Depends(require_research_seat)):
    l = db.get(ResearchLiterature, literature_id)
    if not l or not l.file_key:
        raise HTTPException(status_code=404, detail="첨부파일을 찾을 수 없습니다.")
    _own_research_or_404(db, user, l.research_id)
    data = doc_store.read_document(l.file_key)
    if data is None:
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")
    from urllib.parse import quote
    name = l.file_name or "첨부파일"
    disp = f"inline; filename*=UTF-8''{quote(name)}"
    return Response(content=data, media_type=doc_store.guess_media_type(l.file_key),
                    headers={"Content-Disposition": disp})


@app.post("/api/research/{research_id}/literature/suggest")
def suggest_research_literature(research_id: int, db: Session = Depends(get_db),
                                user: User = Depends(require_student),
                                _seat: User = Depends(require_research_seat)):
    """AI에게 참고 자료 후보를 제안해 달라고 맡긴다. 결과는 전부 미확인 상태로 들어간다."""
    r = _own_research_or_404(db, user, research_id)
    if not r.research_question:
        raise HTTPException(status_code=400, detail="먼저 연구 주제를 확정해주세요.")
    require_ai(db, user)
    job = ai_jobs.enqueue(db, user.id, "research_literature", {"research_id": r.id})
    return {"job_id": job.id}


# ── 연구 데이터 ───────────────────────────────────────────────

def _data_out(d: ResearchData) -> dict:
    try:
        content = json.loads(d.content_json or "{}")
    except (ValueError, TypeError):
        content = {}
    return {
        "id": d.id, "title": d.title, "data_type": d.data_type, "content": content,
        "note": d.note, "created_at": d.created_at,
        "image_url": f"/api/research-data/{d.id}/image" if d.data_type == "image" else None,
    }


@app.post("/api/research/{research_id}/data")
def add_research_data(research_id: int, payload: dict, db: Session = Depends(get_db),
                      user: User = Depends(require_student),
                      _seat: User = Depends(require_research_seat)):
    """표 형태 또는 자유 텍스트로 데이터를 직접 입력한다.

    text 를 주면 정형화되지 않은 관찰 기록·메모로 남긴다(통계 분석 대상은
    아니다 — 분석은 표 데이터만 대상으로 한다, 아래 request_research_analysis
    참고). columns/rows 를 주면 기존처럼 표로 저장하고, 실제로 측정·수집한
    값이어야 한다."""
    r = _own_research_or_404(db, user, research_id)
    title = str(payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="제목을 입력해주세요.")

    text = str(payload.get("text") or "").strip()
    if text:
        d = ResearchData(research_id=r.id, title=title[:200], data_type="text",
                         content_json=json.dumps({"text": text}, ensure_ascii=False),
                         note=str(payload.get("note") or ""))
        db.add(d)
        db.commit()
        db.refresh(d)
        return _data_out(d)

    columns = [str(c) for c in (payload.get("columns") or [])]
    rows = [[str(cell) for cell in row] for row in (payload.get("rows") or [])]
    if not columns or not rows:
        raise HTTPException(status_code=400, detail="표 데이터가 비어 있습니다.")
    d = ResearchData(research_id=r.id, title=title[:200], data_type="table",
                     content_json=json.dumps({"columns": columns, "rows": rows}, ensure_ascii=False),
                     note=str(payload.get("note") or ""))
    db.add(d)
    db.commit()
    db.refresh(d)
    return _data_out(d)


@app.post("/api/research/{research_id}/data/image")
async def upload_research_data_image(
    research_id: int, title: str = Form(""), note: str = Form(""),
    file: UploadFile = File(...), db: Session = Depends(get_db),
    user: User = Depends(require_student),
    _seat: User = Depends(require_research_seat),
):
    """실험 사진·현장 조사 사진 등을 올린다."""
    r = _own_research_or_404(db, user, research_id)
    if file.content_type not in image_store.ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="사진 파일만 올릴 수 있습니다(jpg/png/webp/gif).")
    data = await file.read()
    try:
        storage_key, web_key, thumb_key, w, h = image_store.save_image(user.id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    d = ResearchData(research_id=r.id, title=(title or file.filename or "사진")[:200],
                     data_type="image", storage_key=storage_key, web_key=web_key,
                     thumbnail_key=thumb_key, note=note)
    db.add(d)
    db.commit()
    db.refresh(d)
    return _data_out(d)


@app.get("/api/research/{research_id}/data")
def list_research_data(research_id: int, db: Session = Depends(get_db),
                       user: User = Depends(require_student),
                       _seat: User = Depends(require_research_seat)):
    r = _own_research_or_404(db, user, research_id)
    rows = (db.query(ResearchData).filter(ResearchData.research_id == r.id)
           .order_by(ResearchData.created_at.asc()).all())
    return {"items": [_data_out(d) for d in rows]}


@app.get("/api/research-data/{data_id}/image")
def get_research_data_image(data_id: int, variant: str = Query("web", pattern="^(original|web|thumbnail)$"),
                            db: Session = Depends(get_db), user: User = Depends(require_student),
                            _seat: User = Depends(require_research_seat)):
    d = db.get(ResearchData, data_id)
    if not d or d.data_type != "image":
        raise HTTPException(status_code=404, detail="사진을 찾을 수 없습니다.")
    _own_research_or_404(db, user, d.research_id)
    key = {"original": d.storage_key, "web": d.web_key or d.storage_key,
          "thumbnail": d.thumbnail_key or d.storage_key}[variant]
    file_data = image_store.read_variant(key)
    if file_data is None:
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")
    return Response(content=file_data, media_type="image/jpeg")


@app.delete("/api/research/{research_id}/data/{data_id}")
def delete_research_data(research_id: int, data_id: int, db: Session = Depends(get_db),
                         user: User = Depends(require_student),
                         _seat: User = Depends(require_research_seat)):
    r = _own_research_or_404(db, user, research_id)
    d = db.get(ResearchData, data_id)
    if not d or d.research_id != r.id:
        raise HTTPException(status_code=404, detail="데이터를 찾을 수 없습니다.")
    db.delete(d)
    db.commit()
    return {"ok": True}


# ── 데이터 분석 ───────────────────────────────────────────────

def _compute_stats(data_rows: List[ResearchData]) -> dict:
    """표 데이터의 숫자 열만 골라 실제로 통계를 계산한다. AI는 이 결과를
    바꾸지 않고 해석만 한다."""
    stats = {}
    for d in data_rows:
        try:
            content = json.loads(d.content_json or "{}")
        except (ValueError, TypeError):
            continue
        columns = content.get("columns") or []
        rows = content.get("rows") or []
        for i, col in enumerate(columns):
            values = []
            for row in rows:
                if i >= len(row):
                    continue
                try:
                    values.append(float(row[i]))
                except (TypeError, ValueError):
                    continue
            if len(values) < 2:
                continue
            key = f"{d.title} · {col}"
            stats[key] = {
                "count": len(values),
                "mean": round(statistics.mean(values), 3),
                "median": round(statistics.median(values), 3),
                "stdev": round(statistics.stdev(values), 3),
                "min": round(min(values), 3),
                "max": round(max(values), 3),
            }
    return stats


# 5회는 "우연히 한 번 그랬을 수도 있다"는 의심을 걷어낼 수 있는 최소한의
# 기준으로 잡았다. AI 해석이 이 부족함을 언급할지 말지에 맡기지 않고,
# 여기서 직접 계산해 항상 알려준다(§9 "데이터 부족 시 반복측정 권고").
MIN_MEASUREMENTS = 5


def _low_data_note(stats: dict) -> str:
    min_count = min((s["count"] for s in stats.values()), default=0)
    if min_count >= MIN_MEASUREMENTS or min_count == 0:
        return ""
    return (
        f"측정을 {min_count}번밖에 안 했어요. 우연히 그런 결과가 나왔을 수도 있으니, "
        f"같은 조건으로 {MIN_MEASUREMENTS}번 이상 반복해서 측정해보면 결과를 더 믿을 수 있어요."
    )


def _analysis_out(a: ResearchAnalysis) -> dict:
    try:
        stats = json.loads(a.computed_stats_json or "{}")
        data_ids = json.loads(a.data_ids or "[]")
    except (ValueError, TypeError):
        stats, data_ids = {}, []
    return {
        "id": a.id, "data_ids": data_ids, "stats": stats,
        "method_suggestion": a.method_suggestion, "interpretation": a.interpretation,
        "low_data_note": _low_data_note(stats),
        "created_at": a.created_at,
    }


@app.post("/api/research/{research_id}/analysis")
def request_research_analysis(research_id: int, db: Session = Depends(get_db),
                              user: User = Depends(require_student),
                              _seat: User = Depends(require_research_seat)):
    """표 데이터의 통계를 실제로 계산하고, AI에게 해석을 맡긴다."""
    r = _own_research_or_404(db, user, research_id)
    table_rows = (db.query(ResearchData)
                 .filter(ResearchData.research_id == r.id, ResearchData.data_type == "table").all())
    if not table_rows:
        raise HTTPException(status_code=400, detail="분석할 표 데이터가 없습니다. 먼저 데이터를 입력해주세요.")
    stats = _compute_stats(table_rows)
    if not stats:
        raise HTTPException(status_code=400, detail="숫자로 된 열이 없어 통계를 계산할 수 없습니다.")
    require_ai(db, user)
    job = ai_jobs.enqueue(db, user.id, "research_analysis", {
        "research_id": r.id, "data_ids": [d.id for d in table_rows], "stats": stats,
    })
    return {"job_id": job.id, "low_data_note": _low_data_note(stats)}


@app.get("/api/research/{research_id}/analysis")
def list_research_analysis(research_id: int, db: Session = Depends(get_db),
                           user: User = Depends(require_student),
                           _seat: User = Depends(require_research_seat)):
    r = _own_research_or_404(db, user, research_id)
    rows = (db.query(ResearchAnalysis).filter(ResearchAnalysis.research_id == r.id)
           .order_by(ResearchAnalysis.created_at.desc()).all())
    return {"items": [_analysis_out(a) for a in rows]}


@app.post("/api/research/{research_id}/data/direction")
def request_research_data_direction(research_id: int, db: Session = Depends(get_db),
                                    user: User = Depends(require_student),
                                    _seat: User = Depends(require_research_seat)):
    """아직 데이터를 모으기 전, 무엇을 어떻게 모으면 좋을지 AI에게 방향을 맡긴다.

    결과는 저장하지 않는다 — 연구 계획이 바뀌면 방향도 바뀌어야 하므로,
    매번 지금 시점의 계획을 근거로 새로 만든다(연구심사·주제 검토와 같은 방식).
    """
    r = _own_research_or_404(db, user, research_id)
    if not r.research_question:
        raise HTTPException(status_code=400, detail="먼저 연구 주제를 확정해주세요.")
    require_ai(db, user)
    job = ai_jobs.enqueue(db, user.id, "research_data_direction", {"research_id": r.id})
    return {"job_id": job.id}


# ── 연구심사 ──────────────────────────────────────────────────

def _review_out(r: ResearchReview) -> dict:
    try:
        findings = json.loads(r.findings_json or "[]")
    except (ValueError, TypeError):
        findings = []
    return {"id": r.id, "stage": r.stage, "findings": findings, "created_at": r.created_at}


@app.post("/api/research/{research_id}/review")
def request_research_review(research_id: int, db: Session = Depends(get_db),
                            user: User = Depends(require_student),
                            _seat: User = Depends(require_research_seat)):
    r = _own_research_or_404(db, user, research_id)
    if not r.research_question:
        raise HTTPException(status_code=400, detail="먼저 연구 주제를 확정해주세요.")
    require_ai(db, user)
    job = ai_jobs.enqueue(db, user.id, "research_review", {"research_id": r.id})
    return {"job_id": job.id}


@app.get("/api/research/{research_id}/review")
def list_research_review(research_id: int, db: Session = Depends(get_db),
                         user: User = Depends(require_student),
                         _seat: User = Depends(require_research_seat)):
    r = _own_research_or_404(db, user, research_id)
    rows = (db.query(ResearchReview).filter(ResearchReview.research_id == r.id)
           .order_by(ResearchReview.created_at.desc()).all())
    return {"items": [_review_out(x) for x in rows]}


@app.post("/api/research/{research_id}/followup")
def request_research_followup(research_id: int, db: Session = Depends(get_db),
                              user: User = Depends(require_student),
                              _seat: User = Depends(require_research_seat)):
    """후속 연구 제안을 만들어 달라고 맡긴다."""
    r = _own_research_or_404(db, user, research_id)
    if not r.research_question:
        raise HTTPException(status_code=400, detail="먼저 연구 주제를 확정해주세요.")
    require_ai(db, user)
    job = ai_jobs.enqueue(db, user.id, "research_followup", {"research_id": r.id})
    return {"job_id": job.id}


# ── 중간 리포트 ───────────────────────────────────────────────

def _report_out(rp: ResearchReport) -> dict:
    try:
        completed = json.loads(rp.completed_tasks_json or "[]")
    except (ValueError, TypeError):
        completed = []
    return {
        "id": rp.id, "report_type": rp.report_type,
        "period_start": rp.period_start.isoformat() if rp.period_start else None,
        "period_end": rp.period_end.isoformat() if rp.period_end else None,
        "summary": rp.summary, "completed_tasks": completed, "current_stage": rp.current_stage,
        "blockers": rp.blockers, "ai_feedback": rp.ai_feedback, "next_steps": rp.next_steps,
        "created_at": rp.created_at,
    }


@app.post("/api/research/{research_id}/reports")
def request_research_report(research_id: int, payload: dict, db: Session = Depends(get_db),
                            user: User = Depends(require_student),
                            _seat: User = Depends(require_research_seat)):
    """리포트를 만들어 달라고 맡긴다. 기간은 마지막 리포트 이후~오늘로 서버가 정한다."""
    r = _own_research_or_404(db, user, research_id)
    if not r.research_question:
        raise HTTPException(status_code=400, detail="먼저 연구 주제를 확정해주세요.")
    require_ai(db, user)

    report_type = str(payload.get("report_type") or "weekly")
    if report_type not in ("weekly", "midterm", "final"):
        report_type = "weekly"
    blockers = str(payload.get("blockers") or "")

    # completed_at은 datetime.utcnow()(UTC)로 찍히는데 date.today()는 서버 로컬
    # 날짜라, 자정 근처 시간대 차이(예: 한국시간 UTC+9)에서는 방금 완료한
    # 할 일이 기간 밖으로 밀려나 빠질 수 있었다 — 같은 기준(UTC)으로 맞춘다.
    today = datetime.utcnow().date()
    last = (db.query(ResearchReport).filter(ResearchReport.research_id == r.id)
           .order_by(ResearchReport.period_end.desc()).first())
    if last and last.period_end:
        period_start = last.period_end + timedelta(days=1)
    else:
        # r.start_date는 서버 로컬 날짜라 UTC 기준 today보다 하루 앞설 수 있다
        # (예: 한국시간 UTC+9, 자정 직후) — 더 이른 쪽을 골라야 방금 완료한
        # 할 일이 기간 밖으로 밀려나지 않는다.
        period_start = min(r.start_date, today) if r.start_date else today
    period_end = today

    completed = (db.query(ResearchTask)
                .filter(ResearchTask.research_id == r.id, ResearchTask.status == "completed",
                        ResearchTask.completed_at.isnot(None),
                        ResearchTask.completed_at >= datetime.combine(period_start, datetime.min.time()))
                .all())
    completed_titles = [t.title for t in completed]

    job = ai_jobs.enqueue(db, user.id, "research_report", {
        "research_id": r.id, "report_type": report_type, "blockers": blockers,
        "period_start": period_start.isoformat(), "period_end": period_end.isoformat(),
        "completed_tasks": completed_titles,
    })
    return {"job_id": job.id}


@app.get("/api/research/{research_id}/reports")
def list_research_reports(research_id: int, db: Session = Depends(get_db),
                          user: User = Depends(require_student),
                          _seat: User = Depends(require_research_seat)):
    r = _own_research_or_404(db, user, research_id)
    rows = (db.query(ResearchReport).filter(ResearchReport.research_id == r.id)
           .order_by(ResearchReport.created_at.desc()).all())
    return {"items": [_report_out(x) for x in rows]}


@app.get("/api/research/{research_id}/feedback")
def list_research_feedback_student(research_id: int, db: Session = Depends(get_db),
                                   user: User = Depends(require_student),
                                   _seat: User = Depends(require_research_seat)):
    """학생이 담임 선생님의 지도 피드백을 확인한다."""
    r = _own_research_or_404(db, user, research_id)
    rows = (db.query(ResearchFeedback).filter(ResearchFeedback.research_id == r.id)
           .order_by(ResearchFeedback.created_at.desc()).all())
    return {"items": [_feedback_out(f) for f in rows]}


# ── 최종 논문 / 연구 포트폴리오 ────────────────────────────────

def _research_summary_text(r: ResearchProject) -> str:
    # 값이 없는 항목을 그냥 빼 버리면 AI가 "안 적혀 있으니 그럴듯하게
    # 채워도 되나 보다"라고 오해할 수 있다 — "아직 정해지지 않음"이라고
    # 명시해 AI가 구체적인 방법·도구를 지어내지 않도록 한다.
    def field(v: str) -> str:
        return v.strip() if v and v.strip() else "(아직 정해지지 않음)"

    parts = [f"제목: {r.title or r.interest_keyword}"]
    if r.research_type:
        parts.append(f"연구 유형: {r.research_type}")
    if r.research_question:
        parts.append(f"연구 질문: {r.research_question}")
    parts.append(f"가설: {field(r.hypothesis)}")
    parts.append(f"연구 대상: {field(r.target_sample)}")
    parts.append(f"변인: {field(r.variables)}")
    parts.append(f"연구 방법: {field(r.method_detail)}")
    struct = _research_structure(r)
    if struct:
        parts.append("── 아래는 위 내용을 연구 구조로 정리한 것(참고용, 학생에게 보여주지 말 것) ──")
        if struct.get("independent_variable"):
            parts.append(f"독립변수: {struct['independent_variable']}")
        if struct.get("dependent_variable"):
            parts.append(f"종속변수: {struct['dependent_variable']}")
        if struct.get("control_variables"):
            parts.append(f"통제변수: {', '.join(struct['control_variables'])}")
        if struct.get("comparison_groups"):
            parts.append(f"비교 집단: {', '.join(struct['comparison_groups'])}")
        if struct.get("measurement"):
            parts.append(f"측정 방법: {struct['measurement']}")
        if struct.get("repetition"):
            parts.append(f"반복·재검증: {struct['repetition']}")
    return "\n".join(parts)


def _research_structure(r: ResearchProject) -> dict:
    """학생이 쉬운 말로 쓴 계획을 번역해 둔 연구 구조. 아직 안 만들어졌으면 {}."""
    try:
        return json.loads(r.structure_json) if r.structure_json else {}
    except (ValueError, TypeError):
        return {}


def _verified_literature_text(db: Session, research_id: int) -> str:
    """AI가 지어낸 문헌을 논문에 못 쓰게, 학생이 직접 확인 처리한 것만 넘긴다."""
    rows = (db.query(ResearchLiterature)
           .filter(ResearchLiterature.research_id == research_id,
                   ResearchLiterature.verified.is_(True))
           .order_by(ResearchLiterature.sort_order.asc()).all())
    lines = []
    for l in rows:
        bits = [l.title]
        if l.author:
            bits.append(f"({l.author}{', ' + l.year if l.year else ''})")
        line = " ".join(bits)
        if l.summary:
            line += f" - {l.summary}"
        if l.stance:
            line += f" [학생 입장: {l.stance}]"
        lines.append(f"- {line}")
    return "\n".join(lines)


def _approved_external_notes_text(db: Session, research_id: int) -> str:
    """학생이 승인한 '연구 반영' 노트만 넘긴다 — 미승인 상태로는 절대
    논문에 안 들어간다(§19)."""
    rows = (db.query(ExternalAnswerNote)
           .filter(ExternalAnswerNote.research_id == research_id,
                   ExternalAnswerNote.approved.is_(True))
           .order_by(ExternalAnswerNote.created_at.asc()).all())
    stage_label = {"literature": "문헌·배경지식", "method": "연구 방법",
                  "analysis": "데이터 분석", "discussion": "해석·논의"}
    lines = []
    for n in rows:
        label = stage_label.get(n.suggested_stage, "")
        lines.append(f"- ({label}) {n.note}" if label else f"- {n.note}")
    return "\n".join(lines)


def _reference_list(db: Session, research_id: int) -> List[dict]:
    """확인된 참고자료로 참고문헌 목록을 만든다. 저자·제목 순으로 정렬한다.
    url이 있으면 화면에서 바로 그 링크로, 없으면 학술 검색으로 이어줄 수
    있도록 인용 문구와 함께 url·제목도 같이 내려준다."""
    rows = (db.query(ResearchLiterature)
           .filter(ResearchLiterature.research_id == research_id,
                   ResearchLiterature.verified.is_(True))
           .order_by(ResearchLiterature.author.asc(), ResearchLiterature.title.asc()).all())
    return [{"citation": _format_citation(l, i + 1), "url": l.url, "title": l.title}
           for i, l in enumerate(rows)]


def _latest_analysis_text(db: Session, research_id: int) -> str:
    a = (db.query(ResearchAnalysis).filter(ResearchAnalysis.research_id == research_id)
        .order_by(ResearchAnalysis.created_at.desc()).first())
    if not a:
        return ""
    try:
        stats = json.loads(a.computed_stats_json or "{}")
    except (ValueError, TypeError):
        stats = {}
    return f"통계: {json.dumps(stats, ensure_ascii=False)}\n해석: {a.interpretation}"


def _latest_review_text(db: Session, research_id: int) -> str:
    rv = (db.query(ResearchReview).filter(ResearchReview.research_id == research_id)
         .order_by(ResearchReview.created_at.desc()).first())
    if not rv:
        return ""
    try:
        findings = json.loads(rv.findings_json or "[]")
    except (ValueError, TypeError):
        findings = []
    return "\n".join(
        f"- {f}" if isinstance(f, str) else f"- {json.dumps(f, ensure_ascii=False)}"
        for f in findings)


def _paper_out(p: ResearchPaper) -> dict:
    try:
        sections = json.loads(p.sections_json or "{}")
    except (ValueError, TypeError):
        sections = {}
    return {
        "id": p.id, "title": p.title, "abstract": p.abstract,
        "sections": {k: sections.get(k, "") for k in PAPER_SECTION_KEYS},
        "created_at": p.created_at, "updated_at": p.updated_at,
    }


def _portfolio_out(p: ResearchPortfolio) -> dict:
    try:
        sections = json.loads(p.sections_json or "{}")
    except (ValueError, TypeError):
        sections = {}
    return {
        "id": p.id, "title": p.title, "cover_data_id": p.cover_data_id,
        "sections": {k: sections.get(k, "") for k in PORTFOLIO_SECTION_KEYS},
        "visibility": p.visibility,
        "share_token": p.share_token if p.visibility == "shared" else None,
        "created_at": p.created_at, "updated_at": p.updated_at,
    }


@app.post("/api/research/{research_id}/paper/draft")
def draft_research_paper(research_id: int, db: Session = Depends(get_db),
                         user: User = Depends(require_student),
                         _seat: User = Depends(require_research_seat)):
    """확인된 참고자료·실제 분석 결과만 근거로 논문 초안을 AI에게 맡긴다."""
    r = _own_research_or_404(db, user, research_id)
    if not r.research_question:
        raise HTTPException(status_code=400, detail="먼저 연구 주제를 확정해주세요.")
    require_ai(db, user)
    job = ai_jobs.enqueue(db, user.id, "research_paper", {"research_id": r.id})
    return {"job_id": job.id}


@app.get("/api/research/{research_id}/paper")
def get_research_paper(research_id: int, db: Session = Depends(get_db),
                       user: User = Depends(require_student),
                       _seat: User = Depends(require_research_seat)):
    r = _own_research_or_404(db, user, research_id)
    p = db.query(ResearchPaper).filter(ResearchPaper.research_id == r.id).first()
    return {"paper": _paper_out(p) if p else None, "references": _reference_list(db, r.id)}


@app.put("/api/research/{research_id}/paper")
def update_research_paper(research_id: int, payload: dict, db: Session = Depends(get_db),
                          user: User = Depends(require_student),
                          _seat: User = Depends(require_research_seat)):
    """학생이 초안을 직접 고쳐 쓴다."""
    r = _own_research_or_404(db, user, research_id)
    p = db.query(ResearchPaper).filter(ResearchPaper.research_id == r.id).first()
    if not p:
        p = ResearchPaper(research_id=r.id, sections_json="{}")
        db.add(p)
    if "title" in payload:
        p.title = str(payload.get("title") or "")[:200]
    if "abstract" in payload:
        p.abstract = str(payload.get("abstract") or "")
    if isinstance(payload.get("sections"), dict):
        try:
            sections = json.loads(p.sections_json or "{}")
        except (ValueError, TypeError):
            sections = {}
        for k in PAPER_SECTION_KEYS:
            if k in payload["sections"]:
                sections[k] = str(payload["sections"][k] or "")
        p.sections_json = json.dumps(sections, ensure_ascii=False)
    db.commit()
    db.refresh(p)
    return _paper_out(p)


@app.get("/api/research/{research_id}/paper/pdf")
def download_research_paper_pdf(research_id: int, db: Session = Depends(get_db),
                                user: User = Depends(require_student),
                                _seat: User = Depends(require_research_seat)):
    r = _own_research_or_404(db, user, research_id)
    p = db.query(ResearchPaper).filter(ResearchPaper.research_id == r.id).first()
    if not p:
        raise HTTPException(status_code=404, detail="아직 작성된 논문이 없습니다.")
    try:
        sections = json.loads(p.sections_json or "{}")
    except (ValueError, TypeError):
        sections = {}
    section_labels = [
        ("introduction", "1. 서론"), ("literature_review", "2. 선행 연구"),
        ("method", "3. 연구 방법"), ("results", "4. 연구 결과"),
        ("discussion", "5. 논의"), ("limitations", "6. 연구의 한계"),
        ("conclusion", "7. 결론"),
    ]
    body = [(label, sections.get(k, "")) for k, label in section_labels]
    if p.abstract:
        body = [("초록", p.abstract)] + body
    references = _reference_list(db, r.id)
    meta = [
        ("연구 기간", f"{r.start_date.isoformat()} ~ {r.target_end_date.isoformat()}"
         if r.start_date and r.target_end_date else ""),
        ("연구 유형", r.research_type or ""),
    ]
    try:
        pdf_bytes = research_export.build_research_pdf(
            "연구 논문", p.title or r.title or r.interest_keyword, r.research_question, meta, body,
            references=references)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    stem = fonts.safe_filename(p.title or r.title or "연구논문")
    from urllib.parse import quote
    disp = f"attachment; filename=\"paper.pdf\"; filename*=UTF-8''{quote(stem)}.pdf"
    write_audit(db, request=None, actor=user, action="research.paper_download",
               target_type="research", target_id=r.id, detail="")
    return Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": disp})


@app.post("/api/research/{research_id}/portfolio/draft")
def draft_research_portfolio(research_id: int, db: Session = Depends(get_db),
                             user: User = Depends(require_student),
                             _seat: User = Depends(require_research_seat)):
    r = _own_research_or_404(db, user, research_id)
    if not r.research_question:
        raise HTTPException(status_code=400, detail="먼저 연구 주제를 확정해주세요.")
    require_ai(db, user)
    job = ai_jobs.enqueue(db, user.id, "research_portfolio", {"research_id": r.id})
    return {"job_id": job.id}


@app.get("/api/research/{research_id}/portfolio")
def get_research_portfolio(research_id: int, db: Session = Depends(get_db),
                           user: User = Depends(require_student),
                           _seat: User = Depends(require_research_seat)):
    r = _own_research_or_404(db, user, research_id)
    p = db.query(ResearchPortfolio).filter(ResearchPortfolio.research_id == r.id).first()
    return {"portfolio": _portfolio_out(p) if p else None}


def _own_research_portfolio_or_404(db: Session, r: ResearchProject) -> ResearchPortfolio:
    p = db.query(ResearchPortfolio).filter(ResearchPortfolio.research_id == r.id).first()
    if not p:
        raise HTTPException(status_code=404, detail="아직 작성된 포트폴리오가 없습니다.")
    return p


@app.put("/api/research/{research_id}/portfolio")
def update_research_portfolio(research_id: int, payload: dict, db: Session = Depends(get_db),
                              user: User = Depends(require_student),
                              _seat: User = Depends(require_research_seat)):
    r = _own_research_or_404(db, user, research_id)
    p = db.query(ResearchPortfolio).filter(ResearchPortfolio.research_id == r.id).first()
    if not p:
        p = ResearchPortfolio(research_id=r.id, sections_json="{}")
        db.add(p)
    if "title" in payload:
        p.title = str(payload.get("title") or "")[:200]
    if "cover_data_id" in payload:
        cid = payload.get("cover_data_id")
        if cid:
            data = db.get(ResearchData, int(cid))
            if not data or data.research_id != r.id or data.data_type != "image":
                raise HTTPException(status_code=400, detail="표지로 쓸 수 없는 자료입니다.")
            p.cover_data_id = data.id
        else:
            p.cover_data_id = None
    if isinstance(payload.get("sections"), dict):
        try:
            sections = json.loads(p.sections_json or "{}")
        except (ValueError, TypeError):
            sections = {}
        for k in PORTFOLIO_SECTION_KEYS:
            if k in payload["sections"]:
                sections[k] = str(payload["sections"][k] or "")
        p.sections_json = json.dumps(sections, ensure_ascii=False)
    db.commit()
    db.refresh(p)
    return _portfolio_out(p)


@app.get("/api/research/{research_id}/portfolio/pdf")
def download_research_portfolio_pdf(research_id: int, db: Session = Depends(get_db),
                                    user: User = Depends(require_student),
                                    _seat: User = Depends(require_research_seat)):
    r = _own_research_or_404(db, user, research_id)
    p = _own_research_portfolio_or_404(db, r)
    try:
        sections = json.loads(p.sections_json or "{}")
    except (ValueError, TypeError):
        sections = {}
    section_labels = [
        ("why", "왜 이 연구를 시작했나요"), ("question", "무엇이 궁금했나요"),
        ("hypothesis", "어떤 가설을 세웠나요"), ("method", "어떻게 연구했나요"),
        ("data", "어떤 데이터를 얻었나요"), ("result", "무엇을 발견했나요"),
        ("discussion", "어떻게 해석했나요"), ("limitation", "무엇이 부족했나요"),
        ("next", "다음엔 무엇을 하고 싶나요"),
    ]
    body = [(label, sections.get(k, "")) for k, label in section_labels]
    meta = [
        ("연구 기간", f"{r.start_date.isoformat()} ~ {r.target_end_date.isoformat()}"
         if r.start_date and r.target_end_date else ""),
    ]
    try:
        pdf_bytes = research_export.build_research_pdf(
            "연구 포트폴리오", p.title or r.title or r.interest_keyword, r.research_question, meta, body)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    stem = fonts.safe_filename(p.title or r.title or "연구포트폴리오")
    from urllib.parse import quote
    disp = f"attachment; filename=\"portfolio.pdf\"; filename*=UTF-8''{quote(stem)}.pdf"
    write_audit(db, request=None, actor=user, action="research.portfolio_download",
               target_type="research", target_id=r.id, detail="")
    return Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": disp})


@app.post("/api/research/{research_id}/portfolio/share")
def share_research_portfolio(research_id: int, db: Session = Depends(get_db),
                             user: User = Depends(require_student),
                             _seat: User = Depends(require_research_seat)):
    """공유 링크를 만든다. 기본은 비공개이고, 이 API를 직접 불러야만 보기 전용 링크가 생긴다."""
    r = _own_research_or_404(db, user, research_id)
    p = _own_research_portfolio_or_404(db, r)
    if not p.share_token:
        p.share_token = secrets.token_urlsafe(24)
    p.visibility = "shared"
    db.commit()
    return {"ok": True, "share_token": p.share_token}


@app.delete("/api/research/{research_id}/portfolio/share")
def unshare_research_portfolio(research_id: int, db: Session = Depends(get_db),
                               user: User = Depends(require_student),
                               _seat: User = Depends(require_research_seat)):
    r = _own_research_or_404(db, user, research_id)
    p = _own_research_portfolio_or_404(db, r)
    p.visibility = "private"
    p.share_token = None
    db.commit()
    return {"ok": True}


@app.get("/api/research-portfolio-share/{token}")
def view_shared_research_portfolio(token: str, db: Session = Depends(get_db)):
    """로그인 없이 여는 보기 전용 화면."""
    p = db.query(ResearchPortfolio).filter(ResearchPortfolio.share_token == token).first()
    if not p or p.visibility != "shared":
        raise HTTPException(status_code=404, detail="공유되지 않은 포트폴리오입니다.")
    r = db.get(ResearchProject, p.research_id)
    student = db.get(User, r.student_id) if r else None
    out = _portfolio_out(p)
    out["research_title"] = r.title if r else ""
    out["research_question"] = r.research_question if r else ""
    out["student_name"] = student.name if student else ""
    return out


# ── 공동 연구(팀) ────────────────────────────────────────────
# 팀 데이터는 전부 신규 테이블(ResearchTeam 등)이고, 기존 개인 연구
# 51개 엔드포인트는 _own_research_or_404 확장 하나로 팀원 전원에게
# 자동으로 열린다(위 §_own_research_or_404 참고). 여기서는 팀 자체를
# 만들고 관리하는 엔드포인트만 다룬다.

@app.get("/api/research/{research_id}/team")
def get_research_team(research_id: int, db: Session = Depends(get_db),
                      user: User = Depends(require_student),
                      _seat: User = Depends(require_research_seat)):
    r = _own_research_or_404(db, user, research_id)
    return _team_out(db, _get_research_team(db, r.id)) or {"members": []}


@app.get("/api/research/{research_id}/team/candidates")
def search_team_candidates(research_id: int, q: str = "", db: Session = Depends(get_db),
                           user: User = Depends(require_student),
                           _seat: User = Depends(require_research_seat)):
    """팀장이 초대할 친구를 찾는다. 같은 학교 학생만 이름으로 검색한다."""
    r = _own_research_or_404(db, user, research_id)
    team = _require_team_leader(db, r.id, user)
    term = q.strip()
    if not term:
        return {"items": []}
    existing = {m.user_id for m in db.query(ResearchTeamMember).filter(
        ResearchTeamMember.team_id == team.id).all()}
    pending = {i.invited_user_id for i in db.query(ResearchTeamInvite).filter(
        ResearchTeamInvite.team_id == team.id, ResearchTeamInvite.status == "pending").all()}
    rows = (db.query(User).filter(User.school_id == user.school_id, User.role == Role.student,
                                  User.verified.is_(True), User.name.ilike(f"%{term}%"))
            .limit(20).all())
    return {"items": [{
        "user_id": u.id, "name": u.name, "class_name": u.class_name or "", "grade": u.grade,
        "already_member": u.id in existing, "already_invited": u.id in pending,
    } for u in rows if u.id != user.id]}


@app.post("/api/research/{research_id}/team/invites")
def invite_team_member(research_id: int, payload: dict, db: Session = Depends(get_db),
                       user: User = Depends(require_student),
                       _seat: User = Depends(require_research_seat)):
    """팀장이 친구를 초대한다. 다른 팀원을 강제로 넣는 게 아니라
    초대만 보내고, 상대가 수락해야 팀원이 된다(§12 팀장 권한 최소화)."""
    r = _own_research_or_404(db, user, research_id)
    team = _require_team_leader(db, r.id, user)

    invited_id = payload.get("invited_user_id")
    try:
        invited_id = int(invited_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="초대할 학생을 골라주세요.")
    invited = db.get(User, invited_id)
    if not invited or invited.role != Role.student or invited.school_id != user.school_id:
        raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다.")
    if invited.id == user.id:
        raise HTTPException(status_code=400, detail="자기 자신은 초대할 수 없습니다.")
    if _team_member_or_none(db, team.id, invited.id):
        raise HTTPException(status_code=400, detail="이미 팀에 있는 학생입니다.")
    exists = db.query(ResearchTeamInvite).filter(
        ResearchTeamInvite.team_id == team.id, ResearchTeamInvite.invited_user_id == invited.id,
        ResearchTeamInvite.status == "pending").first()
    if exists:
        return _invite_out(exists)

    inv = ResearchTeamInvite(team_id=team.id, invited_user_id=invited.id, invited_by=user.id)
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return _invite_out(inv)


def _invite_out(i: ResearchTeamInvite) -> dict:
    team = None  # 지연 조회는 호출부에서 필요할 때만
    return {"id": i.id, "team_id": i.team_id, "invited_user_id": i.invited_user_id,
            "status": i.status, "created_at": i.created_at, "responded_at": i.responded_at}


@app.get("/api/team-invites")
def list_my_team_invites(db: Session = Depends(get_db), user: User = Depends(require_student)):
    """내가 받은 초대(대기 중인 것) 목록 — 아직 그 연구를 볼 권한이 없으니
    research_id 로 접근하지 않고 전역으로 조회한다."""
    rows = (db.query(ResearchTeamInvite, ResearchTeam, ResearchProject)
            .join(ResearchTeam, ResearchTeamInvite.team_id == ResearchTeam.id)
            .join(ResearchProject, ResearchTeam.research_id == ResearchProject.id)
            .filter(ResearchTeamInvite.invited_user_id == user.id,
                    ResearchTeamInvite.status == "pending")
            .order_by(ResearchTeamInvite.created_at.desc()).all())
    out = []
    for inv, team, proj in rows:
        inviter = db.get(User, inv.invited_by)
        out.append({
            **_invite_out(inv), "research_id": proj.id,
            "research_title": proj.title or proj.interest_keyword,
            "invited_by_name": inviter.name if inviter else "",
        })
    return {"items": out}


@app.post("/api/team-invites/{invite_id}/accept")
def accept_team_invite(invite_id: int, db: Session = Depends(get_db),
                       user: User = Depends(require_student),
                       _seat: User = Depends(require_research_seat)):
    inv = db.get(ResearchTeamInvite, invite_id)
    if not inv or inv.invited_user_id != user.id:
        raise HTTPException(status_code=404, detail="초대를 찾을 수 없습니다.")
    if inv.status != "pending":
        raise HTTPException(status_code=400, detail="이미 처리된 초대입니다.")
    if not _team_member_or_none(db, inv.team_id, user.id):
        db.add(ResearchTeamMember(team_id=inv.team_id, user_id=user.id))
    inv.status = "accepted"
    inv.responded_at = datetime.utcnow()
    db.commit()
    team = db.get(ResearchTeam, inv.team_id)
    return {"ok": True, "research_id": team.research_id if team else None}


@app.post("/api/team-invites/{invite_id}/decline")
def decline_team_invite(invite_id: int, db: Session = Depends(get_db),
                        user: User = Depends(require_student)):
    inv = db.get(ResearchTeamInvite, invite_id)
    if not inv or inv.invited_user_id != user.id:
        raise HTTPException(status_code=404, detail="초대를 찾을 수 없습니다.")
    if inv.status != "pending":
        raise HTTPException(status_code=400, detail="이미 처리된 초대입니다.")
    inv.status = "declined"
    inv.responded_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


@app.put("/api/research/{research_id}/team/members/{member_user_id}/role")
def update_team_member_role(research_id: int, member_user_id: int, payload: dict,
                            db: Session = Depends(get_db), user: User = Depends(require_student),
                            _seat: User = Depends(require_research_seat)):
    """역할은 본인만 바꾼다 — 팀장도 다른 팀원의 역할을 강제로 바꾸지 못한다
    (§12). 실제 배정은 팀원들이 서로 협의해 각자 자기 화면에서 적는다."""
    if member_user_id != user.id:
        raise HTTPException(status_code=403, detail="본인 역할만 바꿀 수 있습니다.")
    r = _own_research_or_404(db, user, research_id)
    team = _get_research_team(db, r.id)
    if not team:
        raise HTTPException(status_code=400, detail="팀 연구가 아닙니다.")
    member = _team_member_or_none(db, team.id, user.id)
    if not member:
        raise HTTPException(status_code=404, detail="팀원이 아닙니다.")

    new_role = str(payload.get("research_role") or "").strip()[:60]
    if new_role != (member.research_role or ""):
        db.add(ResearchTeamRoleHistory(team_id=team.id, user_id=user.id,
                                       old_role=member.research_role or "", new_role=new_role))
        member.research_role = new_role
        db.commit()
    return _team_out(db, team)


@app.get("/api/research/{research_id}/team/role-history")
def list_team_role_history(research_id: int, db: Session = Depends(get_db),
                           user: User = Depends(require_student),
                           _seat: User = Depends(require_research_seat)):
    r = _own_research_or_404(db, user, research_id)
    team = _get_research_team(db, r.id)
    if not team:
        return {"items": []}
    rows = (db.query(ResearchTeamRoleHistory, User)
            .join(User, ResearchTeamRoleHistory.user_id == User.id)
            .filter(ResearchTeamRoleHistory.team_id == team.id)
            .order_by(ResearchTeamRoleHistory.changed_at.desc()).all())
    return {"items": [{"user_id": u.id, "name": u.name, "old_role": h.old_role,
                       "new_role": h.new_role, "changed_at": h.changed_at} for h, u in rows]}


@app.post("/api/research/{research_id}/team/role-suggestions")
def request_team_role_suggestions(research_id: int, db: Session = Depends(get_db),
                                  user: User = Depends(require_student),
                                  _seat: User = Depends(require_research_seat)):
    """연구 주제·유형을 보고 역할 후보를 제안해 달라고 맡긴다. 배정은
    강제하지 않는다 — 팀원들이 협의해서 정한다(§11)."""
    r = _own_research_or_404(db, user, research_id)
    require_ai(db, user)
    job = ai_jobs.enqueue(db, user.id, "research_team_roles", {"research_id": r.id})
    return {"job_id": job.id}


@app.post("/api/research/{research_id}/team/leave-request")
def request_leave_team(research_id: int, db: Session = Depends(get_db),
                       user: User = Depends(require_student),
                       _seat: User = Depends(require_research_seat)):
    """탈퇴는 학생 마음대로 바로 되지 않고 담임 교사 승인을 거친다(§13).
    담임이 없으면(교사 미배정) 승인해 줄 사람이 없어 무기한 대기가 되므로
    그 경우만 즉시 승인 처리한다."""
    r = _own_research_or_404(db, user, research_id)
    team = _get_research_team(db, r.id)
    if not team:
        raise HTTPException(status_code=400, detail="팀 연구가 아닙니다.")
    member = _team_member_or_none(db, team.id, user.id)
    if not member:
        raise HTTPException(status_code=404, detail="팀원이 아닙니다.")
    member_count = db.query(func.count(ResearchTeamMember.id)).filter(
        ResearchTeamMember.team_id == team.id).scalar()
    # 혼자 남은 상태에서 탈퇴를 허용하면 팀(ResearchTeam)만 멤버 없이 남는다 —
    # 그러면 나중에 아무도(원래 만든 사람도) 팀장 권한 검사를 통과 못 해
    # 연구를 영영 못 지우는 상태가 된다. 혼자면 탈퇴 대신 연구 삭제를 안내한다.
    if member_count <= 1:
        raise HTTPException(status_code=400,
                            detail="혼자 남은 팀은 탈퇴할 수 없습니다. 연구를 그만하려면 연구 삭제를 이용해주세요.")
    if member.is_leader:
        raise HTTPException(status_code=400,
                            detail="팀장은 다른 팀원이 있는 동안 탈퇴할 수 없습니다. 팀을 먼저 정리해주세요.")

    existing = db.query(ResearchTeamLeaveRequest).filter(
        ResearchTeamLeaveRequest.team_id == team.id, ResearchTeamLeaveRequest.user_id == user.id,
        ResearchTeamLeaveRequest.status == "pending").first()
    if existing:
        return _leave_request_out(existing)

    req = ResearchTeamLeaveRequest(team_id=team.id, user_id=user.id)
    if not user.teacher_udj_id:
        req.status = "approved"
        req.note = "담당 선생님이 없어 자동으로 승인됨"
        req.reviewed_at = datetime.utcnow()
        db.add(req)
        db.delete(member)
        db.commit()
        return _leave_request_out(req)

    db.add(req)
    db.commit()
    db.refresh(req)
    return _leave_request_out(req)


def _leave_request_out(r: ResearchTeamLeaveRequest) -> dict:
    return {"id": r.id, "team_id": r.team_id, "user_id": r.user_id, "status": r.status,
            "note": r.note or "", "created_at": r.created_at, "reviewed_at": r.reviewed_at}


@app.get("/api/teacher/team-leave-requests")
def list_team_leave_requests(db: Session = Depends(get_db),
                             user: User = Depends(require_roles(Role.teacher, Role.admin))):
    """담임 학급 학생의 탈퇴 신청 대기 목록."""
    rows = (db.query(ResearchTeamLeaveRequest, User, ResearchTeam, ResearchProject)
            .join(User, ResearchTeamLeaveRequest.user_id == User.id)
            .join(ResearchTeam, ResearchTeamLeaveRequest.team_id == ResearchTeam.id)
            .join(ResearchProject, ResearchTeam.research_id == ResearchProject.id)
            .filter(ResearchTeamLeaveRequest.status == "pending",
                    User.teacher_udj_id == user.udj_user_id)
            .order_by(ResearchTeamLeaveRequest.created_at.asc()).all())
    return {"items": [{
        **_leave_request_out(req), "student_name": stu.name,
        "research_title": proj.title or proj.interest_keyword,
    } for req, stu, team, proj in rows]}


@app.post("/api/team-leave-requests/{request_id}/approve")
def approve_team_leave(request_id: int, db: Session = Depends(get_db),
                       user: User = Depends(require_roles(Role.teacher, Role.admin))):
    req = db.get(ResearchTeamLeaveRequest, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="신청을 찾을 수 없습니다.")
    student = db.get(User, req.user_id)
    if not student:
        raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다.")
    assert_is_homeroom(db, user, student)
    if req.status != "pending":
        raise HTTPException(status_code=400, detail="이미 처리된 신청입니다.")

    member = _team_member_or_none(db, req.team_id, req.user_id)
    if member:
        db.delete(member)
    req.status = "approved"
    req.reviewed_by = user.id
    req.reviewed_at = datetime.utcnow()
    db.commit()
    return _leave_request_out(req)


@app.post("/api/team-leave-requests/{request_id}/reject")
def reject_team_leave(request_id: int, payload: dict, db: Session = Depends(get_db),
                      user: User = Depends(require_roles(Role.teacher, Role.admin))):
    req = db.get(ResearchTeamLeaveRequest, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="신청을 찾을 수 없습니다.")
    student = db.get(User, req.user_id)
    if not student:
        raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다.")
    assert_is_homeroom(db, user, student)
    if req.status != "pending":
        raise HTTPException(status_code=400, detail="이미 처리된 신청입니다.")

    req.status = "rejected"
    req.reviewed_by = user.id
    req.note = str(payload.get("note") or "")[:300]
    req.reviewed_at = datetime.utcnow()
    db.commit()
    return _leave_request_out(req)


def _board_post_out(p: ResearchBoardPost, author_name: str = "") -> dict:
    return {"id": p.id, "author_id": p.author_id, "author_name": author_name,
            "title": p.title or "", "content": p.content,
            "ai_suggestion": p.ai_suggestion or "", "ai_note": p.ai_note or "",
            "decision": p.decision, "decided_by": p.decided_by, "created_at": p.created_at}


@app.post("/api/research/{research_id}/board")
def create_board_post(research_id: int, payload: dict, db: Session = Depends(get_db),
                      user: User = Depends(require_student),
                      _seat: User = Depends(require_research_seat)):
    """팀 게시판에 조사·수집한 내용을 올린다(§14)."""
    r = _own_research_or_404(db, user, research_id)
    team = _get_research_team(db, r.id)
    if not team:
        raise HTTPException(status_code=400, detail="팀 연구가 아닙니다.")
    content = str(payload.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="내용을 입력해주세요.")
    post = ResearchBoardPost(team_id=team.id, author_id=user.id,
                             title=str(payload.get("title") or "")[:200], content=content)
    db.add(post)
    db.commit()
    db.refresh(post)
    return _board_post_out(post, user.name)


@app.get("/api/research/{research_id}/board")
def list_board_posts(research_id: int, db: Session = Depends(get_db),
                     user: User = Depends(require_student),
                     _seat: User = Depends(require_research_seat)):
    r = _own_research_or_404(db, user, research_id)
    team = _get_research_team(db, r.id)
    if not team:
        return {"items": []}
    rows = (db.query(ResearchBoardPost, User)
            .join(User, ResearchBoardPost.author_id == User.id)
            .filter(ResearchBoardPost.team_id == team.id)
            .order_by(ResearchBoardPost.created_at.desc()).all())
    return {"items": [_board_post_out(p, u.name) for p, u in rows]}


@app.post("/api/research/{research_id}/board/synthesize")
def synthesize_board(research_id: int, db: Session = Depends(get_db),
                     user: User = Depends(require_student),
                     _seat: User = Depends(require_research_seat)):
    """팀 게시글 전체를 AI가 훑어보고 유지/수정/중복/근거부족/제외를 제안한다.
    확정은 학생이 한다(§14) — AI 응답은 각 글의 ai_suggestion/ai_note 에만 반영된다."""
    r = _own_research_or_404(db, user, research_id)
    team = _get_research_team(db, r.id)
    if not team:
        raise HTTPException(status_code=400, detail="팀 연구가 아닙니다.")
    require_ai(db, user)
    posts = db.query(func.count(ResearchBoardPost.id)).filter(
        ResearchBoardPost.team_id == team.id).scalar() or 0
    if posts == 0:
        raise HTTPException(status_code=400, detail="아직 게시글이 없습니다.")

    # research_id 자체가 이미 이 팀 하나만 가리키는 값이라, 팀원 중 누가
    # 눌렀든(dedup_scope="any") 같은 요청으로 합친다.
    job = ai_jobs.enqueue(db, user.id, "research_board_synthesis", {"research_id": r.id},
                          dedup_key=f"board_synth:{r.id}", dedup_scope="any")
    return {"job_id": job.id}


@app.post("/api/research/{research_id}/board/{post_id}/decide")
def decide_board_post(research_id: int, post_id: int, payload: dict,
                      db: Session = Depends(get_db), user: User = Depends(require_student),
                      _seat: User = Depends(require_research_seat)):
    r = _own_research_or_404(db, user, research_id)
    team = _get_research_team(db, r.id)
    post = db.get(ResearchBoardPost, post_id) if team else None
    if not post or post.team_id != team.id:
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다.")
    decision = str(payload.get("decision") or "").strip()
    if decision not in ("approved", "rejected", "revised"):
        raise HTTPException(status_code=400, detail="처리 값이 올바르지 않습니다.")
    post.decision = decision
    post.decided_by = user.id
    if decision == "revised" and "content" in payload:
        post.content = str(payload.get("content") or post.content).strip() or post.content
    db.commit()
    return _board_post_out(post, (db.get(User, post.author_id) or user).name)


@app.get("/api/research/{research_id}/activity")
def list_research_activity(research_id: int, before_id: Optional[int] = None,
                           limit: int = Query(20, ge=1, le=50),
                           db: Session = Depends(get_db), user: User = Depends(require_student),
                           _seat: User = Depends(require_research_seat)):
    """최근 활동을 모아 보여준다 — 팀 연구를 염두에 뒀지만 개인 연구에서도
    그대로 쓸 수 있다. 별도 이벤트 테이블 없이, 이미 있는 기록들의
    시각을 모아 합성한다(§15 — 처음엔 기존 인프라로 polling)."""
    r = _own_research_or_404(db, user, research_id)
    events: List[dict] = []

    for p, u in (db.query(ResearchBoardPost, User)
                .join(User, ResearchBoardPost.author_id == User.id)
                .filter(ResearchBoardPost.team_id.in_(
                    db.query(ResearchTeam.id).filter(ResearchTeam.research_id == r.id)))
                .order_by(ResearchBoardPost.created_at.desc()).limit(limit).all()):
        events.append({"kind": "board_post", "at": p.created_at,
                       "text": f"{u.name}님이 게시글을 올렸어요: {p.title or p.content[:30]}"})

    for t in (db.query(ResearchTask)
             .filter(ResearchTask.research_id == r.id, ResearchTask.status == "completed",
                     ResearchTask.completed_at.isnot(None))
             .order_by(ResearchTask.completed_at.desc()).limit(limit).all()):
        events.append({"kind": "task_done", "at": t.completed_at, "text": f"할 일 완료: {t.title}"})

    team = _get_research_team(db, r.id)
    if team:
        for m, u in (db.query(ResearchTeamMember, User)
                    .join(User, ResearchTeamMember.user_id == User.id)
                    .filter(ResearchTeamMember.team_id == team.id)
                    .order_by(ResearchTeamMember.joined_at.desc()).limit(limit).all()):
            events.append({"kind": "member_joined", "at": m.joined_at,
                          "text": f"{u.name}님이 팀에 합류했어요"})

    events = [e for e in events if e["at"] is not None]
    events.sort(key=lambda e: e["at"], reverse=True)
    if before_id is not None:
        # before_id 는 클라이언트가 이미 본 마지막 이벤트의 시각(ms epoch)로 보낸다 —
        # 별도 id 체계가 없는 합성 스트림이라, 페이지네이션도 시각 기준으로 한다.
        cutoff = datetime.utcfromtimestamp(before_id / 1000)
        events = [e for e in events if e["at"] < cutoff]
    return {"items": events[:limit]}


# ── 외부 교사 질문 ────────────────────────────────────────────
# 같은 학교 담임이 아니라, 낯선 학교의 교사와 이어지는 완전히 별도 경로다
# (§17을 학생→교사만이 아니라 교사→학생 쪽도 가려 양방향 익명으로 확장 —
# 아래 _external_question_out/_external_answer_out 이 그 가림을 담당한다).
# 기존 viewable_students/assert_is_homeroom 스코프는 여기서 전혀 안 쓴다.

def _question_field_tags(q: "ExternalQuestion") -> List[str]:
    try:
        tags = json.loads(q.field_tags_json) if q.field_tags_json else []
        return [str(t) for t in tags] if isinstance(tags, list) else []
    except (ValueError, TypeError):
        return []


def _external_question_out(q: "ExternalQuestion", answer_count: int = 0) -> dict:
    """학생 쪽에 보여줄 모양 — 질문은 본인 것이니 그대로, 답변 개수만 곁들인다."""
    return {
        "id": q.id, "research_id": q.research_id, "title": q.title or "", "body": q.body,
        "field_tags": _question_field_tags(q), "status": q.status,
        "answer_count": answer_count, "created_at": q.created_at,
    }


def _external_answer_out_for_student(a: "ExternalAnswer", helpful: bool, reflected: bool) -> dict:
    """학생에게는 교사 신원을 절대 보여주지 않는다 — '교사 답변'이라는 표시만."""
    return {
        "id": a.id, "question_id": a.question_id, "body": a.body,
        "created_at": a.created_at, "helpful": helpful, "reflected": reflected,
    }


def _external_question_out_for_teacher(q: "ExternalQuestion", research_title: str,
                                       answered_by_me: bool) -> dict:
    """교사에게는 학생 신원·학교를 절대 보여주지 않는다 — 연구 제목·질문만."""
    return {
        "id": q.id, "research_title": research_title, "title": q.title or "", "body": q.body,
        "field_tags": _question_field_tags(q), "created_at": q.created_at,
        "answered_by_me": answered_by_me,
    }


@app.post("/api/research/{research_id}/questions")
def create_external_question(research_id: int, payload: dict, db: Session = Depends(get_db),
                             user: User = Depends(require_student),
                             _seat: User = Depends(require_research_seat)):
    """외부 교사에게 질문을 올린다. 팀 연구면 팀원 누구나 올릴 수 있다."""
    r = _own_research_or_404(db, user, research_id)
    body = str(payload.get("body") or "").strip()
    if not body:
        raise HTTPException(status_code=400, detail="질문 내용을 입력해주세요.")
    q = ExternalQuestion(research_id=r.id, asked_by=user.id,
                         title=str(payload.get("title") or "")[:200], body=body[:2000])
    db.add(q)
    db.commit()
    db.refresh(q)

    # 분야 태그는 AI가 추천한다(학생이 직접 안 골라도 됨, §16) — 실패해도
    # 질문 작성 자체는 이미 끝났으므로 조용히 넘어간다.
    if llm.available() and has_ai_consent(db, user):
        ai_jobs.enqueue(db, user.id, "research_question_tags", {"question_id": q.id})
    return _external_question_out(q, 0)


@app.get("/api/research/{research_id}/questions")
def list_external_questions(research_id: int, db: Session = Depends(get_db),
                            user: User = Depends(require_student),
                            _seat: User = Depends(require_research_seat)):
    r = _own_research_or_404(db, user, research_id)
    rows = (db.query(ExternalQuestion)
           .filter(ExternalQuestion.research_id == r.id)
           .order_by(ExternalQuestion.created_at.desc()).all())
    counts = dict(
        db.query(ExternalAnswer.question_id, func.count(ExternalAnswer.id))
        .filter(ExternalAnswer.question_id.in_([q.id for q in rows] or [0]))
        .group_by(ExternalAnswer.question_id).all()
    )
    return {"items": [_external_question_out(q, counts.get(q.id, 0)) for q in rows]}


@app.get("/api/external-questions/{question_id}/answers")
def list_external_answers(question_id: int, db: Session = Depends(get_db),
                          user: User = Depends(require_student)):
    q = db.get(ExternalQuestion, question_id)
    if not q:
        raise HTTPException(status_code=404, detail="질문을 찾을 수 없습니다.")
    _own_research_or_404(db, user, q.research_id)  # 이 질문이 내 연구 것인지 확인

    rows = (db.query(ExternalAnswer)
           .filter(ExternalAnswer.question_id == question_id)
           .order_by(ExternalAnswer.created_at.asc()).all())
    feedback = {
        f.answer_id for f in db.query(ExternalAnswerFeedback).filter(
            ExternalAnswerFeedback.user_id == user.id,
            ExternalAnswerFeedback.answer_id.in_([a.id for a in rows] or [0]),
            ExternalAnswerFeedback.helpful.is_(True)).all()
    }
    reflected = {
        n.answer_id for n in db.query(ExternalAnswerNote).filter(
            ExternalAnswerNote.answer_id.in_([a.id for a in rows] or [0])).all()
    }
    return {"items": [_external_answer_out_for_student(a, a.id in feedback, a.id in reflected)
                      for a in rows]}


@app.post("/api/external-answers/{answer_id}/helpful")
def toggle_answer_helpful(answer_id: int, db: Session = Depends(get_db),
                          user: User = Depends(require_student)):
    a = db.get(ExternalAnswer, answer_id)
    if not a:
        raise HTTPException(status_code=404, detail="답변을 찾을 수 없습니다.")
    q = db.get(ExternalQuestion, a.question_id)
    _own_research_or_404(db, user, q.research_id)

    existing = db.query(ExternalAnswerFeedback).filter(
        ExternalAnswerFeedback.answer_id == answer_id,
        ExternalAnswerFeedback.user_id == user.id).first()
    if existing:
        existing.helpful = not existing.helpful
    else:
        existing = ExternalAnswerFeedback(answer_id=answer_id, user_id=user.id, helpful=True)
        db.add(existing)
    db.commit()
    return {"ok": True, "helpful": bool(existing.helpful)}


@app.post("/api/external-answers/{answer_id}/reflect")
def reflect_answer_to_research(answer_id: int, db: Session = Depends(get_db),
                               user: User = Depends(require_student)):
    """이 답변을 연구에 반영할지 AI에게 정리를 맡긴다. AI는 정리만 하고,
    학생이 승인해야만 논문에 쓰인다(§19)."""
    a = db.get(ExternalAnswer, answer_id)
    if not a:
        raise HTTPException(status_code=404, detail="답변을 찾을 수 없습니다.")
    q = db.get(ExternalQuestion, a.question_id)
    r = _own_research_or_404(db, user, q.research_id)
    require_ai(db, user)

    job = ai_jobs.enqueue(db, user.id, "research_reflect_answer",
                          {"research_id": r.id, "answer_id": a.id},
                          dedup_key=f"reflect:{answer_id}")
    return {"job_id": job.id}


def _external_answer_note_out(n: "ExternalAnswerNote") -> dict:
    return {"id": n.id, "research_id": n.research_id, "answer_id": n.answer_id,
            "suggested_stage": n.suggested_stage or "", "note": n.note or "",
            "approved": n.approved, "created_at": n.created_at}


@app.get("/api/research/{research_id}/answer-notes")
def list_answer_notes(research_id: int, db: Session = Depends(get_db),
                      user: User = Depends(require_student),
                      _seat: User = Depends(require_research_seat)):
    r = _own_research_or_404(db, user, research_id)
    rows = (db.query(ExternalAnswerNote)
           .filter(ExternalAnswerNote.research_id == r.id)
           .order_by(ExternalAnswerNote.created_at.desc()).all())
    return {"items": [_external_answer_note_out(n) for n in rows]}


@app.post("/api/external-answer-notes/{note_id}/approve")
def approve_answer_note(note_id: int, db: Session = Depends(get_db),
                        user: User = Depends(require_student)):
    n = db.get(ExternalAnswerNote, note_id)
    if not n:
        raise HTTPException(status_code=404, detail="반영 제안을 찾을 수 없습니다.")
    _own_research_or_404(db, user, n.research_id)
    n.approved = True
    db.commit()
    return _external_answer_note_out(n)


@app.delete("/api/external-answer-notes/{note_id}")
def discard_answer_note(note_id: int, db: Session = Depends(get_db),
                        user: User = Depends(require_student)):
    """AI가 정리한 내용이 마음에 안 들면 학생이 그냥 지울 수 있다."""
    n = db.get(ExternalAnswerNote, note_id)
    if not n:
        raise HTTPException(status_code=404, detail="반영 제안을 찾을 수 없습니다.")
    _own_research_or_404(db, user, n.research_id)
    db.delete(n)
    db.commit()
    return {"ok": True}


# ── 외부 교사 질문 — 교사 쪽 ───────────────────────────────────────

@app.get("/api/teacher/field-tags")
def list_my_field_tags(db: Session = Depends(get_db),
                       user: User = Depends(require_roles(Role.teacher, Role.admin))):
    rows = (db.query(TeacherFieldTag).filter(TeacherFieldTag.teacher_id == user.id)
           .order_by(TeacherFieldTag.created_at.asc()).all())
    return {"items": [{"id": t.id, "tag": t.tag} for t in rows]}


@app.post("/api/teacher/field-tags")
def add_my_field_tag(payload: dict, db: Session = Depends(get_db),
                     user: User = Depends(require_roles(Role.teacher, Role.admin))):
    """분야 태그를 등록해야만 외부 질문이 보인다(옵트인, §17)."""
    tag = str(payload.get("tag") or "").strip()[:60]
    if not tag:
        raise HTTPException(status_code=400, detail="분야를 입력해주세요.")
    existing = db.query(TeacherFieldTag).filter(
        TeacherFieldTag.teacher_id == user.id, TeacherFieldTag.tag == tag).first()
    if existing:
        return {"id": existing.id, "tag": existing.tag}
    row = TeacherFieldTag(teacher_id=user.id, tag=tag)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "tag": row.tag}


@app.delete("/api/teacher/field-tags/{tag_id}")
def remove_my_field_tag(tag_id: int, db: Session = Depends(get_db),
                        user: User = Depends(require_roles(Role.teacher, Role.admin))):
    row = db.get(TeacherFieldTag, tag_id)
    if not row or row.teacher_id != user.id:
        raise HTTPException(status_code=404, detail="분야 태그를 찾을 수 없습니다.")
    db.delete(row)
    db.commit()
    return {"ok": True}


@app.get("/api/teacher/external-questions")
def list_matched_external_questions(db: Session = Depends(get_db),
                                    user: User = Depends(require_roles(Role.teacher, Role.admin))):
    """내가 등록한 분야 태그와 겹치는 질문만 보여준다. 태그를 하나도
    등록하지 않았으면 아무것도 안 보인다(옵트인)."""
    my_tags = {t.tag for t in db.query(TeacherFieldTag).filter(
        TeacherFieldTag.teacher_id == user.id).all()}
    if not my_tags:
        return {"items": [], "my_tags": []}

    rows = (db.query(ExternalQuestion, ResearchProject)
           .join(ResearchProject, ExternalQuestion.research_id == ResearchProject.id)
           .order_by(ExternalQuestion.created_at.desc()).limit(100).all())
    my_answered = {
        a.question_id for a in db.query(ExternalAnswer).filter(
            ExternalAnswer.teacher_id == user.id).all()
    }
    items = []
    for q, proj in rows:
        if my_tags & set(_question_field_tags(q)):
            items.append(_external_question_out_for_teacher(
                q, proj.title or proj.interest_keyword, q.id in my_answered))
    return {"items": items, "my_tags": sorted(my_tags)}


@app.post("/api/external-questions/{question_id}/answers")
def answer_external_question(question_id: int, payload: dict, db: Session = Depends(get_db),
                             user: User = Depends(require_roles(Role.teacher, Role.admin))):
    q = db.get(ExternalQuestion, question_id)
    if not q:
        raise HTTPException(status_code=404, detail="질문을 찾을 수 없습니다.")
    body = str(payload.get("body") or "").strip()
    if not body:
        raise HTTPException(status_code=400, detail="답변 내용을 입력해주세요.")
    a = ExternalAnswer(question_id=question_id, teacher_id=user.id, body=body[:3000])
    db.add(a)
    if q.status == "open":
        q.status = "answered"
    db.commit()
    db.refresh(a)
    return {"id": a.id, "question_id": a.question_id, "body": a.body, "created_at": a.created_at}


@app.get("/api/schools/research-contribution")
def school_research_contribution(db: Session = Depends(get_db),
                                 user: User = Depends(require_roles(
                                     Role.student, Role.school, Role.teacher, Role.admin))):
    """학교별 답변 기여도 TOP 10. 목적은 경쟁이 아니라 지원 장려라, 교사
    개인 식별자는 안 넣는다(§20). 학생 홈 화면에도 그대로 보여줄 만큼
    안전한 데이터라 학생 role 도 허용한다."""
    rows = (db.query(User.school_id, func.count(ExternalAnswer.id))
           .join(ExternalAnswer, ExternalAnswer.teacher_id == User.id)
           .filter(User.school_id.isnot(None))
           .group_by(User.school_id).all())
    counts = {sid: n for sid, n in rows}
    helpful_rows = (db.query(User.school_id, func.count(ExternalAnswerFeedback.id))
                   .join(ExternalAnswer, ExternalAnswer.teacher_id == User.id)
                   .join(ExternalAnswerFeedback, ExternalAnswerFeedback.answer_id == ExternalAnswer.id)
                   .filter(User.school_id.isnot(None), ExternalAnswerFeedback.helpful.is_(True))
                   .group_by(User.school_id).all())
    helpful = {sid: n for sid, n in helpful_rows}
    reflected_rows = (db.query(User.school_id, func.count(ExternalAnswerNote.id))
                      .join(ExternalAnswer, ExternalAnswer.teacher_id == User.id)
                      .join(ExternalAnswerNote, ExternalAnswerNote.answer_id == ExternalAnswer.id)
                      .filter(User.school_id.isnot(None), ExternalAnswerNote.approved.is_(True))
                      .group_by(User.school_id).all())
    reflected = {sid: n for sid, n in reflected_rows}

    # 기록해엔 School 표가 따로 없다 — school_id 는 UDJ 쪽 학교를 가리키는
    # 숫자일 뿐이라, 이름은 User.school_name(로그인 때마다 UDJ에서 받아온
    # 값)에서 학교당 아무거나 하나 골라 쓴다.
    schools = {}
    if counts:
        for sid, name in (db.query(User.school_id, User.school_name)
                          .filter(User.school_id.in_(counts.keys()), User.school_name != "")
                          .all()):
            schools.setdefault(sid, name)
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:10]
    return {"items": [
        {"school_name": schools.get(sid, ""), "answers": n,
         "helpful": helpful.get(sid, 0), "reflected": reflected.get(sid, 0)}
        for sid, n in ranked
    ]}


@app.get("/api/notifications/summary")
def notifications_summary(db: Session = Depends(get_db), user: User = Depends(require_student)):
    """홈 화면 알림 배지. 일지 피드백은 이용권과 무관하게 항상 무료라
    좌석 검사 없이 누구나 볼 수 있다 — 연구를 아예 안 하는 학생도 이 배지는
    써야 한다."""
    unread_feedback = db.query(func.count(JournalEntry.id)).filter(
        JournalEntry.user_id == user.id, JournalEntry.feedback.isnot(None),
        JournalEntry.feedback != "", JournalEntry.feedback_read_at.is_(None)).scalar() or 0

    team_research_ids = (
        db.query(ResearchTeam.research_id)
        .join(ResearchTeamMember, ResearchTeamMember.team_id == ResearchTeam.id)
        .filter(ResearchTeamMember.user_id == user.id)
    )
    research_ids = [rid for (rid,) in db.query(ResearchProject.id).filter(
        or_(ResearchProject.student_id == user.id,
            ResearchProject.id.in_(team_research_ids))).all()]

    new_answers = 0
    if research_ids:
        # 연구별로 "마지막으로 확인한 시각"이 따로 있다 — 하나로 합쳐서 쓰면
        # 연구 A를 보러 들어간 것만으로 연구 B에 온 안 읽은 답변까지 같이
        # 읽음 처리돼 버린다(실제로 발견된 버그). epoch 이전이면 전부 새것.
        epoch = datetime(2000, 1, 1)
        seen_map = {
            s.research_id: s.seen_at for s in db.query(ExternalAnswerSeen).filter(
                ExternalAnswerSeen.user_id == user.id,
                ExternalAnswerSeen.research_id.in_(research_ids)).all()
        }
        rows = (db.query(ExternalAnswer.created_at, ExternalQuestion.research_id)
               .join(ExternalQuestion, ExternalQuestion.id == ExternalAnswer.question_id)
               .filter(ExternalQuestion.research_id.in_(research_ids)).all())
        new_answers = sum(1 for created_at, rid in rows if created_at > seen_map.get(rid, epoch))
    return {"unread_journal_feedback": unread_feedback, "new_external_answers": new_answers}


@app.post("/api/notifications/mark-external-answers-seen")
def mark_external_answers_seen(payload: dict, db: Session = Depends(get_db),
                               user: User = Depends(require_student)):
    """연구 하나의 답변을 확인했다고 표시한다 — 전체가 아니라 이 연구만."""
    research_id = payload.get("research_id")
    if not research_id:
        raise HTTPException(status_code=400, detail="research_id가 필요합니다.")
    r = _own_research_or_404(db, user, int(research_id))
    row = db.query(ExternalAnswerSeen).filter(
        ExternalAnswerSeen.user_id == user.id, ExternalAnswerSeen.research_id == r.id).first()
    if row:
        row.seen_at = datetime.utcnow()
    else:
        db.add(ExternalAnswerSeen(user_id=user.id, research_id=r.id))
    db.commit()
    return {"ok": True}


# ── 교사: 담당 학급 연구 현황 ────────────────────────────────────

def _feedback_out(f: ResearchFeedback) -> dict:
    return {"id": f.id, "stage": f.stage, "content": f.content, "created_at": f.created_at}


# 학생 화면(ResearchWorkspace.jsx)의 단계 사다리와 정확히 같은 순서·이름을
# 서버에도 둔다(§9 "단계 사다리 서버 반영") — 지금까진 이 계산이 그 화면
# 안에만 있어서, 교사 현황판(/api/teacher/research)은 계획 확정 이후로는
# 절대 안 바뀌는 raw current_stage 를 그대로 보여줬다. 학생이 로드맵·논문
# 까지 다 마쳐도 교사 눈엔 "연구 계획"에 멈춰 있는 것처럼 보였다는 뜻이다.
DISPLAY_STAGE_ORDER = [
    ("interest", "관심 탐색"), ("topic", "주제 선정"), ("question", "연구 질문"),
    ("plan", "연구 계획"), ("literature", "문헌 조사"), ("method", "연구 설계"),
    ("execution", "실행"), ("data", "데이터 수집"), ("analysis", "분석"),
    ("discussion", "논의"), ("final", "최종 산출물"),
]
_DISPLAY_STAGE_INDEX = {k: i for i, (k, _label) in enumerate(DISPLAY_STAGE_ORDER)}


def _display_stages_batch(db: Session, researches: List[ResearchProject]) -> Dict[int, dict]:
    """current_stage 는 '연구 계획 확정'까지만 서버에 저장된다(그 뒤로는
    학생이 실제로 자료를 쌓았는지로만 진행을 판단할 수 있다) — 그래서
    여기서도 실제로 쌓인 자료를 보고 단계를 다시 계산한다. 뒤로는
    안 돌아간다(한 번 도달한 단계보다 앞으로 표시하지 않는다).

    여러 연구를 한 번에 계산한다 — 교사 현황판처럼 학생 수만큼 반복 호출하면
    학생당 6쿼리씩 나가는 N+1이 생기므로, research_id IN (...) 로 한 번에 모아 온다."""
    ids = [r.id for r in researches]
    if not ids:
        return {}
    roadmap = {rid for (rid,) in db.query(ResearchRoadmapStep.research_id)
              .filter(ResearchRoadmapStep.research_id.in_(ids)).distinct()}
    literature = {rid for (rid,) in db.query(ResearchLiterature.research_id)
                 .filter(ResearchLiterature.research_id.in_(ids),
                         ResearchLiterature.verified.is_(True)).distinct()}
    analysis = {rid for (rid,) in db.query(ResearchAnalysis.research_id)
               .filter(ResearchAnalysis.research_id.in_(ids)).distinct()}
    review = {rid for (rid,) in db.query(ResearchReview.research_id)
             .filter(ResearchReview.research_id.in_(ids)).distinct()}
    paper = {rid for (rid,) in db.query(ResearchPaper.research_id)
            .filter(ResearchPaper.research_id.in_(ids)).distinct()}
    portfolio = {rid for (rid,) in db.query(ResearchPortfolio.research_id)
                .filter(ResearchPortfolio.research_id.in_(ids)).distinct()}

    out: Dict[int, dict] = {}
    for r in researches:
        idx = _DISPLAY_STAGE_INDEX.get(r.current_stage, 0)
        if r.id in roadmap:
            idx = max(idx, _DISPLAY_STAGE_INDEX["literature"])
        if r.id in literature:
            idx = max(idx, _DISPLAY_STAGE_INDEX["method"])
        if r.id in analysis:
            idx = max(idx, _DISPLAY_STAGE_INDEX["analysis"])
        if r.id in review or r.follow_up_ideas:
            idx = max(idx, _DISPLAY_STAGE_INDEX["discussion"])
        if r.id in paper or r.id in portfolio:
            idx = max(idx, _DISPLAY_STAGE_INDEX["final"])
        key, label = DISPLAY_STAGE_ORDER[idx]
        out[r.id] = {
            "stage": key, "stage_label": label,
            "stage_progress": round(idx / (len(DISPLAY_STAGE_ORDER) - 1) * 100),
        }
    return out


def _display_stage(db: Session, r: ResearchProject) -> dict:
    return _display_stages_batch(db, [r])[r.id]


def _latest_research_for(db: Session, student_id: int) -> Optional[ResearchProject]:
    return (db.query(ResearchProject)
           .filter(ResearchProject.student_id == student_id,
                   ResearchProject.status.in_(("planning", "active", "paused")))
           .order_by(ResearchProject.updated_at.desc()).first())


def _last_activity_at(db: Session, research_id: int, fallback: datetime) -> datetime:
    latest_turn = (db.query(func.max(ResearchDialogueTurn.created_at))
                  .filter(ResearchDialogueTurn.research_id == research_id).scalar())
    latest_task = (db.query(func.max(ResearchTask.completed_at))
                  .filter(ResearchTask.research_id == research_id).scalar())
    candidates = [d for d in (fallback, latest_turn, latest_task) if d]
    return max(candidates) if candidates else fallback


def _last_activity_batch(db: Session, research_ids: List[int]) -> Dict[int, datetime]:
    """research_id 별 최근 활동 시각을 한 번에 모아 온다(교사 현황판용 N+1 방지)."""
    if not research_ids:
        return {}
    turns = dict(db.query(ResearchDialogueTurn.research_id, func.max(ResearchDialogueTurn.created_at))
                .filter(ResearchDialogueTurn.research_id.in_(research_ids))
                .group_by(ResearchDialogueTurn.research_id).all())
    tasks = dict(db.query(ResearchTask.research_id, func.max(ResearchTask.completed_at))
                .filter(ResearchTask.research_id.in_(research_ids), ResearchTask.completed_at.isnot(None))
                .group_by(ResearchTask.research_id).all())
    out: Dict[int, datetime] = {}
    for rid in research_ids:
        candidates = [d for d in (turns.get(rid), tasks.get(rid)) if d]
        if candidates:
            out[rid] = max(candidates)
    return out


@app.get("/api/teacher/research")
def list_teacher_research(db: Session = Depends(get_db),
                          user: User = Depends(require_roles(Role.teacher, Role.admin))):
    """담임 학급 학생들의 연구 현황을 한눈에 본다. 점수판이 아니라
    현황판이다 — 평가하는 표현은 쓰지 않는다."""
    students = (db.query(User)
               .filter(User.teacher_udj_id == user.udj_user_id, User.role == Role.student,
                       User.verified.is_(True)).all())
    student_ids = [s.id for s in students]
    now = datetime.utcnow()

    researches = (db.query(ResearchProject)
                 .filter(ResearchProject.student_id.in_(student_ids),
                         ResearchProject.status.in_(("planning", "active", "paused")))
                 .all()) if student_ids else []
    latest_by_student: Dict[int, ResearchProject] = {}
    for r in researches:
        cur = latest_by_student.get(r.student_id)
        if not cur or r.updated_at > cur.updated_at:
            latest_by_student[r.student_id] = r

    latest_list = list(latest_by_student.values())
    stages = _display_stages_batch(db, latest_list)
    activity = _last_activity_batch(db, [r.id for r in latest_list])

    items = []
    for s in students:
        research = latest_by_student.get(s.id)
        if not research:
            items.append({"student_id": s.id, "student_name": s.name, "research": None,
                         "activity_status": "no_research"})
            continue
        last_active = activity.get(research.id) or research.updated_at
        inactive_days = (now - last_active).days
        items.append({
            "student_id": s.id, "student_name": s.name,
            "research": {"id": research.id, "title": research.title or research.interest_keyword,
                        "current_stage": research.current_stage, "progress": research.progress,
                        **stages[research.id]},
            "activity_status": "inactive" if inactive_days >= 10 else "normal",
            "inactive_days": inactive_days,
        })
    return {"items": items}


@app.get("/api/teacher/research/{student_id}")
def get_teacher_research_detail(student_id: int, db: Session = Depends(get_db),
                                user: User = Depends(require_roles(Role.teacher, Role.admin))):
    student = db.get(User, student_id)
    if not student:
        raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다.")
    assert_is_homeroom(db, user, student)

    research = _latest_research_for(db, student_id)
    if not research:
        return {"student_name": student.name, "research": None}

    steps = (db.query(ResearchRoadmapStep).filter(ResearchRoadmapStep.research_id == research.id)
            .order_by(ResearchRoadmapStep.week_number.asc()).all())
    tasks = (db.query(ResearchTask).filter(ResearchTask.research_id == research.id).all())
    by_status: Dict[str, List[str]] = {"completed": [], "in_progress": [], "todo": []}
    for t in tasks:
        by_status.setdefault(t.status, []).append(t.title)
    last_report = (db.query(ResearchReport).filter(ResearchReport.research_id == research.id)
                  .order_by(ResearchReport.created_at.desc()).first())

    return {
        "student_name": student.name,
        "research": research_out(db, research),
        "structure": _research_structure(research),
        "roadmap_weeks": len(steps),
        "tasks": {"completed": by_status.get("completed", []),
                 "in_progress": by_status.get("in_progress", []),
                 "next": by_status.get("todo", [])[:5]},
        "last_report": _report_out(last_report) if last_report else None,
    }


@app.post("/api/teacher/research/{research_id}/feedback")
def add_teacher_research_feedback(research_id: int, payload: dict, request: Request,
                                  db: Session = Depends(get_db),
                                  user: User = Depends(require_roles(Role.teacher, Role.admin))):
    research = db.get(ResearchProject, research_id)
    if not research:
        raise HTTPException(status_code=404, detail="연구를 찾을 수 없습니다.")
    student = db.get(User, research.student_id)
    assert_is_homeroom(db, user, student)

    content = str(payload.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="내용을 입력해주세요.")
    fb = ResearchFeedback(research_id=research.id, teacher_id=user.id,
                          stage=research.current_stage, content=content)
    db.add(fb)
    db.commit()
    db.refresh(fb)
    write_audit(db, request, user, action="research.feedback", target_type="research",
               target_id=research.id, detail=f"student={student.id}")
    return _feedback_out(fb)


@app.get("/api/teacher/research/{research_id}/feedback")
def list_teacher_research_feedback(research_id: int, db: Session = Depends(get_db),
                                   user: User = Depends(require_roles(Role.teacher, Role.admin))):
    research = db.get(ResearchProject, research_id)
    if not research:
        raise HTTPException(status_code=404, detail="연구를 찾을 수 없습니다.")
    student = db.get(User, research.student_id)
    assert_is_homeroom(db, user, student)
    rows = (db.query(ResearchFeedback).filter(ResearchFeedback.research_id == research.id)
           .order_by(ResearchFeedback.created_at.desc()).all())
    return {"items": [_feedback_out(f) for f in rows]}






# ── 뒤에서 실제로 일하는 함수들 ────────────────────────────
# ai_jobs 가 이 함수를 부른다. 여기서 ai_jobs 를 부르면 서로 물고 물려
# import 가 꼬이므로, 등록하는 방식으로 이어 둔다.


def _load_experiences(db: Session, user_id: int, ids: List[int]) -> List[dict]:
    """고른 일지의 분석 결과를 모은다.

    분석해 둔 것이 있으면 그것을 쓰고, 없으면 원문을 그대로 쓴다.
    분석을 안 했다고 초안을 못 만들 이유는 없다.
    """
    out = []
    for jid in ids[:5]:
        e = db.get(JournalEntry, jid)
        if not e or e.user_id != user_id:
            continue
        content = journal_content(e)
        text = ai_service.journal_text(e, content)
        digest = ai_service.content_hash(text)

        row = (db.query(JournalAnalysis)
               .filter(JournalAnalysis.journal_id == e.id,
                       JournalAnalysis.content_hash == digest).first())
        if row:
            try:
                data = json.loads(row.analysis_json or "{}")
            except (ValueError, TypeError):
                data = {}
            out.append({
                "journal_id": e.id,
                "entry_date": e.entry_date.isoformat() if e.entry_date else "",
                "experience": data.get("experience") or {},
                "skills": data.get("skills") or [],
                "content": row.cleaned_content or text,
            })
        else:
            out.append({
                "journal_id": e.id,
                "entry_date": e.entry_date.isoformat() if e.entry_date else "",
                "content": text,
            })
    return out


def _load_research_experiences(db: Session, user_id: int, ids: List[int]) -> List[dict]:
    """연구 활동도 자소서 재료로 쓴다(§23). 팀 연구면 본인이 한 일만 담는다 —
    팀원 전체의 성과를 자기 것처럼 쓰면 안 되기 때문이다. 그래서 여기서는
    연구 개요와, 팀이면 본인 역할·본인이 직접 올린 게시글만 골라 담는다."""
    out = []
    for rid in ids[:5]:
        r = db.get(ResearchProject, rid)
        if not r:
            continue
        team = _get_research_team(db, r.id)
        member = _team_member_or_none(db, team.id, user_id) if team else None
        if r.student_id != user_id and not member:
            continue  # 내 연구도, 내가 속한 팀도 아니면 재료로 못 쓴다

        parts = [f"연구 주제: {r.title or r.interest_keyword}"]
        if r.research_question:
            parts.append(f"연구 질문: {r.research_question}")
        if team:
            role = (member.research_role if member else "") or "(역할 미지정)"
            parts.append(f"팀으로 진행한 연구이며, 이 중 본인이 맡은 역할: {role}")
            own_posts = (db.query(ResearchBoardPost)
                        .filter(ResearchBoardPost.team_id == team.id,
                                ResearchBoardPost.author_id == user_id)
                        .order_by(ResearchBoardPost.created_at.asc()).limit(5).all())
            for p in own_posts:
                parts.append(f"- (본인이 직접 조사·작성) {p.title or ''}: {p.content}")
        elif r.method_detail:
            parts.append(f"연구 방법: {r.method_detail}")
        if r.follow_up_ideas:
            parts.append(f"후속 생각: {r.follow_up_ideas}")

        out.append({
            "research_id": r.id,
            "entry_date": (r.completed_at or r.updated_at).isoformat()
                if (r.completed_at or r.updated_at) else "",
            "content": "\n".join(parts),
        })
    return out


def _job_analyze(db: Session, user_id: int, payload: dict) -> dict:
    user = db.get(User, user_id)
    e = db.get(JournalEntry, int(payload.get("journal_id") or 0))
    if not user or not e or e.user_id != user_id:
        return {"ok": False, "error": "일지를 찾을 수 없습니다."}

    content = journal_content(e)
    result = ai_service.analyze_journal(e, content, user)
    if not result.get("ok"):
        return result

    # 다음에 또 부르지 않도록 남겨 둔다.
    digest = payload.get("hash") or ai_service.content_hash(
        ai_service.journal_text(e, content))
    keep = {k: result[k] for k in ("experience", "skills", "keywords",
                                   "inappropriate") if k in result}
    row = (db.query(JournalAnalysis)
           .filter(JournalAnalysis.journal_id == e.id,
                   JournalAnalysis.content_hash == digest).first())
    if row is None:
        row = JournalAnalysis(journal_id=e.id, user_id=user_id,
                              content_hash=digest)
        db.add(row)
    row.model_name = result.get("model", "")
    row.cleaned_content = result.get("cleaned_content", "")
    row.analysis_json = json.dumps(keep, ensure_ascii=False)
    db.commit()
    return result


def _job_generate(db: Session, user_id: int, payload: dict) -> dict:
    user = db.get(User, user_id)
    if not user:
        return {"ok": False, "error": "이용자를 찾을 수 없습니다."}
    exps = (_load_experiences(db, user_id, payload.get("journal_ids") or [])
           + _load_research_experiences(db, user_id, payload.get("research_ids") or []))
    if not exps:
        return {"ok": False, "error": "고른 경험을 찾을 수 없습니다."}
    return ai_service.generate_essay(
        str(payload.get("question") or ""), exps, user,
        limit=int(payload.get("limit") or ai_service.DEFAULT_LIMIT))


def _job_verify(db: Session, user_id: int, payload: dict) -> dict:
    user = db.get(User, user_id)
    if not user:
        return {"ok": False, "error": "이용자를 찾을 수 없습니다."}
    exps = (_load_experiences(db, user_id, payload.get("journal_ids") or [])
           + _load_research_experiences(db, user_id, payload.get("research_ids") or []))
    if not exps:
        return {"ok": False, "error": "근거가 될 경험을 찾을 수 없습니다."}
    return ai_service.verify_essay(str(payload.get("draft") or ""), exps, user)


def _job_subject_note(db: Session, user_id: int, payload: dict) -> dict:
    """user_id 는 이 작업을 맡긴 교사다(글의 주인인 학생이 아니다).

    작업이 실제로 도는 시점에 권한을 한 번 더 확인한다 — 요청을 받은
    순간과 큐에서 처리되는 순간 사이에 담당이 바뀌었을 수도 있다.
    """
    teacher = db.get(User, user_id)
    student_id = int(payload.get("student_id") or 0)
    subject_id = int(payload.get("subject_id") or 0)
    student = db.get(User, student_id)
    if not teacher or not student:
        return {"ok": False, "error": "계정을 찾을 수 없습니다."}
    try:
        assert_can_view_lesson(db, teacher, student, subject_id)
    except HTTPException as exc:
        return {"ok": False, "error": exc.detail}

    records = _journal_records(db, payload.get("journal_ids") or [],
                               student_id, "lesson", subject_id)
    if not records:
        return {"ok": False, "error": "이 과목의 수업일지가 없습니다."}

    subj = db.get(SchoolSubject, subject_id)
    result = ai_service.build_subject_note(records, subj.name if subj else "", student)
    if not result.get("ok"):
        return result

    draft = StudentRecordAiDraft(
        school_id=student.school_id, student_id=student_id, teacher_id=teacher.id,
        type="subject_special_note", subject_id=subject_id,
        content=result["draft"], ai_original=result["draft"],
        source_journal_ids=json.dumps([r["journal_id"] for r in records]),
        source_kind="journal",
        status="draft", model_name=result.get("model", ""),
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    result["draft_id"] = draft.id
    return result


def _job_observation_subject_note(db: Session, user_id: int, payload: dict) -> dict:
    """user_id 는 관찰 기록을 쓴 그 교사 본인이다 — 관찰 기록은 애초에
    작성자만의 것이라, /ai-special-note 처럼 '이 교사가 이 과목을
    담당하는가'만 확인하면 되고 다른 교사 것이 섞일 걱정은 구조적으로 없다.
    """
    teacher = db.get(User, user_id)
    student_id = int(payload.get("student_id") or 0)
    subject_id = int(payload.get("subject_id") or 0)
    student = db.get(User, student_id)
    if not teacher or not student:
        return {"ok": False, "error": "계정을 찾을 수 없습니다."}
    try:
        assert_can_view_lesson(db, teacher, student, subject_id)
    except HTTPException as exc:
        return {"ok": False, "error": exc.detail}

    records = _observation_records(db, payload.get("observation_ids") or [],
                                   teacher.id, student_id, subject_id)
    if not records:
        return {"ok": False, "error": "이 과목의 관찰 기록이 없습니다."}

    subj = db.get(SchoolSubject, subject_id)
    result = ai_service.build_subject_note(records, subj.name if subj else "", student)
    if not result.get("ok"):
        return result

    draft = StudentRecordAiDraft(
        school_id=student.school_id, student_id=student_id, teacher_id=teacher.id,
        type="subject_special_note", subject_id=subject_id,
        content=result["draft"], ai_original=result["draft"],
        source_journal_ids=json.dumps([r["observation_id"] for r in records]),
        source_kind="observation",
        status="draft", model_name=result.get("model", ""),
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    result["draft_id"] = draft.id
    return result


def _job_behavior_note(db: Session, user_id: int, payload: dict) -> dict:
    teacher = db.get(User, user_id)
    student_id = int(payload.get("student_id") or 0)
    student = db.get(User, student_id)
    if not teacher or not student:
        return {"ok": False, "error": "계정을 찾을 수 없습니다."}
    try:
        assert_is_homeroom(db, teacher, student)
    except HTTPException as exc:
        return {"ok": False, "error": exc.detail}

    records = _journal_records(db, payload.get("journal_ids") or [], student_id, "diary")
    if not records:
        return {"ok": False, "error": "학교생활일지가 없습니다."}

    result = ai_service.build_behavior_note(records, student)
    if not result.get("ok"):
        return result

    draft = StudentRecordAiDraft(
        school_id=student.school_id, student_id=student_id, teacher_id=teacher.id,
        type="behavioral_characteristics", subject_id=None,
        content=result["draft"], ai_original=result["draft"],
        source_journal_ids=json.dumps([r["journal_id"] for r in records]),
        status="draft", model_name=result.get("model", ""),
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    result["draft_id"] = draft.id
    return result


def _all_journal_texts(db: Session, student_id: int) -> List[dict]:
    """이 학생이 제출한 일지 전부를 (id, 날짜, 글) 목록으로."""
    rows = (db.query(JournalEntry)
           .filter(JournalEntry.user_id == student_id, JournalEntry.sent_at.isnot(None))
           .order_by(JournalEntry.entry_date.desc()).all())
    out = []
    for e in rows:
        text = ai_service.journal_text(e, journal_content(e))
        if text.strip():
            out.append({"id": e.id, "entry_date": e.entry_date.isoformat() if e.entry_date else "",
                       "text": text})
    return out












def _job_research_dialogue(db: Session, user_id: int, payload: dict) -> dict:
    user = db.get(User, user_id)
    research = db.get(ResearchProject, int(payload.get("research_id") or 0))
    if not user or not research or not _job_research_authorized(db, research, user_id):
        return {"ok": False, "error": "연구를 찾을 수 없습니다."}

    result = research_ai.run_dialogue(
        research.interest_keyword, payload.get("turns") or [],
        str(payload.get("message") or ""), user)
    if not result.get("ok"):
        return result

    # 지시문에 "질문은 최대 3개까지"라 못박아 뒀지만, AI가 이 규칙을 놓치고
    # ready_for_topics 를 계속 false로 돌려주면 학생이 같은 대화에 갇힌다.
    # 이미 AI가 3번 이상 답했다면(=이번이 네 번째 이상 응답) 서버가 강제로
    # 다음 단계로 넘긴다 — AI 판단을 신뢰하되, 무한 반복은 서버가 막는다.
    ai_turn_count = db.query(func.count(ResearchDialogueTurn.id)).filter(
        ResearchDialogueTurn.research_id == research.id, ResearchDialogueTurn.role == "ai").scalar() or 0
    if ai_turn_count >= 3:
        result["ready_for_topics"] = True

    db.add(ResearchDialogueTurn(research_id=research.id, role="ai",
                                stage=research.current_stage,
                                content=result["question"]))
    if result.get("ready_for_topics"):
        research.current_stage = "topic"
    db.commit()
    return result


def _job_research_topics(db: Session, user_id: int, payload: dict) -> dict:
    user = db.get(User, user_id)
    research = db.get(ResearchProject, int(payload.get("research_id") or 0))
    if not user or not research or not _job_research_authorized(db, research, user_id):
        return {"ok": False, "error": "연구를 찾을 수 없습니다."}

    result = research_ai.generate_topics(
        research.interest_keyword, payload.get("turns") or [], user,
        difficulty=research.difficulty_level or "easy")
    if not result.get("ok"):
        return result

    for t in result["topics"]:
        db.add(ResearchTopicSuggestion(
            research_id=research.id, title=t["title"][:200],
            research_question=t["research_question"],
            research_type=t["research_type"][:20],
            feasibility_note=t["feasibility_note"],
            expected_duration=t["expected_duration"][:40],
            required_materials=t["required_materials"],
            method_summary=t["method_summary"],
            difficulty=t["difficulty"][:10],
            extensibility=t["extensibility"],
        ))
    research.current_stage = "topic"
    db.commit()
    return result


def _job_research_topic_review(db: Session, user_id: int, payload: dict) -> dict:
    user = db.get(User, user_id)
    research = db.get(ResearchProject, int(payload.get("research_id") or 0))
    if not user or not research or not _job_research_authorized(db, research, user_id):
        return {"ok": False, "error": "연구를 찾을 수 없습니다."}
    topic = db.get(ResearchTopicSuggestion, int(payload.get("topic_id") or 0))
    if not topic or topic.research_id != research.id:
        return {"ok": False, "error": "주제를 찾을 수 없습니다."}

    return research_ai.review_topic(
        research.interest_keyword, str(payload.get("title") or topic.title),
        str(payload.get("research_question") or topic.research_question), user)


def _job_research_plan(db: Session, user_id: int, payload: dict) -> dict:
    user = db.get(User, user_id)
    research = db.get(ResearchProject, int(payload.get("research_id") or 0))
    if not user or not research or not _job_research_authorized(db, research, user_id):
        return {"ok": False, "error": "연구를 찾을 수 없습니다."}

    result = research_ai.generate_plan(research.title, research.research_question,
                                       research.research_type, user,
                                       difficulty=research.difficulty_level or "easy")
    if not result.get("ok"):
        return result

    # AI 초안은 시작점일 뿐이다 — 이미 학생이 직접 채운 값이 있으면 덮어쓰지 않는다.
    if not research.hypothesis:
        research.hypothesis = result["hypothesis"]
    if not research.variables:
        research.variables = result["variables"]
    if not research.target_sample:
        research.target_sample = result["target_sample"]
    if not research.method_detail:
        research.method_detail = result["method_detail"]
    if not research.expected_limitations:
        research.expected_limitations = result["expected_limitations"]
    db.commit()
    return result


def _job_research_structure(db: Session, user_id: int, payload: dict) -> dict:
    """학생이 쉬운 말로 쓴 계획을 전문 연구 구조로 번역해 둔다.

    학생 화면에는 절대 노출하지 않는다 — 논문·심사·교사 화면에서만 읽는다.
    실패해도 계획 확정 자체는 이미 끝난 상태라 학생 흐름을 막지 않는다.
    """
    user = db.get(User, user_id)
    research = db.get(ResearchProject, int(payload.get("research_id") or 0))
    if not user or not research or not _job_research_authorized(db, research, user_id):
        return {"ok": False, "error": "연구를 찾을 수 없습니다."}

    result = research_ai.structure_plan(research, user)
    if not result.get("ok"):
        return result

    research.structure_json = json.dumps({
        "research_question": result.get("research_question", ""),
        "hypothesis_formal": result.get("hypothesis_formal", ""),
        "independent_variable": result.get("independent_variable", ""),
        "dependent_variable": result.get("dependent_variable", ""),
        "control_variables": result.get("control_variables", []),
        "comparison_groups": result.get("comparison_groups", []),
        "measurement": result.get("measurement", ""),
        "sample": result.get("sample", ""),
        "repetition": result.get("repetition", ""),
        "unclear": result.get("unclear", []),
    }, ensure_ascii=False)
    db.commit()
    return result


def _job_research_roadmap(db: Session, user_id: int, payload: dict) -> dict:
    user = db.get(User, user_id)
    research = db.get(ResearchProject, int(payload.get("research_id") or 0))
    if not user or not research or not _job_research_authorized(db, research, user_id):
        return {"ok": False, "error": "연구를 찾을 수 없습니다."}

    result = research_ai.generate_roadmap(research.title, research.research_question,
                                          research.research_type,
                                          research.duration_weeks, user,
                                          difficulty=research.difficulty_level or "easy")
    if not result.get("ok"):
        return result

    # 다시 만들면 기존 로드맵·할 일을 지우고 새로 만든다.
    old_step_ids = [s.id for s in db.query(ResearchRoadmapStep.id)
                    .filter(ResearchRoadmapStep.research_id == research.id).all()]
    if old_step_ids:
        db.query(ResearchTask).filter(ResearchTask.research_id == research.id).delete(
            synchronize_session=False)
        db.query(ResearchRoadmapStep).filter(
            ResearchRoadmapStep.research_id == research.id).delete(synchronize_session=False)

    for w in result["weeks"]:
        step = ResearchRoadmapStep(
            research_id=research.id, week_number=w["week_number"], title=w["title"],
            goal=w["goal"], expected_hours=w["expected_hours"],
            completion_criteria=w["completion_criteria"])
        db.add(step)
        db.flush()  # step.id 를 바로 써야 하니 커밋 전에 반영한다
        for task_title in w["tasks"]:
            db.add(ResearchTask(research_id=research.id, roadmap_step_id=step.id,
                                title=task_title[:200]))

    if research.current_stage in ("interest", "topic", "question"):
        research.current_stage = "plan"
    if not research.start_date:
        research.start_date = date.today()
    research.target_end_date = date.today() + timedelta(weeks=research.duration_weeks)
    research.current_week = 1  # 할 일이 통째로 새로 생겼으니 주차도 처음부터
    db.commit()
    return result


def _job_research_literature(db: Session, user_id: int, payload: dict) -> dict:
    user = db.get(User, user_id)
    research = db.get(ResearchProject, int(payload.get("research_id") or 0))
    if not user or not research or not _job_research_authorized(db, research, user_id):
        return {"ok": False, "error": "연구를 찾을 수 없습니다."}

    result = research_ai.suggest_literature(research.research_question, research.hypothesis, user)
    if not result.get("ok"):
        return result

    last = (db.query(func.max(ResearchLiterature.sort_order))
           .filter(ResearchLiterature.research_id == research.id).scalar())
    next_order = (last + 1) if last is not None else 0
    for i, it in enumerate(result["items"]):
        db.add(ResearchLiterature(
            research_id=research.id, title=it["title"], author=it["author"], year=it["year"],
            source=it["source"], url=it["url"], summary=it["summary"], relevance=it["relevance"],
            stance=it["stance"], verified=False, ai_suggested=True, sort_order=next_order + i))
    db.commit()
    return result


def _job_research_analysis(db: Session, user_id: int, payload: dict) -> dict:
    user = db.get(User, user_id)
    research = db.get(ResearchProject, int(payload.get("research_id") or 0))
    if not user or not research or not _job_research_authorized(db, research, user_id):
        return {"ok": False, "error": "연구를 찾을 수 없습니다."}

    stats = payload.get("stats") or {}
    result = research_ai.interpret_analysis(research.research_question, research.hypothesis,
                                            stats, user)
    if not result.get("ok"):
        return result

    row = ResearchAnalysis(
        research_id=research.id, data_ids=json.dumps(payload.get("data_ids") or []),
        computed_stats_json=json.dumps(stats, ensure_ascii=False),
        method_suggestion=result["method_suggestion"], interpretation=result["interpretation"])
    db.add(row)
    db.commit()
    result["stats"] = stats
    return result


def _job_research_data_direction(db: Session, user_id: int, payload: dict) -> dict:
    user = db.get(User, user_id)
    research = db.get(ResearchProject, int(payload.get("research_id") or 0))
    if not user or not research or not _job_research_authorized(db, research, user_id):
        return {"ok": False, "error": "연구를 찾을 수 없습니다."}

    literature = _verified_literature_text(db, research.id)
    return research_ai.suggest_data_direction(research, literature, user)


def _job_research_task_guide(db: Session, user_id: int, payload: dict) -> dict:
    user = db.get(User, user_id)
    research = db.get(ResearchProject, int(payload.get("research_id") or 0))
    task = db.get(ResearchTask, int(payload.get("task_id") or 0))
    if not user or not research or not _job_research_authorized(db, research, user_id) or not task or task.research_id != research.id:
        return {"ok": False, "error": "할 일을 찾을 수 없습니다."}

    step = db.get(ResearchRoadmapStep, task.roadmap_step_id) if task.roadmap_step_id else None
    result = research_ai.generate_task_guide(task.title, step.goal if step else "", research, user)
    if not result.get("ok"):
        return result

    task.guide = json.dumps({"steps": result["steps"], "tips": result["tips"]}, ensure_ascii=False)
    db.commit()
    return result


def _job_research_review(db: Session, user_id: int, payload: dict) -> dict:
    user = db.get(User, user_id)
    research = db.get(ResearchProject, int(payload.get("research_id") or 0))
    if not user or not research or not _job_research_authorized(db, research, user_id):
        return {"ok": False, "error": "연구를 찾을 수 없습니다."}

    lit_count = db.query(func.count(ResearchLiterature.id)).filter(
        ResearchLiterature.research_id == research.id).scalar() or 0
    data_count = db.query(func.count(ResearchData.id)).filter(
        ResearchData.research_id == research.id).scalar() or 0
    summary = (f"참고 자료 {lit_count}건 모음. 데이터 {data_count}건 모음. "
              f"현재 단계: {research.current_stage}.")

    result = research_ai.review_research(research, summary, user)
    if not result.get("ok"):
        return result

    row = ResearchReview(research_id=research.id, stage=research.current_stage,
                         findings_json=json.dumps(result["findings"], ensure_ascii=False))
    db.add(row)
    db.commit()
    return result


def _job_research_followup(db: Session, user_id: int, payload: dict) -> dict:
    user = db.get(User, user_id)
    research = db.get(ResearchProject, int(payload.get("research_id") or 0))
    if not user or not research or not _job_research_authorized(db, research, user_id):
        return {"ok": False, "error": "연구를 찾을 수 없습니다."}

    result = research_ai.suggest_followup(research.research_question,
                                          research.expected_limitations, user)
    if not result.get("ok"):
        return result

    if not research.follow_up_ideas:
        research.follow_up_ideas = "\n".join(f"- {i}" for i in result["ideas"])
        db.commit()
    return result


def _job_research_report(db: Session, user_id: int, payload: dict) -> dict:
    user = db.get(User, user_id)
    research = db.get(ResearchProject, int(payload.get("research_id") or 0))
    if not user or not research or not _job_research_authorized(db, research, user_id):
        return {"ok": False, "error": "연구를 찾을 수 없습니다."}

    completed_tasks = payload.get("completed_tasks") or []
    result = research_ai.draft_report(research.research_question, research.current_stage,
                                      completed_tasks, str(payload.get("blockers") or ""), user)
    if not result.get("ok"):
        return result

    row = ResearchReport(
        research_id=research.id, report_type=str(payload.get("report_type") or "weekly"),
        period_start=date.fromisoformat(payload["period_start"]),
        period_end=date.fromisoformat(payload["period_end"]),
        summary=result["summary"], completed_tasks_json=json.dumps(completed_tasks, ensure_ascii=False),
        current_stage=research.current_stage, blockers=str(payload.get("blockers") or ""),
        ai_feedback=result["ai_feedback"], next_steps=result["next_steps"])
    db.add(row)
    db.commit()
    return result


def _job_research_paper(db: Session, user_id: int, payload: dict) -> dict:
    user = db.get(User, user_id)
    research = db.get(ResearchProject, int(payload.get("research_id") or 0))
    if not user or not research or not _job_research_authorized(db, research, user_id):
        return {"ok": False, "error": "연구를 찾을 수 없습니다."}

    summary = _research_summary_text(research)
    literature = _verified_literature_text(db, research.id)
    external_notes = _approved_external_notes_text(db, research.id)
    if external_notes:
        # 미승인 상태로는 여기 안 들어온다(_approved_external_notes_text 가
        # approved=True 만 골라 준다, §19) — 확인된 문헌과 같은 자격으로 취급한다.
        literature = f"{literature}\n\n[외부 선생님 답변 중 학생이 반영 승인한 내용]\n{external_notes}" \
            if literature else f"[외부 선생님 답변 중 학생이 반영 승인한 내용]\n{external_notes}"
    analysis = _latest_analysis_text(db, research.id)
    review = _latest_review_text(db, research.id)
    result = research_ai.draft_paper(summary, literature, analysis, review,
                                     research.expected_limitations, research.follow_up_ideas, user)
    if not result.get("ok"):
        return result

    row = db.query(ResearchPaper).filter(ResearchPaper.research_id == research.id).first()
    if not row:
        row = ResearchPaper(research_id=research.id)
        db.add(row)
    row.title = result["title"] or row.title
    row.abstract = result["abstract"]
    row.sections_json = json.dumps(result["sections"], ensure_ascii=False)
    db.commit()
    return result


def _job_research_portfolio(db: Session, user_id: int, payload: dict) -> dict:
    user = db.get(User, user_id)
    research = db.get(ResearchProject, int(payload.get("research_id") or 0))
    if not user or not research or not _job_research_authorized(db, research, user_id):
        return {"ok": False, "error": "연구를 찾을 수 없습니다."}

    summary = _research_summary_text(research)
    analysis = _latest_analysis_text(db, research.id)
    result = research_ai.draft_portfolio(summary, analysis, user)
    if not result.get("ok"):
        return result

    row = db.query(ResearchPortfolio).filter(ResearchPortfolio.research_id == research.id).first()
    if not row:
        row = ResearchPortfolio(research_id=research.id)
        db.add(row)
    row.title = result["title"] or row.title
    row.sections_json = json.dumps(result["sections"], ensure_ascii=False)
    db.commit()
    return result


def _job_research_team_roles(db: Session, user_id: int, payload: dict) -> dict:
    user = db.get(User, user_id)
    research = db.get(ResearchProject, int(payload.get("research_id") or 0))
    if not user or not research or not _job_research_authorized(db, research, user_id):
        return {"ok": False, "error": "연구를 찾을 수 없습니다."}

    team = _get_research_team(db, research.id)
    team_size = db.query(func.count(ResearchTeamMember.id)).filter(
        ResearchTeamMember.team_id == team.id).scalar() if team else 1

    return research_ai.suggest_team_roles(research.research_question, research.research_type,
                                          team_size or 1, user)


def _job_research_board_synthesis(db: Session, user_id: int, payload: dict) -> dict:
    user = db.get(User, user_id)
    research = db.get(ResearchProject, int(payload.get("research_id") or 0))
    if not user or not research or not _job_research_authorized(db, research, user_id):
        return {"ok": False, "error": "연구를 찾을 수 없습니다."}

    team = _get_research_team(db, research.id)
    if not team:
        return {"ok": False, "error": "팀 연구가 아닙니다."}

    rows = (db.query(ResearchBoardPost, User)
           .join(User, ResearchBoardPost.author_id == User.id)
           .filter(ResearchBoardPost.team_id == team.id).all())
    if not rows:
        return {"ok": False, "error": "아직 게시글이 없습니다."}

    posts = [{"id": p.id, "title": p.title, "content": p.content} for p, _u in rows]
    members = (db.query(User).join(ResearchTeamMember, ResearchTeamMember.user_id == User.id)
              .filter(ResearchTeamMember.team_id == team.id).all())

    result = research_ai.synthesize_board(research.research_question, posts, members, user)
    if not result.get("ok"):
        return result

    by_id = {p.id: p for p, _u in rows}
    for item in result["items"]:
        post = by_id.get(item["post_id"])
        if post:
            post.ai_suggestion = item["suggestion"]
            post.ai_note = item["note"]
    db.commit()
    return result


def _job_research_question_tags(db: Session, user_id: int, payload: dict) -> dict:
    q = db.get(ExternalQuestion, int(payload.get("question_id") or 0))
    user = db.get(User, user_id)
    if not q or not user:
        return {"ok": False, "error": "질문을 찾을 수 없습니다."}
    research = db.get(ResearchProject, q.research_id)
    if not research:
        return {"ok": False, "error": "연구를 찾을 수 없습니다."}

    result = research_ai.suggest_question_tags(
        research.title or research.interest_keyword, q.body, user)
    if not result.get("ok"):
        return result
    q.field_tags_json = json.dumps(result["tags"], ensure_ascii=False)
    db.commit()
    return result


def _job_research_reflect_answer(db: Session, user_id: int, payload: dict) -> dict:
    answer = db.get(ExternalAnswer, int(payload.get("answer_id") or 0))
    user = db.get(User, user_id)
    research = db.get(ResearchProject, int(payload.get("research_id") or 0))
    if not answer or not user or not research or not _job_research_authorized(db, research, user_id):
        return {"ok": False, "error": "연구를 찾을 수 없습니다."}
    question = db.get(ExternalQuestion, answer.question_id)
    if not question or question.research_id != research.id:
        return {"ok": False, "error": "질문을 찾을 수 없습니다."}

    result = research_ai.reflect_answer(question.body, answer.body, user)
    if not result.get("ok"):
        return result
    note = ExternalAnswerNote(research_id=research.id, answer_id=answer.id,
                              suggested_stage=result["suggested_stage"], note=result["note"])
    db.add(note)
    db.commit()
    db.refresh(note)
    return {**result, "note_id": note.id}


ai_jobs.register("research_dialogue", _job_research_dialogue)
ai_jobs.register("research_topics", _job_research_topics)
ai_jobs.register("research_topic_review", _job_research_topic_review)
ai_jobs.register("research_plan", _job_research_plan)
ai_jobs.register("research_structure", _job_research_structure)
ai_jobs.register("research_roadmap", _job_research_roadmap)
ai_jobs.register("research_literature", _job_research_literature)
ai_jobs.register("research_analysis", _job_research_analysis)
ai_jobs.register("research_data_direction", _job_research_data_direction)
ai_jobs.register("research_task_guide", _job_research_task_guide)
ai_jobs.register("research_review", _job_research_review)
ai_jobs.register("research_followup", _job_research_followup)
ai_jobs.register("research_report", _job_research_report)
ai_jobs.register("research_paper", _job_research_paper)
ai_jobs.register("research_portfolio", _job_research_portfolio)
ai_jobs.register("research_team_roles", _job_research_team_roles)
ai_jobs.register("research_question_tags", _job_research_question_tags)
ai_jobs.register("research_reflect_answer", _job_research_reflect_answer)
ai_jobs.register("research_board_synthesis", _job_research_board_synthesis)


@app.on_event("startup")
def _start_ai_worker():
    """AI 작업 일꾼을 띄운다.

    키가 없으면 띄우지 않는다. 할 일이 생길 수 없으므로 실만 놀게 된다.
    """
    if llm.available():
        ai_jobs.start()
    else:
        print("[AI] 키가 없어 AI 기능을 쓰지 않습니다.", flush=True)




# ══════════════════════════════════════════════════════════
# 관리자
# ══════════════════════════════════════════════════════════


# ── 입금 내역 대조 ─────────────────────────────────────────
#
# PG 를 쓰지 않으면 입금 확인을 사람이 해야 한다. 건수가 늘면 이게 제일 지친다.
# 통장 거래내역을 복사해 붙여넣으면 대기 중인 주문과 맞춰주는 것으로 대신한다.
# 은행마다 형식이 달라 완벽히 읽어낼 수는 없으므로, 줄에서 '금액'과 '이름'만
# 뽑아 쓴다. 최종 승인은 사람이 눌러야 한다.

_AMOUNT_RE = re.compile(r"\d{1,3}(?:,\d{3})+|\d{1,9}")
# 날짜와 시각은 금액처럼 생겼다. '2026-08-20' 의 2026 을 금액으로 읽으면
# 엉뚱한 주문에 붙으므로, 금액을 뽑기 전에 먼저 지운다.
_DATETIME_RE = re.compile(
    r"\d{4}[-./]\d{1,2}[-./]\d{1,2}"      # 2026-08-20, 2026.08.20
    r"|\d{1,2}[-./]\d{1,2}(?![-./\d])"     # 08/20
    r"|\d{1,2}:\d{2}(?::\d{2})?"           # 14:22, 14:22:05
)
# 이름을 괄호로 감싸 적으면 추측이 확정으로 바뀐다.
_BRACKET_NAME_RE = re.compile(r"[(\[]([^)\]]{1,40})[)\]]")
# 계좌번호·날짜처럼 사람 이름이 아닌 것을 걸러내기 위해 한글 이름만 본다.
_NAME_RE = re.compile(r"[가-힣]{2,10}")

# 통장 내역에 흔히 섞이는 낱말. 이름으로 잘못 집으면 대조가 어긋난다.
_NOISE = {
    "입금", "출금", "잔액", "거래", "내역", "일시", "적요", "구분", "메모",
    "이체", "타행", "송금", "수수료", "은행", "계좌", "합계", "원",
}


def _clean_name(text: str) -> str:
    """줄에서 사람 이름으로 보이는 것을 고른다."""
    for cand in _NAME_RE.findall(text or ""):
        if cand in _NOISE:
            continue
        if any(cand.startswith(n) or n in cand for n in _NOISE):
            continue
        return cand
    return ""


def parse_statement(text: str) -> List[dict]:
    """붙여넣은 거래내역에서 (금액, 이름) 을 줄 단위로 뽑는다."""
    out = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        body = line
        name = ""

        # 이름을 괄호로 감싸 적으면 추측할 필요가 없어진다. 이름에 숫자가
        # 섞여 있어도(예: 홍길동5900) 금액으로 오해하지 않는다.
        m = _BRACKET_NAME_RE.search(body)
        if m:
            name = m.group(1).strip()[:40]
            body = body[:m.start()] + " " + body[m.end():]

        body = _DATETIME_RE.sub(" ", body)
        # 계좌번호(123-45-6789)도 숫자 덩어리로 잡히므로 하이픈으로 이어진 것은 지운다.
        body = re.sub(r"\d[\d-]{6,}\d", " ", body)

        amounts = [int(a.replace(",", "")) for a in _AMOUNT_RE.findall(body)]
        # 하한을 두지 않는다. 3원짜리 시험 결제도 대조할 수 있어야 한다.
        amounts = [a for a in amounts if 0 < a <= 10_000_000]
        if not amounts:
            continue
        if not name:
            name = _clean_name(line)
        out.append({
            "line": line[:120],
            # 한 줄에 금액이 여러 개면 뒤쪽이 잔액인 경우가 많다.
            # 잔액은 거래액보다 크므로 작은 쪽을 거래액으로 본다.
            "amount": min(amounts),
            "name": name,
        })
    return out


class DepositIn(BaseModel):
    amount: int
    name: str = Field(default="", max_length=40)
    line: str = Field(default="", max_length=200)
    # 파일을 여러 개 올리면 줄마다 계좌가 다르다. 비어 있으면 요청의 bank_key 를 쓴다.
    bank_key: str = Field(default="", max_length=20)


class StatementIn(BaseModel):
    text: str = Field(default="", max_length=20000)
    # 파일에서 읽은 결과. 있으면 text 보다 이것을 쓴다.
    deposits: Optional[List[DepositIn]] = None
    # 어느 계좌의 내역인지. 여러 계좌를 쓰면 각각 붙여넣는다.
    bank_key: str = Field(default="", max_length=20)
    # 금액이 유일하게 맞는 건을 곧바로 승인할지. 기본은 사람이 누른다.
    auto_approve: bool = False


def auto_approve_enabled(db: Session) -> bool:
    row = db.get(Setting, "deposit_auto_approve")
    return bool(row and (row.value or "").strip() == "on")


# 거래 시각을 뽑아 중복 판정에 쓴다. 같은 계좌에 같은 시각, 같은 금액이
# 두 번 찍히는 일은 사실상 없다.
_WHEN_RE = re.compile(r"\d{2,4}[-./]\d{1,2}[-./]\d{1,2}[\sT]*\d{0,2}:?\d{0,2}:?\d{0,2}")


def _fingerprint(bank_key: str, line: str, amount: int = 0) -> str:
    """같은 입금인지 가리는 열쇠.

    원문 줄을 그대로 쓰면, 같은 입금이라도 파일에서 읽은 줄과 손으로
    붙여넣은 줄의 모양이 달라 서로 다른 건으로 쌓인다. 그래서 줄에서
    거래 시각만 뽑아 계좌·금액과 함께 열쇠로 삼는다.
    """
    m = _WHEN_RE.search(line or "")
    when = re.sub(r"[^\d]", "", m.group(0)) if m else ""
    if when:
        return hashlib.sha256(f"{bank_key}|{when}|{amount}".encode()).hexdigest()
    # 시각을 못 찾으면 예전처럼 줄 전체로 가린다.
    return hashlib.sha256(f"{bank_key}|{line}".encode()).hexdigest()


def record_unmatched(db: Session, bank_key: str, ln: dict, reason: str) -> None:
    """못 붙인 입금을 미매칭함에 남긴다.

    같은 내역을 다시 붙여넣어도 쌓이지 않도록 지문으로 막는다. 이미 처리한
    건이면 다시 열지 않는다.
    """
    fp = _fingerprint(bank_key, ln["line"], ln["amount"])
    if db.query(UnmatchedDeposit).filter(UnmatchedDeposit.fingerprint == fp).first():
        return
    db.add(UnmatchedDeposit(
        fingerprint=fp, bank_key=bank_key[:20], line=ln["line"][:200],
        amount=ln["amount"], name=(ln["name"] or "")[:40], reason=reason[:120],
    ))










class ResolveIn(BaseModel):
    action: str = Field(..., pattern="^(link|ignore|reopen)$")
    order_id: Optional[int] = None
    note: str = Field(default="", max_length=200)




@app.get("/api/admin/settings")
def admin_get_settings(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    return {
        "subscription_price": subscription_price(db),
        # 학교 이용권 단가. 지금은 이쪽이 본 요금이다.
        "seat_price": seat_price(db),
        "seat_discount_enabled": "on" if discount_on(db) else "off",
        "seat_discount_tiers": discount_tiers(db),
        **bank_info(db),
        "payment_method": payment_method(db),
        # 화면이 '지금 무엇으로 받고 있는지'를 정확히 말해줄 수 있게 함께 내려준다.
        "bank_ready": bank_ready(db),
        "effective": "toss" if use_toss(db) else "bank_transfer",
        "bank_accounts": bank_accounts(db),
        "deposit_auto_approve": "on" if auto_approve_enabled(db) else "off",
        # 미매칭함에 쌓인 건수. 설정 화면에서도 밀린 것을 알 수 있게 한다.
        "unmatched_open": db.query(func.count(UnmatchedDeposit.id))
                            .filter(UnmatchedDeposit.status == "open").scalar() or 0,
    }


@app.put("/api/admin/settings")
def admin_set_settings(payload: dict, request: Request, db: Session = Depends(get_db),
                       user: User = Depends(require_admin)):
    allowed = {"subscription_price", "bank_name", "bank_account", "bank_holder",
               "payment_note", "payment_method", "bank_accounts", "deposit_auto_approve",
               "seat_price", "seat_discount_enabled", "seat_discount_tiers"}

    method = payload.get("payment_method")
    if method is not None and method not in PAYMENT_METHODS:
        raise HTTPException(status_code=400, detail="결제 방식 값이 올바르지 않습니다.")

    accounts = payload.get("bank_accounts")
    if accounts is not None:
        if isinstance(accounts, str):
            try:
                accounts = json.loads(accounts or "[]")
            except Exception:
                raise HTTPException(status_code=400, detail="계좌 목록 형식이 올바르지 않습니다.")
        if not isinstance(accounts, list):
            raise HTTPException(status_code=400, detail="계좌 목록 형식이 올바르지 않습니다.")

        cleaned, seen = [], set()
        for i, it in enumerate(accounts):
            if not isinstance(it, dict):
                continue
            name = str(it.get("bank_name") or "").strip()
            acct = str(it.get("bank_account") or "").strip()
            holder = str(it.get("bank_holder") or "").strip()
            if not (name or acct or holder):
                continue  # 빈 줄은 지운 것으로 본다
            if not (name and acct and holder):
                raise HTTPException(
                    status_code=400,
                    detail=f"{i + 1}번째 계좌의 은행·계좌번호·예금주를 모두 채워주세요.",
                )
            key = str(it.get("key") or "").strip()[:20] or f"acc{i + 1}"
            # 열쇠가 겹치면 배정과 대조가 엉킨다.
            while key in seen:
                key = f"{key}_{i + 1}"
            seen.add(key)
            cleaned.append({"key": key, "bank_name": name[:40],
                            "bank_account": acct[:60], "bank_holder": holder[:40]})
        payload["bank_accounts"] = json.dumps(cleaned, ensure_ascii=False)

        if method == "bank" and not cleaned:
            raise HTTPException(
                status_code=400,
                detail="무통장 입금으로 받으려면 계좌를 한 개 이상 등록해야 합니다.",
            )

    tiers = payload.get("seat_discount_tiers")
    if tiers is not None:
        if isinstance(tiers, str):
            try:
                tiers = json.loads(tiers or "[]")
            except Exception:
                raise HTTPException(status_code=400, detail="할인 구간 형식이 올바르지 않습니다.")
        if not isinstance(tiers, list):
            raise HTTPException(status_code=400, detail="할인 구간 형식이 올바르지 않습니다.")
        clean = []
        for i, t in enumerate(tiers):
            if not isinstance(t, dict):
                continue
            try:
                m = int(t.get("min") or 0); pc = int(t.get("percent") or 0)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="할인 구간은 숫자로 적어주세요.")
            if m <= 0 and pc <= 0:
                continue  # 빈 줄은 지운 것으로 본다
            if m <= 0:
                raise HTTPException(status_code=400, detail=f"{i + 1}번째 구간의 인원수를 적어주세요.")
            if not (0 < pc < 100):
                raise HTTPException(status_code=400, detail=f"{i + 1}번째 구간의 할인율은 1~99 사이로 적어주세요.")
            clean.append({"min": m, "percent": pc})
        clean.sort(key=lambda x: x["min"])
        payload["seat_discount_tiers"] = json.dumps(clean, ensure_ascii=False)

    disc = payload.get("seat_discount_enabled")
    if disc is not None and disc not in ("on", "off"):
        raise HTTPException(status_code=400, detail="할인 사용 여부 값이 올바르지 않습니다.")

    auto = payload.get("deposit_auto_approve")
    if auto is not None and auto not in ("on", "off"):
        raise HTTPException(status_code=400, detail="자동 승인 값이 올바르지 않습니다.")

    # 무통장으로 돌리면서 계좌가 비어 있으면 결제가 통째로 막힌다.
    # 저장되고 나서야 알게 되면 늦으므로 여기서 잡는다.
    if method == "bank":
        # 계좌 목록이 채워져 있으면 그것으로 충분하다. 옛 단일 계좌 칸은
        # 목록이 비어 있을 때만 본다.
        has_list = bool(json.loads(payload.get("bank_accounts") or "[]")) \
            if isinstance(payload.get("bank_accounts"), str) else bool(bank_accounts(db))
        merged = {**bank_info(db)}
        for k in ("bank_name", "bank_account", "bank_holder"):
            if k in payload:
                merged[k] = str(payload[k] or "")
        missing = [] if has_list else [
            k for k in ("bank_name", "bank_account", "bank_holder")
            if not merged.get(k, "").strip()
        ]
        if missing:
            label = {"bank_name": "은행", "bank_account": "계좌번호", "bank_holder": "예금주"}
            raise HTTPException(
                status_code=400,
                detail=f"무통장 입금으로 바꾸려면 {', '.join(label[k] for k in missing)}을(를) 먼저 입력해주세요.",
            )

    for key, value in payload.items():
        if key not in allowed:
            continue
        row = db.query(Setting).filter(Setting.key == key).first()
        if row:
            row.value = str(value)
        else:
            db.add(Setting(key=key, value=str(value)))
    db.commit()
    write_audit(db, request, user, action="setting.update",
                detail=",".join(k for k in payload if k in allowed))
    return {"ok": True}


@app.get("/api/admin/audit-logs")
def admin_audit_logs(limit: int = Query(100, ge=1, le=500), action: str = Query(""),
                     db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """조회 시점에 보관 기간(1년)이 지난 기록을 정리한다."""
    cutoff = datetime.utcnow() - timedelta(days=365)
    db.query(AuditLog).filter(AuditLog.created_at < cutoff).delete(synchronize_session=False)
    db.commit()

    q = db.query(AuditLog)
    if action:
        q = q.filter(AuditLog.action == action)
    rows = q.order_by(AuditLog.created_at.desc()).limit(limit).all()
    return [{
        "id": r.id, "actor_email": r.actor_email, "actor_role": r.actor_role,
        "action": r.action, "target_type": r.target_type, "target_id": r.target_id,
        "detail": r.detail, "ip": r.ip, "created_at": r.created_at,
    } for r in rows]


@app.get("/api/health")
def health():
    """살아 있는지만 본다. 결제·외부 연동이 아직 없어 더 볼 것이 없다."""
    return {"ok": True, "service": "research"}
