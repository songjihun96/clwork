import { useCallback, useEffect, useState } from "react";

/** 처음 자기소개서를 쓰는 학생을 위한 안내.
 *
 *  화면에 버튼이 여럿인데 무엇부터 눌러야 할지 알기 어렵다.
 *  실제 화면의 그 자리를 짚어가며 순서를 보여준다.
 *
 *  **글로만 설명하지 않는 이유**
 *
 *  "왼쪽에서 항목을 고르고 오른쪽에서…" 라고 적어 두면 읽지 않는다.
 *  읽어도 그 버튼이 어디 있는지 눈으로 찾아야 한다.
 *  실제 자리에 동그라미를 그려 주면 한 번에 안다.
 *
 *  **한 번 보면 다시 안 뜬다**
 *
 *  매번 뜨면 방해가 된다. 봤다는 것을 브라우저에 적어 두고,
 *  다시 보고 싶으면 도움말 버튼으로 부를 수 있게 한다.
 */

const SEEN_KEY = "udj_cl_tour_seen";

// 짚어 줄 자리와 할 말. selector 는 화면에서 그 요소를 찾는 데 쓴다.
const STEPS = [
  {
    selector: "[data-tour='title']",
    title: "먼저 이름을 붙이세요",
    body: "어느 회사에 낼 자소서인지 적어 두면 나중에 찾기 쉽습니다.",
    place: "bottom",
  },
  {
    selector: "[data-tour='item']",
    title: "쓰고 싶은 항목을 고릅니다",
    body: "13개 항목이 있습니다. 전부 쓸 필요는 없습니다. " +
          "휴대폰에서는 항목을 누르면 펼쳐집니다.",
    place: "bottom",
  },
  {
    selector: "[data-tour='materials']",
    title: "이 항목 재료 보기",
    body: "그동안 쓴 일지에서 이 항목에 쓸 만한 것을 찾아 줍니다. " +
          "빈 화면을 앞에 두고 고민할 필요가 없습니다.",
    place: "right",
  },
  {
    selector: "[data-tour='panel']",
    title: "여기에 재료가 나옵니다",
    body: "일지에서 찾은 대목이 보입니다. " +
          "본문에 넣기를 누르면 항목 칸에 들어갑니다.",
    place: "left",
  },
  {
    selector: "[data-tour='ai']",
    title: "AI로 정리할 수도 있습니다",
    body: "일지를 자소서에 쓸 수 있는 문장으로 다듬고, 초안을 만들어 줍니다. " +
          "쓰려면 먼저 동의가 필요합니다.",
    place: "left",
    optional: true,
  },
  {
    selector: "[data-tour='download']",
    title: "다 쓰면 파일로 받으세요",
    body: "한글·워드·PDF로 받을 수 있습니다. 양식에 맞춰 나옵니다.",
    place: "top",
  },
];

export function tourSeen() {
  try {
    return localStorage.getItem(SEEN_KEY) === "1";
  } catch {
    // 시크릿 모드나 쿠키 차단이면 저장을 못 읽는다.
    // 예전에는 여기서 true 를 돌려줘 안내가 영영 안 떴다.
    // 못 읽으면 "아직 안 봤다" 로 보는 편이 낫다. 한 번 더 뜨는 것이
    // 아예 안 뜨는 것보다 낫기 때문이다.
    return false;
  }
}

export function markTourSeen() {
  try {
    localStorage.setItem(SEEN_KEY, "1");
  } catch {
    /* 저장이 막혀 있어도 안내는 정상 동작한다 */
  }
}

export default function Tour({ onClose }) {
  const [step, setStep] = useState(0);
  const [box, setBox] = useState(null);

  // 끝내기. useEffect 안에서도 부르므로 그보다 먼저 선언한다.
  // const 는 끌어올려지지 않아, 아래에 두면 첫 실행에서 터진다.
  const finish = useCallback(() => {
    markTourSeen();
    onClose?.();
  }, [onClose]);

  // 짚어 줄 요소를 찾는다. 없으면(예: AI 가 꺼져 있음) 건너뛴다.
  useEffect(() => {
    let n = step;
    let el = null;
    while (n < STEPS.length) {
      el = document.querySelector(STEPS[n].selector);
      if (el) break;
      n += 1;
    }
    if (!el) {
      // 짚을 것이 하나도 없으면 안내를 띄우지 않는다.
      finish();
      return;
    }
    if (n !== step) {
      setStep(n);
      return;
    }

    // 먼저 대략의 자리를 잡아 화면에 띄운다. 스크롤이 끝나기를
    // 기다렸다가 띄우면, 스크롤할 것이 없는 화면에서는 아무것도
    // 뜨지 않은 것처럼 보인다.
    const measure = () => {
      const r = el.getBoundingClientRect();
      setBox({ top: r.top, left: r.left, width: r.width, height: r.height });
    };
    measure();
    el.scrollIntoView({ block: "center", behavior: "smooth" });
    const t = setTimeout(measure, 400);
    return () => clearTimeout(t);
  }, [step, finish]);

  // 창 크기가 바뀌면 짚은 자리도 따라간다.
  useEffect(() => {
    const onMove = () => {
      const el = document.querySelector(STEPS[step].selector);
      if (!el) return;
      const r = el.getBoundingClientRect();
      setBox({ top: r.top, left: r.left, width: r.width, height: r.height });
    };
    window.addEventListener("resize", onMove);
    window.addEventListener("scroll", onMove, true);
    return () => {
      window.removeEventListener("resize", onMove);
      window.removeEventListener("scroll", onMove, true);
    };
  }, [step]);

  if (!box) return null;
  const s = STEPS[step];
  const pad = 6;

  // 말풍선 자리. 화면 밖으로 나가지 않게 가둔다.
  const bubbleW = Math.min(320, window.innerWidth - 24);
  let top = box.top + box.height + 12;
  let left = box.left;
  if (s.place === "top") top = Math.max(12, box.top - 170);
  if (s.place === "left") left = Math.max(12, box.left - bubbleW - 12);
  if (s.place === "right") left = box.left + box.width + 12;
  left = Math.min(Math.max(12, left), window.innerWidth - bubbleW - 12);
  top = Math.min(Math.max(12, top), window.innerHeight - 210);

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 3000 }}>
      {/* 어둡게 덮되, 짚어 준 자리만 밝게 남긴다.
          그림자를 크게 주면 구멍만 밝아진다. */}
      <div
        onClick={finish}
        style={{
          position: "absolute",
          top: box.top - pad, left: box.left - pad,
          width: box.width + pad * 2, height: box.height + pad * 2,
          borderRadius: 10,
          boxShadow: "0 0 0 9999px rgba(0,0,0,.55)",
          border: "2px solid var(--signal, #f26522)",
        }}
      />

      <div style={{
        position: "absolute", top, left, width: bubbleW,
        background: "#fff", borderRadius: 12, padding: 16,
        boxShadow: "0 10px 30px rgba(0,0,0,.25)",
      }}>
        <div style={{ fontSize: 12, color: "var(--steel-light)" }}>
          {step + 1} / {STEPS.length}
        </div>
        <h3 style={{ margin: "4px 0 6px", fontSize: 16 }}>{s.title}</h3>
        <p style={{ margin: 0, fontSize: 13.5, lineHeight: 1.8,
                    color: "var(--steel)" }}>
          {s.body}
        </p>

        <div className="row" style={{ gap: 6, marginTop: 14 }}>
          {step > 0 && (
            <button className="btn btn-sm btn-ghost"
              onClick={() => setStep(step - 1)}>이전</button>
          )}
          <div className="spacer" />
          <button className="btn btn-sm btn-ghost" onClick={finish}>
            그만 보기
          </button>
          <button className="btn btn-sm btn-primary"
            onClick={() => (step + 1 >= STEPS.length ? finish() : setStep(step + 1))}>
            {step + 1 >= STEPS.length ? "다 봤어요" : "다음"}
          </button>
        </div>
      </div>
    </div>
  );
}
