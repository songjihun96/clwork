import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, PLAN_LABEL } from "../api";
import SchoolDetailView from "../components/SchoolDetailView";
import { useSeo } from "../seo";
import CareerChat from "../components/CareerChat";
import CareerChatExport from "../components/CareerChatReport";

const CATEGORY_ICONS = {
  특성화고: "🏫", 마이스터고: "⚙️", 과학고: "🔬", 외국어고: "🌐",
  국제고: "🌏", 예술고: "🎨", 체육고: "🏅", 자율고: "📘", 일반고: "🎓",
};

const AXIS_COLOR = {
  TECH: "#f2603f",
  IT: "#5aa9d6",
  DESIGN: "#a882e0",
  BIZ: "#2bb98a",
  CARE: "#ff7a59",
  AGRI: "#7cb342",
};

// 단계: intro(위치·통학) -> quiz(문항) -> result(결과)
export default function Quiz() {
  useSeo({ title: "진로 적성 검사", description: "간단한 진로 적성 검사로 나에게 맞는 특성화고 계열과 학교를 추천받으세요.", path: "/quiz" });
  const navigate = useNavigate();
  const [stage, setStage] = useState("intro");
  const [meta, setMeta] = useState(null);
  const [addressSearchAvailable, setAddressSearchAvailable] = useState(false);
  const [location, setLocation] = useState(null); // { lat, lng, label }
  const [commute, setCommute] = useState("1h");
  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState([]);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [openId, setOpenId] = useState(null);
  const cardRef = useRef(null);

  useEffect(() => {
    api.quizQuestions().then(setMeta).catch((e) => setError(e.message));
    api.geoConfig().then((c) => setAddressSearchAvailable(c.address_search)).catch(() => {});
  }, []);

  const start = () => {
    setError("");
    setAnswers([]);
    setStep(0);
    setStage("quiz");
  };

  const pick = (choice) => {
    const next = [...answers];
    next[step] = choice;
    setAnswers(next);
    if (step + 1 < meta.questions.length) {
      setStep(step + 1);
    } else {
      submit(next);
    }
  };

  const submit = async (finalAnswers) => {
    setLoading(true);
    setError("");
    try {
      const r = await api.quizResult(
        finalAnswers,
        location?.lat ?? null,
        location?.lng ?? null,
        location?.label ?? "",
        commute,
        meta?.seed ?? null
      );
      setResult(r);
      setStage("result");
    } catch (e) {
      setError(e.message);
      setStage("quiz");
    } finally {
      setLoading(false);
    }
  };

  const restart = () => {
    setResult(null);
    setAnswers([]);
    setStep(0);
    setStage("intro");
  };

  const saveImage = async () => {
    const html2canvas = (await import("html2canvas")).default;
    const canvas = await html2canvas(cardRef.current, {
      backgroundColor: "#ffffff",
      scale: 2,
      useCORS: true,
    });
    const link = document.createElement("a");
    link.download = `우리동네직업계고_진로테스트_결과.png`;
    link.href = canvas.toDataURL("image/png");
    link.click();
  };

  if (error && !meta) {
    return <div className="wrap" style={{ padding: 60 }}><div className="notice notice-error">{error}</div></div>;
  }
  if (!meta) {
    return <div className="wrap" style={{ padding: 60 }}><div className="empty"><p>불러오는 중…</p></div></div>;
  }

  return (
    <div className="wrap" style={{ maxWidth: 720, padding: "34px 0 60px" }}>
      {stage === "intro" && (
        <Intro
          meta={meta}
          location={location}
          setLocation={setLocation}
          addressSearchAvailable={addressSearchAvailable}
          commute={commute}
          setCommute={setCommute}
          onStart={start}
          error={error}
          setError={setError}
        />
      )}

      {stage === "quiz" && (
        <Quizzing
          meta={meta}
          step={step}
          answers={answers}
          onPick={pick}
          onBack={() => (step > 0 ? setStep(step - 1) : setStage("intro"))}
          loading={loading}
        />
      )}

      {stage === "result" && result && (
        <Result
          result={result}
          cardRef={cardRef}
          onSaveImage={saveImage}
          onRestart={restart}
          onOpenSchool={setOpenId}
          navigate={navigate}
        />
      )}

      {openId && (
        <div className="modal-backdrop" onClick={() => setOpenId(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <SchoolDetailView schoolId={openId} embedded />
            <div style={{ padding: "0 28px 24px" }}>
              <button className="btn btn-ghost" onClick={() => setOpenId(null)}>닫기</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Intro({ meta, location, setLocation, addressSearchAvailable, commute, setCommute, onStart, error, setError }) {
  const [address, setAddress] = useState("");
  const [busy, setBusy] = useState(false);
  const [gpsBusy, setGpsBusy] = useState(false);

  const searchAddress = async () => {
    if (!address.trim()) return;
    setBusy(true);
    setError("");
    try {
      const r = await api.geocode(address.trim());
      setLocation({ lat: r.lat, lng: r.lng, label: r.address });
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const useCurrentLocation = () => {
    if (!navigator.geolocation) {
      setError("이 브라우저는 현재 위치를 지원하지 않습니다. 주소를 입력해주세요.");
      return;
    }
    setGpsBusy(true);
    setError("");
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocation({
          lat: pos.coords.latitude,
          lng: pos.coords.longitude,
          label: "현재 위치",
        });
        setGpsBusy(false);
      },
      (err) => {
        const msg =
          err.code === 1
            ? "위치 권한이 거부되었습니다. 브라우저 설정에서 허용하거나 주소를 입력해주세요."
            : "현재 위치를 가져오지 못했습니다. 주소를 입력해주세요.";
        setError(msg);
        setGpsBusy(false);
      },
      { enableHighAccuracy: true, timeout: 10000 }
    );
  };

  const minutes = Math.max(3, Math.round(meta.questions.length * 0.4));

  return (
    <>
      <div style={{ textAlign: "center", maxWidth: 560, margin: "0 auto" }}>
        <div style={{ display: "inline-flex", alignItems: "center", gap: 6,
          background: "var(--color-accent-soft)", color: "var(--color-accent)",
          padding: "5px 12px", borderRadius: 999, fontSize: 12.5, fontWeight: 600, marginBottom: 18 }}>
          <span className="msi" style={{ fontSize: 15 }}>explore</span> 나만의 나침반 찾기
        </div>
        <h1 style={{ fontSize: 32, margin: "0 0 14px", lineHeight: 1.3 }}>
          나에게 딱 맞는<br /><span style={{ color: "var(--color-accent)" }}>미래의 무대</span>를 발견하세요
        </h1>
        <p style={{ color: "var(--steel)", fontSize: 15, margin: "0 auto", lineHeight: 1.7 }}>
          상황과 활동에 대한 생각을 차근차근 답하면 관심 분야와 세부 성향에 맞는 학과와 학교를 추천해드립니다.
        </p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
        gap: 14, margin: "28px 0" }}>
        <IntroFeature icon="timer" title={`소요 시간 ${minutes}분`} desc="직관적으로 떠오르는 답을 선택해주세요." />
        <IntroFeature icon="checklist" title="다각도 진단" desc="흥미·성향·문제해결 방식을 여러 질문으로 살펴봅니다." />
        <IntroFeature icon="auto_awesome" title="맞춤 학과 추천" desc="성향에 맞는 계열과 통학 가능한 학교를 안내합니다." />
      </div>

      <div className="panel" style={{ marginTop: 22 }}>
        <h3>어디서 통학하나요? <span style={{ fontSize: 12, color: "var(--steel-light)", fontWeight: "normal" }}>선택</span></h3>

        {location ? (
          <div className="notice notice-ok" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
            <span>📍 {location.label} 기준으로 추천합니다</span>
            <button className="btn btn-ghost btn-sm" onClick={() => setLocation(null)}>바꾸기</button>
          </div>
        ) : (
          <div style={{ display: "grid", gap: 14 }}>
            {/* 주소 입력 */}
            <div className="field">
              <label className="label">도로명주소 또는 지번주소</label>
              <div style={{ display: "flex", gap: 6 }}>
                <input
                  className="input"
                  placeholder={addressSearchAvailable ? "예: 인천 남동구 정각로 29" : "주소 검색이 설정되지 않았습니다"}
                  value={address}
                  disabled={!addressSearchAvailable}
                  onChange={(e) => setAddress(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && searchAddress()}
                />
                <button className="btn" onClick={searchAddress} disabled={busy || !addressSearchAvailable}>
                  {busy ? "검색 중…" : "검색"}
                </button>
              </div>
              {!addressSearchAvailable && (
                <span style={{ fontSize: 12, color: "var(--steel-light)" }}>
                  주소 검색은 카카오 API 키가 필요합니다. 대신 아래 현재 위치를 눌러주세요.
                </span>
              )}
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: 10, color: "var(--steel-light)", fontSize: 12 }}>
              <span style={{ flex: 1, height: 1, background: "var(--line)" }} />
              또는
              <span style={{ flex: 1, height: 1, background: "var(--line)" }} />
            </div>

            {/* 현재 위치 */}
            <button className="btn btn-ghost" onClick={useCurrentLocation} disabled={gpsBusy} style={{ width: "100%" }}>
              {gpsBusy ? "위치 확인 중…" : "📍 현재 위치 사용하기"}
            </button>
          </div>
        )}

        <div className="field" style={{ marginTop: 18 }}>
          <label className="label">통학 가능한 거리</label>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(110px, 1fr))", gap: 8 }}>
            {meta.time_options.map((opt) => (
              <button
                key={opt.key}
                onClick={() => setCommute(opt.key)}
                className="panel"
                style={{
                  padding: "12px 8px",
                  textAlign: "center",
                  cursor: "pointer",
                  fontSize: 13,
                  fontWeight: 600,
                  borderWidth: commute === opt.key ? 2 : 1,
                  borderColor: commute === opt.key ? "var(--color-accent)" : "var(--line)",
                  background: commute === opt.key ? "var(--color-accent-soft)" : "var(--surface)",
                  opacity: location ? 1 : 0.55,
                }}
                disabled={!location}
              >
                {/* 실제로 거르는 기준은 거리다. 거리를 크게 두고, 감을
                    잡기 쉬우라고 대중교통 기준 시간을 아래에 덧붙인다. */}
                {opt.label}
                {opt.hint && (
                  <span style={{ display: "block", fontSize: 11, fontWeight: 400,
                                 color: "var(--steel-light)", marginTop: 2 }}>
                    {opt.hint}
                  </span>
                )}
              </button>
            ))}
          </div>
          <span style={{ fontSize: 12, color: "var(--steel-light)", marginTop: 2 }}>
            {location
              ? "위치에서 이 거리 안에 있는 학교를 추천합니다. 직선거리 기준이라 실제 통학 시간은 교통편에 따라 다릅니다."
              : "위치를 설정하면 통학 거리로 걸러줍니다. 위치 없이도 테스트는 가능해요."}
          </span>
        </div>

        {error && <div className="notice notice-error" style={{ marginTop: 14 }}>{error}</div>}

        <button className="btn btn-signal" style={{ marginTop: 18, width: "100%", padding: "12px" }} onClick={onStart}>
          {location ? "테스트 시작하기" : "위치 없이 테스트 시작하기"}
        </button>
      </div>
    </>
  );
}

function IntroFeature({ icon, title, desc }) {
  return (
    <div className="panel" style={{ textAlign: "left" }}>
      <div style={{ width: 40, height: 40, borderRadius: 10, background: "var(--color-accent-soft)",
        color: "var(--color-accent)", display: "grid", placeItems: "center", marginBottom: 12 }}>
        <span className="msi">{icon}</span>
      </div>
      <b style={{ fontSize: 15 }}>{title}</b>
      <p style={{ fontSize: 13, color: "var(--steel)", margin: "6px 0 0", lineHeight: 1.6 }}>{desc}</p>
    </div>
  );
}

function Quizzing({ meta, step, answers, onPick, onBack, loading }) {
  const q = meta.questions[step];
  const progress = ((step + 1) / meta.questions.length) * 100;

  if (loading) {
    return (
      <div className="empty" style={{ marginTop: 40 }}>
        <h3>결과를 계산하고 있어요</h3>
        <p>통학 거리와 관심 분야를 맞춰보는 중…</p>
      </div>
    );
  }

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 6 }}>
        <button className="btn btn-ghost btn-sm" onClick={onBack}>← 이전</button>
        <span className="label">{step + 1} / {meta.questions.length}</span>
      </div>

      <div style={{ height: 6, background: "var(--line)", borderRadius: 3, overflow: "hidden", marginBottom: 30 }}>
        <div style={{ width: `${progress}%`, height: "100%", background: "var(--signal)", transition: "width 0.3s ease" }} />
      </div>

      <h2 style={{ fontSize: 22, lineHeight: 1.4, marginBottom: 26, textAlign: "center", minHeight: 62 }}>
        {q.q}
      </h2>

      <div style={{ display: "grid", gap: 10 }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(5, minmax(0, 1fr))", gap: 8 }}>
          {q.scale.map((opt) => (
            <button
              key={opt.value}
              onClick={() => onPick(String(opt.value))}
              className="panel"
              style={{
                minHeight: 92,
                padding: "14px 8px",
                textAlign: "center",
                cursor: "pointer",
                fontSize: 13,
                lineHeight: 1.45,
                fontWeight: 600,
                borderWidth: answers[step] === String(opt.value) ? 2 : 1,
                borderColor: answers[step] === String(opt.value) ? "var(--ink)" : "var(--line)",
                background: answers[step] === String(opt.value) ? "#fff9e8" : "var(--surface)",
                transition: "border-color 0.15s, transform 0.1s",
              }}
              onMouseDown={(e) => (e.currentTarget.style.transform = "scale(0.98)")}
              onMouseUp={(e) => (e.currentTarget.style.transform = "scale(1)")}
              onMouseLeave={(e) => (e.currentTarget.style.transform = "scale(1)")}
            >
              <span style={{ display: "block", fontFamily: "var(--font-display)", fontSize: 20, marginBottom: 6 }}>
                {opt.value}
              </span>
              {opt.label}
            </button>
          ))}
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", color: "var(--steel-light)", fontSize: 11.5, padding: "0 2px" }}>
          <span>← 전혀 그렇지 않다</span>
          <span>매우 그렇다 →</span>
        </div>
      </div>
    </>
  );
}

function Result({ result, cardRef, onSaveImage, onRestart, onOpenSchool, navigate }) {
  const maxScore = Math.max(...Object.values(result.scores), 1);
  const [chatGroup, setChatGroup] = useState(null);   // 챗봇으로 연 추천 학과
  // 계열마다 나눈 대화. 창을 닫아도 남아 있어야 이어 묻고, 한 장으로 정리해 저장할 수 있다.
  const [chatLogs, setChatLogs] = useState({});
  const setGroupLog = (group) => (upd) => setChatLogs((all) => ({
    ...all, [group]: typeof upd === "function" ? upd(all[group] || []) : upd,
  }));

  return (
    <>
      {chatGroup && (
        <CareerChat group={chatGroup} onClose={() => setChatGroup(null)}
          log={chatLogs[chatGroup] || []} setLog={setGroupLog(chatGroup)}
          allLogs={chatLogs} result={result} />
      )}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16, flexWrap: "wrap", gap: 8 }}>
        <span className="label" style={{ color: "var(--signal-deep)" }}>테스트 결과</span>
        <div style={{ display: "flex", gap: 6 }}>
          <button className="btn btn-signal btn-sm" onClick={onSaveImage}>이미지로 저장</button>
          <button className="btn btn-ghost btn-sm" onClick={onRestart}>다시 하기</button>
        </div>
      </div>
      {/* AI 에게 물어본 게 있으면, 결과와 대화를 함께 정리해 저장하는 단추가 생긴다. */}
      <div style={{ display: "flex", justifyContent: "flex-end", marginTop: -8, marginBottom: 12 }}>
        <CareerChatExport result={result} logs={chatLogs} label="테스트 결과 + AI 대화 정리 저장" />
      </div>

      {result.quality && result.quality.reliable === false && (
        <div className="notice notice-error" style={{ marginBottom: 14 }}>
          ⚠️ {result.quality.note} 다시 하기를 눌러 조금 더 신중하게 답해보세요.
        </div>
      )}

      {/* 이 카드 전체가 이미지로 저장된다 */}
      <div ref={cardRef} style={{ background: "var(--surface)", borderRadius: "var(--radius-lg)", overflow: "hidden", border: "1px solid var(--line)" }}>
        <div style={{ padding: "26px 26px 24px", background: "var(--color-text)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
            <span style={{ background: "rgba(255,255,255,0.25)", color: "#fff", padding: "3px 10px", fontSize: 11, fontWeight: 700, letterSpacing: "0.04em", borderRadius: 999 }}>
              ㅇㅈ
            </span>
            <span style={{ color: "rgba(255,255,255,0.92)", fontSize: 12.5 }}>
              {result.shows_distance
                ? `${result.location_label} · ${result.commute_label}`
                : result.has_location
                ? `${result.location_label} 기준`
                : "전국 추천"}
            </span>
          </div>
          <h2 style={{ color: "#fff", fontSize: 23, lineHeight: 1.4 }}>
            {result.confidence === "close" ? "나와 비슷하게 어울리는 분야는" : "나와 어울리는 분야는"}<br />
            <span style={{ color: "#fff", background: "rgba(255,255,255,0.22)", padding: "1px 10px", borderRadius: 999, display: "inline-block", marginTop: 6 }}>
              {result.departments.map((d) => d.label).join(", ")}
            </span>
          </h2>
          {result.confidence === "close" && (
            <p style={{ color: "rgba(255,255,255,0.85)", fontSize: 12, marginTop: 8 }}>
              여러 분야의 점수가 비슷하게 나왔어요. 아래 계열들을 두루 살펴보세요.
            </p>
          )}
        </div>

        {/* 관심 축 그래프 */}
        <div style={{ padding: "22px 26px", background: "var(--signal-soft)" }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: "var(--signal-deep)", marginBottom: 14 }}>
            나의 관심 분포
          </div>
          <div style={{ display: "grid", gap: 10 }}>
            {result.top_axes.concat(
              Object.keys(result.scores).filter((a) => !result.top_axes.includes(a))
            ).map((axis) => {
              const score = result.scores[axis];
              const pct = (score / maxScore) * 100;
              return (
                <div key={axis} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span style={{ width: 84, fontSize: 12.5, color: "var(--ink-soft)", flexShrink: 0, fontWeight: 500 }}>
                    {result.axis_labels[axis]}
                  </span>
                  <div style={{ flex: 1, height: 14, background: "rgba(0,0,0,0.06)", borderRadius: 999, overflow: "hidden" }}>
                    <div style={{ width: `${pct}%`, height: "100%", background: AXIS_COLOR[axis] || "var(--signal)", borderRadius: 999 }} />
                  </div>
                  <span style={{ width: 22, textAlign: "right", fontSize: 12, fontWeight: 700, color: "var(--steel)" }}>
                    {score}
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        {/* 세부 성향 */}
        <div style={{ padding: "22px 26px", background: "var(--surface)", borderTop: "1px solid var(--line)" }}>
          <div className="label" style={{ marginBottom: 14 }}>세부 진로 성향</div>
          <div style={{ display: "grid", gap: 18 }}>
            {result.top_axes.map((axis) => (
              <div key={axis}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                  <strong style={{ fontSize: 13.5 }}>{result.axis_labels[axis]}</strong>
                  <span style={{ fontSize: 12, fontWeight: 700, color: "var(--steel)" }}>{result.scores[axis]}점</span>
                </div>
                <div style={{ display: "grid", gap: 7 }}>
                  {Object.entries(result.sub_scores?.[axis] || {})
                    .sort((a, b) => b[1] - a[1])
                    .map(([label, score]) => (
                      <div key={label} style={{ display: "grid", gridTemplateColumns: "112px 1fr 30px", gap: 8, alignItems: "center" }}>
                        <span style={{ fontSize: 11.5, color: "var(--steel)" }}>{label}</span>
                        <div style={{ height: 8, background: "rgba(0,0,0,0.06)", borderRadius: 999, overflow: "hidden" }}>
                          <div style={{ width: `${score}%`, height: "100%", background: AXIS_COLOR[axis] || "var(--signal)", borderRadius: 999 }} />
                        </div>
                        <span style={{ textAlign: "right", fontSize: 11.5, fontWeight: 700, color: "var(--steel)" }}>{score}</span>
                      </div>
                    ))}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* 추천 학과 */}
        <div style={{ padding: "22px 26px", background: "var(--surface)" }}>
          <div className="label" style={{ marginBottom: 14 }}>추천 학과 TOP {result.departments.length}</div>
          <div style={{ display: "grid", gap: 10 }}>
            {result.departments.map((d, i) => (
              <div key={d.label} style={{ background: "var(--paper)", border: "1px solid var(--line)", borderLeft: `4px solid ${AXIS_COLOR[d.axis]}`, borderRadius: "var(--radius-sm)", padding: "15px 17px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 5 }}>
                  <span style={{ fontFamily: "var(--font-display)", fontSize: 15 }}>{i + 1}. {d.label}</span>
                  <span className="badge" style={{ fontSize: 9 }}>{d.axis_label}</span>
                </div>
                <p style={{ fontSize: 12.5, color: "var(--steel)", margin: "0 0 7px", lineHeight: 1.5 }}>{d.desc}</p>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                  {d.jobs.map((job) => (
                    <span key={job} style={{ fontSize: 11, background: "var(--surface)", border: "1px solid var(--line)", borderRadius: 999, padding: "3px 10px", color: "var(--steel)" }}>
                      {job}
                    </span>
                  ))}
                </div>
                {/* 이 카드는 통째로 이미지로 저장된다. 단추가 이미지에 찍히면
                    누를 수 없는 단추가 사진에 남으니, 저장할 때는 빼게 한다. */}
                <button type="button" data-html2canvas-ignore="true"
                  className="btn btn-sm" style={{ marginTop: 10 }}
                  onClick={() => setChatGroup(d.label)}>
                  💬 이 직업들, AI에게 물어보기
                </button>
              </div>
            ))}
          </div>
        </div>

        <div style={{ padding: "10px 26px 16px", background: "var(--surface)", textAlign: "center" }}>
          <span style={{ fontSize: 11, color: "var(--steel-light)" }}>
            우리동네 직업계고 · ㅇㅈ
          </span>
        </div>
      </div>

      {/* 통학권 내 추천 학교 (카드 밖, 인터랙티브) */}
      <div style={{ marginTop: 24 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
          <h3 style={{ fontSize: 17 }}>{result.shows_distance ? "통학권 내 추천 학교" : "추천 학교"}</h3>
          <span className="label">
            {result.shows_distance ? `${result.location_label} · ${result.commute_label}` : result.has_location ? result.location_label : "전국"}
          </span>
        </div>

        {result.schools.length === 0 ? (
          <div className="empty">
            <h3>{result.shows_distance ? "통학 범위 안에 맞는 학교가 없어요" : "맞는 학교를 찾지 못했어요"}</h3>
            <p>
              {result.shows_distance
                ? "통학 시간을 늘리거나, 검색 페이지에서 조건을 바꿔 직접 찾아보세요. 학교 위치 정보가 등록되지 않아 거리 계산에서 빠졌을 수도 있습니다."
                : "검색 페이지에서 지역과 계열로 직접 찾아보세요."}
            </p>
          </div>
        ) : (
          <div className="card-list">
            {result.schools.map((s) => (
              <button key={s.id} className={`school-card plan-${s.plan}`} onClick={() => onOpenSchool(s.id)}>
                <div className="card-photo">
                  {CATEGORY_ICONS[s.category] || "🏫"}
                  <span className="card-photo-badge">{s.category}</span>
                </div>
                <div className="card-main">
                  <div className="card-top">
                    <span className="card-name">{s.name}</span>
                    {s.plan === "platinum" && <span className="badge badge-top"><span>추천</span></span>}
                  </div>
                  <div className="card-specs" style={{ marginTop: 6 }}>
                    <span className="spec"><b>위치</b>{s.region} · {s.address.replace(/^[^ ]+ /, "")}</span>
                    {s.distance_km != null && (
                      <span className="spec">
                        <b>거리</b>
                        <span style={{ color: "var(--color-success)", fontWeight: 600 }}>
                          약 {s.distance_km}km
                        </span>
                      </span>
                    )}
                  </div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 8 }}>
                    {s.matched_departments.map((dept) => (
                      <span key={dept} style={{ fontSize: 11.5, background: "var(--color-accent-soft)", borderRadius: 999, padding: "2px 10px", color: "var(--color-accent)", fontWeight: 600 }}>
                        {dept}
                      </span>
                    ))}
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}

        <button className="btn btn-ghost" style={{ marginTop: 16, width: "100%" }} onClick={() => navigate("/")}>
          검색 페이지에서 더 찾아보기
        </button>
      </div>
    </>
  );
}
