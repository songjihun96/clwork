import { useEffect, useRef, useState } from "react";

/** 화면 위쪽에 잠깐 떴다 사라지는 알림.
 *
 * 저장 버튼이 화면 아래쪽에 있는 경우가 많은데, 결과 문구는 패널 맨 위에
 * 뜨다 보니 눌러도 아무 일도 안 일어난 것처럼 보였다. 눌린 자리와 상관없이
 * 같은 곳에 뜨게 한다.
 *
 * 훅이 아니라 그냥 함수로 부른다 — 저장 처리는 컴포넌트 바깥의 async 함수
 * 안에서 끝나는 경우가 많아서, 부르는 쪽이 훅 규칙을 신경 쓰지 않아도 되는
 * 편이 실제로 쓰인다.
 *
 *   toast("저장했습니다.");
 *   toast.error("주소는 http:// 로 시작해야 합니다.");
 */
let seq = 0;
const listeners = new Set();

export function toast(text, type = "ok") {
  const msg = String(text || "").trim();
  if (!msg) return 0;
  const item = { id: ++seq, text: msg, type };
  listeners.forEach((fn) => fn(item));
  return item.id;
}
toast.ok = (text) => toast(text, "ok");
toast.error = (text) => toast(text, "error");

/** 성공 문구에도 "담당자에게 전달하세요" 같은 다음 할 일이 붙는 경우가 있어
 *  한 문장은 읽을 만큼 둔다. 실패는 무엇을 고쳐야 하는지 읽어야 해서 더 길다. */
const LIFE = { ok: 4200, error: 6000 };

export function Toaster() {
  const [items, setItems] = useState([]);
  const timers = useRef([]);

  useEffect(() => {
    const on = (item) => {
      setItems((cur) => [...cur.slice(-2), item]);   // 셋까지만 쌓는다
      const t = setTimeout(() => {
        setItems((cur) => cur.filter((x) => x.id !== item.id));
      }, LIFE[item.type] || LIFE.ok);
      timers.current.push(t);
    };
    listeners.add(on);
    const running = timers.current;
    return () => {
      listeners.delete(on);
      running.forEach(clearTimeout);
    };
  }, []);

  if (items.length === 0) return null;

  return (
    <div className="toast-wrap" aria-live="polite">
      {items.map((it) => (
        <div key={it.id} className={`toast toast-${it.type}`}
          onClick={() => setItems((cur) => cur.filter((x) => x.id !== it.id))}>
          <span className="toast-mark" aria-hidden="true">{it.type === "error" ? "!" : "✓"}</span>
          <span>{it.text}</span>
        </div>
      ))}
    </div>
  );
}

/** 패널 안에 남기는 문구와 토스트를 한 번에 만든다.
 *
 * 화면마다 결과를 패널 맨 위 문구로만 남기고 있었는데, 저장 버튼은 대개
 * 아래쪽에 있어 눌러도 아무 일 없어 보였다. 부르는 쪽 모양은 거의 그대로
 * 두고 토스트만 얹으려고 만든 함수다 — `setMsg(okMsg("저장했습니다."))`.
 */

// 성공은 토스트만 남긴다(null 을 돌려주니 패널 안 문구는 지워진다). 초록 상자와
// 토스트가 같은 말을 두 번 하면 화면만 시끄럽다.
export const okMsg = (text) => { toast.ok(text); return null; };

// 실패는 둘 다 남긴다. 토스트는 3초면 사라지는데, 무엇을 고쳐야 하는지는
// 고칠 때까지 폼 옆에 붙어 있어야 한다.
export const errMsg = (text) => { toast.error(text); return { type: "error", text }; };
