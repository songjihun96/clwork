"""UDJ 에 있던 일지·자기소개서·구독 자료를 기록해 DB 로 옮긴다.

    python -m app.migrate_from_udj --udj-db "postgresql://..." --dry-run
    python -m app.migrate_from_udj --udj-db "postgresql://..."

두 DB 가 분리되었으므로, 기존 자료를 한 번 복사해 와야 한다.
UDJ 쪽은 읽기만 한다. 옮긴 뒤 UDJ 에서 지울지는 사람이 판단한다.

여러 번 돌려도 안전하다. 이미 옮긴 것은 건너뛴다.
"""

import argparse
import json
import sys
from datetime import date, datetime

from sqlalchemy import create_engine, text

from .database import Base, SessionLocal, engine
from .models import (
    CoverLetter, JournalEntry, OrderStatus, Role, SchoolSubject,
    Subscription, SubscriptionOrder, User,
)


def connect_udj(url: str):
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return create_engine(url, pool_pre_ping=True)


def as_date(v):
    """SQLite 는 날짜를 문자열로 돌려준다. 어떤 형식이 와도 date 로 맞춘다."""
    if v is None or isinstance(v, date):
        return v
    if isinstance(v, datetime):
        return v.date()
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def as_dt(v):
    """마찬가지로 datetime 으로 맞춘다."""
    if v is None or isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    text_value = str(v).replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text_value[:26], fmt)
        except ValueError:
            continue
    return None


def rows_of(conn, sql: str, **params):
    """표가 없으면 빈 목록. UDJ 버전에 따라 없는 표가 있을 수 있다."""
    try:
        return [dict(r._mapping) for r in conn.execute(text(sql), params)]
    except Exception as exc:
        print(f"  건너뜀 ({exc.__class__.__name__}): {str(exc)[:80]}")
        return []


def main() -> int:
    parser = argparse.ArgumentParser(description="UDJ → 기록해 데이터 이전")
    parser.add_argument("--udj-db", required=True, help="UDJ 의 DATABASE_URL")
    parser.add_argument("--dry-run", action="store_true", help="옮기지 않고 개수만 센다")
    parser.add_argument("--yes", action="store_true",
                        help="실제로 옮긴다. --dry-run 으로 먼저 확인할 것")
    args = parser.parse_args()


    # 실수로 덮어쓰지 않도록, 미리보기를 거치지 않으면 실행하지 않는다.
    if not args.dry_run and not args.yes:
        print("먼저 --dry-run 으로 확인한 뒤 --yes 를 붙여 실행하세요.")
        return 1
    Base.metadata.create_all(bind=engine)
    udj_engine = connect_udj(args.udj_db)
    db = SessionLocal()
    made = {"users": 0, "journals": 0, "letters": 0, "subs": 0, "orders": 0, "subjects": 0}

    try:
        with udj_engine.connect() as conn:
            # ── 1. 일지를 쓴 적이 있는 사용자만 옮긴다 ──────────
            # 전체 회원을 복사할 이유가 없다. 로그인하면 자동으로 사본이 생긴다.
            print("[1/6] 사용자")
            users = rows_of(conn, """
                SELECT DISTINCT u.id, u.email, u.name, u.role, u.school_id,
                       u.department, u.grade, u.class_name, u.is_active
                  FROM users u
                 WHERE u.id IN (SELECT user_id FROM journal_entries)
                    OR u.id IN (SELECT user_id FROM cover_letters)
                    OR u.id IN (SELECT user_id FROM subscriptions)
                    OR u.role IN ('teacher', 'school', 'admin')
            """)

            # 재학생 인증 정보를 붙여 소속을 채운다.
            verifs = {}
            for v in rows_of(conn, """
                SELECT user_id, school_id, status, teacher_id, class_name
                  FROM school_verifications
            """):
                verifs[v["user_id"]] = v

            schools = {s["id"]: s["name"] for s in rows_of(conn, "SELECT id, name FROM schools")}

            id_map = {}     # UDJ user id -> 기록해 user id
            for u in users:
                exist = db.query(User).filter(User.udj_user_id == u["id"]).first()
                if exist:
                    id_map[u["id"]] = exist.id
                    continue
                v = verifs.get(u["id"])
                school_id = (v or {}).get("school_id") or u.get("school_id")
                new = User(
                    udj_user_id=u["id"],
                    email=(u.get("email") or "")[:120],
                    name=(u.get("name") or "")[:60],
                    role=Role(u.get("role") or "student"),
                    school_id=school_id,
                    school_name=(schools.get(school_id) or "")[:120],
                    department=(u.get("department") or "")[:60],
                    grade=u.get("grade"),
                    verified=bool(v and v.get("status") == "approved"),
                    teacher_udj_id=(v or {}).get("teacher_id"),
                    class_name=((v or {}).get("class_name") or u.get("class_name") or "")[:40],
                    is_active=bool(u.get("is_active", True)),
                )
                if args.dry_run:
                    # 미리보기에서도 이후 단계가 세어질 수 있게 가짜 번호를 넣는다.
                    id_map[u["id"]] = -u["id"]
                else:
                    db.add(new)
                    db.flush()
                    id_map[u["id"]] = new.id
                made["users"] += 1
            if not args.dry_run:
                db.commit()
            print(f"      {made['users']}명")

            # ── 2. 일지·일기 ─────────────────────────────────
            print("[2/6] 일지·일기")
            for j in rows_of(conn, """
                SELECT id, user_id, kind, entry_date, subject, teacher_name,
                       content, sent_at, share_token, created_at
                  FROM journal_entries ORDER BY id
            """):
                new_uid = id_map.get(j["user_id"])
                if not new_uid:
                    continue
                # 같은 사람·같은 날짜·같은 종류면 이미 옮긴 것으로 본다.
                dup = None if args.dry_run else db.query(JournalEntry).filter(
                    JournalEntry.user_id == new_uid,
                    JournalEntry.entry_date == as_date(j["entry_date"]),
                    JournalEntry.kind == j["kind"],
                    JournalEntry.subject == (j.get("subject") or ""),
                ).first()  # 미리보기면 위에서 None
                if dup:
                    continue
                if not args.dry_run:
                    db.add(JournalEntry(
                        user_id=new_uid,
                        kind=j.get("kind") or "diary",
                        entry_date=as_date(j["entry_date"]),
                        subject=(j.get("subject") or "")[:80],
                        teacher_name=(j.get("teacher_name") or "")[:60],
                        content=j.get("content") or "{}",
                        sent_at=as_dt(j.get("sent_at")),
                        share_token=j.get("share_token"),
                        created_at=as_dt(j.get("created_at")) or datetime.utcnow(),
                    ))
                made["journals"] += 1
            if not args.dry_run:
                db.commit()
            print(f"      {made['journals']}건")

            # ── 3. 자기소개서 ────────────────────────────────
            print("[3/6] 자기소개서")
            for c in rows_of(conn, """
                SELECT id, user_id, title, content, created_at FROM cover_letters ORDER BY id
            """):
                new_uid = id_map.get(c["user_id"])
                if not new_uid:
                    continue
                if not args.dry_run and db.query(CoverLetter).filter(
                    CoverLetter.user_id == new_uid,
                    CoverLetter.title == (c.get("title") or ""),
                ).first():
                    continue
                if not args.dry_run:
                    db.add(CoverLetter(
                        user_id=new_uid,
                        title=(c.get("title") or "")[:120],
                        content=c.get("content") or "{}",
                        created_at=as_dt(c.get("created_at")) or datetime.utcnow(),
                    ))
                made["letters"] += 1
            if not args.dry_run:
                db.commit()
            print(f"      {made['letters']}건")

            # ── 4. 구독 ─────────────────────────────────────
            print("[4/6] 구독")
            for sb in rows_of(conn, """
                SELECT user_id, started_at, expires_at FROM subscriptions
            """):
                new_uid = id_map.get(sb["user_id"])
                if not new_uid:
                    continue
                if not args.dry_run and db.query(Subscription).filter(
                        Subscription.user_id == new_uid).first():
                    continue
                if not args.dry_run:
                    db.add(Subscription(
                        user_id=new_uid,
                        started_at=as_dt(sb.get("started_at")) or datetime.utcnow(),
                        expires_at=as_dt(sb["expires_at"]),
                    ))
                made["subs"] += 1
            if not args.dry_run:
                db.commit()
            print(f"      {made['subs']}명")

            # ── 5. 결제 기록 (정산 근거라 함께 옮긴다) ───────────
            print("[5/6] 결제 기록")
            for o in rows_of(conn, """
                SELECT user_id, user_email, months, amount, status, deposit_code,
                       order_uid, payment_key, pay_method, receipt_url,
                       created_at, due_at, paid_at, handled_at
                  FROM subscription_orders ORDER BY id
            """):
                uid = o.get("order_uid")
                if uid and db.query(SubscriptionOrder).filter(
                        SubscriptionOrder.order_uid == uid).first():
                    continue
                if not args.dry_run:
                    db.add(SubscriptionOrder(
                        user_id=id_map.get(o.get("user_id")),
                        user_email=(o.get("user_email") or "")[:120],
                        months=o.get("months") or 1,
                        amount=o.get("amount") or 0,
                        status=OrderStatus(o.get("status") or "pending"),
                        deposit_code=(o.get("deposit_code") or "")[:30],
                        order_uid=uid,
                        payment_key=(o.get("payment_key") or "")[:200],
                        pay_method=(o.get("pay_method") or "")[:30],
                        receipt_url=(o.get("receipt_url") or "")[:300],
                        created_at=as_dt(o.get("created_at")) or datetime.utcnow(),
                        due_at=as_dt(o.get("due_at")), paid_at=as_dt(o.get("paid_at")),
                        handled_at=as_dt(o.get("handled_at")),
                    ))
                made["orders"] += 1
            if not args.dry_run:
                db.commit()
            print(f"      {made['orders']}건")

            # ── 6. 과목 (수업 일지 드롭다운) ────────────────────
            print("[6/6] 과목")
            existing = {
                (r.school_id, r.department, r.grade, r.name)
                for r in db.query(SchoolSubject).all()
            }
            for s in rows_of(conn, """
                SELECT school_id, department, grade, name FROM school_subjects
            """):
                key = (s["school_id"], s.get("department") or "", s.get("grade"), s["name"])
                if key in existing:
                    continue
                existing.add(key)
                if not args.dry_run:
                    db.add(SchoolSubject(
                        school_id=s["school_id"],
                        department=(s.get("department") or "")[:60],
                        grade=s.get("grade"),
                        name=s["name"][:80],
                    ))
                made["subjects"] += 1
            if not args.dry_run:
                db.commit()
            print(f"      {made['subjects']}종")

    finally:
        db.close()

    print()
    if args.dry_run:
        print("※ 미리보기입니다. 아무것도 옮기지 않았습니다.")
        print("  실제로 옮기려면 --dry-run 을 빼고 다시 실행하세요.")
    else:
        print("이전을 마쳤습니다. 기록해에서 로그인해 자료가 보이는지 확인하세요.")
        print("UDJ 쪽 자료는 그대로 두었습니다. 확인 후 직접 정리하시면 됩니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
