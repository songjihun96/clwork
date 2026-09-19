import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";

/** 포트폴리오 목록 + 새로 만들기.
 *  자기소개서를 대신하는 메인 기능이다 — 학교생활 기록을 취업/진학용으로
 *  재구성한 결과물. 만들기는 두 갈래: AI에게 추천받거나, 직접 테마를 골라
 *  바로 빈 포트폴리오를 만든다. 둘 다 만든 뒤엔 같은 편집 화면으로 간다. */
// 만들기 화면은 페이지·블록을 손으로 배치하는 편집기라 손가락보다 마우스가
// 훨씬 편하다. 화면이 좁으면(휴대폰) 만들기 대신 PC로 오라고 안내한다 —
// 이미 만든 포트폴리오를 보는 것까지는 막지 않는다.
const DESKTOP_MIN_WIDTH = 900;

function useIsDesktop() {
  const [isDesktop, setIsDesktop] = useState(
    () => typeof window === "undefined" || window.innerWidth >= DESKTOP_MIN_WIDTH);
  useEffect(() => {
    const onResize = () => setIsDesktop(window.innerWidth >= DESKTOP_MIN_WIDTH);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  return isDesktop;
}

export default function Portfolio() {
  const navigate = useNavigate();
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");
  const [showNew, setShowNew] = useState(false);
  const isDesktop = useIsDesktop();

  const load = () => api.portfolios().then(setItems).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  if (error) return <div className="wrap page"><div className="notice notice-error">{error}</div></div>;
  if (!items) return <div className="wrap page"><p>불러오는 중…</p></div>;

  return (
    <div className="wrap page">
      <div className="row">
        <div>
          <span className="label">포트폴리오</span>
          <h1 style={{ marginTop: 4 }}>내 포트폴리오</h1>
        </div>
        <div className="spacer" />
        <button className="btn btn-primary" onClick={() => setShowNew(true)}>+ 포트폴리오 만들기</button>
      </div>
      <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 10, lineHeight: 1.8 }}>
        그동안 쓴 일지를 바탕으로 취업·진학용 포트폴리오를 만듭니다.
        사진과 결과물을 더해 나만의 이야기로 꾸며보세요.
      </p>

      {showNew && (
        isDesktop ? (
          <NewPortfolio onClose={() => setShowNew(false)}
            onCreated={(id) => navigate(`/portfolio/${id}`)} />
        ) : (
          <MobileNotice onClose={() => setShowNew(false)} />
        )
      )}

      <div style={{ marginTop: 20 }}>
        {items.length === 0 ? (
          <div className="empty">
            <h3>아직 만든 포트폴리오가 없습니다</h3>
            <p>일지에 남긴 경험으로 첫 포트폴리오를 만들어보세요.</p>
          </div>
        ) : (
          <div style={{ display: "grid", gap: 12,
                       gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))" }}>
            {items.map((p) => (
              <Link key={p.id} to={`/portfolio/${p.id}`} className="panel"
                style={{ display: "grid", gap: 6 }}>
                <span className="badge">{p.theme_label}</span>
                <b style={{ fontSize: 16 }}>{p.title || "제목 없음"}</b>
                <span className="meta">페이지 {p.page_count ?? 0}개</span>
                <span className="meta">
                  {p.status === "published" ? "완성" : "작성 중"}
                  {p.visibility === "shared" ? " · 공유 중" : ""}
                </span>
              </Link>
            ))}
          </div>
        )}
      </div>

      <p style={{ fontSize: 13, color: "var(--steel-light)", marginTop: 24 }}>
        예전에 쓰던 <Link to="/cover-letters">자기소개서</Link>는 그대로 남아 있습니다.
      </p>
    </div>
  );
}

function MobileNotice({ onClose }) {
  return (
    <div className="panel" style={{ marginTop: 16, maxWidth: 480 }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <b>PC(컴퓨터)에서 만들어주세요</b>
        <button className="btn btn-sm btn-ghost" onClick={onClose}>닫기</button>
      </div>
      <p style={{ marginTop: 10, fontSize: 14, color: "var(--steel)", lineHeight: 1.8 }}>
        포트폴리오 만들기는 화면이 넓은 PC(컴퓨터)에서만 할 수 있습니다.
        학교나 집의 컴퓨터로 다시 접속해 만들어주세요. 이미 만든 포트폴리오는
        휴대폰에서도 볼 수 있습니다.
      </p>
    </div>
  );
}

function NewPortfolio({ onClose, onCreated }) {
  const [step, setStep] = useState("choose");   // choose / ai / manual
  const [meta, setMeta] = useState(null);
  const [recs, setRecs] = useState(null);
  const [recError, setRecError] = useState("");
  const [busy, setBusy] = useState(false);
  const [manualTheme, setManualTheme] = useState("");
  const [manualPurpose, setManualPurpose] = useState("free");
  const [manualTitle, setManualTitle] = useState("");

  useEffect(() => { api.deptFields().then(setMeta).catch(() => {}); }, []);

  const askAi = async () => {
    setStep("ai"); setBusy(true); setRecError(""); setRecs(null);
    try {
      const job = await api.requestThemeRecommend();
      const result = await api.waitAiJob(job.job_id);
      setRecs(result.recommendations || []);
    } catch (e) {
      setRecError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const makeFromTheme = async (theme_type, purpose = "free") => {
    setBusy(true); setRecError("");
    try {
      const job = await api.requestPortfolioGenerate(theme_type, purpose);
      const result = await api.waitAiJob(job.job_id);
      onCreated(result.portfolio_id);
    } catch (e) {
      setRecError(e.message);
      setBusy(false);
    }
  };

  const createManual = async () => {
    if (!manualTheme) return;
    setBusy(true);
    try {
      const p = await api.createPortfolio({
        title: manualTitle || undefined, theme_type: manualTheme, purpose: manualPurpose,
      });
      onCreated(p.id);
    } catch (e) {
      setRecError(e.message);
      setBusy(false);
    }
  };

  return (
    <div className="panel" style={{ marginTop: 16, maxWidth: 560 }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <b>어떻게 만들까요?</b>
        <button className="btn btn-sm btn-ghost" onClick={onClose}>닫기</button>
      </div>

      {step === "choose" && (
        <div className="row" style={{ gap: 10, marginTop: 14 }}>
          <button className="btn btn-primary" onClick={askAi}>AI에게 추천받기</button>
          <button className="btn" onClick={() => setStep("manual")}>✏️ 직접 만들기</button>
        </div>
      )}

      {step === "ai" && (
        <div style={{ marginTop: 14 }}>
          {busy && !recs && <p className="meta">기록을 살펴보고 있습니다…</p>}
          {recError && <div className="notice notice-error">{recError}</div>}
          {recs && recs.length === 0 && (
            <p className="meta">아직 추천할 만큼 쌓인 기록이 없습니다. 일지를 조금 더 써보세요.</p>
          )}
          {recs && recs.map((r, i) => (
            <div key={r.theme_type} className="panel" style={{ marginTop: i ? 10 : 0 }}>
              <span className="eyebrow">추천 {i + 1}순위</span>
              <b>{r.title}</b>
              <p className="meta" style={{ marginTop: 4, lineHeight: 1.6 }}>{r.reason}</p>
              <p className="meta">관련 기록 {r.source_count}개</p>
              <button className="btn btn-sm btn-primary" style={{ marginTop: 8 }} disabled={busy}
                onClick={() => makeFromTheme(r.theme_type)}>
                {busy ? "만드는 중…" : "이 테마로 만들기"}
              </button>
            </div>
          ))}
          <button className="btn btn-sm btn-ghost" style={{ marginTop: 10 }}
            onClick={() => setStep("choose")}>돌아가기</button>
        </div>
      )}

      {step === "manual" && meta && (
        <div style={{ marginTop: 14, display: "grid", gap: 10 }}>
          <div className="field">
            <span className="label">제목(선택)</span>
            <input className="input" value={manualTitle}
              onChange={(e) => setManualTitle(e.target.value)} placeholder="예: 나의 성장 기록" />
          </div>
          <div className="field">
            <span className="label">테마</span>
            <select className="select" value={manualTheme}
              onChange={(e) => setManualTheme(e.target.value)}>
              <option value="">골라주세요</option>
              {meta.themes.map((t) => (
                <option key={t} value={t}>{meta.theme_labels[t]}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <span className="label">목적</span>
            <select className="select" value={manualPurpose}
              onChange={(e) => setManualPurpose(e.target.value)}>
              {meta.purposes.map((p) => (
                <option key={p} value={p}>{meta.purpose_labels[p]}</option>
              ))}
            </select>
          </div>
          {recError && <div className="notice notice-error">{recError}</div>}
          <div className="row" style={{ gap: 8 }}>
            <button className="btn btn-primary" disabled={!manualTheme || busy} onClick={createManual}>
              {busy ? "만드는 중…" : "만들기"}
            </button>
            <button className="btn btn-ghost" onClick={() => setStep("choose")}>돌아가기</button>
          </div>
        </div>
      )}
    </div>
  );
}
