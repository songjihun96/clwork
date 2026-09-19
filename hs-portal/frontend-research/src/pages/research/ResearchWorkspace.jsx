import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api";
import "../../research-theme.css";

// AI 호출은 스트리밍이 아니라 다 만들어질 때까지 기다렸다가 한 번에
// 받아오므로, "실제로 몇 %를 썼는지"는 알 수 없다. 대신 보통 걸리는
// 시간(expectedSeconds)에 맞춰 90%까지 점점 느려지며 다가가다가, 완료되면
// 100%로 채운다 — 정확한 진행률이 아니라 기다리는 동안의 체감을 위한
// 추정치임을 게이지 자체에도 "예상" 이라고 표시한다.
function estimateAiProgress(seconds, expectedSeconds) {
  const pct = 90 * (1 - Math.exp(-seconds / expectedSeconds));
  return Math.min(90, Math.round(pct));
}

function AiGauge({ percent }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8, maxWidth: 220 }}>
      <div style={{ flex: 1, height: 6, borderRadius: 999, background: "var(--color-border)", overflow: "hidden" }}>
        <div style={{ width: `${percent}%`, height: "100%", background: "var(--color-primary)",
          transition: "width .3s ease" }} />
      </div>
      <span style={{ fontSize: 11.5, color: "var(--color-text-muted)", minWidth: 32, textAlign: "right" }}>
        {percent}%
      </span>
    </div>
  );
}

const STAGE_ORDER = [
  ["interest", "관심 탐색"], ["topic", "주제 선정"], ["question", "연구 질문"],
  ["plan", "연구 계획"], ["literature", "문헌 조사"], ["method", "연구 설계"],
  ["execution", "실행"], ["data", "데이터 수집"], ["analysis", "분석"],
  ["discussion", "논의"], ["final", "최종 산출물"],
];

// [컬럼 키, 요약용 짧은 이름, 학생에게 보여줄 쉬운 질문, 도움말]
// 컬럼 자체는 기존 hypothesis/variables/... 그대로 쓰고, 화면 문구만 쉬운 말로 바꾼다.
const PLAN_FIELDS = [
  ["hypothesis", "예상", "해보기 전에 어떤 결과가 나올 것 같나요?",
    "틀려도 괜찮아요. 예상을 적어두면 나중에 비교할 수 있어요."],
  ["variables", "비교할 것", "무엇을 바꿔서 비교하고, 무엇이 달라지는지 볼까요?",
    "예) 음악을 들려준 화분과 안 들려준 화분의 키를 비교"],
  ["target_sample", "대상", "누구를(무엇을) 몇 개나 살펴볼까요?", ""],
  ["method_detail", "방법", "실제로 어떻게 해볼 건가요?", "순서대로 적어보세요."],
  ["expected_limitations", "한계", "이 연구로는 알기 어려운 게 뭘까요?", ""],
];

const PAPER_SECTIONS = [
  ["introduction", "서론"], ["literature_review", "선행 연구"], ["method", "연구 방법"],
  ["results", "연구 결과"], ["discussion", "논의"], ["limitations", "연구의 한계"],
  ["conclusion", "결론"],
];

const PORTFOLIO_SECTIONS = [
  ["why", "왜 시작했나요"], ["question", "무엇이 궁금했나요"], ["hypothesis", "해보기 전 예상"],
  ["method", "어떻게 연구했나요"], ["data", "어떤 데이터를 얻었나요"], ["result", "무엇을 발견했나요"],
  ["discussion", "어떻게 해석했나요"], ["limitation", "무엇이 부족했나요"], ["next", "다음 계획"],
];

const STANCE_LABEL = { support: "지지", oppose: "반박", conditional: "조건부", uncertain: "불확실" };

function needsAttentionItems({ research, roadmap, counts, todayStep }) {
  const items = [];
  if (research.current_stage === "question" && PLAN_FIELDS.some(([k]) => research[k])) {
    items.push("AI가 만든 연구 계획 초안이 아직 확정되지 않았어요 — 직접 검토하고 고친 뒤 확정해주세요.");
  }
  if (research.current_stage !== "interest" && research.current_stage !== "topic"
      && research.current_stage !== "question" && roadmap.length === 0) {
    items.push("아직 연구 로드맵이 없어요 — 로드맵을 만들면 주차별 할 일이 정해져요.");
  }
  if (counts.literatureUnverified > 0) {
    items.push(`AI가 제안한 참고자료 ${counts.literatureUnverified}건이 아직 확인되지 않았어요 — 실제로 찾아보고 "확인했어요"를 눌러주세요.`);
  }
  if (todayStep) {
    const left = todayStep.tasks.filter((t) => t.status !== "completed").length;
    if (left > 0) items.push(`이번 주(${todayStep.week_number}주차) 할 일이 ${left}개 남았어요.`);
  }
  if (counts.latestReviewFindings > 0) {
    items.push(`최근 연구심사에서 짚어준 내용이 ${counts.latestReviewFindings}가지 있어요 — 확인하고 보완해보세요.`);
  }
  if (counts.feedbackCount > 0) {
    items.push(`선생님이 남긴 지도 피드백이 ${counts.feedbackCount}건 있어요 — 아래에서 확인해보세요.`);
  }
  return items;
}

function currentWeekNumber(research) {
  if (!research.start_date) return 1;
  const start = new Date(research.start_date);
  const days = Math.floor((Date.now() - start.getTime()) / 86400000);
  const week = Math.floor(days / 7) + 1;
  return Math.min(Math.max(week, 1), research.duration_weeks);
}

export default function ResearchWorkspace() {
  const { id } = useParams();
  const [research, setResearch] = useState(null);
  const [roadmap, setRoadmap] = useState(null);
  const [error, setError] = useState("");
  // 다음 단계를 숨겼다 열었다 하려면 각 단계가 "완료됐는지"를 알아야 한다.
  // 실제로 완료됐는지 알 수 있는 건 각 자료 개수뿐이라(current_stage는
  // plan 확정 이후로는 안 바뀐다), 여기서 가볍게 세어 둔다.
  const [counts, setCounts] = useState({
    literatureVerified: 0, literatureUnverified: 0, analyses: 0, reviews: 0,
    latestReviewFindings: 0, hasPaper: false, hasPortfolio: false, feedbackCount: 0,
  });

  const reload = () => {
    api.getResearch(id).then(setResearch).catch((e) => setError(e.message));
    api.getResearchRoadmap(id).then((r) => setRoadmap(r.items)).catch(() => setRoadmap([]));
    Promise.all([
      api.listResearchLiterature(id).catch(() => ({ items: [] })),
      api.listResearchAnalysis(id).catch(() => ({ items: [] })),
      api.listResearchReview(id).catch(() => ({ items: [] })),
      api.getResearchPaper(id).catch(() => ({ paper: null })),
      api.listResearchFeedback(id).catch(() => ({ items: [] })),
      api.getResearchPortfolio(id).catch(() => ({ portfolio: null })),
    ]).then(([lit, an, rv, paper, fb, portfolio]) => setCounts({
      literatureVerified: (lit.items || []).filter((l) => l.verified).length,
      literatureUnverified: (lit.items || []).filter((l) => l.ai_suggested && !l.verified).length,
      analyses: (an.items || []).length,
      reviews: (rv.items || []).length,
      latestReviewFindings: (rv.items || [])[0]?.findings?.length || 0,
      hasPaper: !!paper.paper,
      hasPortfolio: !!portfolio.portfolio,
      feedbackCount: (fb.items || []).length,
    }));
  };

  useEffect(reload, [id]);

  if (error) {
    return <div className="research-theme research-workspace-wrap page"><div className="notice notice-error">{error}</div></div>;
  }
  if (!research || roadmap === null) {
    return <div className="research-theme research-workspace-wrap page"><p>불러오는 중…</p></div>;
  }

  const currentIndex = STAGE_ORDER.findIndex(([k]) => k === research.current_stage);
  const week = research.current_week || 1;
  const todayStep = roadmap.find((s) => s.week_number === week);
  const showAdvanced = research.current_stage === "plan"
    || currentIndex > STAGE_ORDER.findIndex(([k]) => k === "plan");

  const roadmapDone = roadmap.length > 0;
  const literatureDone = counts.literatureVerified >= 1;
  const analysisDone = counts.analyses >= 1;
  const reviewDone = counts.reviews >= 1;
  const followupDone = !!research.follow_up_ideas;

  // current_stage는 서버에 plan 확정까지만 저장된다(그 뒤로는 자료가 실제로
  // 쌓였는지로만 진행을 판단할 수 있다) — 그래서 화면에 보여줄 단계는
  // 이미 계산해 둔 완료 여부들로 다시 계산한다. 실제로 못 지나온 단계는
  // 밟지 않은 채로 둔다(뒤로 되돌아가지 않는다).
  const stageIndexOf = (key) => STAGE_ORDER.findIndex(([k]) => k === key);
  let displayIndex = currentIndex;
  if (roadmapDone) displayIndex = Math.max(displayIndex, stageIndexOf("literature"));
  if (literatureDone) displayIndex = Math.max(displayIndex, stageIndexOf("method"));
  if (analysisDone) displayIndex = Math.max(displayIndex, stageIndexOf("analysis"));
  if (reviewDone || followupDone) displayIndex = Math.max(displayIndex, stageIndexOf("discussion"));
  if (counts.hasPaper || counts.hasPortfolio) displayIndex = Math.max(displayIndex, stageIndexOf("final"));
  const displayStageLabel = STAGE_ORDER[displayIndex]?.[1] || research.current_stage;

  return (
    <div className="research-theme research-workspace-wrap page">
      <Link to="/research" className="label">← 내 연구</Link>
      <h1 style={{ marginTop: 8 }}>{research.title || research.interest_keyword}</h1>
      {research.research_question && (
        <p style={{ fontSize: 15, color: "var(--color-text-secondary)" }}>
          {research.research_question}
        </p>
      )}

      {research.team && <TeamPanel researchId={research.id} team={research.team} />}

      <div className="panel" style={{ marginTop: 14, display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ fontSize: 14 }}>막히는 부분이 있으면 다른 학교 선생님께 물어볼 수 있어요.</span>
        <div className="spacer" />
        <Link to={`/research/${research.id}/questions`} className="btn btn-sm btn-ghost">
          외부 선생님께 질문하기 →
        </Link>
      </div>

      {(() => {
        const items = needsAttentionItems({ research, roadmap, counts, todayStep });
        if (items.length === 0) return null;
        return (
          <div className="panel" style={{ border: "1px solid var(--color-attention)", background: "var(--color-attention-soft)", marginTop: 14 }}>
            <h3 style={{ margin: "0 0 8px" }}>확인이 필요해요</h3>
            <ul style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 6, fontSize: 13.5 }}>
              {items.map((t, i) => <li key={i}>{t}</li>)}
            </ul>
          </div>
        );
      })()}

      <div style={{ display: "flex", gap: 4, flexWrap: "wrap", margin: "16px 0 24px" }}>
        {STAGE_ORDER.map(([key, label], i) => (
          <span key={key} className="research-stage-pill" style={{
            background: i <= displayIndex ? "var(--color-accent-soft)" : "var(--raised)",
            color: i <= displayIndex ? "var(--color-primary)" : "var(--color-text-muted)",
          }}>
            {i < displayIndex ? "●" : i === displayIndex ? "◐" : "○"} {label}
          </span>
        ))}
      </div>

      {todayStep && (
        <TodayPanel researchId={research.id} week={week} step={todayStep}
          isLastWeek={week >= research.duration_weeks} onChanged={reload} />
      )}

      <div className="research-workspace-layout" style={{ marginTop: 24 }}>
        <div style={{ display: "grid", gap: 24 }}>
          <div className="panel">
            <h3>개요</h3>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, fontSize: 14 }}>
              <div>
                <span className="label">연구 기간</span>
                <div>{research.duration_weeks}주{research.start_date ? ` · ${week}주차` : ""}</div>
              </div>
              <div>
                <span className="label">현재 단계</span>
                <div>{displayStageLabel}</div>
              </div>
              <div>
                <span className="label">연구 유형</span>
                <div>{RESEARCH_TYPE_LABEL[research.research_type] || "미정"}</div>
              </div>
            </div>
          </div>

          {research.research_question && (
            <PlanPanel research={research} onChanged={reload} />
          )}

          {showAdvanced && (
            <>
              <RoadmapPanel researchId={research.id} roadmap={roadmap} onChanged={reload} />
              {roadmapDone ? (
                <LiteraturePanel research={research} onChanged={reload} />
              ) : (
                <LockedPanel title="참고 자료" hint="먼저 연구 로드맵을 만들어주세요." />
              )}
              {literatureDone ? (
                <DataAnalysisPanel research={research} onChanged={reload} />
              ) : (
                <LockedPanel title="연구 데이터·분석" hint="먼저 참고 자료를 최소 1건 확인해주세요." />
              )}
              {analysisDone ? (
                <ReviewPanel research={research} onChanged={reload} />
              ) : (
                <LockedPanel title="연구심사" hint="먼저 데이터 분석을 진행해주세요." />
              )}
              {reviewDone ? (
                <FollowupPanel research={research} onChanged={reload} />
              ) : (
                <LockedPanel title="후속 연구" hint="먼저 연구심사를 받아주세요." />
              )}
              {followupDone ? (
                <FinalOutputPanel research={research} hasPaper={counts.hasPaper} onChanged={reload} />
              ) : (
                <LockedPanel title="최종 산출물" hint="먼저 후속 연구 아이디어를 정리해주세요." />
              )}
            </>
          )}
        </div>

        {showAdvanced && (
          <div className="research-workspace-sidebar">
            <ReportPanel research={research} />
            <FeedbackPanel research={research} />
          </div>
        )}
      </div>
    </div>
  );
}

function TeamPanel({ researchId, team }) {
  return (
    <div className="panel" style={{ marginTop: 14 }}>
      <div className="row" style={{ alignItems: "center", gap: 10 }}>
        <h3 style={{ margin: 0 }}>팀 연구 · {team.members.length}명</h3>
        <div className="spacer" />
        <Link to={`/research/${researchId}/team`} className="btn btn-sm btn-ghost">팀 게시판 →</Link>
      </div>
      <div className="row" style={{ gap: 8, flexWrap: "wrap", marginTop: 8 }}>
        {team.members.map((m) => (
          <span key={m.user_id} className="research-stage-pill">
            {m.name}{m.is_leader ? " · 팀장" : ""}{m.research_role ? ` · ${m.research_role}` : ""}
          </span>
        ))}
      </div>
    </div>
  );
}

const RESEARCH_TYPE_LABEL = {
  experimental: "실험형", literature: "문헌형", survey: "설문조사형",
  development: "개발형", field: "현장형", mixed: "혼합형", custom: "자유형",
};

function LockedPanel({ title, hint }) {
  return (
    <div className="panel" style={{ opacity: 0.65 }}>
      <h3 style={{ margin: "0 0 4px" }}>{title} 🔒</h3>
      <p style={{ fontSize: 13.5, color: "var(--color-text-secondary)", margin: 0 }}>{hint}</p>
    </div>
  );
}

function TodayPanel({ researchId, week, step, isLastWeek, onChanged }) {
  const [busy, setBusy] = useState(null);
  const [advancing, setAdvancing] = useState(false);
  const [error, setError] = useState("");
  const toggle = async (task) => {
    setBusy(task.id);
    try {
      await api.updateResearchTask(researchId, task.id,
        task.status === "completed" ? "todo" : "completed");
      onChanged();
    } finally {
      setBusy(null);
    }
  };

  const allDone = step.tasks.length > 0 && step.tasks.every((t) => t.status === "completed");

  const advanceWeek = async () => {
    setAdvancing(true); setError("");
    try {
      await api.advanceResearchWeek(researchId);
      onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setAdvancing(false);
    }
  };

  return (
    <div className="panel" style={{ background: "var(--color-accent-soft)", border: "1px solid var(--color-primary)" }}>
      <h3 style={{ margin: "0 0 4px" }}>오늘의 연구 — {week}주차 · {step.title}</h3>
      <p style={{ fontSize: 13.5, color: "var(--color-text-secondary)", margin: "0 0 10px" }}>{step.goal}</p>
      <div style={{ display: "grid", gap: 10 }}>
        {step.tasks.map((t) => (
          <div key={t.id}>
            <label className="row" style={{ gap: 8, fontSize: 14, cursor: "pointer" }}>
              <input type="checkbox" checked={t.status === "completed"} disabled={busy === t.id}
                onChange={() => toggle(t)} />
              <span style={{ textDecoration: t.status === "completed" ? "line-through" : "none",
                color: t.status === "completed" ? "var(--color-text-muted)" : "var(--color-text)" }}>
                {t.title}
              </span>
            </label>
            <div style={{ marginLeft: 26 }}>
              <TaskGuideButton researchId={researchId} task={t} onChanged={onChanged} />
            </div>
          </div>
        ))}
      </div>
      {allDone && !isLastWeek && (
        <div style={{ marginTop: 14, paddingTop: 12, borderTop: "1px solid var(--color-border)" }}>
          <p style={{ fontSize: 13, color: "var(--color-secondary-accent)", margin: "0 0 8px" }}>
            이번 주 할 일을 모두 끝냈어요! 🎉
          </p>
          {error && <div className="notice notice-error">{error}</div>}
          <button className="btn btn-sm btn-primary" onClick={advanceWeek} disabled={advancing}>
            {advancing ? "넘어가는 중…" : "다음 주차 시작하기 →"}
          </button>
        </div>
      )}
    </div>
  );
}

function TaskGuideButton({ researchId, task, onChanged }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");

  const request = async () => {
    setBusy(true); setError(""); setProgress(0);
    try {
      const { job_id } = await api.requestTaskGuide(researchId, task.id);
      await api.waitAiJob(job_id, { onTick: (s) => setProgress(estimateAiProgress(s, 3)) });
      setProgress(100);
      setOpen(true);
      onChanged?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ marginTop: 2 }}>
      {task.guide ? (
        <>
          <button type="button" className="btn btn-sm btn-ghost" style={{ padding: "2px 8px", fontSize: 11.5 }}
            onClick={() => setOpen((v) => !v)}>
            {open ? "가이드 접기 ▲" : "가이드 보기 ▼"}
          </button>
          {open && (
            <div style={{ fontSize: 12.5, color: "var(--color-text-secondary)",
              background: "var(--raised)", padding: 10, borderRadius: 8, marginTop: 4 }}>
              <ol style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 4 }}>
                {(task.guide.steps || []).map((s, i) => <li key={i}>{s}</li>)}
              </ol>
              {task.guide.tips && (
                <p style={{ margin: "8px 0 0", color: "var(--color-attention)" }}>💡 {task.guide.tips}</p>
              )}
            </div>
          )}
        </>
      ) : (
        <>
          <button type="button" className="btn btn-sm btn-ghost" style={{ padding: "2px 8px", fontSize: 11.5 }}
            onClick={request} disabled={busy}>
            {busy ? "만드는 중…" : "이 할 일 가이드 받기"}
          </button>
          {busy && <AiGauge percent={progress} />}
        </>
      )}
      {error && <span style={{ fontSize: 11.5, color: "var(--color-danger)", marginLeft: 6 }}>{error}</span>}
    </div>
  );
}

function PlanPanel({ research, onChanged }) {
  const [form, setForm] = useState(research);
  const [busy, setBusy] = useState(false);
  const [draftBusy, setDraftBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");
  // 이미 채워진 내용이 있으면(다시 들어온 경우) 정리 화면부터 보여준다.
  // 처음 들어온 경우에만 질문 하나씩 넘기는 화면으로 시작한다.
  const [stepIdx, setStepIdx] = useState(() =>
    PLAN_FIELDS.some(([k]) => research[k]) ? PLAN_FIELDS.length : 0);

  useEffect(() => setForm(research), [research.id, research.updated_at]);

  const draft = async () => {
    setDraftBusy(true); setError(""); setProgress(0);
    try {
      const { job_id } = await api.requestResearchPlan(research.id);
      await api.waitAiJob(job_id, { onTick: (s) => setProgress(estimateAiProgress(s, 3)) });
      setProgress(100);
      onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setDraftBusy(false);
    }
  };

  const save = async () => {
    setBusy(true); setError("");
    try {
      const body = {};
      PLAN_FIELDS.forEach(([k]) => { body[k] = form[k]; });
      await api.updateResearch(research.id, body);
      onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    setBusy(true); setError("");
    try {
      await save();
      await api.confirmResearchPlan(research.id);
      onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const goNext = async () => {
    await save();
    setStepIdx((i) => Math.min(i + 1, PLAN_FIELDS.length));
  };

  const summaryDone = stepIdx >= PLAN_FIELDS.length;

  return (
    <div className="panel">
      <h3>연구 계획</h3>
      <div className="row" style={{ alignItems: "center", gap: 10, marginBottom: 4 }}>
        <p style={{ fontSize: 13.5, color: "var(--color-text-secondary)", margin: 0 }}>
          막히면 AI가 예시를 채워드려요. 초안은 시작점일 뿐이니 꼭 직접 검토하고 고쳐주세요.
        </p>
        <button className="btn btn-sm btn-ghost" onClick={draft} disabled={draftBusy || busy}>
          {draftBusy ? "만드는 중…" : "AI 예시 받기"}
        </button>
      </div>
      {draftBusy && <AiGauge percent={progress} />}
      {error && <div className="notice notice-error">{error}</div>}

      {!summaryDone ? (
        <div style={{ display: "grid", gap: 10, marginTop: 10 }}>
          <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
            {stepIdx + 1} / {PLAN_FIELDS.length}
          </span>
          {(() => {
            const [key, , question, help] = PLAN_FIELDS[stepIdx];
            return (
              <div className="field">
                <label className="label">{question}</label>
                {help && (
                  <p style={{ fontSize: 12.5, color: "var(--color-text-muted)", margin: "2px 0 6px" }}>{help}</p>
                )}
                <textarea className="textarea" value={form[key] || ""} style={{ minHeight: 80 }}
                  onChange={(e) => setForm({ ...form, [key]: e.target.value })} autoFocus />
              </div>
            );
          })()}
          <div className="row" style={{ gap: 8 }}>
            {stepIdx > 0 && (
              <button className="btn btn-sm btn-ghost" onClick={() => setStepIdx((i) => Math.max(i - 1, 0))}
                disabled={busy}>
                이전
              </button>
            )}
            <button className="btn btn-sm btn-primary" onClick={goNext} disabled={busy}>
              {stepIdx === PLAN_FIELDS.length - 1 ? "계획 정리하기" : "다음"}
            </button>
          </div>
        </div>
      ) : (
        <div style={{ display: "grid", gap: 10, marginTop: 10 }}>
          {PLAN_FIELDS.map(([key, , question], i) => (
            <div key={key} className="field"
              style={{ borderBottom: "1px solid var(--color-border)", paddingBottom: 8 }}>
              <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <label className="label">{question}</label>
                  <p style={{ margin: "2px 0 0", fontSize: 13.5, whiteSpace: "pre-wrap" }}>
                    {form[key] || "(비어 있음)"}
                  </p>
                </div>
                <button className="btn btn-sm btn-ghost" onClick={() => setStepIdx(i)} disabled={busy}>
                  고치기
                </button>
              </div>
            </div>
          ))}
          <div className="row" style={{ gap: 8 }}>
            <button className="btn btn-sm" onClick={save} disabled={busy}>저장</button>
            {research.current_stage === "question" && (
              <button className="btn btn-sm btn-primary" onClick={confirm} disabled={busy}>
                계획 확정하고 로드맵 만들기
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function RoadmapPanel({ researchId, roadmap, onChanged }) {
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");

  const generate = async () => {
    if (roadmap.length > 0 && !window.confirm("기존 로드맵을 새로 만든 것으로 바꿉니다. 계속할까요?")) return;
    setBusy(true); setError(""); setProgress(0);
    try {
      const { job_id } = await api.requestResearchRoadmap(researchId);
      await api.waitAiJob(job_id, { onTick: (s) => setProgress(estimateAiProgress(s, 5)) });
      setProgress(100);
      onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel">
      <div className="row" style={{ marginBottom: 8 }}>
        <h3 style={{ margin: 0 }}>연구 로드맵</h3>
        <div className="spacer" />
        <button className="btn btn-sm" onClick={generate} disabled={busy}>
          {busy ? "만드는 중…" : roadmap.length > 0 ? "다시 만들기" : "로드맵 만들기"}
        </button>
      </div>
      {busy && <AiGauge percent={progress} />}
      {error && <div className="notice notice-error">{error}</div>}
      {roadmap.length === 0 ? (
        <p style={{ fontSize: 13.5, color: "var(--color-text-secondary)" }}>
          아직 로드맵이 없습니다. 연구 기간을 주차별 할 일로 나눠드려요.
        </p>
      ) : (
        <div style={{ display: "grid", gap: 10 }}>
          {roadmap.map((s) => (
            <div key={s.id} style={{ borderLeft: "3px solid var(--color-border)", paddingLeft: 12 }}>
              <div className="row" style={{ gap: 6 }}>
                <b>{s.week_number}주차</b>
                <span style={{ fontSize: 13.5 }}>{s.title}</span>
              </div>
              <p style={{ fontSize: 12.5, color: "var(--color-text-secondary)", margin: "2px 0 4px" }}>
                {s.goal}
              </p>
              <div style={{ display: "grid", gap: 4 }}>
                {s.tasks.map((t) => (
                  <div key={t.id}>
                    <div style={{ fontSize: 12.5, color: "var(--color-text-muted)",
                      textDecoration: t.status === "completed" ? "line-through" : "none" }}>
                      • {t.title}
                    </div>
                    <div style={{ marginLeft: 12 }}>
                      <TaskGuideButton researchId={researchId} task={t} onChanged={onChanged} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function scholarSearchUrl(title) {
  return `https://scholar.google.com/scholar?q=${encodeURIComponent(title)}`;
}

// 참고문헌에 제대로 실릴 수 있는 최소한(제목·저자·연도·출처)이 채워져야
// "확인했어요"를 누를 수 있게 한다 — 링크는 「선택」이라 빼 둔다.
function literatureReadyToVerify(l) {
  return !!(l.title?.trim() && l.author?.trim() && l.year?.trim() && l.source?.trim());
}

function LiteraturePanel({ research, onChanged }) {
  const [items, setItems] = useState(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ title: "", author: "", url: "", stance: "uncertain" });
  const [pendingFile, setPendingFile] = useState(null);
  const [copiedId, setCopiedId] = useState(null);
  const [editingId, setEditingId] = useState(null);
  const [editForm, setEditForm] = useState({});

  const load = () => api.listResearchLiterature(research.id).then((r) => { setItems(r.items); onChanged?.(); })
    .catch((e) => setError(e.message));

  const startEdit = (l) => {
    setEditingId(l.id);
    setEditForm({ title: l.title, author: l.author, year: l.year, source: l.source, url: l.url });
  };

  const saveEdit = async (litId) => {
    setBusy(true); setError("");
    try {
      await api.updateResearchLiterature(research.id, litId, editForm);
      setEditingId(null);
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const copyCitation = async (l) => {
    try {
      await navigator.clipboard.writeText(l.citation);
      setCopiedId(l.id);
      setTimeout(() => setCopiedId(null), 1600);
    } catch {
      setError("복사하지 못했습니다. 직접 선택해서 복사해주세요.");
    }
  };
  useEffect(() => { load(); }, [research.id]);

  const suggest = async () => {
    setBusy(true); setError(""); setProgress(0);
    try {
      const { job_id } = await api.suggestResearchLiterature(research.id);
      await api.waitAiJob(job_id, { onTick: (s) => setProgress(estimateAiProgress(s, 4)) });
      setProgress(100);
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const addManual = async () => {
    if (!form.title.trim()) return;
    setBusy(true); setError("");
    try {
      const created = await api.addResearchLiterature(research.id, form);
      if (pendingFile) await api.attachResearchLiteratureFile(research.id, created.id, pendingFile);
      setForm({ title: "", author: "", url: "", stance: "uncertain" });
      setPendingFile(null);
      setAdding(false);
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const verify = async (litId) => {
    await api.verifyResearchLiterature(research.id, litId);
    load();
  };

  const remove = async (litId) => {
    await api.deleteResearchLiterature(research.id, litId);
    load();
  };

  const attachFile = async (litId, file) => {
    setBusy(true); setError("");
    try {
      await api.attachResearchLiteratureFile(research.id, litId, file);
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const removeFile = async (litId) => {
    await api.removeResearchLiteratureFile(research.id, litId);
    load();
  };

  return (
    <div className="panel">
      <div className="row" style={{ marginBottom: 8 }}>
        <h3 style={{ margin: 0 }}>참고 자료</h3>
        <div className="spacer" />
        <button className="btn btn-sm btn-ghost" onClick={() => setAdding((v) => !v)}>직접 추가</button>
        <button className="btn btn-sm" onClick={suggest} disabled={busy} style={{ marginLeft: 6 }}>
          {busy ? "찾는 중…" : "AI 추천받기"}
        </button>
      </div>
      {busy && <AiGauge percent={progress} />}
      {error && <div className="notice notice-error">{error}</div>}
      {adding && (
        <div style={{ display: "grid", gap: 8, marginBottom: 12, padding: 12, border: "1px solid var(--color-border)", borderRadius: "var(--radius)" }}>
          <input className="input" placeholder="제목" value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })} />
          <input className="input" placeholder="저자(선택)" value={form.author}
            onChange={(e) => setForm({ ...form, author: e.target.value })} />
          <input className="input" placeholder="링크(선택, https://…)" value={form.url}
            onChange={(e) => setForm({ ...form, url: e.target.value })} />
          <label className="label" style={{ margin: 0 }}>
            파일 첨부(선택 · PDF/HWP/DOC/이미지)
            <input type="file" accept=".pdf,.hwp,.hwpx,.doc,.docx,image/jpeg,image/png"
              style={{ display: "block", marginTop: 4 }}
              onChange={(e) => setPendingFile(e.target.files?.[0] || null)} />
          </label>
          <button className="btn btn-sm btn-primary" onClick={addManual} disabled={busy}
            style={{ width: "fit-content" }}>추가</button>
        </div>
      )}
      {!items ? <p>불러오는 중…</p> : items.length === 0 ? (
        <p style={{ fontSize: 13.5, color: "var(--color-text-secondary)" }}>
          아직 등록된 자료가 없습니다.
        </p>
      ) : (
        <div style={{ display: "grid", gap: 10 }}>
          {items.map((l) => (
            <div key={l.id} style={{ borderLeft: "3px solid var(--color-border)", paddingLeft: 12 }}>
              {editingId === l.id ? (
                <div style={{ display: "grid", gap: 6, maxWidth: 420 }}>
                  <input className="input" placeholder="제목" value={editForm.title || ""}
                    onChange={(e) => setEditForm({ ...editForm, title: e.target.value })} />
                  <input className="input" placeholder="저자" value={editForm.author || ""}
                    onChange={(e) => setEditForm({ ...editForm, author: e.target.value })} />
                  <div className="row" style={{ gap: 6 }}>
                    <input className="input" placeholder="연도(예: 2024)" value={editForm.year || ""}
                      onChange={(e) => setEditForm({ ...editForm, year: e.target.value })} />
                    <input className="input" placeholder="출처(예: 학술지·기관명)" value={editForm.source || ""}
                      onChange={(e) => setEditForm({ ...editForm, source: e.target.value })} />
                  </div>
                  <input className="input" placeholder="링크(선택, https://…)" value={editForm.url || ""}
                    onChange={(e) => setEditForm({ ...editForm, url: e.target.value })} />
                  <div className="row" style={{ gap: 6 }}>
                    <button className="btn btn-sm btn-primary" onClick={() => saveEdit(l.id)} disabled={busy}>저장</button>
                    <button className="btn btn-sm btn-ghost" onClick={() => setEditingId(null)}>취소</button>
                  </div>
                </div>
              ) : (
                <>
                  <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
                    <b style={{ fontSize: 13.5 }}>{l.title}</b>
                    <span className="badge">{STANCE_LABEL[l.stance] || l.stance}</span>
                    {l.ai_suggested && !l.verified && (
                      <span className="badge" style={{ background: "var(--color-attention-soft)", color: "var(--color-attention)" }}>
                        AI 제안 · 확인 필요
                      </span>
                    )}
                    {l.verified && <span className="badge" style={{ background: "var(--color-success-bg)", color: "var(--color-success)" }}>확인함</span>}
                  </div>
                  {l.author && <p style={{ fontSize: 12.5, color: "var(--color-text-muted)", margin: "2px 0" }}>{l.author}</p>}
                  {l.summary && <p style={{ fontSize: 12.5, color: "var(--color-text-secondary)", margin: "2px 0" }}>{l.summary}</p>}
                  {!l.verified && !literatureReadyToVerify(l) && (
                    <p style={{ fontSize: 11.5, color: "var(--color-attention)", margin: "2px 0" }}>
                      저자·연도·출처를 모두 채워야 "확인했어요"를 누를 수 있어요 — 실제로 확인한 값으로 "수정"에서 채워주세요.
                    </p>
                  )}
                  <div className="row" style={{ gap: 8, marginTop: 4 }}>
                    <span style={{ fontSize: 12, color: "var(--color-text-muted)", fontStyle: "italic" }}>{l.citation}</span>
                    <button className="btn btn-sm btn-ghost" style={{ padding: "1px 7px", fontSize: 11.5 }}
                      onClick={() => copyCitation(l)}>
                      {copiedId === l.id ? "복사됨 ✓" : "인용 복사"}
                    </button>
                  </div>
                  <div className="row" style={{ gap: 10, flexWrap: "wrap", marginTop: 4, fontSize: 12.5 }}>
                    {l.url ? (
                      <a href={l.url} target="_blank" rel="noreferrer" style={{ color: "var(--color-primary)" }}>
                        바로 가기 ↗
                      </a>
                    ) : (
                      <a href={scholarSearchUrl(l.title)} target="_blank" rel="noreferrer" style={{ color: "var(--color-text-secondary)" }}>
                        학술 검색에서 찾아보기 ↗
                      </a>
                    )}
                    {l.file_name ? (
                      <>
                        <a href={l.file_url} target="_blank" rel="noreferrer" style={{ color: "var(--color-primary)" }}>
                          📎 {l.file_name}
                        </a>
                        <button className="btn btn-sm btn-ghost" onClick={() => removeFile(l.id)} disabled={busy}>
                          첨부 삭제
                        </button>
                      </>
                    ) : (
                      <label className="btn btn-sm btn-ghost" style={{ cursor: "pointer" }}>
                        파일 첨부
                        <input type="file" accept=".pdf,.hwp,.hwpx,.doc,.docx,image/jpeg,image/png"
                          style={{ display: "none" }} disabled={busy}
                          onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) attachFile(l.id, f); }} />
                      </label>
                    )}
                  </div>
                  <div className="row" style={{ gap: 6, marginTop: 4 }}>
                    {!l.verified && (
                      <button className="btn btn-sm btn-ghost" onClick={() => verify(l.id)}
                        disabled={!literatureReadyToVerify(l)}
                        title={literatureReadyToVerify(l) ? "" : "저자·연도·출처를 먼저 채워주세요"}>
                        실제로 확인했어요
                      </button>
                    )}
                    <button className="btn btn-sm btn-ghost" onClick={() => startEdit(l)}>수정</button>
                    <button className="btn btn-sm btn-ghost" onClick={() => remove(l.id)}>삭제</button>
                  </div>
                </>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const BLANK_GRID_COLS = ["", ""];
const BLANK_GRID_ROWS = [["", ""], ["", ""], ["", ""]];

function DataAnalysisPanel({ research, onChanged }) {
  const [items, setItems] = useState(null);
  const [analyses, setAnalyses] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [adding, setAdding] = useState(false);
  const [addingText, setAddingText] = useState(false);
  const [title, setTitle] = useState("");
  const [textTitle, setTextTitle] = useState("");
  const [textValue, setTextValue] = useState("");
  const [gridCols, setGridCols] = useState(BLANK_GRID_COLS);
  const [gridRows, setGridRows] = useState(BLANK_GRID_ROWS);
  const [direction, setDirection] = useState(null);
  const [directionBusy, setDirectionBusy] = useState(false);
  const [directionProgress, setDirectionProgress] = useState(0);
  const [analyzeBusy, setAnalyzeBusy] = useState(false);
  const [analyzeProgress, setAnalyzeProgress] = useState(0);

  const load = () => {
    api.listResearchData(research.id).then((r) => setItems(r.items)).catch((e) => setError(e.message));
    api.listResearchAnalysis(research.id).then((r) => { setAnalyses(r.items); onChanged?.(); }).catch(() => setAnalyses([]));
  };
  useEffect(() => { load(); }, [research.id]);

  const requestDirection = async () => {
    setDirectionBusy(true); setError(""); setDirectionProgress(0);
    try {
      const { job_id } = await api.requestResearchDataDirection(research.id);
      const result = await api.waitAiJob(job_id, { onTick: (s) => setDirectionProgress(estimateAiProgress(s, 4)) });
      setDirectionProgress(100);
      setDirection(result);
    } catch (e) {
      setError(e.message);
    } finally {
      setDirectionBusy(false);
    }
  };

  const addColumn = () => {
    setGridCols([...gridCols, ""]);
    setGridRows(gridRows.map((r) => [...r, ""]));
  };
  const removeColumn = (ci) => {
    if (gridCols.length <= 1) return;
    setGridCols(gridCols.filter((_, i) => i !== ci));
    setGridRows(gridRows.map((r) => r.filter((_, i) => i !== ci)));
  };
  const addRow = () => setGridRows([...gridRows, gridCols.map(() => "")]);
  const removeRow = (ri) => {
    if (gridRows.length <= 1) return;
    setGridRows(gridRows.filter((_, i) => i !== ri));
  };
  const updateCell = (ri, ci, value) => {
    setGridRows(gridRows.map((r, i) => (i === ri ? r.map((c, j) => (j === ci ? value : c)) : r)));
  };
  const updateColumnName = (ci, value) => {
    setGridCols(gridCols.map((c, i) => (i === ci ? value : c)));
  };

  // 엑셀·구글 시트에서 셀 범위를 복사해 붙여넣으면(탭/줄바꿈으로 구분된
  // 텍스트) 표가 모자란 만큼 열·행을 늘려가며 그대로 채워 넣는다.
  const handlePaste = (e, startRow, startCol) => {
    const text = e.clipboardData.getData("text");
    if (!text.includes("\t") && !text.includes("\n")) return; // 칸 하나짜리 붙여넣기는 기본 동작에 맡긴다
    e.preventDefault();
    const pasted = text.replace(/\r/g, "").split("\n").filter((l) => l !== "").map((l) => l.split("\t"));
    if (pasted.length === 0) return;
    const neededCols = Math.max(gridCols.length, startCol + Math.max(...pasted.map((r) => r.length)));
    const neededRows = Math.max(gridRows.length, startRow + pasted.length);

    const newCols = [...gridCols];
    while (newCols.length < neededCols) newCols.push("");

    const newRows = [];
    for (let i = 0; i < neededRows; i++) {
      const base = gridRows[i] ? [...gridRows[i]] : [];
      while (base.length < neededCols) base.push("");
      newRows.push(base);
    }
    pasted.forEach((r, ri) => r.forEach((val, ci) => { newRows[startRow + ri][startCol + ci] = val; }));

    setGridCols(newCols);
    setGridRows(newRows);
  };

  const addTable = async () => {
    const columns = gridCols.map((c) => c.trim());
    const columnsValid = columns.length > 0 && columns.every((c) => c);
    const rows = gridRows.map((r) => r.map((c) => c.trim())).filter((r) => r.some((c) => c !== ""));
    if (!title.trim() || !columnsValid || rows.length === 0) {
      return setError("제목, 모든 열 이름, 값을 입력해주세요.");
    }
    setBusy(true); setError("");
    try {
      await api.addResearchData(research.id, { title, columns, rows });
      setTitle(""); setGridCols(BLANK_GRID_COLS); setGridRows(BLANK_GRID_ROWS); setAdding(false);
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const addText = async () => {
    if (!textTitle.trim() || !textValue.trim()) {
      return setError("제목과 내용을 입력해주세요.");
    }
    setBusy(true); setError("");
    try {
      await api.addResearchData(research.id, { title: textTitle, text: textValue });
      setTextTitle(""); setTextValue(""); setAddingText(false);
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const uploadImage = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setBusy(true); setError("");
    try {
      await api.uploadResearchDataImage(research.id, file);
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (dataId) => {
    await api.deleteResearchData(research.id, dataId);
    load();
  };

  const analyze = async () => {
    setAnalyzeBusy(true); setError(""); setAnalyzeProgress(0);
    try {
      const { job_id } = await api.requestResearchAnalysis(research.id);
      await api.waitAiJob(job_id, { onTick: (s) => setAnalyzeProgress(estimateAiProgress(s, 3)) });
      setAnalyzeProgress(100);
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setAnalyzeBusy(false);
    }
  };

  return (
    <div className="panel">
      <div className="row" style={{ marginBottom: 8 }}>
        <h3 style={{ margin: 0 }}>연구 데이터·분석</h3>
        <div className="spacer" />
        <label className="btn btn-sm btn-ghost" style={{ cursor: "pointer" }}>
          사진 올리기
          <input type="file" accept="image/png,image/jpeg,image/webp,image/gif" onChange={uploadImage}
            style={{ display: "none" }} disabled={busy} />
        </label>
        <button className="btn btn-sm btn-ghost" onClick={() => setAdding((v) => !v)} style={{ marginLeft: 6 }}>
          표 데이터 추가
        </button>
        <button className="btn btn-sm btn-ghost" onClick={() => setAddingText((v) => !v)} style={{ marginLeft: 6 }}>
          텍스트로 입력
        </button>
        <button className="btn btn-sm" onClick={analyze} disabled={analyzeBusy} style={{ marginLeft: 6 }}>
          {analyzeBusy ? "분석 중…" : "분석하기"}
        </button>
      </div>
      {analyzeBusy && <div className="row" style={{ justifyContent: "flex-end" }}><AiGauge percent={analyzeProgress} /></div>}
      <div style={{ marginBottom: 12, padding: 12, background: "var(--color-accent-soft)", borderRadius: "var(--radius)" }}>
        <div className="row" style={{ gap: 8 }}>
          <span style={{ fontSize: 13, fontWeight: 600 }}>무엇을 어떻게 모으면 좋을지 모르겠나요?</span>
          <div className="spacer" />
          <button className="btn btn-sm" onClick={requestDirection} disabled={directionBusy}>
            {directionBusy ? "생각하는 중…" : direction ? "다시 추천받기" : "연구 방향 추천받기"}
          </button>
        </div>
        {directionBusy && <div className="row" style={{ justifyContent: "flex-end" }}><AiGauge percent={directionProgress} /></div>}
        {direction && (
          <div style={{ display: "grid", gap: 6, marginTop: 10, fontSize: 13 }}>
            <div><b>방향</b> — {direction.direction}</div>
            <div><b>무엇을 모을까</b> — {direction.what_to_collect}</div>
            <div><b>어떻게 모을까</b> — {direction.how_to_collect}</div>
            <div><b>이후 분석 제안</b> — {direction.suggested_analysis}</div>
          </div>
        )}
      </div>
      {error && <div className="notice notice-error">{error}</div>}
      {adding && (
        <div style={{ display: "grid", gap: 8, marginBottom: 12, padding: 12, border: "1px solid var(--color-border)", borderRadius: "var(--radius)" }}>
          <input className="input" placeholder="제목(예: 잔반량 측정)" value={title}
            onChange={(e) => setTitle(e.target.value)} />
          <p style={{ fontSize: 12, color: "var(--color-text-muted)", margin: 0 }}>
            엑셀·구글 시트에서 표를 복사해 셀에 붙여넣으면 그대로 채워져요.
          </p>
          <div style={{ overflowX: "auto" }}>
            <table style={{ borderCollapse: "collapse", width: "100%" }}>
              <thead>
                <tr>
                  {gridCols.map((c, ci) => (
                    <th key={ci} style={{ border: "1px solid var(--color-border)", padding: 2, minWidth: 110 }}>
                      <div className="row" style={{ gap: 2 }}>
                        <input className="input" style={{ fontSize: 12.5, padding: "5px 6px", fontWeight: 600 }}
                          value={c} placeholder={`열 ${ci + 1} 이름`}
                          onChange={(e) => updateColumnName(ci, e.target.value)} />
                        {gridCols.length > 1 && (
                          <button type="button" className="btn btn-sm btn-ghost" style={{ padding: "2px 6px" }}
                            onClick={() => removeColumn(ci)} title="열 삭제">×</button>
                        )}
                      </div>
                    </th>
                  ))}
                  <th style={{ border: "none", padding: 2, width: 32 }}>
                    <button type="button" className="btn btn-sm btn-ghost" style={{ padding: "5px 8px" }}
                      onClick={addColumn} title="열 추가">+</button>
                  </th>
                </tr>
              </thead>
              <tbody>
                {gridRows.map((row, ri) => (
                  <tr key={ri}>
                    {row.map((cell, ci) => (
                      <td key={ci} style={{ border: "1px solid var(--color-border)", padding: 2 }}>
                        <input className="input" style={{ fontSize: 12.5, padding: "5px 6px" }} value={cell}
                          onPaste={(e) => handlePaste(e, ri, ci)}
                          onChange={(e) => updateCell(ri, ci, e.target.value)} />
                      </td>
                    ))}
                    <td style={{ border: "none", padding: 2, textAlign: "center" }}>
                      {gridRows.length > 1 && (
                        <button type="button" className="btn btn-sm btn-ghost" style={{ padding: "2px 6px" }}
                          onClick={() => removeRow(ri)} title="행 삭제">×</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button type="button" className="btn btn-sm btn-ghost" onClick={addRow} style={{ width: "fit-content" }}>
            + 행 추가
          </button>
          <button className="btn btn-sm btn-primary" onClick={addTable} disabled={busy} style={{ width: "fit-content" }}>추가</button>
        </div>
      )}
      {addingText && (
        <div style={{ display: "grid", gap: 8, marginBottom: 12, padding: 12, border: "1px solid var(--color-border)", borderRadius: "var(--radius)" }}>
          <input className="input" placeholder="제목(예: 관찰한 내용)" value={textTitle}
            onChange={(e) => setTextTitle(e.target.value)} />
          <textarea className="textarea" rows={5} placeholder="표로 정리하기 어려운 관찰·메모를 자유롭게 적어주세요."
            value={textValue} onChange={(e) => setTextValue(e.target.value)} />
          <button className="btn btn-sm btn-primary" onClick={addText} disabled={busy} style={{ width: "fit-content" }}>추가</button>
        </div>
      )}
      {!items ? <p>불러오는 중…</p> : items.length === 0 ? (
        <p style={{ fontSize: 13.5, color: "var(--color-text-secondary)" }}>
          아직 등록된 데이터가 없습니다. 실제로 측정·수집한 값만 넣어주세요.
        </p>
      ) : (
        <div style={{ display: "grid", gap: 8, marginBottom: 12 }}>
          {items.map((d) => (
            <div key={d.id} className="row" style={{ gap: 8, fontSize: 13.5, alignItems: "flex-start" }}>
              <span className="badge">{d.data_type === "image" ? "사진" : d.data_type === "text" ? "텍스트" : "표"}</span>
              <div style={{ minWidth: 0 }}>
                <div>{d.title}</div>
                {d.data_type === "table" && d.content.columns && (
                  <span style={{ color: "var(--color-text-muted)", fontSize: 12 }}>
                    ({d.content.columns.join(", ")} · {d.content.rows.length}행)
                  </span>
                )}
                {d.data_type === "text" && d.content.text && (
                  <p style={{ color: "var(--color-text-muted)", fontSize: 12.5, margin: "2px 0 0", whiteSpace: "pre-wrap" }}>
                    {d.content.text}
                  </p>
                )}
              </div>
              <div className="spacer" />
              <button className="btn btn-sm btn-ghost" onClick={() => remove(d.id)}>삭제</button>
            </div>
          ))}
        </div>
      )}
      {analyses && analyses.length > 0 && (
        <div style={{ display: "grid", gap: 10, borderTop: "1px solid var(--color-border)", paddingTop: 10 }}>
          {analyses.map((a) => (
            <div key={a.id}>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 8, marginBottom: 6 }}>
                {Object.entries(a.stats).map(([key, s]) => (
                  <div key={key} style={{ fontSize: 12, background: "var(--raised)", padding: 8, borderRadius: 8 }}>
                    <div style={{ fontWeight: 600, marginBottom: 2 }}>{key}</div>
                    평균 {s.mean} · 표준편차 {s.stdev} · n={s.count}
                  </div>
                ))}
              </div>
              <p style={{ fontSize: 13.5, margin: "0 0 4px" }}>{a.interpretation}</p>
              <p style={{ fontSize: 12.5, color: "var(--color-text-secondary)", margin: 0 }}>
                다음 분석 제안: {a.method_suggestion}
              </p>
              {a.low_data_note && (
                <p style={{ fontSize: 12.5, color: "var(--color-attention)", margin: "4px 0 0" }}>
                  ⚠ {a.low_data_note}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ReviewPanel({ research, onChanged }) {
  const [items, setItems] = useState(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");

  const load = () => api.listResearchReview(research.id).then((r) => { setItems(r.items); onChanged?.(); })
    .catch((e) => setError(e.message));
  useEffect(() => { load(); }, [research.id]);

  const request = async () => {
    setBusy(true); setError(""); setProgress(0);
    try {
      const { job_id } = await api.requestResearchReview(research.id);
      await api.waitAiJob(job_id, { onTick: (s) => setProgress(estimateAiProgress(s, 5)) });
      setProgress(100);
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel">
      <div className="row" style={{ marginBottom: 8 }}>
        <h3 style={{ margin: 0 }}>연구심사</h3>
        <div className="spacer" />
        <button className="btn btn-sm" onClick={request} disabled={busy}>
          {busy ? "검토 중…" : "연구심사 받기"}
        </button>
      </div>
      {busy && <div className="row" style={{ justifyContent: "flex-end" }}><AiGauge percent={progress} /></div>}
      <p style={{ fontSize: 12.5, color: "var(--color-text-muted)", margin: "0 0 10px" }}>
        AI가 지금까지의 연구에서 논리적으로 약한 부분을 찾아드려요. 학생을 평가하는 게 아니라 연구 자체를 검토합니다.
      </p>
      {error && <div className="notice notice-error">{error}</div>}
      {items && items[0] && (
        <div style={{ display: "grid", gap: 8 }}>
          {items[0].findings.map((f, i) => (
            <div key={i} style={{ borderLeft: "3px solid var(--color-attention)", paddingLeft: 10 }}>
              <b style={{ fontSize: 13 }}>{f.area}</b>
              <p style={{ fontSize: 13, margin: "2px 0 0" }}>{f.concern}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function FollowupPanel({ research, onChanged }) {
  const [text, setText] = useState(research.follow_up_ideas || "");
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");

  useEffect(() => setText(research.follow_up_ideas || ""), [research.follow_up_ideas]);

  const draft = async () => {
    setBusy(true); setError(""); setProgress(0);
    try {
      const { job_id } = await api.requestResearchFollowup(research.id);
      await api.waitAiJob(job_id, { onTick: (s) => setProgress(estimateAiProgress(s, 3)) });
      setProgress(100);
      onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    setBusy(true); setError("");
    try {
      await api.updateResearch(research.id, { follow_up_ideas: text });
      onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel">
      <h3>후속 연구</h3>
      {!text ? (
        <>
          <p style={{ fontSize: 13.5, color: "var(--color-text-secondary)" }}>
            이번 연구에서 이어서 해볼 만한 다음 연구를 AI가 제안해드려요.
          </p>
          <button className="btn btn-sm" onClick={draft} disabled={busy}>
            {busy ? "만드는 중…" : "제안받기"}
          </button>
        </>
      ) : (
        <div style={{ display: "grid", gap: 8 }}>
          <textarea className="textarea" value={text} onChange={(e) => setText(e.target.value)}
            style={{ minHeight: 80 }} />
          {error && <div className="notice notice-error">{error}</div>}
          <button className="btn btn-sm" onClick={save} disabled={busy} style={{ width: "fit-content" }}>저장</button>
        </div>
      )}
    </div>
  );
}

const REPORT_TYPE_LABEL = { weekly: "주간", midterm: "중간", final: "최종" };

function ReportPanel({ research }) {
  const [items, setItems] = useState(null);
  const [reportType, setReportType] = useState("weekly");
  const [blockers, setBlockers] = useState("");
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");

  const load = () => api.listResearchReports(research.id).then((r) => setItems(r.items)).catch((e) => setError(e.message));
  useEffect(() => { load(); }, [research.id]);

  const request = async () => {
    setBusy(true); setError(""); setProgress(0);
    try {
      const { job_id } = await api.requestResearchReport(research.id, reportType, blockers);
      await api.waitAiJob(job_id, { onTick: (s) => setProgress(estimateAiProgress(s, 3)) });
      setProgress(100);
      setBlockers("");
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel">
      <h3>중간 리포트</h3>
      <div style={{ display: "grid", gap: 8, marginBottom: 14, padding: 12, border: "1px solid var(--color-border)", borderRadius: "var(--radius)" }}>
        <div className="row" style={{ gap: 6 }}>
          {Object.entries(REPORT_TYPE_LABEL).map(([k, label]) => (
            <button key={k} className={`btn btn-sm ${reportType === k ? "" : "btn-ghost"}`}
              onClick={() => setReportType(k)}>{label}</button>
          ))}
        </div>
        <textarea className="textarea" placeholder="막힌 부분이 있으면 적어주세요(선택)"
          value={blockers} onChange={(e) => setBlockers(e.target.value)} style={{ minHeight: 50 }} />
        <button className="btn btn-sm btn-primary" onClick={request} disabled={busy} style={{ width: "fit-content" }}>
          {busy ? "만드는 중…" : "리포트 만들기"}
        </button>
        {busy && <AiGauge percent={progress} />}
      </div>
      {error && <div className="notice notice-error">{error}</div>}
      {!items ? <p>불러오는 중…</p> : items.length === 0 ? (
        <p style={{ fontSize: 13.5, color: "var(--color-text-secondary)" }}>아직 만든 리포트가 없습니다.</p>
      ) : (
        <div style={{ display: "grid", gap: 14 }}>
          {items.map((rp) => (
            <div key={rp.id} style={{ borderLeft: "3px solid var(--color-primary)", paddingLeft: 12 }}>
              <div className="row" style={{ gap: 6, marginBottom: 4 }}>
                <span className="badge">{REPORT_TYPE_LABEL[rp.report_type] || rp.report_type}</span>
                <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
                  {rp.period_start} ~ {rp.period_end}
                </span>
              </div>
              <p style={{ fontSize: 13.5, margin: "2px 0" }}>{rp.summary}</p>
              {rp.completed_tasks.length > 0 && (
                <p style={{ fontSize: 12.5, color: "var(--color-text-secondary)", margin: "2px 0" }}>
                  완료: {rp.completed_tasks.join(", ")}
                </p>
              )}
              {rp.blockers && (
                <p style={{ fontSize: 12.5, color: "var(--color-attention)", margin: "2px 0" }}>
                  막힌 부분: {rp.blockers}
                </p>
              )}
              <p style={{ fontSize: 12.5, color: "var(--color-primary)", margin: "2px 0" }}>{rp.ai_feedback}</p>
              <p style={{ fontSize: 12.5, color: "var(--color-text-secondary)", margin: "2px 0" }}>
                다음: {rp.next_steps}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function FeedbackPanel({ research }) {
  const [items, setItems] = useState(null);

  useEffect(() => {
    api.listResearchFeedback(research.id).then((r) => setItems(r.items)).catch(() => setItems([]));
  }, [research.id]);

  if (!items || items.length === 0) return null;

  return (
    <div className="panel">
      <h3>선생님 피드백</h3>
      <div style={{ display: "grid", gap: 8 }}>
        {items.map((f) => (
          <div key={f.id} style={{ borderLeft: "3px solid var(--color-secondary-accent)", paddingLeft: 10 }}>
            <p style={{ fontSize: 13.5, margin: 0 }}>{f.content}</p>
            <span style={{ fontSize: 11.5, color: "var(--color-text-muted)" }}>
              {new Date(f.created_at).toLocaleDateString("ko-KR")}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** 논문과 포트폴리오는 서로 다른 표(ResearchPaper/ResearchPortfolio)로
 *  그대로 남겨 둔다(§22 — 데이터 통합이 아니라 화면 흐름만 정리하면 된다).
 *  같은 연구의 두 가지 모습("학교 제출용 정식 문서" · "친구에게 공유하는
 *  읽기 편한 버전")이라는 게 학생에게 한눈에 보이도록 탭 하나로 묶는다.
 *  예전엔 두 개의 별도 잠금 패널이라 "이거 두 개 다 써야 하나?"로
 *  헷갈렸다. */
function FinalOutputPanel({ research, hasPaper, onChanged }) {
  const [tab, setTab] = useState("paper");

  return (
    <div className="panel">
      <h3 style={{ margin: "0 0 4px" }}>최종 산출물</h3>
      <p style={{ fontSize: 12.5, color: "var(--color-text-muted)", margin: "0 0 12px" }}>
        같은 연구를 두 가지 모습으로 만들어요. <b>논문</b>은 학교에 제출하는 정식 문서이고,
        <b> 포트폴리오</b>는 그 논문을 바탕으로 친구·선생님과 편하게 공유하는 버전이에요.
      </p>
      <div className="row" style={{ gap: 6, marginBottom: 14 }}>
        <button className={`btn btn-sm ${tab === "paper" ? "" : "btn-ghost"}`}
          onClick={() => setTab("paper")}>📄 논문</button>
        <button className={`btn btn-sm ${tab === "portfolio" ? "" : "btn-ghost"}`}
          onClick={() => setTab("portfolio")}>🔗 포트폴리오(공유용)</button>
      </div>

      {tab === "paper"
        ? <PaperTab research={research} onChanged={onChanged} />
        : hasPaper
          ? <PortfolioTab research={research} />
          : (
            <p style={{ fontSize: 13.5, color: "var(--color-text-secondary)" }}>
              포트폴리오는 논문을 바탕으로 만들어요. 먼저 <b>논문</b> 탭에서 초안을 만들어주세요.
            </p>
          )}
    </div>
  );
}

function PaperTab({ research, onChanged }) {
  const [paper, setPaper] = useState(undefined);
  const [references, setReferences] = useState([]);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  const load = () => api.getResearchPaper(research.id)
    .then((r) => { setPaper(r.paper); setReferences(r.references || []); onChanged?.(); })
    .catch((e) => setError(e.message));
  useEffect(() => { load(); }, [research.id]);

  const copyReferences = async () => {
    try {
      await navigator.clipboard.writeText(references.map((r) => r.citation).join("\n"));
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      setError("복사하지 못했습니다. 직접 선택해서 복사해주세요.");
    }
  };

  const draft = async () => {
    if (paper && !window.confirm("기존 초안을 새로 만든 내용으로 덮어씁니다. 계속할까요?")) return;
    setBusy(true); setError(""); setProgress(0);
    try {
      const { job_id } = await api.draftResearchPaper(research.id);
      await api.waitAiJob(job_id, { onTick: (s) => setProgress(estimateAiProgress(s, 12)) });
      setProgress(100);
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const save = async (patch) => {
    try {
      const updated = await api.updateResearchPaper(research.id, patch);
      setPaper(updated);
    } catch (e) {
      setError(e.message);
    }
  };

  const download = async () => {
    try { await api.downloadResearchPaperPdf(research.id); } catch (e) { setError(e.message); }
  };

  return (
    <div>
      <div className="row" style={{ marginBottom: 8 }}>
        <div className="spacer" />
        {paper && <button className="btn btn-sm btn-ghost" onClick={download}>PDF 내려받기</button>}
        <button className="btn btn-sm" onClick={draft} disabled={busy} style={{ marginLeft: 6 }}>
          {busy ? "만드는 중…" : paper ? "다시 만들기" : "논문 초안 만들기"}
        </button>
      </div>
      {busy && <div className="row" style={{ justifyContent: "flex-end" }}><AiGauge percent={progress} /></div>}
      <p style={{ fontSize: 12.5, color: "var(--color-text-muted)", margin: "0 0 10px" }}>
        확인된 참고자료와 실제 분석 결과만 근거로 초안을 만들어요. 만든 뒤 꼭 직접 검토하고 고쳐주세요.
      </p>
      {error && <div className="notice notice-error">{error}</div>}
      {paper === undefined ? <p>불러오는 중…</p> : !paper ? (
        <p style={{ fontSize: 13.5, color: "var(--color-text-secondary)" }}>아직 작성된 논문이 없습니다.</p>
      ) : (
        <div style={{ display: "grid", gap: 12 }}>
          <div className="field">
            <label className="label">제목</label>
            <input className="input" value={paper.title}
              onChange={(e) => setPaper({ ...paper, title: e.target.value })}
              onBlur={() => save({ title: paper.title })} />
          </div>
          <div className="field">
            <label className="label">초록</label>
            <textarea className="textarea" value={paper.abstract} style={{ minHeight: 90 }}
              onChange={(e) => setPaper({ ...paper, abstract: e.target.value })}
              onBlur={() => save({ abstract: paper.abstract })} />
          </div>
          {PAPER_SECTIONS.map(([key, label]) => (
            <div className="field" key={key}>
              <label className="label">{label}</label>
              <textarea className="textarea" value={paper.sections[key] || ""} style={{ minHeight: 200 }}
                onChange={(e) => setPaper({ ...paper, sections: { ...paper.sections, [key]: e.target.value } })}
                onBlur={() => save({ sections: { [key]: paper.sections[key] } })} />
            </div>
          ))}

          <div className="field">
            <div className="row" style={{ gap: 8 }}>
              <label className="label" style={{ margin: 0 }}>참고문헌</label>
              <div className="spacer" />
              {references.length > 0 && (
                <button type="button" className="btn btn-sm btn-ghost" onClick={copyReferences}>
                  {copied ? "복사됨 ✓" : "전체 복사"}
                </button>
              )}
            </div>
            {references.length === 0 ? (
              <p style={{ fontSize: 12.5, color: "var(--color-text-secondary)", margin: "4px 0 0" }}>
                확인된 참고자료가 없어요. 참고 자료를 확인 처리하면 여기 자동으로 나열됩니다.
              </p>
            ) : (
              // 인용 문구 자체에 이미 [1] [2] 번호가 붙어 있어(ol의 자동
              // 번호와 겹치지 않도록) 목록 마커 없는 태그로 감싼다.
              <div style={{ margin: "4px 0 0", display: "grid", gap: 4, fontSize: 13 }}>
                {references.map((ref, i) => (
                  <a key={i} href={ref.url || scholarSearchUrl(ref.title)} target="_blank" rel="noreferrer"
                    style={{ color: ref.url ? "var(--color-primary)" : "var(--color-text-secondary)" }}>
                    {ref.citation}
                  </a>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function PortfolioTab({ research }) {
  const [portfolio, setPortfolio] = useState(undefined);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");

  const load = () => api.getResearchPortfolio(research.id).then((r) => setPortfolio(r.portfolio)).catch((e) => setError(e.message));
  useEffect(() => { load(); }, [research.id]);

  const draft = async () => {
    if (portfolio && !window.confirm("기존 초안을 새로 만든 내용으로 덮어씁니다. 계속할까요?")) return;
    setBusy(true); setError(""); setProgress(0);
    try {
      const { job_id } = await api.draftResearchPortfolio(research.id);
      await api.waitAiJob(job_id, { onTick: (s) => setProgress(estimateAiProgress(s, 6)) });
      setProgress(100);
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const save = async (patch) => {
    try {
      const updated = await api.updateResearchPortfolio(research.id, patch);
      setPortfolio(updated);
    } catch (e) {
      setError(e.message);
    }
  };

  const download = async () => {
    try { await api.downloadResearchPortfolioPdf(research.id); } catch (e) { setError(e.message); }
  };

  const toggleShare = async () => {
    setBusy(true); setError("");
    try {
      if (portfolio.visibility === "shared") await api.unshareResearchPortfolio(research.id);
      else await api.shareResearchPortfolio(research.id);
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const shareUrl = portfolio?.share_token
    ? `${window.location.origin}/research-portfolio-share/${portfolio.share_token}` : "";

  return (
    <div>
      <div className="row" style={{ marginBottom: 8 }}>
        <div className="spacer" />
        {portfolio && <button className="btn btn-sm btn-ghost" onClick={download}>PDF 내려받기</button>}
        <button className="btn btn-sm" onClick={draft} disabled={busy} style={{ marginLeft: 6 }}>
          {busy ? "만드는 중…" : portfolio ? "다시 만들기" : "포트폴리오 초안 만들기"}
        </button>
      </div>
      {busy && <div className="row" style={{ justifyContent: "flex-end" }}><AiGauge percent={progress} /></div>}
      <p style={{ fontSize: 12.5, color: "var(--color-text-muted)", margin: "0 0 10px" }}>
        논문과 달리 학생 본인의 목소리로, 읽기 편하게 정리해요.
      </p>
      {error && <div className="notice notice-error">{error}</div>}
      {portfolio === undefined ? <p>불러오는 중…</p> : !portfolio ? (
        <p style={{ fontSize: 13.5, color: "var(--color-text-secondary)" }}>아직 작성된 포트폴리오가 없습니다.</p>
      ) : (
        <div style={{ display: "grid", gap: 12 }}>
          <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
            <button className={`btn btn-sm ${portfolio.visibility === "shared" ? "" : "btn-ghost"}`}
              onClick={toggleShare} disabled={busy}>
              {portfolio.visibility === "shared" ? "공유 끄기" : "공유 링크 만들기"}
            </button>
            {shareUrl && (
              <input className="input" readOnly value={shareUrl} style={{ fontSize: 12, flex: 1, minWidth: 200 }}
                onFocus={(e) => e.target.select()} />
            )}
          </div>
          <div className="field">
            <label className="label">제목</label>
            <input className="input" value={portfolio.title}
              onChange={(e) => setPortfolio({ ...portfolio, title: e.target.value })}
              onBlur={() => save({ title: portfolio.title })} />
          </div>
          {PORTFOLIO_SECTIONS.map(([key, label]) => (
            <div className="field" key={key}>
              <label className="label">{label}</label>
              <textarea className="textarea" value={portfolio.sections[key] || ""} style={{ minHeight: 80 }}
                onChange={(e) => setPortfolio({ ...portfolio, sections: { ...portfolio.sections, [key]: e.target.value } })}
                onBlur={() => save({ sections: { [key]: portfolio.sections[key] } })} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
