import { useState } from "react";
import { api } from "../api";
import { toast } from "../toast";

/** 다 보고 나서 남기는 후기.
 *
 * 설명회와 합격생 영상이 같이 쓴다. 묻는 것이 똑같아서(별점 하나, 한 줄)
 * 두 벌로 두면 한쪽만 고쳐 놓고 잊는다. 다른 것은 어느 신청 종류로
 * 접수하는지와 안내 문구뿐이다.
 *
 * **별점과 글 중 하나만 있어도 받는다.** 둘 다 요구하면 별만 누르고 닫는
 * 사람의 응답이 통째로 사라진다 — 그게 제일 많이 들어오는 응답이다.
 */
export default function ReviewForm({
  kind, onDone, onCancel,
  title = "보신 소감을 남겨 주세요",
  intro = "다음 강의를 더 낫게 만드는 데 씁니다.",
  name = "(후기)", phone = "-",
}) {
  const [score, setScore] = useState(0);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    if (!score && !text.trim()) {
      setError("별점이나 한 줄 후기 중 하나는 남겨 주세요.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.submitApplication({
        kind,
        name, phone,
        message: text.trim(),
        extra: { "별점": score ? `${score}점` : "-" },
      });
      toast.ok("후기를 남겨주셔서 고맙습니다.");
      onDone();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit}>
      {/* 창 제목이 이미 같은 말을 하고 있으면 title 을 null 로 준다 —
          같은 문장이 두 줄 겹쳐 있으면 읽는 사람이 한 번 멈칫한다. */}
      {title && <h3 style={{ border: "none", padding: 0, margin: "0 0 4px" }}>{title}</h3>}
      <p style={{ fontSize: 13, color: "var(--steel)", margin: "0 0 16px" }}>{intro}</p>

      <div style={{ display: "grid", gap: 14 }}>
        <div className="field">
          <label className="label">도움이 되었나요?</label>
          <div style={{ display: "flex", gap: 4 }}>
            {[1, 2, 3, 4, 5].map((n) => (
              <button key={n} type="button" onClick={() => setScore(n)}
                aria-label={`${n}점`}
                style={{
                  border: "none", background: "none", cursor: "pointer",
                  fontSize: 26, lineHeight: 1, padding: 2,
                  filter: n <= score ? "none" : "grayscale(1)",
                  opacity: n <= score ? 1 : .35,
                }}>★</button>
            ))}
          </div>
        </div>

        <div className="field">
          <label className="label">한 줄 후기</label>
          <textarea className="textarea" rows={4} value={text}
            placeholder="어떤 점이 도움이 되었는지, 무엇이 더 궁금한지 적어 주세요."
            onChange={(e) => setText(e.target.value)} />
        </div>

        {error && <div className="notice notice-error">{error}</div>}

        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn btn-signal" type="submit" disabled={busy}>
            {busy ? "보내는 중…" : "후기 남기기"}
          </button>
          <button className="btn btn-ghost" type="button" onClick={onCancel}>
            나중에
          </button>
        </div>
      </div>
    </form>
  );
}
