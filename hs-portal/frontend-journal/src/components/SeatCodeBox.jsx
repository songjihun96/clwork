import { useState } from "react";
import { api } from "../api";

/** 학교에서 받은 등록 코드를 넣는 곳.
 *  개인이 결제하는 구조가 아니라, 학교가 나눠준 코드로 이용권을 받는다.
 *  코드 자체에 어떤 상품인지가 담겨 있어(SeatCode.product) 이 화면은
 *  상품을 몰라도 된다 — 안내 문구만 featureLabel 로 받는다. */
export default function SeatCodeBox({ onDone, featureLabel = "이 기능" }) {
  const [code, setCode] = useState("");
  const [studentNo, setStudentNo] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  const submit = async () => {
    setBusy(true); setMsg(null);
    try {
      const r = await api.redeemSeatCode(code.trim(), studentNo.trim() || undefined);
      setMsg({ type: "ok", text: r.message });
      setTimeout(onDone, 900);
    } catch (e) {
      setMsg({ type: "error", text: e.message });
      setBusy(false);
    }
  };

  return (
    <div style={{ textAlign: "left", maxWidth: 380, margin: "0 auto" }}>
      <div className="label">학교에서 받은 등록 코드</div>
      <p className="meta" style={{ margin: "4px 0 8px", lineHeight: 1.7 }}>
        {featureLabel} 이용권은 학교가 신청합니다. 선생님께 받은 코드를 넣어주세요.
      </p>
      <div className="row" style={{ gap: 8 }}>
        <input className="input" value={code} placeholder="예: A3KD-7F2M"
          style={{ flex: 1, fontFamily: "ui-monospace, Menlo, monospace",
                   letterSpacing: "0.08em", textTransform: "uppercase" }}
          onChange={(e) => setCode(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()} />
      </div>
      <div className="field" style={{ marginTop: 8 }}>
        <label className="label" style={{ fontWeight: 400 }}>
          내 번호 <span style={{ color: "var(--steel-light)" }}>(선택 — 알고 있으면 적어주세요)</span>
        </label>
        <input className="input" type="number" min="1" max="999" value={studentNo}
          placeholder="예: 17" style={{ maxWidth: 120 }}
          onChange={(e) => setStudentNo(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()} />
      </div>
      <button className="btn btn-primary" style={{ marginTop: 10, width: "100%" }}
        onClick={submit} disabled={busy || !code.trim()}>
        {busy ? "확인 중…" : "등록"}
      </button>
      {msg && <div className={`notice notice-${msg.type}`} style={{ marginTop: 10 }}>{msg.text}</div>}
      <p className="meta" style={{ marginTop: 10, lineHeight: 1.7 }}>
        코드가 없으시면 담당 선생님께 문의해주세요.
        일지 작성과 제출은 코드 없이도 계속 무료입니다.
      </p>
    </div>
  );
}
