import { useState } from "react";

/** 커리큘럼 — 클래스101 강의 목록 방식.
 *
 * 챕터를 접어 두고 필요한 것만 편다. 챕터 7개에 강의가 스무 개쯤 되면
 * 전부 펼쳐 놓은 목록은 스크롤만 길어져서, 정작 "무엇을 다루는 강의인가"가
 * 한눈에 안 들어온다. 접어 두면 챕터 제목만으로 전체 그림이 먼저 보인다.
 *
 * **한 번에 다 펴는 버튼**을 함께 둔다 — 처음 온 사람은 전부 훑어보고 싶고,
 * 그때 챕터를 일곱 번 누르게 하면 안 된다.
 */
/** onPlay 는 (source, 챕터번호, 강의번호) 로 부른다. 강의가 없는 챕터는
 *  강의번호가 -1 이다. 설명회는 첫 인자만 쓰고 나머지는 무시한다 —
 *  합격생 영상은 티켓이 만료되면 "몇 번째 것을 보고 있었는지"로 다시
 *  받아와야 해서 번호가 필요하다. */
/** onLocked 를 주면, 회원만 볼 수 있어 잠긴 강의(locked)도 누를 수 있게
 *  두고 누르면 그걸 부른다(설명회: 로그인 화면으로 보낸다). */
export default function Curriculum({ chapters, onPlay, onLocked }) {
  const [open, setOpen] = useState(() => new Set());
  const allOpen = open.size === chapters.length && chapters.length > 0;

  const toggle = (i) => {
    setOpen((cur) => {
      const next = new Set(cur);
      if (next.has(i)) next.delete(i); else next.add(i);
      return next;
    });
  };

  const toggleAll = () => {
    setOpen(allOpen ? new Set() : new Set(chapters.map((_, i) => i)));
  };

  if (!chapters.length) return null;

  return (
    <section>
      <div style={{
        display: "flex", alignItems: "baseline", gap: 10,
        padding: "16px 18px", borderRadius: "var(--radius-sm) var(--radius-sm) 0 0",
        border: "1px solid var(--line)", borderBottom: "none",
        background: "var(--surface)",
      }}>
        <h2 style={{ fontSize: 17, margin: 0 }}>커리큘럼</h2>
        <span style={{ fontSize: 13, color: "var(--steel)" }}>
          챕터 {chapters.length}개
        </span>
        <span style={{ flex: 1 }} />
        <button onClick={toggleAll} style={{
          border: "none", background: "none", cursor: "pointer",
          fontSize: 13.5, color: "var(--steel)", padding: 0,
        }}>
          {allOpen ? "전체 챕터 닫기" : "전체 챕터 열기"}
        </button>
      </div>

      <div style={{
        border: "1px solid var(--line)",
        borderRadius: "0 0 var(--radius-sm) var(--radius-sm)",
        overflow: "hidden", background: "var(--surface)",
      }}>
        {chapters.map((ch, i) => {
          const items = ch.items || [];
          const isOpen = open.has(i);
          return (
            <div key={i} style={{
              borderTop: i === 0 ? "none" : "1px solid var(--line)",
            }}>
              <button onClick={() => toggle(i)} style={{
                display: "flex", alignItems: "center", gap: 12, width: "100%",
                padding: "18px 18px", border: "none", background: "none",
                cursor: "pointer", textAlign: "left",
              }}>
                <span style={{ flex: 1, minWidth: 0 }}>
                  <span style={{
                    display: "block", fontSize: 12, color: "var(--steel)",
                    letterSpacing: .4, marginBottom: 4,
                  }}>
                    {`CHAPTER ${i + 1}`}
                  </span>
                  <span style={{ display: "block", fontWeight: 700, fontSize: 15.5, lineHeight: 1.4 }}>
                    {ch.title}
                  </span>
                </span>
                <span style={{ fontSize: 13, color: "var(--steel)", whiteSpace: "nowrap" }}>
                  {items.length > 0 ? `강의 ${items.length}개` : "강의 1개"}
                </span>
                <span style={{
                  fontSize: 12, color: "var(--steel)",
                  transform: isOpen ? "rotate(180deg)" : "none",
                  transition: "transform .15s ease",
                }}>▼</span>
              </button>

              {isOpen && (
                <div style={{ padding: "0 18px 16px" }}>
                  {items.length === 0 ? (
                    <LessonRow label={ch.title} locked={!ch.source && ch.locked && !!onLocked}
                      onClick={ch.source ? () => onPlay(ch.source, i, -1)
                        : (ch.locked && onLocked) || null} />
                  ) : items.map((it, j) => (
                    <LessonRow key={j} label={it.title} locked={!it.source && it.locked && !!onLocked}
                      onClick={it.source ? () => onPlay(it.source, i, j)
                        : (it.locked && onLocked) || null} />
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}

function LessonRow({ label, onClick, locked }) {
  const inner = (
    <>
      <span style={{ color: "var(--steel-light)", fontSize: 13 }}
        title={locked ? "회원만 볼 수 있어요" : undefined}>{locked ? "🔒" : "▶"}</span>
      <span style={{ flex: 1, minWidth: 0 }}>{label}</span>
    </>
  );
  const style = {
    display: "flex", gap: 10, alignItems: "center", width: "100%",
    padding: "10px 12px", fontSize: 14, lineHeight: 1.5,
    borderRadius: "var(--radius-sm)", textAlign: "left",
    border: "none", background: "var(--raised)", marginTop: 6,
  };
  if (!onClick) return <div style={style}>{inner}</div>;
  return (
    <button onClick={onClick} style={{ ...style, cursor: "pointer" }}>
      {inner}
    </button>
  );
}
