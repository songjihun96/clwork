"""기록해 DB 에 남은 연구 자료를 지운다.

연구·논문은 별도 서비스(research-backend)로 옮겨 갔다. 코드는 걷어냈지만
운영 DB 에는 표와 행이 그대로 남는다 — SQLAlchemy 는 모델을 지운다고 표를
지우지 않는다. 이 도구가 그 뒷정리를 한다.

    python -m app.drop_research --dry-run   # 무엇이 지워질지만 본다
    python -m app.drop_research             # 실제로 지운다

**되돌릴 수 없다.** 먼저 --dry-run 으로 확인하고, DB 를 백업한 뒤 실행하세요.

지울 표를 손으로 적지 않는다. 운영 DB 에는 예전 스키마에서 쓰다 만 표
(research_members 처럼 모델에서만 빠지고 DB 에는 남은 것)가 섞여 있어서,
목록을 적어 두면 반드시 빠뜨린다 — 그러면 외래키에 걸려 통째로 멈춘다.
대신 DB 에 있는 표를 훑어 이름으로 고르고, **지금 코드가 쓰는 표는 무슨
일이 있어도 건드리지 않는다**(Base.metadata 에 있으면 제외).
"""
import argparse
import sys

from sqlalchemy import inspect, text

from . import models  # noqa: F401  — 지금 쓰는 표를 Base 에 등록시킨다
from .database import Base, SessionLocal, engine

# 이 접두사로 시작하는 표를 연구 자료로 본다.
PREFIXES = ("research_", "external_")
# 접두사로는 안 걸리지만 연구 기능에만 쓰이던 표.
EXTRA = {"teacher_field_tags"}


def targets(existing: set[str]) -> list[str]:
    live = set(Base.metadata.tables)     # 지금 코드가 쓰는 표 — 절대 제외
    out = [t for t in sorted(existing)
           if (t.startswith(PREFIXES) or t in EXTRA) and t not in live]
    return out


def outside_refs(insp, existing: set[str], drop: set[str]) -> list[str]:
    """지울 표를 가리키는 **다른** 표가 있는지 본다.

    있으면 멈춘다. CASCADE 로 밀면 그 표의 외래키만 조용히 사라지고 고아 행이
    남는다 — 그건 정리가 아니라 더 큰 숙제다.
    """
    bad = []
    for t in sorted(existing - drop):
        for fk in insp.get_foreign_keys(t):
            if fk.get("referred_table") in drop:
                bad.append(t + " -> " + fk["referred_table"])
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description="기록해에 남은 연구 자료를 지웁니다.")
    ap.add_argument("--dry-run", action="store_true", help="세어만 보고 지우지 않는다")
    args = ap.parse_args()

    insp = inspect(engine)
    existing = set(insp.get_table_names())
    present = targets(existing)
    if not present:
        print("지울 연구 표가 없습니다. 이미 정리됐습니다.")
        return 0

    blockers = outside_refs(insp, existing, set(present))
    if blockers:
        print("연구 표를 가리키는 다른 표가 있어 멈췄습니다:")
        for b in blockers:
            print("  " + b)
        print("이 표들을 먼저 정리해야 합니다.")
        return 1

    db = SessionLocal()
    total = 0
    try:
        print("표별 행 수")
        for t in present:
            n = db.execute(text('SELECT COUNT(*) FROM "%s"' % t)).scalar() or 0
            total += n
            if n:
                print("  %-34s %6d" % (t, n))
        print("  %-34s %6d" % ("합계", total))
        print("표 %d개" % len(present))

        if args.dry_run:
            print("")
            print("--dry-run 이라 아무것도 지우지 않았습니다.")
            return 0

        # AI 작업 큐에 남은 연구 작업도 함께 지운다. 여기 남으면 워커가
        # 사라진 핸들러를 찾다가 실패로 쌓인다.
        if "ai_jobs" in existing:
            n = db.execute(text(
                "DELETE FROM ai_jobs WHERE kind LIKE 'research%' OR kind = 'board_synth'"
            )).rowcount or 0
            print("AI 작업 %d건 정리" % n)

        # 표를 지우면 행도 같이 사라진다. 따로 DELETE 하지 않는다 — 순서를
        # 맞춰야 해서 그 자체가 아까 멈춘 원인이었다.
        quoted = ", ".join('"%s"' % t for t in present)
        if engine.dialect.name == "postgresql":
            # CASCADE 는 지울 표끼리 얽힌 외래키만 푼다(밖에서 가리키는 표가
            # 없다는 건 위에서 이미 확인했다).
            db.execute(text("DROP TABLE IF EXISTS " + quoted + " CASCADE"))
        else:
            for t in reversed(present):
                db.execute(text('DROP TABLE IF EXISTS "%s"' % t))
        db.commit()
        print("표 %d개, 행 %d건을 지웠습니다." % (len(present), total))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
