import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../../api";
import "../../research-theme.css";

const DURATIONS = [2, 4, 6, 8, 12];

// 학생이 빈 칸을 마주하지 않도록, 클릭 한 번으로 시작할 수 있는 궁금증 예시.
const CURIOSITY_PRESETS = [
  "AI와 공부에 대해 궁금해요",
  "게임과 집중력의 관계가 궁금해요",
  "식물이 어떻게 자라는지 궁금해요",
  "우리 학교 급식이 궁금해요",
  "환경 문제가 궁금해요",
  "스마트폰 사용이 궁금해요",
];

const DIFFICULTY_LEVELS = [
  { value: "easy", emoji: "🟢", label: "쉽게 시작하기", desc: "몇 번만 재보고 비교해요" },
  { value: "normal", emoji: "🔵", label: "일반 연구", desc: "일반적인 학생 수준의 연구예요" },
  { value: "deep", emoji: "🟣", label: "심화 연구", desc: "반복 측정·비교 조건을 더 넣어요" },
];

// AI 호출은 다 만들어질 때까지 기다렸다가 한 번에 받아오므로 "실제로
// 몇 %를 썼는지"는 알 수 없다 — 보통 걸리는 시간에 맞춰 90%까지
// 점점 느려지며 다가가다가 완료되면 100%로 채우는 추정치다.
function estimateAiProgress(seconds, expectedSeconds) {
  const pct = 90 * (1 - Math.exp(-seconds / expectedSeconds));
  return Math.min(90, Math.round(pct));
}

function AiGauge({ percent }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6, maxWidth: 220 }}>
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

export default function ResearchNew() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const resumeId = params.get("id");

  const [research, setResearch] = useState(null);
  const [turns, setTurns] = useState([]);
  const [dialogueLoaded, setDialogueLoaded] = useState(false);
  const [topics, setTopics] = useState([]);
  const [keyword, setKeyword] = useState("");
  const [showKeywordInput, setShowKeywordInput] = useState(false);
  const [weeks, setWeeks] = useState(4);
  const [difficulty, setDifficulty] = useState("easy");
  const [mode, setMode] = useState(null); // "solo" | "team" — 궁금증 카드보다 먼저 정한다
  const [teamReady, setTeamReady] = useState(false); // 팀 연구는 초대 화면을 한 번 거친다
  const [message, setMessage] = useState("");
  const [options, setOptions] = useState([]);
  const [showTextInput, setShowTextInput] = useState(false);
  const [busy, setBusy] = useState(false);
  const [queueNote, setQueueNote] = useState("");
  const [typing, setTyping] = useState(false);
  const [topicsProgress, setTopicsProgress] = useState(0);
  const [error, setError] = useState("");
  const [locked, setLocked] = useState(false);
  const [aiStatus, setAiStatus] = useState(null); // {consented, ...} — 물어보기 전엔 모른다
  const [consentBusy, setConsentBusy] = useState(false);
  const bottomRef = useRef(null);
  const kickedOff = useRef(false);
  const topicsRequested = useRef(false);
  // start() 도 결국 URL 을 ?id=... 로 바꾸므로, 아래 [resumeId] 이펙트가
  // "이어서 들어온 것"과 "방금 막 만든 것"을 구분 못 하면 방금 만든 팀
  // 연구도 초대 화면을 건너뛰어 버린다. start() 가 이 플래그를 세워 알려준다.
  const justStarted = useRef(false);

  useEffect(() => {
    if (!resumeId) return;
    if (justStarted.current) {
      justStarted.current = false;
    } else {
      setTeamReady(true); // 진짜로 이어서 들어온 경우에만 팀 초대 화면을 건너뛴다
    }
    api.getResearch(resumeId).then((r) => {
      setResearch(r);
      setMode(r.team ? "team" : "solo"); // 새로고침 등으로 이어 들어온 경우 화면 문구를 맞춘다
    }).catch((e) => {
      if (e.status === 402) setLocked(true);
      else setError(e.message);
    });
    api.listResearchDialogue(resumeId).then((r) => { setTurns(r.items); setDialogueLoaded(true); })
      .catch(() => setDialogueLoaded(true));
    api.listResearchTopics(resumeId).then((r) => setTopics(r.items)).catch(() => {});
  }, [resumeId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, typing]);

  // AI 코치가 먼저 말을 걸기 전에 동의 여부를 미리 알아 둔다 — 모르고 걸었다가
  // 403으로 막히면 채팅창이 텅 빈 채로 에러만 뜨고 학생은 뭘 해야 할지 모른다.
  useEffect(() => {
    if (!research) return;
    api.aiStatus().then(setAiStatus).catch(() => setAiStatus({ consented: false }));
  }, [research?.id]);

  // 채팅처럼 느껴지도록 — 대화가 하나도 없으면 AI가 관심 키워드를 보고 먼저 말을 건다.
  // 팀 연구는 초대 화면(teamReady)을 지나야 대화가 시작되고, 동의 전에는
  // 걸어봐야 실패만 하니 동의 화면을 먼저 보여준다(아래 return 블록).
  useEffect(() => {
    if (!research || !dialogueLoaded || kickedOff.current || !teamReady) return;
    // 팀 연구는 팀 초대 화면 다음에 주제(궁금증)를 정하는 화면이 하나 더
    // 있다 — 그 화면을 지나기 전(키워드가 비어 있는 동안)엔 AI가 말을
    // 걸면 안 된다. 무엇이 궁금한지 아직 안 정해졌기 때문이다.
    if (!research.interest_keyword) return;
    if (!aiStatus?.consented) return;
    if (turns.length > 0 || topics.length > 0) return;
    kickedOff.current = true;
    sendMessage("");
  }, [research, dialogueLoaded, turns.length, topics.length, teamReady, aiStatus?.consented]);

  const grantConsent = async () => {
    setConsentBusy(true); setError("");
    try {
      await api.setAiConsent(true);
      setAiStatus(await api.aiStatus());
    } catch (e) {
      setError(e.message);
    } finally {
      setConsentBusy(false);
    }
  };

  // 혼자 연구는 궁금증 화면에서 바로 연구를 만든다(키워드가 그 자리에서 정해짐).
  const start = async (presetKeyword) => {
    const k = (presetKeyword || keyword).trim();
    if (!k) return setError("관심 있는 주제를 입력해주세요.");
    setBusy(true); setError("");
    try {
      const r = await api.startResearch(k, weeks, difficulty, "solo");
      setDialogueLoaded(true);
      setResearch(r);
      setTeamReady(true); // 혼자 모드는 거칠 화면이 없으니 바로 준비 완료로 둔다
      justStarted.current = true;
      navigate(`/research/new?id=${r.id}`, { replace: true });
    } catch (e) {
      if (e.status === 402) setLocked(true);
      else setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  // 팀 연구는 주제 없이 팀부터 만든다 — 팀원을 초대한 뒤에야 궁금증 화면이 나온다.
  const startTeam = async () => {
    setBusy(true); setError("");
    try {
      const r = await api.startResearch("", weeks, difficulty, "team");
      setDialogueLoaded(true);
      setResearch(r);
      setMode("team");
      justStarted.current = true;
      navigate(`/research/new?id=${r.id}`, { replace: true });
    } catch (e) {
      if (e.status === 402) setLocked(true);
      else setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  // 팀이 꾸려진 뒤, 궁금증 화면에서 이미 만들어 둔 연구에 주제를 채운다.
  const submitTeamKeyword = async (presetKeyword) => {
    const k = (presetKeyword || keyword).trim();
    if (!k) return setError("관심 있는 주제를 입력해주세요.");
    setBusy(true); setError("");
    try {
      const r = await api.setResearchKeyword(research.id, {
        interest_keyword: k, duration_weeks: weeks, difficulty_level: difficulty,
      });
      setResearch(r);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  // 궁금증 화면 하나를 혼자/팀 두 경우 다 쓴다 — 연구가 아직 없으면(혼자)
  // 새로 만들고, 이미 있으면(팀, 팀 초대를 마친 뒤) 주제만 채운다.
  const chooseKeyword = research ? submitTeamKeyword : start;

  const sendMessage = async (text) => {
    setBusy(true); setError(""); setTyping(true); setQueueNote("");
    setOptions([]); setShowTextInput(false);
    if (text) setTurns((prev) => [...prev, { id: `local-${Date.now()}`, role: "student", content: text }]);
    try {
      const { job_id } = await api.sendResearchDialogue(research.id, text);
      const result = await api.waitAiJob(job_id, {
        onTick: (_sec, job) => {
          // AI를 쓰는 사람이 몰려 대기열이 생겼을 때만 보여준다 — 평소엔
          // 바로 처리되니 queue_position 이 없거나 0이라 아무것도 안 뜬다.
          setQueueNote(job.queue_position > 0
            ? `AI 요청이 많아 잠시 기다리고 있어요 (앞에 ${job.queue_position}명)`
            : "");
        },
      });
      setTurns((prev) => [...prev, { id: `local-ai-${Date.now()}`, role: "ai", content: result.question }]);
      setOptions(result.options || []);
      if (result.ready_for_topics) {
        setResearch((prev) => ({ ...prev, current_stage: "topic" }));
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false); setTyping(false); setQueueNote("");
    }
  };

  const send = () => {
    const text = message.trim();
    if (!text || busy) return;
    setMessage("");
    sendMessage(text);
  };

  const pickOption = (text) => {
    if (busy) return;
    sendMessage(text);
  };

  const askTopics = async () => {
    setBusy(true); setError(""); setTopicsProgress(0);
    try {
      const { job_id } = await api.requestResearchTopics(research.id);
      await api.waitAiJob(job_id, { onTick: (s) => setTopicsProgress(estimateAiProgress(s, 7)) });
      setTopicsProgress(100);
      const r = await api.listResearchTopics(research.id);
      setTopics(r.items);
    } catch (e) {
      setError(e.message);
      topicsRequested.current = false; // 실패하면 다시 시도할 수 있게 놔둔다
    } finally {
      setBusy(false);
    }
  };

  // 버튼을 누르게 하지 않고, 주제를 추천받을 준비가 되면 바로 만들어준다.
  useEffect(() => {
    if (!research || research.current_stage !== "topic" || topics.length > 0) return;
    if (topicsRequested.current) return;
    topicsRequested.current = true;
    askTopics();
  }, [research?.current_stage, topics.length]);

  const selectTopic = async (topicId) => {
    setBusy(true); setError("");
    try {
      await api.selectResearchTopic(research.id, topicId);
      navigate(`/research/${research.id}`);
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  };

  if (locked) {
    return (
      <div className="research-theme wrap page" style={{ maxWidth: 620 }}>
        <span className="label">연구</span>
        <h1>내 기록으로 연구를 시작합니다</h1>
        <p style={{ color: "var(--color-text-secondary)", lineHeight: 1.8 }}>
          궁금한 것 하나로 시작해서 AI 연구 코치와 함께 논문까지 완성할 수 있습니다.
          
        </p>
        <div className="panel" style={{ marginTop: 18 }}>
          {/* 이용권은 이 서비스에 아직 없다(서버도 402 를 안 준다). 이 갈래를
              지우지 않고 남겨 둔 것은, 나중에 이용권을 붙일 때 들어올 자리가
              여기여서다. */}
          <p style={{ margin: 0, color: "var(--color-text-secondary)" }}>
            준비 중입니다. 잠시 후 다시 시도해 주세요.
          </p>
        </div>
      </div>
    );
  }

  if (!research && !mode) {
    return (
      <div className="research-theme wrap page">
        <span className="label">🔬 나만의 연구 시작하기</span>
        <h1 style={{ marginTop: 4 }}>누구와 함께 연구할까요?</h1>
        <p style={{ color: "var(--color-text-secondary)" }}>
          혼자 해도 되고, 친구들과 팀을 꾸려도 돼요. 나중에 언제든 팀원을 더 초대할 수 있어요.
        </p>
        <div style={{ display: "grid", gap: 10, maxWidth: 420, margin: "16px 0" }}>
          <button className="btn btn-primary" style={{ padding: "16px 18px", textAlign: "left" }}
            onClick={() => setMode("solo")} disabled={busy}>
            <div style={{ fontSize: 15, fontWeight: 700 }}>혼자 연구하기</div>
            <div style={{ fontSize: 12.5, opacity: 0.85, marginTop: 2 }}>나만의 속도로 진행해요</div>
          </button>
          <button className="btn btn-ghost" style={{ padding: "16px 18px", textAlign: "left" }}
            onClick={startTeam} disabled={busy}>
            <div style={{ fontSize: 15, fontWeight: 700 }}>친구들과 팀 만들기</div>
            <div style={{ fontSize: 12.5, color: "var(--color-text-muted)", marginTop: 2 }}>
              같이 조사하고 나눠서 맡아요 — 주제는 팀원을 모은 뒤에 정해요
            </div>
          </button>
        </div>
        {error && <div className="notice notice-error">{error}</div>}
      </div>
    );
  }

  // 팀 연구는 궁금증 화면보다 팀 초대 화면이 먼저다 — 주제를 정하기 전에
  // 팀원부터 모은다(연구는 이미 startTeam() 이 키워드 없이 만들어 둔 상태).
  if (mode === "team" && research && !teamReady) {
    return <TeamSetup research={research} onReady={() => setTeamReady(true)} />;
  }

  if (!research || (research && !research.interest_keyword)) {
    return (
      <div className="research-theme wrap page">
        <span className="label">🔬 {mode === "team" ? "팀 연구 시작하기" : "나만의 연구 시작하기"}</span>
        <h1 style={{ marginTop: 4 }}>요즘 궁금한 것이 있나요?</h1>
        <p style={{ color: "var(--color-text-secondary)" }}>
          아래에서 골라도 되고, 다른 게 궁금하면 직접 적어도 돼요.
        </p>

        <div style={{ display: "grid", gap: 8, maxWidth: 460, margin: "14px 0" }}>
          {CURIOSITY_PRESETS.map((k) => (
            <button key={k} className="btn btn-ghost" style={{ textAlign: "left", justifyContent: "flex-start" }}
              onClick={() => chooseKeyword(k)} disabled={busy}>
              {k}
            </button>
          ))}
          <button className="btn btn-ghost" style={{ textAlign: "left", justifyContent: "flex-start" }}
            onClick={() => setShowKeywordInput((v) => !v)} disabled={busy}>
            직접 입력하기
          </button>
        </div>

        {showKeywordInput && (
          <div className="field" style={{ maxWidth: 420 }}>
            <label className="label">관심 키워드</label>
            <input className="input" value={keyword} onChange={(e) => setKeyword(e.target.value)}
              placeholder="예: 학교 급식" maxLength={80} autoFocus />
          </div>
        )}

        <div className="field" style={{ maxWidth: 420 }}>
          <label className="label">연구 기간</label>
          <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
            {DURATIONS.map((w) => (
              <button key={w} className={`btn btn-sm ${weeks === w ? "" : "btn-ghost"}`}
                onClick={() => setWeeks(w)}>{w}주</button>
            ))}
          </div>
        </div>

        <div className="field" style={{ maxWidth: 460 }}>
          <label className="label">연구 난이도</label>
          <div style={{ display: "grid", gap: 6 }}>
            {DIFFICULTY_LEVELS.map((d) => (
              <button key={d.value}
                className={`btn btn-sm ${difficulty === d.value ? "" : "btn-ghost"}`}
                style={{ justifyContent: "flex-start", gap: 8 }}
                onClick={() => setDifficulty(d.value)}>
                <span>{d.emoji} {d.label}</span>
                <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>— {d.desc}</span>
              </button>
            ))}
          </div>
        </div>

        {error && <div className="notice notice-error">{error}</div>}
        {showKeywordInput && (
          <button className="btn btn-primary" onClick={() => chooseKeyword()} disabled={busy} style={{ marginTop: 12 }}>
            {busy ? "시작하는 중…" : "시작하기"}
          </button>
        )}
      </div>
    );
  }

  if (aiStatus && !aiStatus.consented && turns.length === 0 && topics.length === 0) {
    return (
      <ConsentGate keyword={research.interest_keyword} busy={consentBusy} error={error}
        onConsent={grantConsent} />
    );
  }

  return (
    <div className="research-theme wrap page" style={{ maxWidth: 620 }}>
      <span className="research-stage-pill">{research.interest_keyword}</span>
      <h1 style={{ marginTop: 10 }}>연구 코치와 대화하기</h1>

      <div className="research-chat" style={{ margin: "18px 0" }}>
        {!dialogueLoaded || (turns.length === 0 && typing) ? (
          <div className="research-chat-turn role-ai">
            <div className="research-chat-bubble research-chat-typing"><TypingDots /></div>
          </div>
        ) : null}
        {turns.map((t) => (
          <div key={t.id} className={`research-chat-turn role-${t.role}`}>
            <div className="research-chat-bubble">{t.content}</div>
          </div>
        ))}
        {typing && turns.length > 0 && (
          <div className="research-chat-turn role-ai">
            <div className="research-chat-bubble research-chat-typing"><TypingDots /></div>
          </div>
        )}
        {queueNote && (
          <p style={{ fontSize: 12, color: "var(--color-text-muted)", margin: "4px 0 0 4px" }}>
            {queueNote}
          </p>
        )}
        <div ref={bottomRef} />
      </div>

      {error && <div className="notice notice-error">{error}</div>}

      {topics.length === 0 ? (
        <>
          {research.current_stage === "topic" ? (
            error ? (
              <div style={{ display: "grid", gap: 8 }}>
                <button className="btn btn-primary" onClick={askTopics} disabled={busy}>
                  {busy ? "주제를 만드는 중…" : "다시 시도"}
                </button>
              </div>
            ) : (
              <div>
                <div className="research-chat-turn role-ai">
                  <div className="research-chat-bubble research-chat-typing"><TypingDots /></div>
                </div>
                <AiGauge percent={topicsProgress} />
              </div>
            )
          ) : options.length > 0 && !showTextInput ? (
            <div key="options" style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {options.map((o) => (
                <button key={o} className="btn btn-sm btn-ghost" onClick={() => pickOption(o)} disabled={busy}>
                  {o}
                </button>
              ))}
              <button className="btn btn-sm btn-ghost" onClick={() => setShowTextInput(true)} disabled={busy}>
                기타(직접 입력)
              </button>
            </div>
          ) : (
            <div key="text-input" style={{ display: "grid", gap: 6 }}>
              {options.length > 0 && (
                <button className="btn btn-sm btn-ghost" style={{ width: "fit-content" }}
                  onClick={() => setShowTextInput(false)} disabled={busy}>
                  ← 선택지로 돌아가기
                </button>
              )}
              <div className="row" style={{ gap: 8 }}>
                <input className="input" value={message} onChange={(e) => setMessage(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && send()} autoFocus
                  placeholder="답변을 입력해주세요" disabled={busy} />
                <button className="btn btn-primary" onClick={send} disabled={busy || !message.trim()}>
                  {busy ? "…" : "보내기"}
                </button>
              </div>
            </div>
          )}
        </>
      ) : (
        <>
          <h3 style={{ marginTop: 24 }}>이 중 하나를 골라보세요</h3>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 14 }}>
            {topics.map((t) => (
              <TopicCard key={t.id} topic={t} researchId={research.id} onSelect={selectTopic}
                onChanged={(updated) => setTopics((prev) => prev.map((x) => (x.id === updated.id ? updated : x)))} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

/** AI 연구 코치를 쓰기 전 동의 화면. 실패한 뒤 빈 채팅창만 보여주면 학생이
 *  뭘 해야 할지 못 찾으므로, 아예 대화를 걸기 전에 먼저 보여준다.
 *  문구는 CoverLetterEdit.jsx의 동의 안내와 같은 내용(개인정보처리방침
 *  제7조에 적힌 것)을 연구 코치 맥락으로 옮긴 것이다. */
function ConsentGate({ keyword, busy, error, onConsent }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="research-theme wrap page" style={{ maxWidth: 620 }}>
      <span className="research-stage-pill">{keyword}</span>
      <h1 style={{ marginTop: 10 }}>연구 코치와 대화하기</h1>
      <div style={{ padding: 14, borderRadius: 8, background: "#fdf6ec",
                    border: "1px solid #f0dcc0", fontSize: 13, lineHeight: 1.8, marginTop: 14 }}>
        <b>AI 연구 코치가 질문을 이어가며 주제를 함께 좁혀갑니다</b>
        <p style={{ margin: "6px 0 0" }}>
          지어낸 사실을 답으로 주지 않고, 학생의 답변을 보고 다음 질문만 만듭니다.
        </p>
        <p style={{ margin: "6px 0 0" }}>
          쓰려면 동의가 필요합니다. 대화를 위해{" "}
          <b>입력한 내용이 국외(미국)의 AI 서비스로 전송</b>됩니다.
          이름·학교·연락처는 전송 전에 가려서 보내고, 전송된 내용은
          AI 학습에 쓰이지 않습니다.
        </p>
        <button className="btn btn-sm btn-ghost" style={{ marginTop: 4 }}
          onClick={() => setOpen(!open)}>
          {open ? "접기" : "자세히"}
        </button>
        {open && (
          <p style={{ margin: "6px 0 0", color: "var(--steel)" }}>
            이전받는 자 Anthropic PBC · 이전 국가 미국 ·
            이전 항목 대화에 입력한 내용(개인 식별 정보 제외) ·
            보유 기간 처리 완료 시까지. 동의하지 않아도 다른 기록 기능에는
            불이익이 없고, 언제든 거둘 수 있습니다.{" "}
            <a href="https://udjschool.ggm.kr/privacy" target="_blank"
              rel="noreferrer">개인정보처리방침 제7조</a>
          </p>
        )}
        {error && <p style={{ margin: "8px 0 0", color: "var(--color-danger, #b3261e)" }}>{error}</p>}
        <button className="btn btn-primary" style={{ marginTop: 10 }}
          onClick={onConsent} disabled={busy}>
          {busy ? "처리하는 중…" : "동의하고 대화 시작하기"}
        </button>
      </div>
    </div>
  );
}

function TypingDots() {
  return (
    <span className="research-typing-dots">
      <span /><span /><span />
    </span>
  );
}

/** 팀 연구를 막 시작한 직후 — 궁금증 대화를 시작하기 전에 팀원부터 초대한다. */
function TeamSetup({ research, onReady }) {
  const [members, setMembers] = useState([]);
  const [q, setQ] = useState("");
  const [candidates, setCandidates] = useState([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const loadTeam = () => {
    api.getResearchTeam(research.id).then((t) => setMembers(t.members || [])).catch(() => {});
  };
  useEffect(() => { loadTeam(); }, [research.id]);

  useEffect(() => {
    const term = q.trim();
    if (!term) { setCandidates([]); return; }
    const t = setTimeout(() => {
      api.searchTeamCandidates(research.id, term).then((r) => setCandidates(r.items || [])).catch(() => {});
    }, 250);
    return () => clearTimeout(t);
  }, [q, research.id]);

  const invite = async (userId) => {
    setBusy(true); setMsg("");
    try {
      await api.inviteTeamMember(research.id, userId);
      setMsg("초대를 보냈어요. 친구가 수락하면 팀에 합류해요.");
      setCandidates((prev) => prev.map((c) => (c.user_id === userId ? { ...c, already_invited: true } : c)));
    } catch (e) {
      setMsg(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="research-theme wrap page">
      <span className="label">🔬 팀 연구 시작하기</span>
      <h1 style={{ marginTop: 4 }}>팀원을 초대해보세요</h1>
      <p style={{ color: "var(--color-text-secondary)" }}>
        지금 안 해도 나중에 언제든 초대할 수 있어요. 준비되면 다음 화면에서 팀이 함께 궁금해할 주제를 정해요.
      </p>

      <div className="panel" style={{ marginTop: 14, maxWidth: 460 }}>
        <div className="label">현재 팀원 ({members.length}명)</div>
        <div style={{ display: "grid", gap: 6, marginTop: 8 }}>
          {members.map((m) => (
            <div key={m.user_id} className="row" style={{ gap: 6, alignItems: "center" }}>
              <span>{m.name}</span>
              {m.is_leader && <span className="badge">팀장</span>}
            </div>
          ))}
        </div>
      </div>

      <div className="field" style={{ maxWidth: 460, marginTop: 14 }}>
        <label className="label">같은 학교 친구 이름으로 검색</label>
        <input className="input" value={q} onChange={(e) => setQ(e.target.value)}
          placeholder="예: 김민수" />
      </div>

      {candidates.length > 0 && (
        <div style={{ display: "grid", gap: 6, maxWidth: 460, marginTop: 8 }}>
          {candidates.map((cnd) => (
            <div key={cnd.user_id} className="row entry"
              style={{ gap: 8, alignItems: "center", padding: "8px 10px" }}>
              <span>{cnd.name}</span>
              <span className="meta">{cnd.class_name || (cnd.grade ? `${cnd.grade}학년` : "")}</span>
              <div className="spacer" />
              {cnd.already_member ? (
                <span className="badge badge-done">팀원</span>
              ) : cnd.already_invited ? (
                <span className="meta">초대함</span>
              ) : (
                <button className="btn btn-sm" disabled={busy} onClick={() => invite(cnd.user_id)}>
                  초대
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {msg && <div className="notice" style={{ marginTop: 10, maxWidth: 460 }}>{msg}</div>}

      <button className="btn btn-primary" style={{ marginTop: 18 }} onClick={onReady}>
        다음: 주제 정하기 →
      </button>
    </div>
  );
}

function TopicCard({ topic, researchId, onSelect, onChanged }) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(topic.title);
  const [question, setQuestion] = useState(topic.research_question);
  const [reviewMsg, setReviewMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [reviewBusy, setReviewBusy] = useState(false);
  const [reviewProgress, setReviewProgress] = useState(0);

  const save = async () => {
    setBusy(true);
    try {
      const updated = await api.editResearchTopic(researchId, topic.id,
        { title, research_question: question });
      onChanged(updated);
      setEditing(false);
    } finally {
      setBusy(false);
    }
  };

  const review = async () => {
    setReviewBusy(true); setReviewMsg(""); setReviewProgress(0);
    try {
      const { job_id } = await api.reviewResearchTopic(researchId, topic.id);
      const result = await api.waitAiJob(job_id, { onTick: (s) => setReviewProgress(estimateAiProgress(s, 5)) });
      setReviewProgress(100);
      setReviewMsg(result.comment || (result.feasible ? "수행 가능한 주제입니다." : "검토가 필요합니다."));
    } catch (e) {
      setReviewMsg(e.message);
    } finally {
      setReviewBusy(false);
    }
  };

  return (
    <div className="research-topic-card">
      {editing ? (
        <>
          <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} />
          <textarea className="textarea" value={question} onChange={(e) => setQuestion(e.target.value)}
            style={{ minHeight: 60 }} />
          <div className="row" style={{ gap: 6 }}>
            <button className="btn btn-sm" onClick={save} disabled={busy}>저장</button>
            <button className="btn btn-sm btn-ghost" onClick={() => setEditing(false)}>취소</button>
          </div>
        </>
      ) : (
        <>
          <span className="badge">난이도 {topic.difficulty || "-"}</span>
          <h4 style={{ margin: "4px 0" }}>{topic.title}</h4>
          <p style={{ fontSize: 13.5, color: "var(--color-text-secondary)", margin: 0 }}>
            {topic.research_question}
          </p>
          <p style={{ fontSize: 12.5, color: "var(--color-text-muted)", margin: 0 }}>
            예상 기간 {topic.expected_duration}
          </p>
          {topic.feasibility_note && (
            <p style={{ fontSize: 12.5, color: "var(--color-text-muted)", margin: "4px 0 0", lineHeight: 1.6 }}>
              💡 {topic.feasibility_note}
            </p>
          )}
          {reviewMsg && <p style={{ fontSize: 12.5, color: "var(--color-primary)" }}>{reviewMsg}</p>}
          <div className="row" style={{ gap: 6, marginTop: 6 }}>
            <button className="btn btn-sm btn-primary" onClick={() => onSelect(topic.id)} disabled={busy || reviewBusy}>
              이 주제로 시작
            </button>
            <button className="btn btn-sm btn-ghost" onClick={() => setEditing(true)} disabled={busy || reviewBusy}>
              수정
            </button>
            <button className="btn btn-sm btn-ghost" onClick={review} disabled={busy || reviewBusy}>
              {reviewBusy ? "검토 중…" : "검토받기"}
            </button>
          </div>
          {reviewBusy && <AiGauge percent={reviewProgress} />}
        </>
      )}
    </div>
  );
}
