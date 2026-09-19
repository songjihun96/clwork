import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";

/** 유료 서비스 신청폼.
 *
 * 네 가지 신청(컨설팅·상담·영상·설명회)이 묻는 것이 거의 같아서 폼을 하나로
 * 둔다. 다른 부분은 `kind` 와 위에 얹는 안내문뿐이다.
 *
 * **대개 로그인을 요구하지 않는다.** 중학생과 학부모가 대상이라 가입부터
 * 시키면 대부분 거기서 나간다. 예외는 **사고 나서 볼 것이 생기는 신청**
 * (합격생 영상)뿐이다 — 열어 줄 상대를 알아야 열 수 있어서, 그때만 서버가
 * `login_required` 를 내려보내고 여기서 계정을 먼저 받는다.
 *
 * 보내고 나면 **계좌 안내 팝업**이 뜬다. 결제를 붙이지 않았으므로 이 화면이
 * 곧 결제 안내다 — 그래서 닫기 전에 금액과 계좌를 또렷하게 보여 주고,
 * 입금자명을 신청자 이름으로 해달라고 반드시 적는다(이게 없으면 누가 넣은
 * 돈인지 대조할 수가 없다).
 */
export default function ApplyForm({ kind, title, intro, applicantLabels,
                                   messageLabel = "문의 및 요청사항",
                                   messagePlaceholder, onApplied, doneNote }) {
  const [info, setInfo] = useState(null);
  const [form, setForm] = useState({
    found_path: "", found_etc: "", applicant: "",
    name: "", phone: "", email: "", message: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(null);   // {amount, bank}
  const { user } = useAuth();
  const loc = useLocation();

  const people = applicantLabels || ["본인", "학부모"];

  useEffect(() => {
    api.applicationInfo(kind).then(setInfo).catch(() => setInfo(null));
  }, [kind]);

  // 로그인한 사람에게 이름·연락처를 다시 묻지 않는다. 이미 계정에 있는 것을
  // 또 적게 하면, 둘이 어긋났을 때 어느 쪽이 맞는지 알 수 없게 된다.
  useEffect(() => {
    if (!user) return;
    setForm((f) => ({
      ...f,
      name: f.name || user.name || "",
      phone: f.phone || user.phone || "",
      email: f.email || user.email || "",
    }));
  }, [user]);

  const set = (patch) => setForm({ ...form, ...patch });

  const needLogin = !!info?.login_required && !user;

  const submit = async (e) => {
    e.preventDefault();
    if (!form.name.trim() || !form.phone.trim()) {
      setError("이름과 연락 가능한 전화번호는 꼭 입력해 주세요.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const r = await api.submitApplication({ kind, ...form });
      setDone({ amount: r.amount, bank: r.bank });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  // 팝업을 닫을 때에야 바깥 화면에 알린다.
  //
  // 접수하자마자 알리면 바깥이 "입금 확인 중"으로 바뀌면서 이 폼을 통째로
  // 걷어내고, 그러면 방금 띄운 계좌 팝업까지 같이 사라진다. 계좌번호를 못
  // 본 채로 끝나는 셈이라, 돈을 넣어야 진행되는 신청에서는 치명적이다.
  const close = () => {
    setDone(null);
    if (onApplied) onApplied();
  };

  // 접수 결과는 **팝업**으로 띄운다. 폼 자리에 조용히 바꿔 끼우면 계좌번호를
  // 못 보고 지나치는 사람이 생긴다. 돈을 넣어야 진행되는 신청이라 이 화면은
  // 반드시 눈에 걸려야 한다.
  if (done) {
    return (
      <div onClick={(e) => { if (e.target === e.currentTarget) close(); }}
        style={{
          position: "fixed", inset: 0, zIndex: 90, background: "rgba(0,0,0,.55)",
          display: "grid", placeItems: "center", padding: 16, overflowY: "auto",
        }}>
      <div className="panel" style={{
        textAlign: "center", width: "100%", maxWidth: 420, margin: 0,
        boxShadow: "0 12px 40px rgba(0,0,0,.35)",
      }}>
        <h3 style={{ border: "none", padding: 0 }}>신청이 접수되었습니다</h3>
        {done.amount > 0 ? (
          <>
            <p style={{ fontSize: 14, color: "var(--steel)", margin: "8px 0 16px" }}>
              아래 계좌로 입금해 주시면 확인 후 연락드립니다.
            </p>
            <div style={{
              display: "inline-block", textAlign: "left", padding: "16px 20px",
              borderRadius: "var(--radius-sm)", background: "var(--raised)",
              border: "1px solid var(--line)",
            }}>
              <div style={{ fontSize: 13, color: "var(--steel)" }}>입금하실 금액</div>
              <div style={{ fontSize: 24, fontWeight: 800, margin: "2px 0 12px" }}>
                {done.amount.toLocaleString()}원
              </div>
              <div style={{ fontSize: 13, color: "var(--steel)" }}>입금 계좌</div>
              <div style={{ fontSize: 16, fontWeight: 700, marginTop: 2 }}>{done.bank}</div>
            </div>
            <p style={{ fontSize: 13, color: "var(--color-attention)", marginTop: 14 }}>
              입금자명을 <b>{form.name}</b> 님 이름으로 해주세요. 다르면 확인이 늦어집니다.
            </p>
            <p style={{ fontSize: 13.5, marginTop: 10 }}>
              {/* 신청마다 그 다음이 다르다. 영상은 연락이 아니라 이 화면이
                  열리는 것이라, 연락을 기다리게 두면 안 온다고 여긴다. */}
              <b>{doneNote || "입금이 확인되면 연락드리겠습니다."}</b>
            </p>
          </>
        ) : (
          <p style={{ fontSize: 14, color: "var(--steel)", marginTop: 8 }}>
            확인 후 연락드리겠습니다.
          </p>
        )}
        <div style={{ marginTop: 18 }}>
          <button className="btn btn-ghost btn-sm" onClick={() => close()}>닫기</button>
        </div>
      </div>
      </div>
    );
  }

  // 로그인이 있어야 하는 신청인데 아직 안 했다면, 폼을 보여 주지 않는다.
  // 다 적고 나서 마지막에 "로그인하세요"를 만나면 적은 것이 다 날아간다.
  if (needLogin) {
    const next = encodeURIComponent(loc.pathname);
    return (
      <div className="panel" style={{ marginTop: 18 }}>
        <h3>{title || "신청폼"}</h3>
        <p style={{ fontSize: 14, lineHeight: 1.75, color: "var(--steel)", margin: "0 0 16px" }}>
          이 영상은 <b>회원 계정으로만</b> 신청할 수 있습니다.
          입금이 확인되면 <b>그 계정으로 로그인해서 바로</b> 보실 수 있어서,
          따로 링크를 기다리실 필요가 없습니다.
        </p>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <Link className="btn btn-signal" to={`/login?next=${next}`}>로그인하고 신청하기</Link>
          <Link className="btn btn-ghost" to="/signup">회원가입</Link>
        </div>
      </div>
    );
  }

  return (
    <form className="panel" style={{ marginTop: 18 }} onSubmit={submit}>
      <h3>{title || "신청폼"}</h3>
      {intro}

      {info && info.amount > 0 && (
        <p style={{ fontSize: 14, margin: "0 0 14px" }}>
          비용 <b>{info.amount.toLocaleString()}원</b>
          <span style={{ color: "var(--steel)" }}> · 신청 후 계좌를 안내해 드립니다.</span>
        </p>
      )}

      <div style={{ display: "grid", gap: 14 }}>
        <div className="field">
          <label className="label">우리동네직업계고를 알게 된 경로</label>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            {["소개", "검색", "기타"].map((v) => (
              <label key={v} style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 14 }}>
                <input type="radio" name="found" value={v}
                  checked={form.found_path === v}
                  onChange={() => set({ found_path: v })} />
                {v}
              </label>
            ))}
          </div>
          {form.found_path === "기타" && (
            <input className="input" style={{ marginTop: 8, maxWidth: 320 }}
              placeholder="어떻게 알게 되셨나요?"
              value={form.found_etc}
              onChange={(e) => set({ found_etc: e.target.value })} />
          )}
        </div>

        <div className="field">
          <label className="label">신청자</label>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            {people.map((v) => (
              <label key={v} style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 14 }}>
                <input type="radio" name="applicant" value={v}
                  checked={form.applicant === v}
                  onChange={() => set({ applicant: v })} />
                {v}
              </label>
            ))}
          </div>
        </div>

        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <div className="field" style={{ flex: "1 1 180px" }}>
            <label className="label">이름</label>
            <input className="input" value={form.name} required
              onChange={(e) => set({ name: e.target.value })} />
          </div>
          <div className="field" style={{ flex: "1 1 200px" }}>
            <label className="label">연락 가능한 전화번호</label>
            <input className="input" value={form.phone} required
              inputMode="tel" placeholder="010-0000-0000"
              onChange={(e) => set({ phone: e.target.value })} />
          </div>
        </div>

        <div className="field">
          <label className="label">이메일 주소</label>
          <input className="input" type="email" value={form.email}
            onChange={(e) => set({ email: e.target.value })} />
        </div>

        <div className="field">
          <label className="label">{messageLabel}</label>
          <textarea className="textarea" rows={5} value={form.message}
            placeholder={messagePlaceholder
              || "자세하게 입력해 주세요. 무엇이 궁금하고 어떤 도움이 필요한지 적어주실수록 준비가 정확해집니다."}
            onChange={(e) => set({ message: e.target.value })} />
        </div>

        {error && <div className="notice notice-error">{error}</div>}

        <div>
          <button className="btn btn-signal" type="submit" disabled={busy}>
            {busy ? "보내는 중…" : "신청하기"}
          </button>
        </div>
      </div>
    </form>
  );
}
