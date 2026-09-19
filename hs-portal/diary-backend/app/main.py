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

from . import (ai, ai_jobs, ai_portfolio, ai_service, dept_fields, doc_store, image_store,
               llm, mailer, portfolio, resume_export, spellcheck,
               statement, toss, udj, writing)
from .auth import (
    create_access_token, get_current_user, get_current_user_optional,
    require_admin, require_journal_viewer, require_roles, require_student,
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
resume_export.find_font()

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
        "school_id": user.school_id,
        "school_name": user.school_name,
        "department": user.department or "",
        "grade": user.grade,
        "verified": bool(user.verified),
        "class_name": user.class_name or "",
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
# 계정 (원본은 UDJ, 이곳은 창구)
# ══════════════════════════════════════════════════════════
@app.post("/api/auth/login")
def login(payload: LoginIn, db: Session = Depends(get_db)):
    profile = udj.login(str(payload.email).strip(), payload.password)
    user = upsert_user(db, profile)
    return {"access_token": create_access_token(user), "user": user_out(user)}


@app.post("/api/auth/signup")
def signup(payload: SignupIn, db: Session = Depends(get_db)):
    """기록해 화면에서 가입한다. 계정은 UDJ 에 만들어진다."""
    if not (payload.privacy_consent and payload.terms_consent):
        raise HTTPException(status_code=400, detail="약관과 개인정보 수집에 동의해야 합니다.")

    result = udj.create_user({
        "email": str(payload.email).strip(),
        "password": payload.password,
        "name": payload.name,
        "phone": payload.phone,
        "phone_verification_token": payload.phone_verification_token,
        "birth_date": payload.birth_date.isoformat(),
        "guardian_email": str(payload.guardian_email or ""),
    })

    if result.get("guardian_consent_required"):
        # 만 14세 미만은 보호자 동의 전까지 로그인할 수 없다.
        return {
            "guardian_consent_required": True,
            "guardian_email": result.get("guardian_email", ""),
        }

    user = upsert_user(db, result["profile"])
    return {"access_token": create_access_token(user), "user": user_out(user)}


@app.get("/api/auth/me")
def me(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """내 정보. 소속이 바뀌었을 수 있어 UDJ 에서 최신 값을 받아 갱신한다."""
    profile = udj.fetch_profile(user.udj_user_id)
    if profile:
        user.apply_profile(profile)
        db.commit()
        db.refresh(user)
    return user_out(user)


@app.patch("/api/me")
def update_me(payload: ProfileIn, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    body = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if not body:
        return user_out(user)

    # 학생의 학과·학년은 이용권 코드로만 정해진다(redeem_seat_code). 화면에는
    # 이 값을 바꾸는 입력칸이 없지만, API를 직접 두드리면 통과할 수 있었다.
    # 프론트가 안 보여준다고 막힌 게 아니므로 여기서 다시 막는다.
    if user.role == Role.student:
        blocked = {"department", "grade"} & body.keys()
        if blocked:
            raise HTTPException(
                status_code=403,
                detail="학과·학년은 이용권 코드로만 정해집니다. 담당 선생님께 문의해주세요.",
            )

    profile = udj.update_user(user.udj_user_id, body)
    user.apply_profile(profile)
    db.commit()
    db.refresh(user)
    return user_out(user)


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


@app.post("/api/me/change-password")
def change_password(payload: PasswordIn, user: User = Depends(get_current_user)):
    udj.change_password(user.udj_user_id, payload.current_password, payload.new_password)
    return {"ok": True}


@app.delete("/api/me")
def delete_me(payload: DeleteIn, request: Request,
              db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """탈퇴. 기록해 자료를 먼저 지운 뒤 UDJ 계정을 지운다.

    순서가 중요하다. UDJ 를 먼저 지우면 비밀번호 확인이 불가능해져,
    이곳 자료를 지울 근거가 사라진다.
    """
    # 먼저 삭제할 일지의 ID를 확보한다. journal_analyses가 journal_entries를
    # FK로 참조하므로 일지보다 분석 결과를 먼저 지워야 한다.
    journal_ids = [row[0] for row in db.query(JournalEntry.id)
                   .filter(JournalEntry.user_id == user.id).all()]
    if journal_ids:
        db.query(JournalAnalysis).filter(
            JournalAnalysis.journal_id.in_(journal_ids)
        ).delete(synchronize_session=False)
        db.query(JournalEntry).filter(
            JournalEntry.id.in_(journal_ids)
        ).delete(synchronize_session=False)

    # 사용자 소유 데이터
    db.query(CoverLetter).filter(CoverLetter.user_id == user.id).delete(synchronize_session=False)
    db.query(Subscription).filter(Subscription.user_id == user.id).delete(synchronize_session=False)
    db.query(AiConsent).filter(AiConsent.user_id == user.id).delete(synchronize_session=False)
    db.query(AiJob).filter(AiJob.user_id == user.id).delete(synchronize_session=False)
    db.query(SeatHolder).filter(SeatHolder.user_id == user.id).delete(synchronize_session=False)

    # 이 사용자가 다른 사람의 일지에 남긴 피드백/감사 로그/주문은 보존하고
    # 사용자 FK만 끊는다.
    db.query(JournalEntry).filter(JournalEntry.feedback_by == user.id).update(
        {JournalEntry.feedback_by: None}, synchronize_session=False)
    db.query(SubscriptionOrder).filter(SubscriptionOrder.user_id == user.id).update(
        {SubscriptionOrder.user_id: None}, synchronize_session=False)
    db.query(AuditLog).filter(AuditLog.actor_id == user.id).update(
        {AuditLog.actor_id: None}, synchronize_session=False)
    db.commit()

    udj.delete_user(user.udj_user_id, payload.password)

    db.delete(user)
    db.commit()
    return {"ok": True, "message": "탈퇴가 완료되었습니다."}


# ══════════════════════════════════════════════════════════
# 일지 · 일기
# ══════════════════════════════════════════════════════════
@app.get("/api/journal-meta")
def journal_meta():
    return {
        "kinds": [
            {"kind": k, "label": ai.KIND_LABEL.get(k, k),
             "fields": [{"key": key, "label": label} for key, label in ai.field_labels(k)]}
            for k in ("diary", "lesson")
        ],
        "resume_templates": [{"key": k, "label": v} for k, v in ai.RESUME_TEMPLATES.items()],
        # 예전 양식에만 있던 항목. 이미 글을 쓴 학생이 그것을 잃지 않도록
        # 이름만 함께 내려준다. 새로 고를 수는 없다.
        "legacy_templates": [{"key": k, "label": v}
                             for k, v in ai.LEGACY_TEMPLATES.items()],
        # PDF 는 서버가 글자를 직접 그려야 해서 한글 글꼴이 필요하다.
        # 없으면 화면에서 미리 알려주고, 학생이 헛되이 누르지 않게 한다.
        "pdf_available": bool(resume_export.find_font()),
    }


def _sync_school_subjects_from_udj(db: Session, school_id: int) -> Optional[List[str]]:
    """UDJ(U.D.T)에서 최신 학과·과목을 받아 로컬 사본을 채운다.

    로컬 SchoolSubject 는 예전에 한 번 옮겨온 사본이라, 그 뒤 학교가
    새로 생기거나 학과가 늘면 낡는다. 여기서 매번 UDJ 학교 정보의
    School.departments(학과 이름 목록)를 그대로 받아 최신값으로 쓰고,
    NEIS 시간표에서 나온 과목이 있으면 로컬 표에도 채워 둬 다음에
    UDJ 가 응답하지 않을 때도 과목명이 남아 있게 한다.

    UDJ 에 닿지 못하면 None 을 돌려준다 — 그러면 부르는 쪽이 로컬
    사본만으로 계속 동작한다(연동 미설정인 로컬/테스트 환경 포함).
    """
    data = udj.fetch_school_subjects(school_id)
    if not data:
        return None

    for s in (data.get("subjects") or []):
        name = (s.get("name") or "").strip()[:80]
        if not name:
            continue
        dept = (s.get("department") or "")[:60]
        grade = s.get("grade")
        exists = (db.query(SchoolSubject)
                  .filter(SchoolSubject.school_id == school_id,
                          SchoolSubject.department == dept,
                          SchoolSubject.grade == grade,
                          SchoolSubject.name == name).first())
        if not exists:
            db.add(SchoolSubject(school_id=school_id, department=dept, grade=grade, name=name))
    if data.get("subjects"):
        db.commit()

    return [d.strip() for d in (data.get("departments") or []) if d.strip()]


@app.get("/api/journal-subjects")
def journal_subjects(db: Session = Depends(get_db),
                     user: User = Depends(require_roles(Role.student, Role.teacher, Role.school))):
    """학과·과목 드롭다운. 학생은 일지 작성용, 선생님·학교는 담당 학과/코드 발급용으로 쓴다.

    학과·학년으로 좁히되 비면 넓힌다."""
    if not user.school_id:
        return {"school_name": "", "department": user.department or "", "grade": user.grade,
                "departments": [], "grades": [], "subjects": [], "scope": "전체"}

    live_departments = _sync_school_subjects_from_udj(db, user.school_id)
    rows = db.query(SchoolSubject).filter(SchoolSubject.school_id == user.school_id).all()
    dept, grade = user.department or "", user.grade

    def pick(by_dept: bool, by_grade: bool):
        out = rows
        if by_dept and dept:
            out = [r for r in out if r.department == dept]
        if by_grade and grade:
            out = [r for r in out if r.grade == grade]
        return out

    picked, scope = rows, "전체"
    for by_dept, by_grade in [(True, True), (True, False), (False, True)]:
        if (by_dept and not dept) or (by_grade and not grade):
            continue
        found = pick(by_dept, by_grade)
        if found:
            picked = found
            applied = (["학과"] if by_dept and dept else []) + (["학년"] if by_grade and grade else [])
            scope = "·".join(applied) or "전체"
            break

    return {
        "school_name": user.school_name,
        "department": dept,
        "grade": grade,
        # UDJ 가 준 학과 이름을 우선 쓴다. 로컬 SchoolSubject 에만 있고
        # UDJ 목록엔 없는 이름도 있을 수 있어(과목만 있고 학과 미등록 등) 합쳐 둔다.
        "departments": sorted(set(live_departments or []) | {r.department for r in rows if r.department}),
        "grades": sorted({r.grade for r in rows if r.grade}) or [1, 2, 3],
        "subjects": sorted({r.name for r in picked if r.name}),
        "scope": scope,
        # 담당 과목 배정 화면에서 쓴다. 이름만으로는 같은 과목명이 학과·학년마다
        # 겹칠 수 있어 배정은 반드시 id 로 한다.
        "subject_options": [
            {"id": r.id, "name": r.name, "department": r.department or "", "grade": r.grade}
            for r in sorted(rows, key=lambda r: (r.department or "", r.grade or 0, r.name))
        ],
    }


@app.get("/api/journals")
def list_journals(db: Session = Depends(get_db), user: User = Depends(require_student)):
    rows = (
        db.query(JournalEntry)
        .filter(JournalEntry.user_id == user.id)
        .order_by(JournalEntry.entry_date.desc(), JournalEntry.id.desc())
        .all()
    )
    def preview_of(e) -> str:
        """목록에서 어떤 일지인지 알아볼 만큼만. 본문은 상세에서 읽는다.

        자소서를 쓸 때 일지를 직접 골라야 하는데, 날짜만 보고는
        어느 것이 무엇인지 알 수 없다.
        """
        try:
            content = json.loads(e.content or "{}")
        except (ValueError, TypeError):
            return ""
        for _key, value in content.items():
            body = (value or "").strip()
            if body:
                return body[:60]
        return ""

    return [{
        "id": e.id, "kind": e.kind, "entry_date": e.entry_date,
        "kind_label": ai.KIND_LABEL.get(e.kind, e.kind),
        "title": e.title or "",
        "subject": e.subject or "", "subject_id": e.subject_id,
        "teacher_name": e.teacher_name or "",
        "preview": preview_of(e),
        "sent_at": e.sent_at,
        # 목록에서 답글이 달린 것을 바로 알아보게 한다. 본문은 상세에서 읽는다.
        "has_feedback": bool(e.feedback),
        "feedback_unread": bool(e.feedback and not e.feedback_read_at),
    } for e in rows]


@app.get("/api/notifications/summary")
def notifications_summary(db: Session = Depends(get_db),
                          user: User = Depends(require_student)):
    """홈 화면 위쪽에 뜨는 알림.

    연구를 걷어낼 때 이 엔드포인트까지 같이 없어져서, 학생 홈의 "선생님
    한마디 N건 도착"이 영영 안 떴다(화면은 404 를 조용히 삼키고 있었다).
    남은 것은 일지 답글 하나뿐이라 여기서 세어 돌려준다.
    """
    unread = db.query(JournalEntry).filter(
        JournalEntry.user_id == user.id,
        JournalEntry.feedback != "",
        JournalEntry.feedback.isnot(None),
        JournalEntry.feedback_read_at.is_(None)).count()
    return {"unread_journal_feedback": unread}


@app.get("/api/journals/{journal_id}")
def get_journal(journal_id: int, db: Session = Depends(get_db),
                user: User = Depends(require_student)):
    e = db.get(JournalEntry, journal_id)
    if not e or e.user_id != user.id:
        raise HTTPException(status_code=404, detail="기록을 찾을 수 없습니다.")
    # 학생이 상세를 열면 그때 읽음으로 표시한다. 선생님은 전달됐는지 알 수 있다.
    if e.feedback and not e.feedback_read_at:
        e.feedback_read_at = datetime.utcnow()
        db.commit()

    return {
        "id": e.id, "kind": e.kind, "entry_date": e.entry_date,
        "title": e.title or "",
        "subject": e.subject or "", "subject_id": e.subject_id,
        "teacher_name": e.teacher_name or "",
        "content": journal_content(e), "sent_at": e.sent_at,
        "share_token": e.share_token or "",
        "feedback": e.feedback or "",
        "feedback_by_name": e.feedback_by_name or "",
        "feedback_at": e.feedback_at,
    }


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


@app.post("/api/journals")
def create_journal(payload: JournalIn, db: Session = Depends(get_db),
                   user: User = Depends(require_student)):
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="제목을 적어주세요.")
    e = JournalEntry(
        user_id=user.id, kind=payload.kind, entry_date=payload.entry_date,
        title=title[:120],
        subject=payload.subject[:80], teacher_name=payload.teacher_name[:60],
        subject_id=(_resolve_subject_id(db, user, payload.subject)
                   if payload.kind == "lesson" else None),
        content=json.dumps(payload.content or {}, ensure_ascii=False),
    )
    db.add(e)
    db.commit()
    db.refresh(e)
    return {"id": e.id}


@app.put("/api/journals/{journal_id}")
def update_journal(journal_id: int, payload: JournalIn, db: Session = Depends(get_db),
                   user: User = Depends(require_student)):
    e = db.get(JournalEntry, journal_id)
    if not e or e.user_id != user.id:
        raise HTTPException(status_code=404, detail="기록을 찾을 수 없습니다.")
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="제목을 적어주세요.")
    e.kind = payload.kind
    e.entry_date = payload.entry_date
    e.title = title[:120]
    e.subject = payload.subject[:80]
    e.teacher_name = payload.teacher_name[:60]
    e.subject_id = (_resolve_subject_id(db, user, payload.subject)
                    if payload.kind == "lesson" else None)
    e.content = json.dumps(payload.content or {}, ensure_ascii=False)
    db.commit()
    return {"ok": True}


@app.delete("/api/journals/{journal_id}")
def delete_journal(journal_id: int, db: Session = Depends(get_db),
                   user: User = Depends(require_student)):
    e = db.get(JournalEntry, journal_id)
    if not e or e.user_id != user.id:
        raise HTTPException(status_code=404, detail="기록을 찾을 수 없습니다.")
    db.delete(e)
    db.commit()
    return {"ok": True}


@app.post("/api/journals/{journal_id}/submit")
def submit_journal(journal_id: int, db: Session = Depends(get_db),
                   user: User = Depends(require_student)):
    e = db.get(JournalEntry, journal_id)
    if not e or e.user_id != user.id:
        raise HTTPException(status_code=404, detail="기록을 찾을 수 없습니다.")
    if not user.verified:
        raise HTTPException(
            status_code=400,
            detail="재학생 인증을 받아야 선생님께 제출할 수 있습니다.",
        )
    e.sent_at = datetime.utcnow()
    if not e.share_token:
        e.share_token = secrets.token_urlsafe(24)
    db.commit()
    return {"ok": True, "sent_at": e.sent_at, "share_token": e.share_token}


@app.post("/api/journals/{journal_id}/share")
def create_share_link(journal_id: int, db: Session = Depends(get_db),
                      user: User = Depends(require_student)):
    """이 일지를 링크로 보여줄 수 있게 한다.

    제출하지 않은 일지도 공유할 수 있다. 학교에 내는 것과 부모님께 보여드리는
    것은 다른 일이기 때문이다.
    """
    e = db.get(JournalEntry, journal_id)
    if not e or e.user_id != user.id:
        raise HTTPException(status_code=404, detail="기록을 찾을 수 없습니다.")
    if not e.share_token:
        e.share_token = secrets.token_urlsafe(24)
        db.commit()
    return {"ok": True, "share_token": e.share_token}


@app.delete("/api/journals/{journal_id}/share")
def revoke_share_link(journal_id: int, db: Session = Depends(get_db),
                      user: User = Depends(require_student)):
    """공유를 끊는다. 이미 퍼진 링크도 즉시 열리지 않는다."""
    e = db.get(JournalEntry, journal_id)
    if not e or e.user_id != user.id:
        raise HTTPException(status_code=404, detail="기록을 찾을 수 없습니다.")
    e.share_token = None
    db.commit()
    return {"ok": True}


@app.get("/api/share/{token}")
def read_shared_journal(token: str, db: Session = Depends(get_db)):
    """링크를 받은 사람이 로그인 없이 읽는 화면.

    토큰을 아는 사람은 누구나 열 수 있으므로, 학생 이름과 일지 본문 외에는
    아무것도 내보내지 않는다. 학교·학년·연락처는 포함하지 않는다.
    링크를 끊으면 곧바로 404 가 된다.
    """
    if not token or len(token) < 16:
        raise HTTPException(status_code=404, detail="링크를 찾을 수 없습니다.")

    e = db.query(JournalEntry).filter(JournalEntry.share_token == token).first()
    if not e:
        raise HTTPException(
            status_code=404,
            detail="링크가 만료되었거나 공유가 해제되었습니다.",
        )

    return {
        "student_name": e.user.name if e.user else "",
        "kind": e.kind,
        "kind_label": ai.KIND_LABEL.get(e.kind, e.kind),
        "entry_date": e.entry_date,
        "title": e.title or "",
        "subject": e.subject or "",
        "teacher_name": e.teacher_name or "",
        "content": journal_content(e),
        "feedback": e.feedback or "",
        "feedback_by_name": e.feedback_by_name or "",
    }


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


@app.get("/api/teacher/journals")
def teacher_journals(
    scope: str = Query("mine", pattern="^(mine|all)$"),
    school_id: Optional[int] = Query(None, description="관리자 전용"),
    student_id: Optional[int] = Query(None, description="이 학생 것만 본다"),
    kind: Optional[str] = Query(None, pattern="^(diary|lesson)$"),
    subject_id: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_journal_viewer),
):
    if user.role != Role.teacher:
        scope = "all"
    ids = viewable_students(db, user, school_id, scope)
    if not ids:
        return []
    # 학생 카드에서 한 명만 골라 보는 화면은 이 목록을 student_id 로 좁혀
    # 쓴다. viewable_students 로 이미 걸러진 범위 밖의 id 를 넣어도
    # 아무것도 나오지 않는다 — 여기서 다시 한번 교차시키기 때문이다.
    if student_id is not None:
        ids = [i for i in ids if i == student_id]
        if not ids:
            return []

    q = db.query(JournalEntry).filter(
        JournalEntry.user_id.in_(ids), JournalEntry.sent_at.isnot(None))
    if user.role == Role.teacher and scope == "mine":
        # ids 에는 담임 학급 학생과 담당 과목으로만 이어진 학생이 섞여 있다.
        # 담임 학급 학생은 뭐든 보이지만, 담당 과목뿐인 학생은 그 과목
        # 수업일지만 보여야 한다 — 학교생활일지나 다른 과목까지 새는 걸
        # 막는다.
        homeroom_ids = {
            r[0] for r in db.query(User.id).filter(
                User.id.in_(ids), User.teacher_udj_id == user.udj_user_id).all()
        }
        subj_ids = teacher_subject_ids(db, user)
        q = q.filter(or_(
            JournalEntry.user_id.in_(homeroom_ids or [-1]),
            and_(JournalEntry.kind == "lesson",
                 JournalEntry.subject_id.in_(subj_ids or [-1])),
        ))
    if kind:
        q = q.filter(JournalEntry.kind == kind)
    if subject_id is not None:
        q = q.filter(JournalEntry.subject_id == subject_id)

    # 제출된 일지를 전부 내리면 큰 학교에서 수천 건이 된다. 최근 것부터
    # 끊어서 준다. e.user 로 이름을 꺼내면 건마다 조회가 한 번씩 더 나가므로
    # (N+1) 이름은 한 번에 받아 짝지어 둔다.
    total = q.with_entities(func.count(JournalEntry.id)).scalar() or 0
    rows = q.order_by(JournalEntry.sent_at.desc()).offset(offset).limit(limit).all()
    names = dict(db.query(User.id, User.name).filter(
        User.id.in_([e.user_id for e in rows] or [0])).all())
    return [{
        "id": e.id,
        "student_name": names.get(e.user_id, ""),
        "kind": e.kind,
        "kind_label": ai.KIND_LABEL.get(e.kind, e.kind),
        "entry_date": e.entry_date,
        "title": e.title or "",
        "subject": e.subject or "", "subject_id": e.subject_id,
        "submitted_at": e.sent_at,
    } for e in rows]


@app.get("/api/teacher/journals/{journal_id}")
def teacher_journal_detail(
    journal_id: int,
    request: Request,
    school_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_journal_viewer),
):
    e = db.get(JournalEntry, journal_id)
    if not e or not e.sent_at:
        raise HTTPException(status_code=404, detail="일지를 찾을 수 없습니다.")
    if e.user_id not in viewable_students(db, user, school_id, "all"):
        raise HTTPException(status_code=403, detail="볼 수 없는 학생의 기록입니다.")

    # 담당 교사가 아닌 계정의 열람은 기록으로 남긴다.
    if user.role != Role.teacher:
        write_audit(db, request, user, action="journal.view",
                    target_type="journal", target_id=e.id,
                    detail=f"학생 {e.user.name if e.user else e.user_id} · {e.entry_date}")

    content = journal_content(e)
    return {
        "id": e.id,
        "student_name": e.user.name if e.user else "",
        "kind_label": ai.KIND_LABEL.get(e.kind, e.kind),
        "entry_date": e.entry_date,
        "title": e.title or "",
        "subject": e.subject or "", "subject_id": e.subject_id,
        "record_draft": ai.build_record_draft(e.kind, content),
        "items": ai.build_teacher_summary(e.kind, content),
        "feedback": e.feedback or "",
        "feedback_by_name": e.feedback_by_name or "",
        "feedback_at": e.feedback_at,
        "feedback_read_at": e.feedback_read_at,
    }


class FeedbackIn(BaseModel):
    text: str = Field(..., max_length=1000)


@app.get("/api/teacher/students")
def teacher_students(
    scope: str = Query("mine", pattern="^(mine|all)$"),
    school_id: Optional[int] = Query(None, description="관리자 전용"),
    db: Session = Depends(get_db),
    user: User = Depends(require_journal_viewer),
):
    """볼 수 있는 학생 명단과 각자의 제출 현황.

    일지 목록만 보면 '낸 학생'만 보인다. 정작 챙겨야 할 쪽은 아직 한 번도
    내지 않은 학생이라, 명단을 기준으로 세어 보여준다.
    """
    if user.role != Role.teacher:
        scope = "all"
    ids = viewable_students(db, user, school_id, scope)
    if not ids:
        return []

    rows = db.query(User).filter(User.id.in_(ids)).order_by(User.name).all()

    # 학생별 제출 건수와 마지막 제출일을 한 번에 세어 온다.
    counts = dict(
        db.query(JournalEntry.user_id, func.count(JournalEntry.id))
        .filter(JournalEntry.user_id.in_(ids), JournalEntry.sent_at.isnot(None))
        .group_by(JournalEntry.user_id).all()
    )
    lasts = dict(
        db.query(JournalEntry.user_id, func.max(JournalEntry.sent_at))
        .filter(JournalEntry.user_id.in_(ids), JournalEntry.sent_at.isnot(None))
        .group_by(JournalEntry.user_id).all()
    )
    # 답을 아직 못 준 것도 함께 센다. 밀린 것이 눈에 보여야 처리한다.
    no_reply = dict(
        db.query(JournalEntry.user_id, func.count(JournalEntry.id))
        .filter(JournalEntry.user_id.in_(ids),
                JournalEntry.sent_at.isnot(None),
                or_(JournalEntry.feedback.is_(None), JournalEntry.feedback == ""))
        .group_by(JournalEntry.user_id).all()
    )
    # 학생 카드에 종류별로 나눠 보여주려고 kind 별로도 센다.
    diary_counts = dict(
        db.query(JournalEntry.user_id, func.count(JournalEntry.id))
        .filter(JournalEntry.user_id.in_(ids), JournalEntry.kind == "diary",
                JournalEntry.sent_at.isnot(None))
        .group_by(JournalEntry.user_id).all()
    )
    lesson_counts = dict(
        db.query(JournalEntry.user_id, func.count(JournalEntry.id))
        .filter(JournalEntry.user_id.in_(ids), JournalEntry.kind == "lesson",
                JournalEntry.sent_at.isnot(None))
        .group_by(JournalEntry.user_id).all()
    )
    # 올해 소속(학번)이 있으면 함께 보여준다. 없어도 카드는 정상 표시된다.
    year = datetime.utcnow().year
    enrollments = dict(
        (e.user_id, e) for e in
        db.query(StudentEnrollment).filter(
            StudentEnrollment.user_id.in_(ids),
            StudentEnrollment.academic_year == year).all()
    )

    out = []
    for u in rows:
        enr = enrollments.get(u.id)
        out.append({
            "id": u.id,
            "name": u.name,
            "class_name": u.class_name or "",
            "grade": u.grade,
            "class_no": (enr.class_no if enr else "") or u.class_name or "",
            "student_no": enr.student_no if enr else None,
            "department": u.department or "",
            "submitted": counts.get(u.id, 0),
            "diary_count": diary_counts.get(u.id, 0),
            "lesson_count": lesson_counts.get(u.id, 0),
            "awaiting_feedback": no_reply.get(u.id, 0),
            "last_submitted_at": lasts.get(u.id),
        })
    return out


@app.post("/api/teacher/journals/{journal_id}/feedback")
def write_feedback(
    journal_id: int,
    payload: FeedbackIn,
    request: Request,
    school_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_journal_viewer),
):
    """제출된 일지에 선생님이 한마디 남긴다.

    학생이 일지를 내는 이유는 누군가 읽어준다는 감각 때문이다. 읽기만 하고
    아무 말이 없으면 제출이 형식이 된다.

    한 번 쓴 뒤에도 고칠 수 있게 두었다. 급히 남긴 말을 다듬을 여지는 있어야
    한다. 다만 고치면 학생의 '읽음' 표시는 지워서, 바뀐 내용을 다시 보게 한다.
    """
    e = db.get(JournalEntry, journal_id)
    if not e or not e.sent_at:
        raise HTTPException(status_code=404, detail="일지를 찾을 수 없습니다.")
    if e.user_id not in viewable_students(db, user, school_id, "all"):
        raise HTTPException(status_code=403, detail="볼 수 없는 학생의 기록입니다.")

    text_value = (payload.text or "").strip()
    if not text_value:
        # 빈 내용으로 저장하면 지우는 것으로 본다.
        e.feedback = ""
        e.feedback_by = None
        e.feedback_by_name = ""
        e.feedback_at = None
        e.feedback_read_at = None
        db.commit()
        write_audit(db, request, user, action="journal.feedback_delete",
                    target_type="journal", target_id=e.id,
                    detail=f"학생 {e.user.name if e.user else e.user_id}")
        return {"ok": True, "feedback": ""}

    changed = (e.feedback or "") != text_value
    e.feedback = text_value
    e.feedback_by = user.id
    e.feedback_by_name = (user.name or "")[:60]
    e.feedback_at = datetime.utcnow()
    if changed:
        e.feedback_read_at = None
    db.commit()

    write_audit(db, request, user, action="journal.feedback",
                target_type="journal", target_id=e.id,
                detail=f"학생 {e.user.name if e.user else e.user_id} · {e.entry_date}")
    return {
        "ok": True,
        "feedback": e.feedback,
        "feedback_by_name": e.feedback_by_name,
        "feedback_at": e.feedback_at,
    }


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


def use_toss(db: Session) -> bool:
    """새 결제를 카드로 받을지 판단한다.

    토스를 꺼도 키는 .env 에 그대로 두어야 한다. 이미 카드로 결제한 주문을
    환불하려면 토스에 취소를 넣어야 하는데, 키를 지우면 그 길이 막힌다.
    그래서 '새 결제를 무엇으로 받을지'와 '환불이 가능한지'를 분리했다.
    """
    method = payment_method(db)
    if method == "bank":
        return False
    if method == "toss":
        return toss.is_ready()
    return toss.is_ready()


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
    def dependency(db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)) -> User:
        if user.role == Role.admin:
            return user
        if not subscription_active(db, user, product):
            label = SEAT_PRODUCT_LABEL.get(product, product)
            raise HTTPException(status_code=402,
                                detail=f"{label} 기능은 이용권이 있어야 이용할 수 있습니다.")
        return user
    return dependency


require_subscription = _require_product_seat("essay")


def make_deposit_code(db: Session) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    for _ in range(30):
        code = "SUB-" + "".join(random.choices(alphabet, k=4))
        if not db.query(SubscriptionOrder).filter(SubscriptionOrder.deposit_code == code).first():
            return code
    return "SUB-" + secrets.token_hex(3).upper()


@app.get("/api/subscription/me")
def my_subscription(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    sub = db.query(Subscription).filter(Subscription.user_id == user.id).first()
    pending = (
        db.query(SubscriptionOrder)
        .filter(SubscriptionOrder.user_id == user.id,
                SubscriptionOrder.status.in_([OrderStatus.pending, OrderStatus.paid]))
        .order_by(SubscriptionOrder.created_at.desc())
        .first()
    )
    return {
        "active": subscription_active(db, user),
        "expires_at": sub.expires_at if sub else None,
        "price_per_month": subscription_price(db),
        # 결제 화면이 카드용인지 무통장용인지 미리 알아야 입력칸을 맞게 보여준다.
        "pay_with": "toss" if use_toss(db) else "bank",
        # 이용권은 이제 학교가 산다. 학생 화면이 그렇게 안내할 수 있게 알려준다.
        "sold_to_school": True,
        "seat_price": seat_price(db),
        "school_seat": (lambda info: info if user.school_id else None)(
            seat_summary(db, user.school_id) if user.school_id else None
        ),
        "pending_order": None if not pending else {
            "id": pending.id, "months": pending.months, "amount": pending.amount,
            "status": pending.status.value,
            "status_label": ORDER_STATUS_LABEL.get(pending.status.value, ""),
            "deposit_code": pending.deposit_code, "due_at": pending.due_at,
            "depositor_name": pending.depositor_name or "",
            "bank": find_bank(db, pending.bank_key) or bank_info(db),
            # 신청한 뒤 요금이 바뀌었을 수 있다. 화면이 두 값을 비교해
            # '이 신청은 신청 당시 금액으로 받는다'고 알려줄 수 있게 한다.
            "price_at_order": (pending.amount // pending.months) if pending.months else pending.amount,
        },
    }


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


@app.get("/api/school/teachers")
def list_school_teachers(db: Session = Depends(get_db),
                         user: User = Depends(require_school_account)):
    """우리 학교 선생님 명단. 담당 과목 배정 화면에서 고르는 용도다."""
    rows = (db.query(User)
            .filter(User.school_id == user.school_id, User.role == Role.teacher)
            .order_by(User.name).all())
    counts = dict(
        db.query(TeacherSubjectAssignment.teacher_id, func.count(TeacherSubjectAssignment.id))
        .filter(TeacherSubjectAssignment.teacher_id.in_([t.id for t in rows] or [0]))
        .group_by(TeacherSubjectAssignment.teacher_id).all()
    )
    return [{
        "id": t.id, "name": t.name, "class_name": t.class_name or "",
        "subject_count": counts.get(t.id, 0),
    } for t in rows]


@app.get("/api/teacher/my-subjects")
def my_subjects(db: Session = Depends(get_db),
                user: User = Depends(require_roles(Role.teacher, Role.admin))):
    """교사 자신의 담당 과목 목록. 자기 것만 보이므로 ID 검사가 필요 없다."""
    rows = (db.query(TeacherSubjectAssignment)
            .filter(TeacherSubjectAssignment.teacher_id == user.id)
            .order_by(TeacherSubjectAssignment.id).all())
    return [subject_assignment_out(a) for a in rows]


@app.get("/api/school/teachers/{teacher_id}/subjects")
def list_teacher_subjects(teacher_id: int, db: Session = Depends(get_db),
                          user: User = Depends(require_school_account)):
    t = db.get(User, teacher_id)
    if not t or t.role != Role.teacher or t.school_id != user.school_id:
        raise HTTPException(status_code=404, detail="선생님을 찾을 수 없습니다.")
    rows = (db.query(TeacherSubjectAssignment)
            .filter(TeacherSubjectAssignment.teacher_id == teacher_id)
            .order_by(TeacherSubjectAssignment.id).all())
    return [subject_assignment_out(a) for a in rows]


@app.post("/api/school/teachers/{teacher_id}/subjects")
def add_teacher_subject(teacher_id: int, payload: dict, request: Request,
                        db: Session = Depends(get_db),
                        user: User = Depends(require_school_account)):
    """학교 계정이 선생님에게 담당 과목을 추가한다.

    과목은 반드시 우리 학교 SchoolSubject 에서 골라야 한다. 다른 학교의
    subject_id 를 넣어도 세특이 섞이지 않도록 여기서 한 번 막는다.
    """
    t = db.get(User, teacher_id)
    if not t or t.role != Role.teacher or t.school_id != user.school_id:
        raise HTTPException(status_code=404, detail="선생님을 찾을 수 없습니다.")

    try:
        subject_id = int(payload.get("subject_id") or 0)
    except (TypeError, ValueError):
        subject_id = 0
    if not subject_id:
        raise HTTPException(status_code=400, detail="과목을 선택해주세요.")

    subj = db.get(SchoolSubject, subject_id)
    if not subj or subj.school_id != user.school_id:
        raise HTTPException(status_code=404, detail="우리 학교 과목이 아닙니다.")

    exists = (db.query(TeacherSubjectAssignment)
              .filter(TeacherSubjectAssignment.teacher_id == teacher_id,
                      TeacherSubjectAssignment.subject_id == subject_id).first())
    if exists:
        return subject_assignment_out(exists)

    a = TeacherSubjectAssignment(teacher_id=teacher_id, school_id=user.school_id,
                                 subject_id=subject_id)
    db.add(a)
    db.commit()
    db.refresh(a)
    write_audit(db, request, user, action="teacher.subject_add", target_type="user",
               target_id=teacher_id, detail=f"{t.name} · {subj.name}")
    return subject_assignment_out(a)


@app.delete("/api/school/teachers/{teacher_id}/subjects/{assignment_id}")
def remove_teacher_subject(teacher_id: int, assignment_id: int, request: Request,
                           db: Session = Depends(get_db),
                           user: User = Depends(require_school_account)):
    a = db.get(TeacherSubjectAssignment, assignment_id)
    if not a or a.teacher_id != teacher_id or a.school_id != user.school_id:
        raise HTTPException(status_code=404, detail="담당 과목을 찾을 수 없습니다.")
    subj_name = a.subject.name if a.subject else ""
    db.delete(a)
    db.commit()
    write_audit(db, request, user, action="teacher.subject_remove", target_type="user",
               target_id=teacher_id, detail=subj_name)
    return {"ok": True}


# ══════════════════════════════════════════════════════════
# 선생님 계정 — 검색·권한부여·해제 (예전에는 UDJ 화면에 있던 기능, 이동해 옴)
# 계정 원본은 여전히 UDJ 뿐이라, 여기서는 매 요청마다 UDJ를 그대로 불러
# 대신 처리한다(partner API, X-Partner-Secret 인증). 담당 과목 배정용
# /api/school/teachers(위, 기록해 로컬 사본)와는 다른 목적이라 경로를
# teacher-accounts 로 분리했다 — 아직 기록해에 한 번도 로그인 안 한
# 선생님도 여기서는 검색·부여가 가능해야 하기 때문이다.
def _require_udj() -> None:
    if not udj.is_ready():
        raise HTTPException(status_code=503, detail="계정 연동이 설정되지 않았습니다.")


@app.get("/api/school/teacher-accounts")
def list_teacher_accounts(user: User = Depends(require_school_account)):
    _require_udj()
    return udj.list_teachers(user.school_id)


@app.get("/api/school/teacher-accounts/search")
def search_teacher_accounts(q: str, user: User = Depends(require_school_account)):
    _require_udj()
    return udj.search_teacher_candidates(user.school_id, q)


@app.post("/api/school/teacher-accounts/grant")
def grant_teacher_account(payload: dict, request: Request, db: Session = Depends(get_db),
                          user: User = Depends(require_school_account)):
    _require_udj()
    result = udj.grant_teacher(
        user.school_id, int(payload.get("user_id") or 0), str(payload.get("class_name") or ""))
    write_audit(db, request, user, action="teacher_account.grant",
               target_type="udj_user", target_id=payload.get("user_id"),
               detail=(result.get("teacher") or {}).get("name", ""))
    return result


@app.put("/api/school/teacher-accounts/{teacher_id}")
def update_teacher_account(teacher_id: int, payload: dict,
                           user: User = Depends(require_school_account)):
    _require_udj()
    return udj.update_teacher(user.school_id, teacher_id, payload)


@app.delete("/api/school/teacher-accounts/{teacher_id}")
def revoke_teacher_account(teacher_id: int, request: Request, db: Session = Depends(get_db),
                           user: User = Depends(require_school_account)):
    _require_udj()
    result = udj.revoke_teacher(user.school_id, teacher_id)
    write_audit(db, request, user, action="teacher_account.revoke",
               target_type="udj_user", target_id=teacher_id, detail="")
    return result


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


@app.get("/api/school/dashboard")
def school_dashboard(db: Session = Depends(get_db),
                     user: User = Depends(require_seat_manager)):
    """학교 계정이 처음 보는 화면.

    통계를 늘어놓기보다 '지금 손이 필요한 것'이 드러나게 짰다.
    이용권을 사 두고 아무에게도 안 나눠준 상태, 일지를 한 번도 안 낸
    학생 같은 것들이 그렇다.
    """
    sid = user.school_id
    now = datetime.utcnow()

    # 학생 수와 인증 수는 세기만 하면 된다. id 목록은 일지를 셀 때 쓴다.
    ids = [i for (i,) in db.query(User.id).filter(
        User.school_id == sid, User.role == Role.student).all()]
    students_n = len(ids)
    verified = db.query(func.count(User.id)).filter(
        User.school_id == sid, User.role == Role.student,
        User.verified.is_(True)).scalar() or 0

    info = seat_summary(db, sid)

    # 일지를 전부 읽어 파이썬에서 세면, 학생 200명 학교에서 2만 건이 통째로
    # 메모리에 올라온다(본문까지). 세는 일은 DB 에 맡긴다.
    def jcount(*conds):
        q = db.query(func.count(JournalEntry.id)).filter(JournalEntry.user_id.in_(ids))
        for cnd in conds:
            q = q.filter(cnd)
        return q.scalar() or 0

    if ids:
        entries_n = jcount()
        submitted_n = jcount(JournalEntry.sent_at.isnot(None))
        recent_n = jcount(JournalEntry.created_at > now - timedelta(days=30))
        awaiting = jcount(JournalEntry.sent_at.isnot(None),
                          or_(JournalEntry.feedback.is_(None), JournalEntry.feedback == ""))
        wrote_n = db.query(func.count(func.distinct(JournalEntry.user_id))).filter(
            JournalEntry.user_id.in_(ids)).scalar() or 0
        letters = db.query(func.count(CoverLetter.id)).filter(
            CoverLetter.user_id.in_(ids)).scalar() or 0
    else:
        entries_n = submitted_n = recent_n = awaiting = wrote_n = letters = 0

    teachers = db.query(func.count(User.id)).filter(
        User.school_id == sid, User.role == Role.teacher).scalar() or 0

    codes = db.query(SeatCode).filter(SeatCode.school_id == sid,
                                      SeatCode.is_active.is_(True)).all()
    code_left = sum(max(0, c.max_uses - c.used_count) for c in codes)

    pending_order = db.query(SeatOrder).filter(
        SeatOrder.school_id == sid,
        SeatOrder.status.in_([OrderStatus.pending, OrderStatus.paid])).first()

    # 만료가 가까우면 미리 알려준다. 끊기고 나서 알면 늦다.
    days_left = None
    if info["expires_at"]:
        days_left = (info["expires_at"] - now).days

    return {
        "school_id": sid,
        "students": students_n,
        "verified": verified,
        "unverified": students_n - verified,
        "teachers": teachers,
        "seats": info["seats"], "seats_used": info["used"], "seats_left": info["left"],
        "seat_active": info["active"], "expires_at": info["expires_at"],
        "days_left": days_left,
        "unit_price": info["unit_price"],
        "code_left": code_left,
        "active_codes": len(codes),
        "journals": entries_n,
        "journals_30d": recent_n,
        "submitted": submitted_n,
        "awaiting_feedback": awaiting,
        "never_wrote": len(ids) - wrote_n,
        "cover_letters": letters,
        "pending_order": None if not pending_order else {
            "id": pending_order.id, "seats": pending_order.seats,
            "amount": pending_order.amount,
            "status_label": ORDER_STATUS_LABEL.get(pending_order.status.value, ""),
        },
    }


@app.get("/api/school/seats")
def get_school_seats(product: str = Query("essay"), db: Session = Depends(get_db),
                     user: User = Depends(require_seat_manager)):
    """우리 학교 좌석 현황과 배정된 학생. product: essay(자기소개서) 또는 research(연구)."""
    holders = (db.query(SeatHolder, User)
               .join(User, SeatHolder.user_id == User.id)
               .filter(SeatHolder.school_id == user.school_id,
                       SeatHolder.product == product)
               .order_by(User.name).all())
    return {
        **seat_summary(db, user.school_id, product),
        "holders": [{
            "user_id": u.id, "name": u.name, "email": u.email,
            "class_name": u.class_name or "", "grade": u.grade,
            "granted_at": h.granted_at,
        } for h, u in holders],
    }


@app.get("/api/school/students")
def school_students(q: str = "", product: str = Query("essay"),
                    limit: int = Query(20, ge=1, le=100),
                    offset: int = Query(0, ge=0),
                    db: Session = Depends(get_db),
                    user: User = Depends(require_seat_manager)):
    """우리 학교 학생 명단. 한 번에 다 내리면 큰 학교에서 화면이 버거워진다."""
    base = db.query(User).filter(User.school_id == user.school_id,
                                 User.role == Role.student)
    term = q.strip()
    if term:
        base = base.filter(or_(User.name.ilike(f"%{term}%"),
                               User.class_name.ilike(f"%{term}%"),
                               User.email.ilike(f"%{term}%")))
    total = base.count()
    rows = (base.order_by(User.grade, User.class_name, User.name)
            .offset(offset).limit(limit).all())
    held = {h.user_id for h in db.query(SeatHolder).filter(
        SeatHolder.school_id == user.school_id, SeatHolder.product == product).all()}
    return {
        "total": total, "limit": limit, "offset": offset,
        "items": [{
            "user_id": u.id, "name": u.name, "email": u.email,
            "grade": u.grade, "class_name": u.class_name or "",
            "verified": bool(u.verified),
            "has_seat": u.id in held,
        } for u in rows],
    }


@app.post("/api/school/seats/assign")
def assign_seats(payload: dict, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(require_school_account)):
    """학생에게 좌석을 준다. 남은 좌석 수를 넘길 수 없다."""
    ids = payload.get("user_ids") or []
    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=400, detail="학생을 골라주세요.")
    product = str(payload.get("product") or "essay")

    info = seat_summary(db, user.school_id, product)
    if not info["active"]:
        raise HTTPException(status_code=400, detail="이용 중인 좌석이 없습니다. 먼저 결제해주세요.")

    students = db.query(User).filter(
        User.id.in_(ids), User.school_id == user.school_id,
        User.role == Role.student).all()
    held = {h.user_id for h in db.query(SeatHolder).filter(
        SeatHolder.school_id == user.school_id, SeatHolder.product == product).all()}
    fresh = [u for u in students if u.id not in held]

    if len(fresh) > info["left"]:
        raise HTTPException(
            status_code=400,
            detail=f"남은 좌석이 {info['left']}개입니다. {len(fresh)}명을 배정할 수 없습니다.",
        )

    for u in fresh:
        db.add(SeatHolder(school_id=user.school_id, user_id=u.id, granted_by=user.id,
                          product=product))
    db.commit()
    write_audit(db, request, user, action="seat.assign", target_type="school",
                target_id=user.school_id, detail=f"{len(fresh)}명 배정({product})")
    return {"ok": True, "assigned": len(fresh),
            "message": f"{len(fresh)}명에게 좌석을 주었습니다.",
            **seat_summary(db, user.school_id, product)}


@app.post("/api/school/seats/revoke")
def revoke_seats(payload: dict, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(require_school_account)):
    """좌석을 회수한다. 다른 학생에게 넘길 수 있다."""
    ids = payload.get("user_ids") or []
    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=400, detail="학생을 골라주세요.")
    product = str(payload.get("product") or "essay")
    n = db.query(SeatHolder).filter(
        SeatHolder.school_id == user.school_id,
        SeatHolder.user_id.in_(ids),
        SeatHolder.product == product).delete(synchronize_session=False)
    db.commit()
    write_audit(db, request, user, action="seat.revoke", target_type="school",
                target_id=user.school_id, detail=f"{n}명 회수({product})")
    return {"ok": True, "revoked": n,
            "message": f"{n}명의 좌석을 회수했습니다. 작성한 자기소개서는 남아 있습니다.",
            **seat_summary(db, user.school_id, product)}


@app.post("/api/admin/reset-subscriptions")
def reset_subscriptions(payload: dict, request: Request, db: Session = Depends(get_db),
                        user: User = Depends(require_admin)):
    """이용권 관련 자료를 모두 지운다.

    정식 오픈 전에 시험하며 만든 좌석·구독·주문을 한 번에 치운다.
    되돌릴 수 없으므로 확인 문구를 정확히 입력해야 실행된다.

    일지와 자기소개서 본문은 건드리지 않는다. 결제와 관계없는 자료다.
    """
    if str(payload.get("confirm") or "").strip() != "초기화":
        raise HTTPException(
            status_code=400,
            detail="확인을 위해 '초기화' 를 정확히 입력해주세요.",
        )

    counts = {
        "seat_holders": db.query(SeatHolder).delete(synchronize_session=False),
        "seat_codes": db.query(SeatCode).delete(synchronize_session=False),
        "school_seats": db.query(SchoolSeat).delete(synchronize_session=False),
        "seat_orders": db.query(SeatOrder).delete(synchronize_session=False),
        "subscriptions": db.query(Subscription).delete(synchronize_session=False),
        "subscription_orders": db.query(SubscriptionOrder).delete(synchronize_session=False),
        "unmatched_deposits": db.query(UnmatchedDeposit).delete(synchronize_session=False),
    }
    db.commit()
    write_audit(db, request, user, action="admin.reset_subscriptions",
                target_type="system", target_id="",
                detail=", ".join(f"{k} {v}" for k, v in counts.items()))
    total = sum(counts.values())
    return {
        "ok": True, "counts": counts,
        "message": f"이용권 관련 자료 {total}건을 지웠습니다. 일지와 자기소개서는 그대로입니다.",
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


@app.get("/api/school/seat-codes")
def list_seat_codes(product: str = Query("essay"), db: Session = Depends(get_db),
                    user: User = Depends(require_seat_manager)):
    rows = (db.query(SeatCode).filter(SeatCode.school_id == user.school_id,
                                      SeatCode.product == product)
            .order_by(SeatCode.created_at.desc()).all())
    return [code_out(x) for x in rows]


@app.post("/api/school/seat-codes")
def create_seat_code(payload: dict, request: Request, db: Session = Depends(get_db),
                     user: User = Depends(require_seat_manager)):
    """등록 코드를 만든다. 쓸 수 있는 횟수는 남은 좌석을 넘을 수 없다."""
    product = str(payload.get("product") or "essay")
    info = seat_summary(db, user.school_id, product)
    if not info["active"]:
        raise HTTPException(status_code=400, detail="이용 중인 좌석이 없습니다. 먼저 신청해주세요.")

    try:
        uses = int(payload.get("max_uses") or 0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="인원수를 숫자로 적어주세요.")
    if uses < 1:
        raise HTTPException(status_code=400, detail="1명 이상으로 적어주세요.")

    # 이미 만들어 둔 코드가 쓸 자리까지 미리 셈한다. 그러지 않으면
    # 코드를 여러 장 만들어 좌석보다 많이 나눠줄 수 있다.
    reserved = db.query(func.coalesce(
        func.sum(SeatCode.max_uses - SeatCode.used_count), 0)).filter(
        SeatCode.school_id == user.school_id, SeatCode.product == product,
        SeatCode.is_active.is_(True)).scalar() or 0
    if uses > info["left"] - reserved:
        raise HTTPException(
            status_code=400,
            detail=(f"남은 좌석 {info['left']}석 중 이미 만든 코드가 {reserved}석을 "
                    f"쓰고 있습니다. {max(0, info['left'] - reserved)}명까지 만들 수 있습니다."),
        )

    # 코드에 학년·반·학과를 담는다. 학생이 이 코드를 넣으면 그대로
    # 옮겨 담아, 학생이 직접 고르지 않아도 된다.
    #
    # 선생님이 만들면 그 선생님 것을 기본으로 쓴다. 코드를 만든 사람이
    # 곧 그 반의 담당이기 때문이다. 학교 계정이 만들 때는 직접 적는다.
    def pick(key, fallback=""):
        v = payload.get(key)
        if v is None or str(v).strip() == "":
            return fallback
        return str(v).strip()

    is_teacher = user.role == Role.teacher
    grade_raw = pick("grade", user.grade if is_teacher else "")
    try:
        grade = int(grade_raw) if str(grade_raw).strip() else None
    except (TypeError, ValueError):
        grade = None
    class_no = pick("class_no", user.class_name if is_teacher else "")[:20]
    department = pick("department", user.department if is_teacher else "")[:60]

    # 이름표를 비우면 학년·반으로 만든다. 어디서 나눠준 코드인지
    # 나중에 알아보기 위해서다.
    label = pick("label")
    if not label:
        parts = [f"{grade}학년" if grade else "", class_no, department]
        label = " ".join(x for x in parts if x)

    x = SeatCode(
        school_id=user.school_id, code=make_seat_code(db),
        product=product, label=label[:60],
        grade=grade, class_no=class_no, department=department,
        max_uses=uses, created_by=user.id,
        expires_at=school_seat(db, user.school_id, product).expires_at,
    )
    db.add(x)
    db.commit()
    db.refresh(x)
    write_audit(db, request, user, action="seat.code_create", target_type="school",
                target_id=user.school_id, detail=f"{x.code} {uses}명 {x.label}({product})")
    return code_out(x)


@app.post("/api/school/seat-codes/{code_id}/toggle")
def toggle_seat_code(code_id: int, db: Session = Depends(get_db),
                     user: User = Depends(require_seat_manager)):
    """코드를 끄거나 켠다. 끄면 그 코드로는 더 등록할 수 없다."""
    x = db.get(SeatCode, code_id)
    if not x or x.school_id != user.school_id:
        raise HTTPException(status_code=404, detail="코드를 찾을 수 없습니다.")
    x.is_active = not bool(x.is_active)
    db.commit()
    return code_out(x)


@app.post("/api/seat-codes/redeem")
def redeem_seat_code(payload: dict, request: Request, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    """학생이 코드를 입력해 좌석을 받는다."""
    if user.role != Role.student:
        raise HTTPException(status_code=403, detail="학생만 등록할 수 있습니다.")

    raw = str(payload.get("code") or "").strip().upper().replace(" ", "")
    if raw and "-" not in raw and len(raw) == 8:
        raw = f"{raw[:4]}-{raw[4:]}"
    if not raw:
        raise HTTPException(status_code=400, detail="코드를 입력해주세요.")

    x = db.query(SeatCode).filter(SeatCode.code == raw).first()
    # 어느 학교 코드인지까지 알려주지 않는다. 코드를 찍어보는 것을 돕지 않기 위해서다.
    if not x or not x.is_active:
        raise HTTPException(status_code=400, detail="쓸 수 없는 코드입니다. 다시 확인해주세요.")
    if x.school_id != user.school_id:
        raise HTTPException(status_code=400, detail="우리 학교 코드가 아닙니다.")
    if x.expires_at and x.expires_at <= datetime.utcnow():
        raise HTTPException(status_code=400, detail="기간이 지난 코드입니다.")

    already = db.query(SeatHolder).filter(
        SeatHolder.school_id == user.school_id, SeatHolder.user_id == user.id,
        SeatHolder.product == x.product).first()
    if already:
        return {"ok": True, "already": True, "message": "이미 이용권이 있습니다."}

    if x.used_count >= x.max_uses:
        raise HTTPException(status_code=400, detail="이 코드는 인원이 다 찼습니다. 선생님께 문의해주세요.")

    info = seat_summary(db, user.school_id, x.product)
    if not info["active"] or info["left"] <= 0:
        raise HTTPException(status_code=400, detail="학교에 남은 좌석이 없습니다. 선생님께 문의해주세요.")

    # 학생 번호(선택). 학년·반이 코드에 담겨 있어야 몇 반 몇 번인지가 정해진다.
    # 좌석을 내주기 전에 먼저 확인한다 — 번호가 겹쳐 막힌다면 유료 좌석을
    # 미리 써버리는 일이 없어야 한다.
    academic_year = datetime.utcnow().year
    student_no = None
    if x.grade and x.class_no:
        raw_no = payload.get("student_no")
        if raw_no not in (None, ""):
            try:
                student_no = int(raw_no)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="학생 번호는 숫자로 적어주세요.")
            if student_no < 1 or student_no > 999:
                raise HTTPException(status_code=400, detail="학생 번호를 다시 확인해주세요.")
            dup = (db.query(StudentEnrollment)
                   .filter(StudentEnrollment.school_id == user.school_id,
                           StudentEnrollment.academic_year == academic_year,
                           StudentEnrollment.grade == x.grade,
                           StudentEnrollment.class_no == x.class_no,
                           StudentEnrollment.student_no == student_no).first())
            if dup:
                raise HTTPException(
                    status_code=409,
                    detail=(f"{x.grade}학년 {x.class_no} {student_no}번은 이미 등록되어 "
                            "있습니다. 번호를 다시 확인하거나 선생님께 문의해주세요."))

    db.add(SeatHolder(school_id=user.school_id, user_id=user.id, granted_by=x.created_by,
                      product=x.product))
    x.used_count += 1

    # 코드에 담긴 학년·반·학과를 학생에게 옮겨 담는다.
    # 학생이 직접 고르면 오타가 나고, 반을 잘못 고르면 담당 선생님과
    # 이어지지 않는다. 코드를 만든 사람이 곧 그 반의 담당이므로,
    # 코드에 딸려 오게 하는 편이 정확하다.
    moved = []
    if x.grade:
        user.grade = x.grade
        moved.append(f"{x.grade}학년")
    if x.class_no:
        user.class_name = x.class_no
        moved.append(x.class_no)
    if x.department:
        user.department = x.department
        moved.append(x.department)

    if student_no is not None:
        db.add(StudentEnrollment(
            user_id=user.id, school_id=user.school_id, academic_year=academic_year,
            grade=x.grade, class_no=x.class_no, student_no=student_no,
            department=x.department or user.department or "",
        ))
        moved.append(f"{student_no}번")

    # 담당 선생님도 이어 준다. 선생님이 만든 코드일 때만이다.
    # 학교 계정이 만든 코드에는 담당이랄 것이 없다.
    maker = db.get(User, x.created_by) if x.created_by else None
    if maker and maker.role == Role.teacher and maker.udj_user_id:
        user.teacher_udj_id = maker.udj_user_id

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="처리 중 충돌이 발생했습니다. 다시 시도해주세요.")
    write_audit(db, request, user, action="seat.code_redeem", target_type="seat_code",
                target_id=x.id, detail=f"{x.code} {x.label}({x.product})")
    feature_label = SEAT_PRODUCT_LABEL.get(x.product, x.product)
    return {
        "ok": True, "already": False,
        "moved_to": " ".join(moved),
        "message": (
            f"이용권이 등록되었습니다. {' '.join(moved)} 로 배정되었습니다."
            if moved else
            f"이용권이 등록되었습니다. 이제 {feature_label}을(를) 쓸 수 있습니다."
        ),
    }


@app.post("/api/school/seat-orders")
def create_seat_order(payload: dict, request: Request, db: Session = Depends(get_db),
                      user: User = Depends(require_school_account)):
    """좌석을 신청한다. 인원은 학교가 적고 관리자가 확인한다."""
    try:
        seats = int(payload.get("seats") or 0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="인원수를 숫자로 적어주세요.")
    if seats < 1 or seats > 5000:
        raise HTTPException(status_code=400, detail="인원수는 1명 이상 5000명 이하로 적어주세요.")
    product = str(payload.get("product") or "essay")

    exists = db.query(SeatOrder).filter(
        SeatOrder.school_id == user.school_id, SeatOrder.product == product,
        SeatOrder.status.in_([OrderStatus.pending, OrderStatus.paid])).first()
    if exists:
        # 같은 학교의 같은 상품 신청이 여러 건 쌓이면 입금 대조가 꼬인다.
        out = seat_order_out(db, exists)
        out["reused"] = True
        return out

    q = seat_quote(db, seats)
    months = SEAT_MONTHS_DEFAULT
    o = SeatOrder(
        school_id=user.school_id, product=product,
        school_name=(payload.get("school_name") or "")[:120],
        requested_by=user.id, requester_email=user.email,
        seats=seats, unit_price=q["unit_price"], months=months,
        discount_percent=q["discount_percent"], amount=q["amount"],
        note=str(payload.get("note") or "")[:300],
        depositor_name=str(payload.get("depositor_name") or "").strip()[:40],
        deposit_code=make_deposit_code(db),
        bank_key=assign_bank(db),
        due_at=datetime.utcnow() + timedelta(days=SUBSCRIPTION_DUE_DAYS),
    )
    db.add(o)
    db.commit()
    db.refresh(o)
    return seat_order_out(db, o)


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


@app.get("/api/school/seat-quote")
def get_seat_quote(seats: int = Query(0, ge=0, le=5000),
                   db: Session = Depends(get_db),
                   user: User = Depends(require_school_account)):
    """신청 전에 얼마인지 미리 보여준다."""
    return seat_quote(db, max(0, seats))


@app.get("/api/school/seat-orders")
def list_seat_orders(db: Session = Depends(get_db),
                     user: User = Depends(require_school_account)):
    rows = (db.query(SeatOrder).filter(SeatOrder.school_id == user.school_id)
            .order_by(SeatOrder.created_at.desc()).all())
    return [seat_order_out(db, o) for o in rows]


@app.post("/api/school/seat-orders/{order_id}/cancel")
def cancel_seat_order(order_id: int, request: Request, db: Session = Depends(get_db),
                      user: User = Depends(require_school_account)):
    o = db.get(SeatOrder, order_id)
    if not o or o.school_id != user.school_id:
        raise HTTPException(status_code=404, detail="신청을 찾을 수 없습니다.")
    if o.status != OrderStatus.pending:
        raise HTTPException(status_code=400, detail="입금 대기 상태만 취소할 수 있습니다.")
    o.status = OrderStatus.rejected
    o.handled_at = datetime.utcnow()
    db.commit()
    write_audit(db, request, user, action="seat.order_cancel", target_type="seat_order",
                target_id=o.id, detail="학교 취소")
    return {"ok": True, "message": "신청을 취소했습니다."}


# ── 관리자: 좌석 주문 확인 ──────────────────────────────────


@app.get("/api/admin/seat-orders")
def admin_seat_orders(status: str = "", db: Session = Depends(get_db),
                      user: User = Depends(require_admin)):
    q = db.query(SeatOrder)
    if status in ("pending", "paid", "approved", "rejected"):
        q = q.filter(SeatOrder.status == OrderStatus(status))
    rows = q.order_by(SeatOrder.created_at.desc()).limit(300).all()
    return [{
        **seat_order_out(db, o),
        "school_id": o.school_id, "school_name": o.school_name or "",
        "requester_email": o.requester_email or "",
    } for o in rows]


@app.post("/api/admin/seat-orders/{order_id}/approve")
def approve_seat_order(order_id: int, payload: dict, request: Request,
                       db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """인원을 확인하고 승인한다.

    학교가 적은 인원과 실제 인원이 다를 수 있어, 승인할 때 관리자가 인원을
    다시 정한다. 인원이 바뀌면 금액도 다시 계산해 기록에 남긴다.
    """
    o = db.get(SeatOrder, order_id)
    if not o:
        raise HTTPException(status_code=404, detail="신청을 찾을 수 없습니다.")
    if o.status == OrderStatus.approved:
        raise HTTPException(status_code=400, detail="이미 승인된 신청입니다.")
    if o.status not in (OrderStatus.pending, OrderStatus.paid):
        raise HTTPException(status_code=400, detail="승인할 수 없는 상태입니다.")

    try:
        seats = int(payload.get("seats") or o.seats)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="인원수를 숫자로 적어주세요.")
    if seats < 1 or seats > 5000:
        raise HTTPException(status_code=400, detail="인원수는 1명 이상 5000명 이하로 적어주세요.")

    now = datetime.utcnow()
    # 인원이 바뀌면 할인 구간도 달라질 수 있어 다시 계산한다.
    q = seat_quote(db, seats)
    o.approved_seats = seats
    o.unit_price = q["unit_price"]
    o.discount_percent = q["discount_percent"]
    o.amount = q["amount"]
    o.status = OrderStatus.approved
    o.paid_at = o.paid_at or now
    o.handled_at = now
    o.admin_note = str(payload.get("note") or "")[:300]

    # 좌석을 더한다. 학년별로 여러 번 사면 쌓인다(상품별로 따로 쌓인다).
    product = o.product or "essay"
    seat = school_seat(db, o.school_id, product)
    add_days = SEAT_DAYS_PER_YEAR * max(1, o.months // 12)
    if seat is None:
        seat = SchoolSeat(school_id=o.school_id, product=product, seats=seats, started_at=now,
                          expires_at=now + timedelta(days=add_days))
        db.add(seat)
    else:
        seat.seats = (seat.seats or 0) + seats
        base = seat.expires_at if seat.expires_at > now else now
        seat.expires_at = base + timedelta(days=add_days)
    db.commit()

    write_audit(db, request, user, action="seat.order_approve", target_type="seat_order",
                target_id=o.id,
                detail=f"{o.school_name} {seats}명 · {o.amount}원"
                       + (f" (신청 {o.seats}명)" if seats != o.seats else ""))
    return {"ok": True, "seats": seats, "amount": o.amount,
            "expires_at": seat.expires_at,
            "message": f"{seats}명 좌석을 승인했습니다."}


@app.post("/api/admin/seat-orders/{order_id}/confirm-deposit")
def confirm_seat_deposit(order_id: int, request: Request, db: Session = Depends(get_db),
                         user: User = Depends(require_admin)):
    """입금이 들어온 것만 확인해 둔다.

    통장 대조로 알 수 있는 것은 돈이 들어왔다는 사실뿐이다. 인원이 맞는지는
    사람이 봐야 하므로 승인은 따로 한다.
    """
    o = db.get(SeatOrder, order_id)
    if not o:
        raise HTTPException(status_code=404, detail="신청을 찾을 수 없습니다.")
    if o.status != OrderStatus.pending:
        raise HTTPException(status_code=400, detail="입금 대기 상태인 신청만 확인할 수 있습니다.")
    o.status = OrderStatus.paid
    o.paid_at = datetime.utcnow()
    db.commit()
    write_audit(db, request, user, action="seat.deposit_confirm",
                target_type="seat_order", target_id=o.id, detail=f"{o.amount}원")
    return {"ok": True, "message": "입금 확인으로 바꿨습니다. 인원 확인 후 승인해주세요."}


@app.post("/api/admin/seat-orders/{order_id}/reject")
def reject_seat_order(order_id: int, payload: dict, request: Request,
                      db: Session = Depends(get_db), user: User = Depends(require_admin)):
    o = db.get(SeatOrder, order_id)
    if not o:
        raise HTTPException(status_code=404, detail="신청을 찾을 수 없습니다.")
    if o.status == OrderStatus.approved:
        raise HTTPException(status_code=400, detail="이미 승인된 신청입니다.")
    o.status = OrderStatus.rejected
    o.handled_at = datetime.utcnow()
    o.admin_note = str(payload.get("note") or "")[:300]
    db.commit()
    write_audit(db, request, user, action="seat.order_reject", target_type="seat_order",
                target_id=o.id, detail=o.admin_note)
    return {"ok": True, "message": "신청을 반려했습니다."}


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


@app.get("/api/refund-policy")
def get_refund_policy():
    """환불 규정. 결제 화면과 환불 규정 페이지에서 함께 보여준다."""
    return REFUND_POLICY


@app.post("/api/cover-letters/review")
def review_cover_letter(payload: WritingReviewIn,
                        user: User = Depends(require_subscription)):
    """작성한 글을 점검한다. 문장을 새로 지어내지 않고 고칠 지점만 알려준다."""
    return {"results": writing.review_many(payload.fields, payload.limit)}


@app.get("/api/cover-letters/materials")
def cover_letter_materials(topic: Optional[str] = Query(None, description="항목 키로 좁히기"),
                           db: Session = Depends(get_db),
                           user: User = Depends(require_subscription)):
    """그동안 쓴 일지를 자소서 항목별로 모아준다. 새 문장을 지어내지 않는다."""
    rows = (
        db.query(JournalEntry)
        .filter(JournalEntry.user_id == user.id)
        .order_by(JournalEntry.entry_date.desc()).all()
    )
    entries = []
    for e in rows:
        labels = dict(ai.field_labels(e.kind))
        for key, text_value in journal_content(e).items():
            if key not in labels or not (text_value or "").strip():
                continue
            entries.append({
                "id": e.id, "kind": e.kind,
                "entry_date": e.entry_date.isoformat() if e.entry_date else "",
                "field_key": key, "field_label": labels[key],
                "text": text_value.strip(),
            })
    topics = ai.match_resume_topics(entries)
    if topic:
        topics = [t for t in topics if t["key"] == topic]

    return {
        "journal_count": len(rows),
        "passage_count": len(entries),
        "topics": topics,
        "analyzed_at": datetime.utcnow(),
    }


@app.get("/api/cover-letters")
def list_cover_letters(db: Session = Depends(get_db),
                       user: User = Depends(require_subscription)):
    rows = (
        db.query(CoverLetter).filter(CoverLetter.user_id == user.id)
        .order_by(CoverLetter.updated_at.desc()).all()
    )
    return [{"id": r.id, "title": r.title, "updated_at": r.updated_at} for r in rows]


@app.get("/api/cover-letters/{letter_id}")
def get_cover_letter(letter_id: int, db: Session = Depends(get_db),
                     user: User = Depends(require_subscription)):
    r = db.get(CoverLetter, letter_id)
    if not r or r.user_id != user.id:
        raise HTTPException(status_code=404, detail="자기소개서를 찾을 수 없습니다.")
    try:
        content = json.loads(r.content or "{}")
    except (ValueError, TypeError):
        content = {}
    return {"id": r.id, "title": r.title, "content": content,
            "created_at": r.created_at, "updated_at": r.updated_at}


@app.post("/api/cover-letters")
def create_cover_letter(payload: CoverLetterIn, db: Session = Depends(get_db),
                        user: User = Depends(require_subscription)):
    r = CoverLetter(user_id=user.id, title=(payload.title or "제목 없음")[:120],
                    content=json.dumps(payload.content or {}, ensure_ascii=False))
    db.add(r)
    db.commit()
    db.refresh(r)
    return {"id": r.id}


@app.get("/api/cover-letters/{letter_id}/download")
def download_cover_letter(letter_id: int, fmt: str = Query("pdf"),
                          db: Session = Depends(get_db),
                          user: User = Depends(require_subscription)):
    """자기소개서를 양식이 갖춰진 파일로 내려준다.

    화면에서 항목을 하나씩 복사해 붙이면 빠뜨리거나 순서가 뒤바뀐다.
    제출용 문서로 바로 받게 한다.
    """
    if fmt not in resume_export.FORMATS:
        raise HTTPException(status_code=400, detail="지원하지 않는 형식입니다.")

    r = db.get(CoverLetter, letter_id)
    if not r or r.user_id != user.id:
        raise HTTPException(status_code=404, detail="자기소개서를 찾을 수 없습니다.")

    try:
        content = json.loads(r.content or "{}")
    except (ValueError, TypeError):
        content = {}

    # 내용이 있는 항목만, 양식에 적힌 순서대로 담는다.
    # 예전 양식으로 쓴 글도 뒤에 붙인다. 양식이 바뀌었다고 학생이 써 둔
    # 글이 파일에서 통째로 빠지면 안 된다.
    items = [(label, content[key])
             for key, label in ai.ALL_TEMPLATES.items()
             if (content.get(key) or "").strip()]
    if not items:
        raise HTTPException(status_code=400, detail="내용이 있는 항목이 없습니다.")

    media, ext, builder = resume_export.FORMATS[fmt]
    title = (r.title or "").strip() or "자기소개서"
    try:
        data = builder(user.name or "", title, items)
    except RuntimeError as exc:
        # 글꼴이 없어 PDF 를 못 만드는 경우. 다른 형식은 쓸 수 있다고 알린다.
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        print(f"[자소서 내보내기] {fmt} 실패: {exc!r}", flush=True)
        raise HTTPException(status_code=500, detail="파일을 만들지 못했습니다.")

    stem = resume_export.safe_filename(f"{title}_{user.name}" if user.name else title)
    # 한글 파일 이름은 브라우저마다 다루는 방식이 달라 두 가지를 함께 준다.
    from urllib.parse import quote
    disp = (f"attachment; filename=\"resume.{ext}\"; "
            f"filename*=UTF-8''{quote(stem)}.{ext}")

    write_audit(db, request=None, actor=user, action="cover_letter.download",
                target_type="cover_letter", target_id=r.id, detail=fmt)
    return Response(content=data, media_type=media,
                    headers={"Content-Disposition": disp})


@app.put("/api/cover-letters/{letter_id}")
def update_cover_letter(letter_id: int, payload: CoverLetterIn,
                        db: Session = Depends(get_db),
                        user: User = Depends(require_subscription)):
    r = db.get(CoverLetter, letter_id)
    if not r or r.user_id != user.id:
        raise HTTPException(status_code=404, detail="자기소개서를 찾을 수 없습니다.")
    r.title = (payload.title or "제목 없음")[:120]
    r.content = json.dumps(payload.content or {}, ensure_ascii=False)
    db.commit()
    return {"ok": True}


@app.delete("/api/cover-letters/{letter_id}")
def delete_cover_letter(letter_id: int, db: Session = Depends(get_db),
                        user: User = Depends(require_subscription)):
    r = db.get(CoverLetter, letter_id)
    if not r or r.user_id != user.id:
        raise HTTPException(status_code=404, detail="자기소개서를 찾을 수 없습니다.")
    db.delete(r)
    db.commit()
    return {"ok": True}


@app.post("/api/cover-letters/polish")
def polish_cover_letter(payload: dict, user: User = Depends(require_subscription)):
    """자소서 본문을 서류 말투로 다듬고, 어울리지 않는 표현을 알려준다.

    글을 대신 써 주지 않는다. 겪은 일은 학생의 것이고 우리는 말투만
    손본다. 걸린 표현도 몰래 지우지 않고 무엇이 왜 걸렸는지 알려 준다.
    """
    text = str(payload.get("text") or "")
    if len(text) > 20000:
        raise HTTPException(status_code=400, detail="글이 너무 깁니다.")
    return ai.polish_resume_text(text)


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


def portfolio_out(p: Portfolio, page_count: int = None, image_count: int = None) -> dict:
    out = {
        "id": p.id, "title": p.title, "description": p.description,
        "purpose": p.purpose, "theme_type": p.theme_type,
        "theme_label": portfolio.THEME_LABEL.get(p.theme_type, p.theme_type),
        "career_goal": p.career_goal or "",
        "cover_image_id": p.cover_image_id,
        "visibility": p.visibility, "status": p.status,
        "created_at": p.created_at, "updated_at": p.updated_at,
    }
    if page_count is not None:
        out["page_count"] = page_count
    if image_count is not None:
        out["image_count"] = image_count
    return out


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
    return {"fields": dept_fields.options(), "themes": portfolio.THEME_TYPES,
           "theme_labels": portfolio.THEME_LABEL,
           "purposes": portfolio.PURPOSE_TYPES, "purpose_labels": portfolio.PURPOSE_LABEL}


@app.get("/api/portfolios")
def list_portfolios(db: Session = Depends(get_db), user: User = Depends(require_student)):
    rows = (db.query(Portfolio).filter(Portfolio.student_id == user.id)
           .order_by(Portfolio.updated_at.desc()).all())
    page_counts = dict(
        db.query(PortfolioPage.portfolio_id, func.count(PortfolioPage.id))
        .filter(PortfolioPage.portfolio_id.in_([p.id for p in rows] or [0]))
        .group_by(PortfolioPage.portfolio_id).all())
    return [portfolio_out(p, page_count=page_counts.get(p.id, 0)) for p in rows]


@app.post("/api/portfolios")
def create_portfolio(payload: PortfolioIn, db: Session = Depends(get_db),
                     user: User = Depends(require_student)):
    if payload.theme_type not in portfolio.THEME_TYPES:
        raise HTTPException(status_code=400, detail="올바르지 않은 테마입니다.")
    if payload.purpose not in portfolio.PURPOSE_TYPES:
        raise HTTPException(status_code=400, detail="올바르지 않은 목적입니다.")
    p = Portfolio(student_id=user.id, title=(payload.title or "제목 없는 포트폴리오")[:120],
                 description=payload.description, purpose=payload.purpose,
                 theme_type=payload.theme_type, career_goal=payload.career_goal)
    db.add(p)
    db.commit()
    db.refresh(p)
    # 빈 포트폴리오보다는 표지 페이지 하나가 있는 편이 덜 막막하다.
    cover = PortfolioPage(portfolio_id=p.id, title="표지", sort_order=0)
    db.add(cover)
    db.commit()
    return portfolio_out(p, page_count=1)


@app.get("/api/portfolios/{portfolio_id}")
def get_portfolio(portfolio_id: int, db: Session = Depends(get_db),
                  user: User = Depends(require_student)):
    p = get_own_portfolio(db, user, portfolio_id)
    pages = (db.query(PortfolioPage).filter(PortfolioPage.portfolio_id == p.id)
            .order_by(PortfolioPage.sort_order).all())
    blocks_by_page = {}
    if pages:
        all_blocks = (db.query(PortfolioBlock)
                     .filter(PortfolioBlock.page_id.in_([pg.id for pg in pages]))
                     .order_by(PortfolioBlock.sort_order).all())
        for b in all_blocks:
            blocks_by_page.setdefault(b.page_id, []).append(b)
    out = portfolio_out(p)
    out["pages"] = [page_out(pg, blocks_by_page.get(pg.id, [])) for pg in pages]
    return out


@app.put("/api/portfolios/{portfolio_id}")
def update_portfolio(portfolio_id: int, payload: PortfolioPatchIn,
                     db: Session = Depends(get_db), user: User = Depends(require_student)):
    p = get_own_portfolio(db, user, portfolio_id)
    data = payload.model_dump(exclude_unset=True)
    if "theme_type" in data and data["theme_type"] not in portfolio.THEME_TYPES:
        raise HTTPException(status_code=400, detail="올바르지 않은 테마입니다.")
    if "purpose" in data and data["purpose"] not in portfolio.PURPOSE_TYPES:
        raise HTTPException(status_code=400, detail="올바르지 않은 목적입니다.")
    if "visibility" in data and data["visibility"] not in ("private", "shared"):
        raise HTTPException(status_code=400, detail="올바르지 않은 공개 범위입니다.")
    if "status" in data and data["status"] not in ("draft", "published"):
        raise HTTPException(status_code=400, detail="올바르지 않은 상태입니다.")
    if "cover_image_id" in data and data["cover_image_id"] is not None:
        img = db.get(PortfolioImage, data["cover_image_id"])
        if not img or img.student_id != user.id:
            raise HTTPException(status_code=400, detail="대표 사진을 찾을 수 없습니다.")
    for key, value in data.items():
        setattr(p, key, value)
    db.commit()
    return portfolio_out(p)


@app.delete("/api/portfolios/{portfolio_id}")
def delete_portfolio(portfolio_id: int, db: Session = Depends(get_db),
                     user: User = Depends(require_student)):
    p = get_own_portfolio(db, user, portfolio_id)
    pages = db.query(PortfolioPage).filter(PortfolioPage.portfolio_id == p.id).all()
    page_ids = [pg.id for pg in pages]
    if page_ids:
        db.query(PortfolioBlock).filter(PortfolioBlock.page_id.in_(page_ids)).delete(
            synchronize_session=False)
    db.query(PortfolioPage).filter(PortfolioPage.portfolio_id == p.id).delete(
        synchronize_session=False)
    db.query(PortfolioSource).filter(PortfolioSource.portfolio_id == p.id).delete(
        synchronize_session=False)
    imgs = db.query(PortfolioImage).filter(PortfolioImage.portfolio_id == p.id).all()
    for img in imgs:
        image_store.delete_image(img.storage_key, img.web_key, img.thumbnail_key)
    db.query(PortfolioImage).filter(PortfolioImage.portfolio_id == p.id).delete(
        synchronize_session=False)
    db.delete(p)
    db.commit()
    return {"ok": True}


@app.post("/api/portfolios/{portfolio_id}/duplicate")
def duplicate_portfolio(portfolio_id: int, db: Session = Depends(get_db),
                        user: User = Depends(require_student)):
    src = get_own_portfolio(db, user, portfolio_id)
    copy = Portfolio(student_id=user.id, title=f"{src.title} 사본"[:120],
                     description=src.description, purpose=src.purpose,
                     theme_type=src.theme_type, career_goal=src.career_goal)
    db.add(copy)
    db.commit()
    db.refresh(copy)

    pages = (db.query(PortfolioPage).filter(PortfolioPage.portfolio_id == src.id)
            .order_by(PortfolioPage.sort_order).all())
    for pg in pages:
        new_page = PortfolioPage(portfolio_id=copy.id, title=pg.title, sort_order=pg.sort_order)
        db.add(new_page)
        db.commit()
        db.refresh(new_page)
        blocks = (db.query(PortfolioBlock).filter(PortfolioBlock.page_id == pg.id)
                 .order_by(PortfolioBlock.sort_order).all())
        for b in blocks:
            db.add(PortfolioBlock(page_id=new_page.id, block_type=b.block_type,
                                  sort_order=b.sort_order, content_json=b.content_json,
                                  style_json=b.style_json))
    db.commit()
    return portfolio_out(copy)


@app.post("/api/portfolios/{portfolio_id}/share")
def share_portfolio(portfolio_id: int, db: Session = Depends(get_db),
                    user: User = Depends(require_student)):
    """공유 링크를 만든다. 기본은 비공개이고, 이 API를 직접 불러야만
    보기 전용 링크가 생긴다."""
    p = get_own_portfolio(db, user, portfolio_id)
    if not p.share_token:
        p.share_token = secrets.token_urlsafe(24)
    p.visibility = "shared"
    db.commit()
    return {"ok": True, "share_token": p.share_token}


@app.delete("/api/portfolios/{portfolio_id}/share")
def unshare_portfolio(portfolio_id: int, db: Session = Depends(get_db),
                      user: User = Depends(require_student)):
    """공유를 끊는다. 이미 퍼진 링크도 즉시 안 열린다."""
    p = get_own_portfolio(db, user, portfolio_id)
    p.visibility = "private"
    p.share_token = None
    db.commit()
    return {"ok": True}


@app.get("/api/portfolio-share/{token}")
def view_shared_portfolio(token: str, db: Session = Depends(get_db)):
    """로그인 없이 여는 보기 전용 화면. 수정 API는 전부 소유자 검사를
    하므로 이 경로로는 애초에 닿지 않는다."""
    p = db.query(Portfolio).filter(Portfolio.share_token == token).first()
    if not p or p.visibility != "shared":
        raise HTTPException(status_code=404, detail="공유되지 않은 포트폴리오입니다.")
    pages = (db.query(PortfolioPage).filter(PortfolioPage.portfolio_id == p.id)
            .order_by(PortfolioPage.sort_order).all())
    blocks_by_page = {}
    if pages:
        all_blocks = (db.query(PortfolioBlock)
                     .filter(PortfolioBlock.page_id.in_([pg.id for pg in pages]))
                     .order_by(PortfolioBlock.sort_order).all())
        for b in all_blocks:
            blocks_by_page.setdefault(b.page_id, []).append(b)
    student = db.get(User, p.student_id)
    out = portfolio_out(p)
    out["student_name"] = student.name if student else ""
    out["pages"] = [page_out(pg, blocks_by_page.get(pg.id, [])) for pg in pages]
    return out


# ── 페이지 ──────────────────────────────────────────────────

@app.post("/api/portfolios/{portfolio_id}/pages")
def create_page(portfolio_id: int, payload: PortfolioPageIn, db: Session = Depends(get_db),
                user: User = Depends(require_student)):
    p = get_own_portfolio(db, user, portfolio_id)
    last = (db.query(func.max(PortfolioPage.sort_order))
           .filter(PortfolioPage.portfolio_id == p.id).scalar())
    pg = PortfolioPage(portfolio_id=p.id, title=payload.title[:120],
                       sort_order=(last + 1) if last is not None else 0)
    db.add(pg)
    db.commit()
    return page_out(pg, [])


@app.put("/api/portfolio-pages/{page_id}")
def update_page(page_id: int, payload: PortfolioPageIn, db: Session = Depends(get_db),
                user: User = Depends(require_student)):
    pg = get_own_page(db, user, page_id)
    pg.title = payload.title[:120]
    db.commit()
    return page_out(pg)


@app.delete("/api/portfolio-pages/{page_id}")
def delete_page(page_id: int, db: Session = Depends(get_db), user: User = Depends(require_student)):
    pg = get_own_page(db, user, page_id)
    db.query(PortfolioBlock).filter(PortfolioBlock.page_id == pg.id).delete(synchronize_session=False)
    db.delete(pg)
    db.commit()
    return {"ok": True}


@app.post("/api/portfolio-pages/{page_id}/duplicate")
def duplicate_page(page_id: int, db: Session = Depends(get_db), user: User = Depends(require_student)):
    pg = get_own_page(db, user, page_id)
    last = (db.query(func.max(PortfolioPage.sort_order))
           .filter(PortfolioPage.portfolio_id == pg.portfolio_id).scalar())
    new_page = PortfolioPage(portfolio_id=pg.portfolio_id, title=f"{pg.title} 사본"[:120],
                             sort_order=(last + 1) if last is not None else 0)
    db.add(new_page)
    db.commit()
    db.refresh(new_page)
    blocks = (db.query(PortfolioBlock).filter(PortfolioBlock.page_id == pg.id)
             .order_by(PortfolioBlock.sort_order).all())
    for b in blocks:
        db.add(PortfolioBlock(page_id=new_page.id, block_type=b.block_type,
                              sort_order=b.sort_order, content_json=b.content_json,
                              style_json=b.style_json))
    db.commit()
    return page_out(new_page, db.query(PortfolioBlock)
                    .filter(PortfolioBlock.page_id == new_page.id).all())


@app.post("/api/portfolio-pages/{page_id}/move")
def move_page(page_id: int, payload: MoveIn, db: Session = Depends(get_db),
             user: User = Depends(require_student)):
    pg = get_own_page(db, user, page_id)
    rows = (db.query(PortfolioPage).filter(PortfolioPage.portfolio_id == pg.portfolio_id)
           .order_by(PortfolioPage.sort_order).all())
    idx = next((i for i, r in enumerate(rows) if r.id == pg.id), None)
    if idx is None:
        return {"ok": True}
    swap = idx - 1 if payload.direction == "up" else idx + 1
    if 0 <= swap < len(rows):
        rows[idx], rows[swap] = rows[swap], rows[idx]
        _reorder(db, rows, pg)
    return {"ok": True}


# ── 블록 ────────────────────────────────────────────────────

@app.post("/api/portfolio-pages/{page_id}/blocks")
def create_block(page_id: int, payload: PortfolioBlockIn, db: Session = Depends(get_db),
                 user: User = Depends(require_student)):
    pg = get_own_page(db, user, page_id)
    if payload.block_type not in portfolio.ALLOWED_BLOCK_TYPES:
        raise HTTPException(status_code=400, detail="지원하지 않는 블록 종류입니다.")
    last = (db.query(func.max(PortfolioBlock.sort_order))
           .filter(PortfolioBlock.page_id == pg.id).scalar())
    b = PortfolioBlock(page_id=pg.id, block_type=payload.block_type,
                       sort_order=(last + 1) if last is not None else 0,
                       content_json=json.dumps(payload.content, ensure_ascii=False),
                       style_json=json.dumps(payload.style, ensure_ascii=False))
    db.add(b)
    db.commit()
    return block_out(b)


@app.put("/api/portfolio-blocks/{block_id}")
def update_block(block_id: int, payload: PortfolioBlockIn, db: Session = Depends(get_db),
                 user: User = Depends(require_student)):
    b = get_own_block(db, user, block_id)
    if payload.block_type not in portfolio.ALLOWED_BLOCK_TYPES:
        raise HTTPException(status_code=400, detail="지원하지 않는 블록 종류입니다.")
    b.block_type = payload.block_type
    b.content_json = json.dumps(payload.content, ensure_ascii=False)
    b.style_json = json.dumps(payload.style, ensure_ascii=False)
    db.commit()
    return block_out(b)


@app.delete("/api/portfolio-blocks/{block_id}")
def delete_block(block_id: int, db: Session = Depends(get_db), user: User = Depends(require_student)):
    b = get_own_block(db, user, block_id)
    db.delete(b)
    db.commit()
    return {"ok": True}


@app.post("/api/portfolio-blocks/{block_id}/duplicate")
def duplicate_block(block_id: int, db: Session = Depends(get_db), user: User = Depends(require_student)):
    b = get_own_block(db, user, block_id)
    last = (db.query(func.max(PortfolioBlock.sort_order))
           .filter(PortfolioBlock.page_id == b.page_id).scalar())
    copy = PortfolioBlock(page_id=b.page_id, block_type=b.block_type,
                          sort_order=(last + 1) if last is not None else 0,
                          content_json=b.content_json, style_json=b.style_json)
    db.add(copy)
    db.commit()
    return block_out(copy)


@app.post("/api/portfolio-blocks/{block_id}/move")
def move_block(block_id: int, payload: MoveIn, db: Session = Depends(get_db),
              user: User = Depends(require_student)):
    b = get_own_block(db, user, block_id)
    rows = (db.query(PortfolioBlock).filter(PortfolioBlock.page_id == b.page_id)
           .order_by(PortfolioBlock.sort_order).all())
    idx = next((i for i, r in enumerate(rows) if r.id == b.id), None)
    if idx is None:
        return {"ok": True}
    swap = idx - 1 if payload.direction == "up" else idx + 1
    if 0 <= swap < len(rows):
        rows[idx], rows[swap] = rows[swap], rows[idx]
        _reorder(db, rows, b)
    return {"ok": True}


# ── 사진 ────────────────────────────────────────────────────

def image_out(img: PortfolioImage) -> dict:
    return {"id": img.id, "portfolio_id": img.portfolio_id, "page_id": img.page_id,
           "block_id": img.block_id, "title": img.title, "caption": img.caption,
           "sort_order": img.sort_order, "width": img.width, "height": img.height,
           "url": f"/api/portfolio-images/{img.id}",
           "thumbnail_url": f"/api/portfolio-images/{img.id}?variant=thumbnail",
           "created_at": img.created_at}


@app.post("/api/portfolio-images")
async def upload_portfolio_image(
    portfolio_id: int = Form(...),
    page_id: Optional[int] = Form(None),
    title: str = Form(""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db), user: User = Depends(require_student),
):
    get_own_portfolio(db, user, portfolio_id)
    if page_id is not None:
        get_own_page(db, user, page_id)
    if file.content_type not in image_store.ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="사진 파일만 올릴 수 있습니다(jpg/png/webp/gif).")
    data = await file.read()
    try:
        storage_key, web_key, thumb_key, w, h = image_store.save_image(user.id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    last = (db.query(func.max(PortfolioImage.sort_order))
           .filter(PortfolioImage.portfolio_id == portfolio_id).scalar())
    img = PortfolioImage(student_id=user.id, portfolio_id=portfolio_id, page_id=page_id,
                         storage_key=storage_key, web_key=web_key, thumbnail_key=thumb_key,
                         title=title[:120], width=w, height=h,
                         sort_order=(last + 1) if last is not None else 0)
    db.add(img)
    db.commit()
    return image_out(img)


@app.get("/api/portfolio-images/{image_id}")
def get_portfolio_image(image_id: int, variant: str = Query("web", pattern="^(original|web|thumbnail)$"),
                        user: Optional[User] = Depends(get_current_user_optional),
                        db: Session = Depends(get_db)):
    """로그인 없이도 열 수 있다 — 단, 그 사진이 걸린 포트폴리오가 공유
    상태일 때만이다. <img src> 태그는 Authorization 헤더를 붙일 수 없으므로,
    화면에서 사진을 보여줄 때는 fetch로 헤더를 붙여 받은 뒤 화면에 꽂는다
    (api.loadPortfolioImageUrl). 공유 화면은 애초에 로그인 없이 여는
    화면이라 헤더 없는 요청이 온다 — 그래서 로그인을 강제하지 않는다."""
    img = db.get(PortfolioImage, image_id)
    if not img:
        raise HTTPException(status_code=404, detail="사진을 찾을 수 없습니다.")

    if not user or img.student_id != user.id:
        p = db.get(Portfolio, img.portfolio_id) if img.portfolio_id else None
        if not p or p.visibility != "shared":
            raise HTTPException(status_code=404, detail="사진을 찾을 수 없습니다.")
    key = {"original": img.storage_key, "web": img.web_key or img.storage_key,
          "thumbnail": img.thumbnail_key or img.storage_key}[variant]
    try:
        data = image_store.read_variant(key)
    except Exception as exc:
        print(f"[포트폴리오 사진] 읽기 실패(id={image_id}): {exc!r}", flush=True)
        data = None
    if data is None:
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")
    return Response(content=data, media_type="image/jpeg")


@app.put("/api/portfolio-images/{image_id}")
def update_portfolio_image(image_id: int, payload: dict, db: Session = Depends(get_db),
                           user: User = Depends(require_student)):
    img = db.get(PortfolioImage, image_id)
    if not img or img.student_id != user.id:
        raise HTTPException(status_code=404, detail="사진을 찾을 수 없습니다.")
    if "title" in payload:
        img.title = str(payload["title"] or "")[:120]
    if "caption" in payload:
        img.caption = str(payload["caption"] or "")[:500]
    if "page_id" in payload:
        pid = payload["page_id"]
        if pid is not None:
            get_own_page(db, user, int(pid))
        img.page_id = pid
    db.commit()
    return image_out(img)


@app.delete("/api/portfolio-images/{image_id}")
def delete_portfolio_image(image_id: int, db: Session = Depends(get_db),
                           user: User = Depends(require_student)):
    img = db.get(PortfolioImage, image_id)
    if not img or img.student_id != user.id:
        raise HTTPException(status_code=404, detail="사진을 찾을 수 없습니다.")
    image_store.delete_image(img.storage_key, img.web_key, img.thumbnail_key)
    db.delete(img)
    db.commit()
    return {"ok": True}


@app.post("/api/portfolio-images/{image_id}/caption")
def request_image_caption(image_id: int, db: Session = Depends(get_db),
                          user: User = Depends(require_subscription)):
    """사용자가 '사진 설명 생성'을 직접 눌렀을 때만 불린다. 업로드했다고
    자동으로 불리지 않는다(main.py 어디에도 업로드 직후 이 함수를 부르는
    코드가 없다 — 반드시 이 엔드포인트를 따로 호출해야 한다)."""
    img = db.get(PortfolioImage, image_id)
    if not img or img.student_id != user.id:
        raise HTTPException(status_code=404, detail="사진을 찾을 수 없습니다.")
    require_ai(db, user)
    job = ai_jobs.enqueue(db, user.id, "image_caption", {"image_id": image_id})
    write_audit(db, None, user, action="ai.image_caption.request",
               target_type="portfolio_image", target_id=image_id)
    return {"job_id": job.id}


# ── 경험 ────────────────────────────────────────────────────

def experience_out(e: Experience) -> dict:
    try:
        content = json.loads(e.content_json or "{}")
    except (ValueError, TypeError):
        content = {}
    return {"id": e.id, "title": e.title, "type": e.type, "summary": e.summary,
           **content, "created_at": e.created_at, "updated_at": e.updated_at}


@app.get("/api/experiences")
def list_experiences(db: Session = Depends(get_db), user: User = Depends(require_student)):
    rows = (db.query(Experience).filter(Experience.student_id == user.id)
           .order_by(Experience.updated_at.desc()).all())
    return [experience_out(e) for e in rows]


@app.post("/api/experiences")
def create_experience(payload: ExperienceIn, db: Session = Depends(get_db),
                      user: User = Depends(require_student)):
    content = {k: getattr(payload, k) for k in
              ("situation", "problem", "action", "result", "lesson")}
    e = Experience(student_id=user.id, title=payload.title[:120], type=payload.type[:30],
                   content_json=json.dumps(content, ensure_ascii=False))
    db.add(e)
    db.commit()
    return experience_out(e)


@app.put("/api/experiences/{experience_id}")
def update_experience(experience_id: int, payload: ExperienceIn, db: Session = Depends(get_db),
                      user: User = Depends(require_student)):
    e = db.get(Experience, experience_id)
    if not e or e.student_id != user.id:
        raise HTTPException(status_code=404, detail="경험을 찾을 수 없습니다.")
    content = {k: getattr(payload, k) for k in
              ("situation", "problem", "action", "result", "lesson")}
    e.title = payload.title[:120]
    e.type = payload.type[:30]
    e.content_json = json.dumps(content, ensure_ascii=False)
    db.commit()
    return experience_out(e)


@app.delete("/api/experiences/{experience_id}")
def delete_experience(experience_id: int, db: Session = Depends(get_db),
                      user: User = Depends(require_student)):
    e = db.get(Experience, experience_id)
    if not e or e.student_id != user.id:
        raise HTTPException(status_code=404, detail="경험을 찾을 수 없습니다.")
    db.query(ExperienceSource).filter(ExperienceSource.experience_id == e.id).delete(
        synchronize_session=False)
    db.delete(e)
    db.commit()
    return {"ok": True}


@app.get("/api/experiences/{experience_id}/sources")
def experience_sources(experience_id: int, db: Session = Depends(get_db),
                       user: User = Depends(require_student)):
    """'관련 기록 보기'. 이 경험이 어느 일지에서 나왔는지 원문과 함께 준다."""
    e = db.get(Experience, experience_id)
    if not e or e.student_id != user.id:
        raise HTTPException(status_code=404, detail="경험을 찾을 수 없습니다.")
    rows = db.query(ExperienceSource).filter(ExperienceSource.experience_id == e.id).all()
    out = []
    for s in rows:
        je = db.get(JournalEntry, s.journal_id)
        if je and je.user_id == user.id:
            out.append({"journal_id": je.id, "entry_date": je.entry_date,
                       "title": je.title, "kind": je.kind})
    return out


@app.post("/api/experiences/extract")
def request_experience_extract(payload: ExperienceExtractIn, db: Session = Depends(get_db),
                               user: User = Depends(require_subscription)):
    je = db.get(JournalEntry, payload.journal_id)
    if not je or je.user_id != user.id:
        raise HTTPException(status_code=404, detail="일지를 찾을 수 없습니다.")
    require_ai(db, user)
    job = ai_jobs.enqueue(db, user.id, "experience_extract",
                          {"journal_id": payload.journal_id},
                          dedup_key=f"extract:{payload.journal_id}")
    write_audit(db, None, user, action="ai.experience_extract.request",
               target_type="journal", target_id=payload.journal_id)
    return {"job_id": job.id}


# ── 테마 추천 · 포트폴리오 생성 · 첨삭 ──────────────────────

@app.post("/api/portfolio-theme-recommendations")
def request_theme_recommend(db: Session = Depends(get_db), user: User = Depends(require_subscription)):
    require_ai(db, user)
    job = ai_jobs.enqueue(db, user.id, "theme_recommend", {},
                          dedup_key="theme_recommend")
    write_audit(db, None, user, action="ai.theme_recommend.request")
    return {"job_id": job.id}


@app.get("/api/portfolio-theme-recommendations")
def cached_theme_recommendations(db: Session = Depends(get_db), user: User = Depends(require_student)):
    """마지막으로 만든 추천 결과. 최근 30분 안에 만든 것만 유효하다고 본다
    — 그 사이 새 일지를 쓸 수 있어 오래된 추천은 낡은 것일 수 있다."""
    cutoff = datetime.utcnow() - timedelta(minutes=30)
    rows = (db.query(PortfolioThemeRecommendation)
           .filter(PortfolioThemeRecommendation.student_id == user.id,
                   PortfolioThemeRecommendation.created_at >= cutoff)
           .order_by(PortfolioThemeRecommendation.score.desc()).all())
    return [{"theme_type": r.theme_type, "title": r.title, "reason": r.reason,
            "source_count": r.source_count} for r in rows]


@app.post("/api/portfolios/generate")
def request_portfolio_generate(payload: PortfolioGenerateIn, db: Session = Depends(get_db),
                               user: User = Depends(require_subscription)):
    if payload.theme_type not in portfolio.THEME_TYPES:
        raise HTTPException(status_code=400, detail="올바르지 않은 테마입니다.")
    require_ai(db, user)
    # 학생이 후보 중 포함/제외를 고른 뒤 넘긴 id만 쓴다. 넘기지 않으면
    # 서버가 다시 골라 준다(테마 키워드로 1차 필터링).
    job = ai_jobs.enqueue(db, user.id, "portfolio_generate", {
        "theme_type": payload.theme_type, "purpose": payload.purpose,
        "journal_ids": payload.journal_ids,
    })
    write_audit(db, None, user, action="ai.portfolio_generate.request",
               detail=payload.theme_type)
    return {"job_id": job.id}


@app.post("/api/portfolio-text/proofread")
def request_proofread(payload: ProofreadIn, db: Session = Depends(get_db),
                      user: User = Depends(require_subscription)):
    require_ai(db, user)
    job = ai_jobs.enqueue(db, user.id, "proofread",
                          {"text": payload.text, "action": payload.action})
    return {"job_id": job.id}


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


@app.get("/api/teacher/observations/summary")
def teacher_observations_summary(scope: str = Query("mine", pattern="^(mine|all)$"),
                                 db: Session = Depends(get_db),
                                 user: User = Depends(require_journal_viewer)):
    """'학급 전체 보기'용 — 학생별 기록 수·최근 날짜.

    반드시 이 교사 본인이 쓴 기록만 센다. 다른 교사가 그 학생에게 몇 건을
    썼는지는 여기 절대 안 섞는다. /api/teacher/observations/{id} 보다 앞에
    등록해야 한다 — 안 그러면 'summary'가 id 자리로 잘못 물린다(경로
    등록 순서로 맞춰 매칭하는 FastAPI 특성 때문에 실제로 겪은 문제다).
    """
    if user.role != Role.teacher:
        raise HTTPException(status_code=403, detail="교사 계정만 볼 수 있습니다.")
    ids = viewable_students(db, user, None, scope)
    if not ids:
        return []
    rows = (db.query(TeacherObservation.student_id, func.count(TeacherObservation.id),
                     func.max(TeacherObservation.observed_at))
           .filter(TeacherObservation.teacher_id == user.id,
                   TeacherObservation.student_id.in_(ids))
           .group_by(TeacherObservation.student_id).all())
    counts = {sid: (cnt, last) for sid, cnt, last in rows}
    students = db.query(User).filter(User.id.in_(ids)).order_by(User.name).all()
    return [{
        "student_id": s.id, "name": s.name, "class_name": s.class_name or "",
        "count": counts.get(s.id, (0, None))[0],
        "last_observed_at": counts.get(s.id, (0, None))[1],
    } for s in students]


@app.get("/api/teacher/observations")
def list_teacher_observations(
    student_id: int = Query(...), order: str = Query("desc", pattern="^(asc|desc)$"),
    subject_id: Optional[int] = Query(None, description="이 과목 기록만"),
    q: str = Query("", description="날짜·과목·내용 키워드로 좁히기"),
    db: Session = Depends(get_db), user: User = Depends(require_journal_viewer),
):
    """작성한 교사 본인의 기록만, 그 학생에 대한 것만 준다."""
    if user.role != Role.teacher:
        raise HTTPException(status_code=403, detail="교사 계정만 볼 수 있습니다.")
    student = db.get(User, student_id)
    if not student or student.id not in viewable_students(db, user, None, "mine"):
        raise HTTPException(status_code=403, detail="볼 수 없는 학생입니다.")
    rows_q = db.query(TeacherObservation).filter(
        TeacherObservation.teacher_id == user.id,
        TeacherObservation.student_id == student_id)
    if subject_id is not None:
        rows_q = rows_q.filter(TeacherObservation.subject_id == subject_id)
    col = TeacherObservation.observed_at
    rows_q = rows_q.order_by(col.asc() if order == "asc" else col.desc())
    rows = rows_q.all()
    if q.strip():
        term = q.strip().lower()
        rows = [n for n in rows if term in (n.content or "").lower()
               or term in (n.title or "").lower()
               or term in str(n.observed_at)
               or (n.subject and term in n.subject.name.lower())]
    return [observation_out(n) for n in rows]


@app.get("/api/teacher/observations/{observation_id}")
def get_teacher_observation(observation_id: int, db: Session = Depends(get_db),
                            user: User = Depends(require_journal_viewer)):
    n = _own_observation_or_403(db, user, observation_id)
    return observation_out(n)


@app.post("/api/teacher/observations")
def create_teacher_observation(payload: TeacherObservationIn, request: Request,
                               db: Session = Depends(get_db),
                               user: User = Depends(require_journal_viewer)):
    if user.role != Role.teacher:
        raise HTTPException(status_code=403, detail="교사 계정만 쓸 수 있습니다.")
    student = db.get(User, payload.student_id)
    if not student or student.id not in viewable_students(db, user, None, "mine"):
        write_audit(db, request, user, action="teacher_observation.denied",
                   target_type="student", target_id=payload.student_id)
        raise HTTPException(status_code=403, detail="볼 수 없는 학생입니다.")
    _require_valid_observation_subject(db, user, payload.subject_id)
    if payload.journal_id is not None:
        je = db.get(JournalEntry, payload.journal_id)
        if not je or je.user_id != payload.student_id:
            raise HTTPException(status_code=400, detail="일지를 찾을 수 없습니다.")
    n = TeacherObservation(teacher_id=user.id, student_id=payload.student_id,
                           observed_at=payload.observed_at or date.today(),
                           title=payload.title, journal_id=payload.journal_id,
                           subject_id=payload.subject_id, content=payload.content)
    db.add(n)
    db.commit()
    write_audit(db, request, user, action="teacher_observation.create",
               target_type="student", target_id=payload.student_id)
    return observation_out(n)


@app.put("/api/teacher/observations/{observation_id}")
def update_teacher_observation(observation_id: int, payload: TeacherObservationPatchIn,
                               request: Request, db: Session = Depends(get_db),
                               user: User = Depends(require_journal_viewer)):
    n = _own_observation_or_403(db, user, observation_id)
    if payload.journal_id is not None:
        je = db.get(JournalEntry, payload.journal_id)
        if not je or je.user_id != n.student_id:
            raise HTTPException(status_code=400, detail="일지를 찾을 수 없습니다.")
    if payload.observed_at is not None:
        n.observed_at = payload.observed_at
    if payload.title is not None:
        n.title = payload.title
    if payload.journal_id is not None:
        n.journal_id = payload.journal_id
    if payload.subject_id is not None:
        _require_valid_observation_subject(db, user, payload.subject_id)
        n.subject_id = payload.subject_id
    n.content = payload.content
    db.commit()
    write_audit(db, request, user, action="teacher_observation.update",
               target_type="teacher_observation", target_id=n.id)
    return observation_out(n)


@app.delete("/api/teacher/observations/{observation_id}")
def delete_teacher_observation(observation_id: int, request: Request, db: Session = Depends(get_db),
                               user: User = Depends(require_journal_viewer)):
    n = _own_observation_or_403(db, user, observation_id)
    student_id = n.student_id
    db.delete(n)
    db.commit()
    write_audit(db, request, user, action="teacher_observation.delete",
               target_type="student", target_id=student_id)
    return {"ok": True}


@app.get("/api/teacher/students/{student_id}/observations")
def list_student_observations_alias(student_id: int, order: str = Query("desc", pattern="^(asc|desc)$"),
                                    subject_id: Optional[int] = Query(None),
                                    q: str = Query(""), db: Session = Depends(get_db),
                                    user: User = Depends(require_journal_viewer)):
    """/api/teacher/observations?student_id= 와 완전히 같다 — 학생 하나를 축으로
    부르고 싶을 때 쓰기 편하도록 경로만 다르게 열어 둔 별칭이다."""
    return list_teacher_observations(student_id=student_id, order=order, subject_id=subject_id,
                                     q=q, db=db, user=user)


# ── 교사 개인 문구 템플릿 ────────────────────────────────────
# "자주 쓰는 표현"을 눌러 바로 넣는 초안일 뿐이다. AI가 학생 행동을 지어
# 내는 것이 아니라, 교사가 미리 등록해 둔 정해진 문구를 다시 꺼내 쓰는
# 것뿐이라 AI 동의·이용권과 무관하게 아무 때나 쓸 수 있다.

def template_out(t: TeacherObservationTemplate) -> dict:
    return {"id": t.id, "title": t.title, "content": t.content}


@app.get("/api/teacher/observation-templates")
def list_observation_templates(db: Session = Depends(get_db),
                               user: User = Depends(require_journal_viewer)):
    if user.role != Role.teacher:
        raise HTTPException(status_code=403, detail="교사 계정만 쓸 수 있습니다.")
    rows = (db.query(TeacherObservationTemplate)
           .filter(TeacherObservationTemplate.teacher_id == user.id)
           .order_by(TeacherObservationTemplate.created_at).all())
    return [template_out(t) for t in rows]


@app.post("/api/teacher/observation-templates")
def create_observation_template(payload: ObservationTemplateIn, db: Session = Depends(get_db),
                                user: User = Depends(require_journal_viewer)):
    if user.role != Role.teacher:
        raise HTTPException(status_code=403, detail="교사 계정만 쓸 수 있습니다.")
    t = TeacherObservationTemplate(teacher_id=user.id, title=payload.title, content=payload.content)
    db.add(t)
    db.commit()
    return template_out(t)


@app.delete("/api/teacher/observation-templates/{template_id}")
def delete_observation_template(template_id: int, db: Session = Depends(get_db),
                                user: User = Depends(require_journal_viewer)):
    t = db.get(TeacherObservationTemplate, template_id)
    if not t or t.teacher_id != user.id:
        raise HTTPException(status_code=404, detail="문구를 찾을 수 없습니다.")
    db.delete(t)
    db.commit()
    return {"ok": True}


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

    **기록이 없으면 동의한 것으로 본다.** 가입할 때 이용약관·개인정보에
    동의하며 이 내용까지 함께 안내하므로, 자기소개서를 쓰려는 순간 벽을
    한 번 더 세우지 않는다.

    다만 **거둔 기록은 끝까지 존중한다** — 한 번 거둔 사람이 다음에 들어올
    때 다시 동의 상태가 되어 있으면 그건 동의가 아니다. 그래서 "기록 없음"과
    "거뒀음"을 반드시 구분한다.

    방침이 바뀌면 예전 동의는 인정하지 않는다. 무엇에 동의했는지가
    달라졌기 때문이다.
    """
    c = ai_consent_of(db, user)
    if c is None:
        return True
    return bool(c.agreed and c.policy_date == AI_POLICY_DATE)


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


@app.get("/api/students/{student_id}/ai-records")
def list_ai_records(student_id: int, type: Optional[str] = Query(None),
                    db: Session = Depends(get_db),
                    user: User = Depends(require_journal_viewer)):
    student = db.get(User, student_id)
    if not student or student.role != Role.student:
        raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다.")
    scope = "mine" if user.role == Role.teacher else "all"
    if student.id not in viewable_students(db, user, None, scope):
        raise HTTPException(status_code=403, detail="볼 수 없는 학생입니다.")

    q = db.query(StudentRecordAiDraft).filter(
        StudentRecordAiDraft.student_id == student_id)
    if type:
        q = q.filter(StudentRecordAiDraft.type == type)
    if user.role == Role.teacher:
        # 담임이라도 담당하지 않는 과목의 세특은 못 본다 — 과목 기록이
        # 섞이면 안 되기 때문이다. 행동특성은 담임 확인을 이미 거쳤다.
        allowed = teacher_subject_ids(db, user)
        q = q.filter(or_(
            StudentRecordAiDraft.type != "subject_special_note",
            StudentRecordAiDraft.subject_id.in_(list(allowed) or [-1]),
        ))
    rows = q.order_by(StudentRecordAiDraft.created_at.desc()).all()
    return [ai_draft_out(d) for d in rows]


@app.post("/api/students/{student_id}/subjects/{subject_id}/ai-special-note")
def request_subject_note(student_id: int, subject_id: int, request: Request,
                         db: Session = Depends(get_db),
                         user: User = Depends(require_roles(Role.teacher, Role.admin))):
    """과목 세특 초안을 만들어 달라고 맡긴다.

    이 과목을 담당하지 않으면 403 이다. 넘길 일지도 여기서 이 과목·이
    학생·제출된 것만 서버가 직접 골라 정한다 — 프론트가 무엇을 보내든
    믿지 않는다.
    """
    student = db.get(User, student_id)
    if not student or student.role != Role.student:
        raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다.")
    assert_can_view_lesson(db, user, student, subject_id)
    require_ai_for_student(db, student)

    ids = _lesson_journal_ids(db, student_id, subject_id)
    if not ids:
        raise HTTPException(status_code=400, detail="이 과목으로 제출된 수업일지가 없습니다.")

    job = ai_jobs.enqueue(db, user.id, "subject_note", {
        "student_id": student_id, "subject_id": subject_id, "journal_ids": ids,
    })
    write_audit(db, request, user, action="ai.subject_note.request",
               target_type="user", target_id=student_id,
               detail=f"subject={subject_id} journals={len(ids)}")
    return {"status": "queued", "job_id": job.id}


@app.post("/api/students/{student_id}/subjects/{subject_id}/ai-observation-note")
def request_observation_note(student_id: int, subject_id: int, request: Request,
                             db: Session = Depends(get_db),
                             user: User = Depends(require_roles(Role.teacher, Role.admin))):
    """이 교사가 이 학생·이 과목에 남긴 관찰 기록(누가기록)만 모아 세특
    초안을 만들어 달라고 맡긴다. 학생이 쓴 수업일지가 아니라 교사 본인이
    쓴 관찰 기록이 재료라는 점만 /ai-special-note 와 다르고, 권한 검사와
    저장 방식은 동일하다(같은 담당 과목 확인, 같은 StudentRecordAiDraft)."""
    student = db.get(User, student_id)
    if not student or student.role != Role.student:
        raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다.")
    assert_can_view_lesson(db, user, student, subject_id)
    require_ai_for_student(db, student)

    ids = _observation_ids(db, user.id, student_id, subject_id)
    if not ids:
        raise HTTPException(status_code=400, detail="이 과목으로 남긴 관찰 기록이 없습니다.")

    job = ai_jobs.enqueue(db, user.id, "observation_subject_note", {
        "student_id": student_id, "subject_id": subject_id, "observation_ids": ids,
    })
    write_audit(db, request, user, action="ai.observation_note.request",
               target_type="user", target_id=student_id,
               detail=f"subject={subject_id} observations={len(ids)}")
    return {"status": "queued", "job_id": job.id}


@app.post("/api/students/{student_id}/ai-behavioral-characteristics")
def request_behavior_note(student_id: int, request: Request,
                          db: Session = Depends(get_db),
                          user: User = Depends(require_roles(Role.teacher, Role.admin))):
    """행동특성 초안을 만들어 달라고 맡긴다. 담임이 아니면 403 이다."""
    student = db.get(User, student_id)
    if not student or student.role != Role.student:
        raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다.")
    assert_is_homeroom(db, user, student)
    require_ai_for_student(db, student)

    ids = _diary_journal_ids(db, student_id)
    if not ids:
        raise HTTPException(status_code=400, detail="제출된 학교생활일지가 없습니다.")

    job = ai_jobs.enqueue(db, user.id, "behavior_note", {
        "student_id": student_id, "journal_ids": ids,
    })
    write_audit(db, request, user, action="ai.behavior_note.request",
               target_type="user", target_id=student_id, detail=f"journals={len(ids)}")
    return {"status": "queued", "job_id": job.id}


@app.put("/api/ai-records/{draft_id}")
def update_ai_record(draft_id: int, payload: dict, request: Request,
                     db: Session = Depends(get_db),
                     user: User = Depends(require_roles(Role.teacher, Role.admin))):
    """교사가 초안을 직접 고친다. 확정 전까지는 몇 번이든 고칠 수 있다."""
    d = db.get(StudentRecordAiDraft, draft_id)
    if not d or (user.role != Role.admin and d.teacher_id != user.id):
        raise HTTPException(status_code=404, detail="초안을 찾을 수 없습니다.")
    content = str(payload.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="내용을 입력해주세요.")
    d.content = content
    if d.status == "draft":
        d.status = "reviewed"
    db.commit()
    write_audit(db, request, user, action="ai_record.edit",
               target_type="ai_record", target_id=d.id)
    return ai_draft_out(d)


@app.post("/api/ai-records/{draft_id}/confirm")
def confirm_ai_record(draft_id: int, request: Request, db: Session = Depends(get_db),
                      user: User = Depends(require_roles(Role.teacher, Role.admin))):
    """초안을 확정한다. 확정본은 다시 생성해도 지워지지 않는다."""
    d = db.get(StudentRecordAiDraft, draft_id)
    if not d or (user.role != Role.admin and d.teacher_id != user.id):
        raise HTTPException(status_code=404, detail="초안을 찾을 수 없습니다.")
    d.status = "confirmed"
    d.confirmed_at = datetime.utcnow()
    db.commit()
    write_audit(db, request, user, action="ai_record.confirm",
               target_type="ai_record", target_id=d.id)
    return ai_draft_out(d)


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


@app.post("/api/journals/{journal_id}/analyze")
def request_journal_analysis(journal_id: int, db: Session = Depends(get_db),
                             user: User = Depends(require_subscription)):
    """일지 하나를 AI 로 분석해 달라고 맡긴다. 바로 돌아온다.

    이미 분석해 둔 것이 있고 글이 바뀌지 않았으면 그것을 그대로 준다.
    같은 글을 다시 보내면 돈만 나간다.
    """
    require_ai(db, user)

    e = db.get(JournalEntry, journal_id)
    if not e or e.user_id != user.id:
        raise HTTPException(status_code=404, detail="일지를 찾을 수 없습니다.")

    content = journal_content(e)
    text = ai_service.journal_text(e, content)
    digest = ai_service.content_hash(text)

    cached = (db.query(JournalAnalysis)
              .filter(JournalAnalysis.journal_id == e.id,
                      JournalAnalysis.content_hash == digest).first())
    if cached:
        try:
            data = json.loads(cached.analysis_json or "{}")
        except (ValueError, TypeError):
            data = {}
        return {"status": "done", "cached": True,
                "result": {"ok": True, "original_content": text,
                           "cleaned_content": cached.cleaned_content, **data}}

    job = ai_jobs.enqueue(db, user.id, "analyze",
                          {"journal_id": e.id, "hash": digest})
    return {"status": "queued", "cached": False, "job_id": job.id}


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








































































# ── 문헌/참고자료 ─────────────────────────────────────────────

_HANGUL_RE = re.compile(r"[가-힣]")


























# ── 연구 데이터 ───────────────────────────────────────────────













# ── 데이터 분석 ───────────────────────────────────────────────



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










# ── 연구심사 ──────────────────────────────────────────────────









# ── 중간 리포트 ───────────────────────────────────────────────









# ── 최종 논문 / 연구 포트폴리오 ────────────────────────────────






















































































# ── 외부 교사 질문 ────────────────────────────────────────────
# 같은 학교 담임이 아니라, 낯선 학교의 교사와 이어지는 완전히 별도 경로다
# (§17을 학생→교사만이 아니라 교사→학생 쪽도 가려 양방향 익명으로 확장 —
# 아래 _external_question_out/_external_answer_out 이 그 가림을 담당한다).
# 기존 viewable_students/assert_is_homeroom 스코프는 여기서 전혀 안 쓴다.



























# ── 외부 교사 질문 — 교사 쪽 ───────────────────────────────────────

















# ── 교사: 담당 학급 연구 현황 ────────────────────────────────────



DISPLAY_STAGE_ORDER = [
    ("interest", "관심 탐색"), ("topic", "주제 선정"), ("question", "연구 질문"),
    ("plan", "연구 계획"), ("literature", "문헌 조사"), ("method", "연구 설계"),
    ("execution", "실행"), ("data", "데이터 수집"), ("analysis", "분석"),
    ("discussion", "논의"), ("final", "최종 산출물"),
]
_DISPLAY_STAGE_INDEX = {k: i for i, (k, _label) in enumerate(DISPLAY_STAGE_ORDER)}




















@app.post("/api/cover-letters/generate")
def request_essay(payload: dict, db: Session = Depends(get_db),
                  user: User = Depends(require_subscription)):
    """고른 경험으로 자소서 초안을 만들어 달라고 맡긴다."""
    require_ai(db, user)

    question = str(payload.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="자소서 항목을 골라주세요.")

    ids = payload.get("journal_ids") or []
    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=400, detail="쓸 경험을 골라주세요.")
    if len(ids) > 5:
        raise HTTPException(status_code=400, detail="경험(일지·연구)은 합쳐서 5개까지 고를 수 있습니다.")

    try:
        limit = int(payload.get("character_limit") or ai_service.DEFAULT_LIMIT)
    except (TypeError, ValueError):
        limit = ai_service.DEFAULT_LIMIT
    limit = min(max(limit, 200), 3000)

    job = ai_jobs.enqueue(db, user.id, "generate", {
        "question": question, "journal_ids": [int(i) for i in ids],
        "limit": limit,
    })
    return {"status": "queued", "job_id": job.id}


@app.post("/api/cover-letters/verify")
def request_verify(payload: dict, db: Session = Depends(get_db),
                   user: User = Depends(require_subscription)):
    """이미 쓴 글에 사실이 아닌 내용이 있는지 확인해 달라고 맡긴다."""
    require_ai(db, user)

    draft = str(payload.get("draft") or "").strip()
    if not draft:
        raise HTTPException(status_code=400, detail="확인할 글이 없습니다.")

    ids = payload.get("journal_ids") or []
    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=400, detail="근거가 될 경험을 골라주세요.")

    job = ai_jobs.enqueue(db, user.id, "verify", {
        "draft": draft, "journal_ids": [int(i) for i in ids],
    })
    return {"status": "queued", "job_id": job.id}


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
    exps = _load_experiences(db, user_id, payload.get("journal_ids") or [])
    if not exps:
        return {"ok": False, "error": "고른 경험을 찾을 수 없습니다."}
    return ai_service.generate_essay(
        str(payload.get("question") or ""), exps, user,
        limit=int(payload.get("limit") or ai_service.DEFAULT_LIMIT))


def _job_verify(db: Session, user_id: int, payload: dict) -> dict:
    user = db.get(User, user_id)
    if not user:
        return {"ok": False, "error": "이용자를 찾을 수 없습니다."}
    exps = _load_experiences(db, user_id, payload.get("journal_ids") or [])
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


def _job_theme_recommend(db: Session, user_id: int, payload: dict) -> dict:
    student = db.get(User, user_id)
    if not student:
        return {"ok": False, "error": "이용자를 찾을 수 없습니다."}

    entries = _all_journal_texts(db, user_id)
    dept_field = dept_fields.classify_one(student.department or "")
    result = ai_portfolio.recommend_themes(entries, dept_field, student)
    if not result.get("ok"):
        return result

    # 캐시에 남긴다 — 기록이 그대로면 다음에 GET으로 이걸 그대로 준다.
    db.query(PortfolioThemeRecommendation).filter(
        PortfolioThemeRecommendation.student_id == user_id).delete(synchronize_session=False)
    for i, r in enumerate(result["recommendations"]):
        db.add(PortfolioThemeRecommendation(
            student_id=user_id, theme_type=r["theme_type"], title=r["title"],
            reason=r["reason"], source_count=r["source_count"],
            score=100 - i,   # 순위를 그대로 점수로 — 정렬용일 뿐 학생에게 보이지 않는다
        ))
    db.commit()
    return result


def _job_portfolio_generate(db: Session, user_id: int, payload: dict) -> dict:
    student = db.get(User, user_id)
    if not student:
        return {"ok": False, "error": "이용자를 찾을 수 없습니다."}

    theme_type = str(payload.get("theme_type") or "custom")
    purpose = str(payload.get("purpose") or "free")
    journal_ids = payload.get("journal_ids") or []

    if journal_ids:
        # 학생이 후보 중 직접 고른 것 — id를 다시 하나하나 확인한다(본인 것만).
        records = []
        for jid in journal_ids[:20]:
            e = db.get(JournalEntry, int(jid))
            if e and e.user_id == user_id and e.sent_at:
                records.append({"journal_id": e.id,
                               "entry_date": e.entry_date.isoformat() if e.entry_date else "",
                               "text": ai_service.journal_text(e, journal_content(e))})
    else:
        # 안 골랐으면 서버가 테마 키워드로 다시 골라 준다.
        entries = _all_journal_texts(db, user_id)
        dept_field = dept_fields.classify_one(student.department or "")
        scored = portfolio.score_themes(entries, dept_field)
        theme_row = next((t for t in scored if t["theme_type"] == theme_type), None)
        if not theme_row:
            return {"ok": False, "error": "이 테마와 관련된 기록이 없습니다."}
        ids = {m["journal_id"] for m in theme_row["matches"]}
        records = [e | {"journal_id": e["id"]} for e in entries if e["id"] in ids]

    result = ai_portfolio.generate_portfolio(theme_type, purpose, records, student)
    if not result.get("ok"):
        return result

    p = Portfolio(student_id=user_id, title=result["title"], description=result["description"],
                 purpose=purpose, theme_type=theme_type if theme_type in portfolio.THEME_TYPES else "custom")
    db.add(p)
    db.commit()
    db.refresh(p)

    for i, page in enumerate(result["pages"]):
        pg = PortfolioPage(portfolio_id=p.id, title=page["title"], sort_order=i)
        db.add(pg)
        db.commit()
        db.refresh(pg)
        for j, blk in enumerate(page["blocks"]):
            db.add(PortfolioBlock(page_id=pg.id, block_type=blk["type"], sort_order=j,
                                  content_json=json.dumps({"text": blk["content"]}, ensure_ascii=False)))
        for jid in page["source_journal_ids"]:
            db.add(PortfolioSource(portfolio_id=p.id, page_id=pg.id, journal_id=jid,
                                   source_type="journal"))
    db.commit()

    result["portfolio_id"] = p.id
    return result


def _job_experience_extract(db: Session, user_id: int, payload: dict) -> dict:
    je = db.get(JournalEntry, int(payload.get("journal_id") or 0))
    student = db.get(User, user_id)
    if not je or je.user_id != user_id or not student:
        return {"ok": False, "error": "일지를 찾을 수 없습니다."}

    text = ai_service.journal_text(je, journal_content(je))
    result = ai_portfolio.extract_experience(text, student)
    if not result.get("ok"):
        return result

    content = {k: result[k] for k in ("situation", "problem", "action", "result", "lesson")}
    e = Experience(student_id=user_id, title=result.get("title", "")[:120],
                  type=result.get("type", "")[:30],
                  content_json=json.dumps(content, ensure_ascii=False))
    db.add(e)
    db.commit()
    db.refresh(e)
    db.add(ExperienceSource(experience_id=e.id, journal_id=je.id))
    db.commit()

    result["experience_id"] = e.id
    return result


def _job_proofread(db: Session, user_id: int, payload: dict) -> dict:
    student = db.get(User, user_id)
    if not student:
        return {"ok": False, "error": "이용자를 찾을 수 없습니다."}
    return ai_portfolio.proofread_text(str(payload.get("text") or ""),
                                       str(payload.get("action") or ""), student)


def _job_image_caption(db: Session, user_id: int, payload: dict) -> dict:
    img = db.get(PortfolioImage, int(payload.get("image_id") or 0))
    if not img or img.student_id != user_id:
        return {"ok": False, "error": "사진을 찾을 수 없습니다."}
    data = image_store.read_variant(img.web_key or img.storage_key)
    if data is None:
        return {"ok": False, "error": "사진 파일을 읽지 못했습니다."}
    result = ai_portfolio.caption_image(data)
    if result.get("ok"):
        img.caption = result["caption"]
        db.commit()
    return result








































ai_jobs.register("analyze", _job_analyze)
ai_jobs.register("generate", _job_generate)
ai_jobs.register("verify", _job_verify)
ai_jobs.register("subject_note", _job_subject_note)
ai_jobs.register("observation_subject_note", _job_observation_subject_note)
ai_jobs.register("behavior_note", _job_behavior_note)
ai_jobs.register("theme_recommend", _job_theme_recommend)
ai_jobs.register("portfolio_generate", _job_portfolio_generate)
ai_jobs.register("experience_extract", _job_experience_extract)
ai_jobs.register("proofread", _job_proofread)
ai_jobs.register("image_caption", _job_image_caption)


@app.on_event("startup")
def _start_ai_worker():
    """AI 작업 일꾼을 띄운다.

    키가 없으면 띄우지 않는다. 할 일이 생길 수 없으므로 실만 놀게 된다.
    """
    if llm.available():
        ai_jobs.start()
    else:
        print("[AI] 키가 없어 AI 기능을 쓰지 않습니다.", flush=True)


@app.post("/api/spellcheck")
def run_spellcheck(payload: SpellCheckIn):
    if payload.fields:
        return {"results": spellcheck.check_many(payload.fields),
                "rule_count": spellcheck.rule_count()}
    return {"results": {"text": spellcheck.check(payload.text or "")},
            "rule_count": spellcheck.rule_count()}


# ══════════════════════════════════════════════════════════
# 관리자
# ══════════════════════════════════════════════════════════
@app.get("/api/admin/stats")
def admin_stats(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    now = datetime.utcnow()
    month_ago = now - timedelta(days=30)
    return {
        "users": db.query(User).count(),
        "students": db.query(User).filter(User.role == Role.student).count(),
        "journals": db.query(JournalEntry).count(),
        "journals_30d": db.query(JournalEntry).filter(
            JournalEntry.created_at >= month_ago).count(),
        "submitted": db.query(JournalEntry).filter(
            JournalEntry.sent_at.isnot(None)).count(),
        "cover_letters": db.query(CoverLetter).count(),
        # 예전 개인 구독. 기간이 남은 동안만 세어진다.
        "subscribers": db.query(Subscription).filter(
            Subscription.expires_at > now).count(),
        # 학교가 산 좌석. 지금은 이쪽이 본 지표다.
        "seat_schools": db.query(SchoolSeat).filter(SchoolSeat.expires_at > now).count(),
        "seats_total": db.query(func.coalesce(func.sum(SchoolSeat.seats), 0)).filter(
            SchoolSeat.expires_at > now).scalar() or 0,
        "seats_used": db.query(func.count(SeatHolder.id)).scalar() or 0,
        "pending_seat_orders": db.query(SeatOrder).filter(
            SeatOrder.status == OrderStatus.pending).count(),
        "pending_orders": db.query(SubscriptionOrder).filter(
            SubscriptionOrder.status == OrderStatus.pending).count(),
        "revenue_30d": sum(
            o.amount for o in db.query(SubscriptionOrder).filter(
                SubscriptionOrder.status == OrderStatus.approved,
                SubscriptionOrder.paid_at >= month_ago).all()
        ),
    }


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


@app.post("/api/admin/match-deposits")
def match_deposits(payload: StatementIn, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(require_admin)):
    """붙여넣은 통장 내역을 입금 대기 주문과 맞춰본다.

    금액이 유일하게 맞는 건만 확실하다고 본다. 같은 금액이 여럿이면 이름으로
    좁혀보고, 그래도 애매하면 손대지 않고 미매칭함으로 보낸다. 안내한 계좌가
    아닌 곳으로 들어온 입금도 확인은 되지만 표시를 남긴다.
    """
    # 입금하는 쪽이 개인에서 학교로 바뀌었다. 대조 대상도 좌석 주문이다.
    pending = (db.query(SeatOrder)
               .filter(SeatOrder.status == OrderStatus.pending)
               .order_by(SeatOrder.created_at).all())
    if payload.deposits:
        lines = [{"amount": d.amount, "name": (d.name or "").strip(),
                  "line": d.line or f"{d.amount} {d.name}".strip(),
                  "bank_key": d.bank_key or payload.bank_key}
                 for d in payload.deposits if d.amount > 0]
    else:
        lines = parse_statement(payload.text)
        for ln in lines:
            ln["bank_key"] = payload.bank_key
    auto = bool(payload.auto_approve and auto_approve_enabled(db))

    used = set()
    matched, approved = [], []

    for ln in lines:
        same_amount = [o for o in pending if o.id not in used and o.amount == ln["amount"]]

        if not same_amount:
            record_unmatched(db, ln.get("bank_key") or payload.bank_key, ln,
                             "금액이 맞는 입금 대기 주문이 없습니다.")
            continue

        if len(same_amount) == 1:
            hit, why = same_amount[0], "금액 일치"
        else:
            by_name = [o for o in same_amount
                       if ln["name"] and (o.depositor_name or "").strip() == ln["name"]]
            if len(by_name) == 1:
                hit, why = by_name[0], "금액·입금자명 일치"
            else:
                record_unmatched(
                    db, ln.get("bank_key") or payload.bank_key, ln,
                    f"같은 금액의 주문이 {len(same_amount)}건이라 고를 수 없습니다.")
                continue

        used.add(hit.id)
        name_mismatch = bool(
            ln["name"] and (hit.depositor_name or "").strip()
            and ln["name"] != (hit.depositor_name or "").strip()
        )
        # 안내한 계좌가 아닌 곳으로 들어온 경우. 막을 일은 아니지만 알려준다.
        line_bank = ln.get("bank_key") or payload.bank_key
        other_bank = bool(line_bank and hit.bank_key and line_bank != hit.bank_key)

        row = {
            "order_id": hit.id,
            "user_email": hit.school_name or hit.requester_email or "",
            "amount": hit.amount, "months": hit.months,
            "seats": hit.seats,
            "deposit_code": hit.deposit_code,
            "depositor_name": hit.depositor_name or "",
            "line": ln["line"], "statement_name": ln["name"],
            "why": why, "name_mismatch": name_mismatch,
            "other_bank": other_bank,
        }

        # 자동 승인은 의심스러운 구석이 하나도 없을 때만 한다.
        if auto and why == "금액 일치" and not name_mismatch and not other_bank:
            # 입금이 확인됐다는 뜻이지, 인원까지 확인했다는 뜻은 아니다.
            # 인원은 사람이 봐야 하므로 '입금 확인'까지만 표시하고 멈춘다.
            hit.status = OrderStatus.paid
            hit.paid_at = datetime.utcnow()
            write_audit(db, request, user, action="seat.deposit_confirm",
                        target_type="seat_order", target_id=hit.id,
                        detail=f"{hit.amount}원 · 통장 대조 자동 확인")
            row["auto_approved"] = True
            approved.append(row)
        else:
            row["auto_approved"] = False
            matched.append(row)

    db.commit()

    return {
        "matched": matched,
        "approved": approved,
        "auto_enabled": auto_approve_enabled(db),
        "pending_total": len(pending),
        "still_pending": [
            {"order_id": o.id,
             "user_email": o.school_name or o.requester_email or "",
             "amount": o.amount, "seats": o.seats,
             "deposit_code": o.deposit_code, "depositor_name": o.depositor_name or "",
             "bank_key": o.bank_key or "", "due_at": o.due_at}
            for o in pending if o.id not in used
        ],
    }


@app.post("/api/admin/parse-statement")
async def parse_statement_file(
    file: UploadFile = File(...),
    password: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """은행에서 받은 거래내역 파일을 읽어 입금 내역만 보여준다.

    바로 대조하지 않는다. 열을 제대로 잡았는지 사람이 먼저 확인해야
    엉뚱한 승인을 막을 수 있다.
    """
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="파일이 너무 큽니다. 5MB 이하로 올려주세요.")
    try:
        result = statement.parse_file(data, file.filename or "", password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        print(f"[거래내역] 읽기 실패: {exc}", flush=True)
        raise HTTPException(status_code=400, detail="파일을 읽지 못했습니다.")

    return {
        "deposits": result["deposits"][:500],
        "withdrawals": result.get("withdrawals", [])[:500],
        "total": len(result["deposits"]),
        "withdrawal_total": len(result.get("withdrawals", [])),
        "skipped": result["skipped"],
        "header_row": result["header_row"],
        "columns": result["columns"],
        # 사람이 눈으로 확인하는 칸. 실제 대조는 위 deposits 를 그대로 쓴다.
        # 이름을 괄호로 감싸 두면 이 칸을 손으로 고친 뒤에도 이름과 금액이
        # 헷갈리지 않게 읽힌다.
        "text": "\n".join(
            (f"{d['when']} {d['amount']} ({d['name']})" if d["name"]
             else f"{d['when']} {d['amount']}").strip()
            for d in result["deposits"]
        ),
    }


@app.get("/api/admin/unmatched")
def list_unmatched(status: str = Query("open", pattern="^(open|linked|ignored|all)$"),
                   db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """미매칭함. 계좌를 가리지 않고 한곳에 모여 있다."""
    q = db.query(UnmatchedDeposit)
    if status != "all":
        q = q.filter(UnmatchedDeposit.status == status)
    rows = q.order_by(UnmatchedDeposit.created_at.desc()).limit(300).all()

    banks = {a["key"]: a for a in bank_accounts(db)}
    return [{
        "id": r.id, "bank_key": r.bank_key,
        "bank_label": banks.get(r.bank_key, {}).get("bank_name", "") or r.bank_key,
        "line": r.line, "amount": r.amount, "name": r.name,
        "reason": r.reason, "status": r.status,
        "linked_order_id": r.linked_order_id, "note": r.note,
        "created_at": r.created_at,
    } for r in rows]


@app.post("/api/admin/unmatched/rematch")
def rematch_unmatched(request: Request, auto_approve: bool = Query(False),
                      db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """미매칭함에 쌓인 것들을 지금 주문 목록과 다시 맞춰본다.

    처음 올렸을 때는 주문이 아직 없었거나, 같은 금액이 여럿이라 못 골랐을 수
    있다. 시간이 지나 상황이 달라지면 붙을 수 있으므로 다시 시도한다.
    붙은 것은 '연결됨'으로 바꾸고, 자동 승인을 허용했으면 승인까지 한다.
    """
    items = (db.query(UnmatchedDeposit)
             .filter(UnmatchedDeposit.status == "open")
             .order_by(UnmatchedDeposit.created_at).all())
    if not items:
        return {"linked": [], "still_open": 0, "checked": 0}

    pending = (db.query(SeatOrder)
               .filter(SeatOrder.status == OrderStatus.pending)
               .order_by(SeatOrder.created_at).all())
    auto = bool(auto_approve and auto_approve_enabled(db))

    used, linked = set(), []
    for it in items:
        same = [o for o in pending if o.id not in used and o.amount == it.amount]
        if not same:
            continue
        if len(same) == 1:
            hit = same[0]
        else:
            by_name = [o for o in same
                       if it.name and (o.depositor_name or "").strip() == it.name]
            if len(by_name) != 1:
                continue
            hit = by_name[0]

        used.add(hit.id)
        row = {"item_id": it.id, "order_id": hit.id, "amount": it.amount,
               "user_email": hit.school_name or hit.requester_email or "",
               "depositor_name": hit.depositor_name or "",
               "statement_name": it.name or "",
               "approved": False}

        if auto:
            # 승인까지 끝내야 '연결됨'이라 부를 수 있다.
            it.status = "linked"
            it.linked_order_id = hit.id
            it.resolved_at = datetime.utcnow()
            # 입금 확인까지만 한다. 인원 확인과 승인은 사람이 한다.
            hit.status = OrderStatus.paid
            hit.paid_at = datetime.utcnow()
            row["approved"] = True
            write_audit(db, request, user, action="seat.deposit_confirm",
                        target_type="seat_order", target_id=hit.id,
                        detail=f"{hit.amount}원 · 미매칭함 재시도")
        else:
            # 자동 승인이 꺼져 있으면 상태를 건드리지 않는다. 주문은 그대로
            # 대기 중인데 '연결됨'으로 바꿔 두면 처리가 끝난 줄 알게 된다.
            # 대신 '이 주문 같습니다'라고 알려만 주고 판단은 사람에게 맡긴다.
            it.reason = (f"{hit.school_name or hit.requester_email} 신청과 금액이 맞습니다. "
                         f"확인 후 연결해주세요.")[:120]

        linked.append(row)

    db.commit()
    still = db.query(func.count(UnmatchedDeposit.id)).filter(
        UnmatchedDeposit.status == "open").scalar() or 0
    return {"linked": linked, "still_open": still, "checked": len(items)}


class ResolveIn(BaseModel):
    action: str = Field(..., pattern="^(link|ignore|reopen)$")
    order_id: Optional[int] = None
    note: str = Field(default="", max_length=200)


@app.post("/api/admin/unmatched/{item_id}/resolve")
def resolve_unmatched(item_id: int, payload: ResolveIn, request: Request,
                      db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """미매칭 건을 주문에 붙이거나 치운다.

    붙이면 그 주문을 승인한다. 사람이 통장을 보고 판단한 결과이므로,
    금액이 달라도 승인은 하되 기록에 남긴다.
    """
    item = db.get(UnmatchedDeposit, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="내역을 찾을 수 없습니다.")

    if payload.action == "reopen":
        item.status = "open"
        item.linked_order_id = None
        item.resolved_at = None
        db.commit()
        return {"ok": True, "status": item.status}

    if payload.action == "ignore":
        item.status = "ignored"
        item.note = payload.note[:200]
        item.resolved_at = datetime.utcnow()
        db.commit()
        write_audit(db, request, user, action="deposit.ignore",
                    target_type="unmatched", target_id=item.id,
                    detail=f"{item.amount}원 {payload.note}".strip()[:300])
        return {"ok": True, "status": item.status}

    order = db.get(SeatOrder, payload.order_id) if payload.order_id else None
    if not order:
        raise HTTPException(status_code=404, detail="신청을 찾을 수 없습니다.")
    if order.status != OrderStatus.pending:
        raise HTTPException(status_code=400, detail="입금 대기 상태인 신청만 처리할 수 있습니다.")

    # 입금이 들어온 것을 확인해 주는 데까지다. 인원 확인과 승인은
    # 학교 이용권 화면에서 사람이 한다.
    order.status = OrderStatus.paid
    order.paid_at = datetime.utcnow()
    expires = None

    item.status = "linked"
    item.linked_order_id = order.id
    item.note = payload.note[:200]
    item.resolved_at = datetime.utcnow()
    db.commit()

    gap = "" if item.amount == order.amount else f" (입금 {item.amount}원 / 주문 {order.amount}원)"
    write_audit(db, request, user, action="deposit.link",
                target_type="order", target_id=order.id,
                detail=f"미매칭 건 수동 연결{gap} {payload.note}".strip()[:300])
    return {"ok": True, "status": "linked", "expires_at": expires}


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
        "toss_configured": toss.is_ready(),
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
def health(db: Session = Depends(get_db)):
    return {
        "ok": True,
        "udj_linked": udj.is_ready(),
        "payment": "toss" if use_toss(db) else "bank_transfer",
        "payment_method": payment_method(db),
        "toss_configured": toss.is_ready(),
        "bank_ready": bank_ready(db),
    }
