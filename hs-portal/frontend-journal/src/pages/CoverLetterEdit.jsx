import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import Tour, { tourSeen, markTourSeen } from "../components/Tour";
import { useAuth } from "../auth";

const LIMIT = 1000;

// 일지에서 답을 바로 찾기 어려운 항목. AI 가 1~2학년 기록으로 질문을 만들어 주고,
// 학생이 답한 말을 재료로 글을 쓴다.
const MOTIVE_TOPICS = ["apply_motive", "future_goal"];

export default function CoverLetterEdit() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const isNew = !id;
  const sheetRef = useRef(null);

  const [templates, setTemplates] = useState([]);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState({});     // {항목키: 본문}
  const [active, setActive] = useState("");       // 지금 쓰고 있는 항목
  const [materials, setMaterials] = useState(null);
  const [matBusy, setMatBusy] = useState(false);
  const [journalCount, setJournalCount] = useState(null);
  const [review, setReview] = useState({});
  const [reviewing, setReviewing] = useState(false);   // 전체 검토 중(저장 중과 문구를 가르려고)       // {항목키: 점검결과}
  const [polish, setPolish] = useState({});       // {항목키: 다듬기결과}
  const [polishing, setPolishing] = useState("");
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const [locked, setLocked] = useState(false);
  const [copied, setCopied] = useState(null);
  // 예전 양식에만 있던 항목. 이미 쓴 글이 있을 때만 뒤에 붙여 보여준다.
  const [legacy, setLegacy] = useState([]);
  const [pdfOk, setPdfOk] = useState(true);
  // AI 기능. 동의하지 않았거나 키가 없으면 버튼 자체를 띄우지 않는다.
  const [aiOk, setAiOk] = useState(null);        // {available, consented, ...}
  const [aiBusy, setAiBusy] = useState("");      // 지금 무엇을 하는 중인지
  const [aiTick, setAiTick] = useState(0);       // 몇 초째인지
  const [analysis, setAnalysis] = useState({});  // {일지id: 분석결과}
  // 항목마다 학생이 직접 고른 기록 {항목키: [일지 id]}. 자소서와 함께 저장한다.
  // 다른 항목으로 옮겨 갔다 와도 그 항목에서 고른 것이 그대로 남는다.
  const [pickedMap, setPickedMap] = useState({});
  const [essay, setEssay] = useState(null);      // AI 초안
  // 키워드가 못 잡은 일지도 학생이 직접 골라 쓸 수 있어야 한다.
  // 본인은 "이 일지가 이 항목에 맞다" 는 것을 알기 때문이다.
  const [pickerOpen, setPickerOpen] = useState(false);   // "내 일지에서 직접 고르기" 목록
  const [pickerTab, setPickerTab] = useState("all");      // all / class / school
  const [picker, setPicker] = useState(null);             // 그 탭의 일지 목록
  // 희망 직업군. 고르면 그 직업군과 이어지는 기록을 먼저 보여 주고 AI 초안에도 넘긴다.
  const [jobs, setJobs] = useState([]);
  const [jobCategory, setJobCategory] = useState("");
  // 지원동기·입사 후 목표: AI 가 만든 질문과 학생의 답. 자소서와 함께 저장한다.
  const [qa, setQa] = useState({});
  // 기록 하나를 펼쳐 보는 창 {id}
  const [viewer, setViewer] = useState(null);
  const [kinds, setKinds] = useState([]);
  const [categoryLabels, setCategoryLabels] = useState({});
  // 처음 쓰는 학생에게 순서를 짚어 준다. 한 번 보면 다시 안 뜬다.
  const [tour, setTour] = useState(false);
  // 좁은 화면에서는 13개를 다 펼치면 끝없이 스크롤해야 한다.
  // 고른 항목 하나만 펼치고 나머지는 한 줄로 접는다.
  const [narrow, setNarrow] = useState(
    typeof window !== "undefined" && window.innerWidth <= 900);

  useEffect(() => {
    const onResize = () => setNarrow(window.innerWidth <= 900);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => {
    api.aiStatus().then(setAiOk).catch(() => setAiOk({ available: false }));
  }, []);

  // 연구는 항목별로 다시 나눌 필요가 없어(§23) topic 없이 한 번만 받아 온다.
  useEffect(() => {
  }, []);

  // 화면이 다 그려진 뒤에 안내를 띄운다. 짚어 줄 요소가 있어야 한다.
  useEffect(() => {
    if (templates.length && !tourSeen()) {
      const t = setTimeout(() => setTour(true), 600);
      return () => clearTimeout(t);
    }
  }, [templates.length]);

  useEffect(() => {
    api.journalMeta()
      .then((m) => {
        const t = m.resume_templates || [];
        setTemplates(t);
        setLegacy(m.legacy_templates || []);
        setJobs(m.job_categories || []);
        setKinds(m.kinds || []);
        setCategoryLabels(Object.fromEntries(
          (m.resume_categories || []).map((c) => [c.key, c.label])));
        // 서버에 한글 글꼴이 없으면 PDF 만 못 만든다.
        setPdfOk(m.pdf_available !== false);
        setActive((v) => v || (t[0]?.key ?? ""));
      })
      .catch(() => {});
  }, []);

  // 양식이 바뀌었다고 학생이 써 둔 글이 화면에서 사라지면 안 된다.
  // 내용이 남아 있는 예전 항목만 목록 끝에 이어 붙인다.
  const shownTemplates = [
    ...templates,
    ...legacy
      .filter((t) => (content[t.key] || "").trim())
      .map((t) => ({ ...t, legacy: true })),
  ];

  useEffect(() => {
    if (isNew) return;
    api.coverLetter(id)
      .then((d) => {
        setTitle(d.title || "");
        setContent(d.content || {});
        setJobCategory(d.job_category || "");
        setQa(d.question_answers || {});
        setPickedMap(d.picked_records || {});
      })
      .catch((e) => {
        if (e.status === 402) setLocked(true);
        else setMsg({ type: "error", text: e.message });
      });
  }, [id, isNew]);

  // 항목을 옮길 때마다 그 항목의 재료를 가져온다.
  // 좁은 화면에서는 재료가 화면 한참 아래에 있다. 항목을 고르면
  // 그 자리로 데려가야 "여기 재료가 있다" 는 것을 안다.
  const scrollToPanel = () => {
    if (!narrow) return;
    setTimeout(() => {
      document.querySelector("[data-tour='panel']")
        ?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 120);
  };

  const loadMaterials = (topic) => {
    if (!topic) return;
    setMatBusy(true);
    api.coverLetterMaterials(topic, jobCategory)
      .then((d) => {
        setJournalCount(d.journal_count ?? 0);
        setMaterials(d.topics?.[0] || { matches: [], count: 0 });
      })
      .catch((e) => {
        if (e.status === 402) setLocked(true);
        setMaterials({ matches: [], count: 0 });
      })
      .finally(() => setMatBusy(false));
  };

  useEffect(() => { loadMaterials(active); }, [active, jobCategory]);

  const setItem = (key) => (e) =>
    setContent((c) => ({ ...c, [key]: e.target.value }));

  // 재료를 본문 끝에 붙인다. 지우지 않고 이어 붙여야 실수로 날리지 않는다.
  const insert = (text) => {
    setContent((c) => {
      const prev = (c[active] || "").trimEnd();
      return { ...c, [active]: prev ? `${prev}\n\n${text}` : text };
    });
    setMsg({ type: "ok", text: "본문에 넣었습니다. 내 말로 다듬어보세요." });
  };

  // 맡긴 일이 끝날 때까지 기다린다. 몇 초째인지 보여줘야 학생이 안 답답하다.
  const runAi = async (label, start) => {
    setAiBusy(label);
    setAiTick(0);
    setMsg(null);
    try {
      const { job_id, status, result } = await start();
      // 저장해 둔 결과가 있으면 기다릴 것 없이 바로 온다.
      if (status === "done") return result;
      return await api.waitAiJob(job_id, { onTick: setAiTick });
    } catch (e) {
      setMsg({ type: "error", text: e.message });
      return null;
    } finally {
      setAiBusy("");
    }
  };

  const picked = pickedMap[active] || [];
  const setPicked = (upd) => setPickedMap((m) => {
    const cur = m[active] || [];
    const next = typeof upd === "function" ? upd(cur) : upd;
    return { ...m, [active]: next };
  });
  const PICK_MAX = 5;
  const togglePick = (id) => {
    if (picked.includes(id)) { setPicked((p) => p.filter((x) => x !== id)); return; }
    if (picked.length >= PICK_MAX) {
      setMsg({ type: "error", text: `한 항목에 기록은 ${PICK_MAX}개까지 고를 수 있습니다.` });
      return;
    }
    setPicked((p) => [...p, id]);
  };

  // 목록은 탭마다 서버에서 그 종류만 받아 온다.
  useEffect(() => {
    if (!pickerOpen) return;
    setPicker(null);
    api.journals(pickerTab)
      .then((rows) => setPicker(Array.isArray(rows) ? rows : []))
      .catch((e) => { setMsg({ type: "error", text: e.message }); setPicker([]); });
  }, [pickerOpen, pickerTab]);

  // 고른 기록의 제목·날짜. 목록을 닫아도 보여야 해서 따로 들고 있는다.
  const [pickedInfo, setPickedInfo] = useState({});
  useEffect(() => {
    api.journals().then((rows) => setPickedInfo(Object.fromEntries(
      (rows || []).map((r) => [r.id, r])))).catch(() => {});
  }, []);

  const analyzeOne = async (journalId) => {
    const r = await runAi("경험을 분석하고 있습니다",
      () => api.analyzeJournal(journalId));
    if (r) {
      setAnalysis((a) => ({ ...a, [journalId]: r }));
      setPicked((p) => (p.includes(journalId) || p.length >= PICK_MAX ? p : [...p, journalId]));
    }
  };

  const activeLabel = shownTemplates.find((t) => t.key === active)?.label || "";
  const isMotive = MOTIVE_TOPICS.includes(active);

  const makeEssay = async () => {
    const r = await runAi("자기소개서를 쓰고 있습니다",
      () => api.generateEssay(activeLabel, picked, LIMIT,
        { job_category: jobCategory, topic: active }));
    if (r) setEssay(r);
  };

  // 기록 하나를 펼쳐 본 뒤 "이 내용으로 자기소개서 작성하기".
  // 지금 항목·희망 직업군·그 기록(과 거기 달린 카테고리)만 AI 에 넘긴다.
  const essayFromRecord = async (journalId) => {
    setViewer(null);
    const r = await runAi("선택한 기록으로 자기소개서를 쓰고 있습니다",
      () => api.generateEssay(activeLabel, [journalId], LIMIT,
        { job_category: jobCategory, topic: active }));
    if (r) setEssay(r);
  };

  // 지원동기·입사 후 목표: 1~2학년 기록으로 질문 만들기
  const makeQuestions = async () => {
    const r = await runAi("내 기록을 읽고 질문을 만들고 있습니다",
      () => api.motiveQuestions(active, jobCategory));
    if (r) {
      setQa((all) => ({
        ...all,
        [active]: { questions: r.questions || [], answers: all[active]?.answers || {},
                    record_count: r.record_count || 0 },
      }));
    }
  };

  const setAnswer = (qid, text) => setQa((all) => ({
    ...all,
    [active]: { ...(all[active] || {}), answers: { ...(all[active]?.answers || {}), [qid]: text } },
  }));

  // 학생의 답(+ 질문의 근거가 된 기록)으로 글을 쓴다.
  const essayFromAnswers = async () => {
    const cur = qa[active] || {};
    const answered = (cur.questions || [])
      .map((q) => ({ q, answer: (cur.answers?.[q.id] || "").trim() }))
      .filter((x) => x.answer);
    if (!answered.length) {
      setMsg({ type: "error", text: "질문에 하나 이상 답해 주세요." });
      return;
    }
    const ids = [...new Set(answered.flatMap((x) => x.q.basis.map((b) => b.record_id)))].slice(0, 5);
    const r = await runAi("내 답변으로 자기소개서를 쓰고 있습니다",
      () => api.generateEssay(activeLabel, ids, LIMIT, {
        job_category: jobCategory, topic: active,
        answers: answered.map((x) => ({ question: `[${x.q.group}] ${x.q.question}`, answer: x.answer })),
      }));
    if (r) setEssay(r);
  };

  const runReview = async () => {
    const target = {};
    for (const t of shownTemplates) {
      const v = (content[t.key] || "").trim();
      if (v) target[t.key] = v;
    }
    if (Object.keys(target).length === 0) {
      setMsg({ type: "error", text: "먼저 내용을 적어주세요." });
      return;
    }
    setBusy(true);
    setReviewing(true);
    try {
      const r = await api.reviewCoverLetter(target, LIMIT);
      setReview(r.results || {});
      setMsg({ type: "ok", text: "전체 검토를 마쳤습니다. 각 항목 아래에서 고칠 부분을 확인해 보세요." });
    } catch (e) {
      setMsg({ type: "error", text: e.message });
    } finally {
      setBusy(false);
      setReviewing(false);
    }
  };

  // 말투 다듬기. 글을 대신 써 주지 않고 말투만 손본다.
  // 바꾼 결과를 바로 덮어쓰지 않고 보여준 뒤, 학생이 고르게 한다.
  const runPolish = async (key, text) => {
    setPolishing(key);
    try {
      const r = await api.polishCoverLetter(text);
      setPolish((p) => ({ ...p, [key]: r }));
    } catch (e) {
      setMsg({ type: "error", text: e.message });
    } finally {
      setPolishing("");
    }
  };

  const filled = shownTemplates.filter((t) => (content[t.key] || "").trim());

  const save = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const body = { title: title.trim() || "제목 없음", content,
                     job_category: jobCategory, question_answers: qa,
                     picked_records: pickedMap };
      // 일지와 같이, 저장하면 바로 홈으로 가고 완료 창은 홈에서 띄운다(2026-09-28 요청).
      const r = isNew ? await api.createCoverLetter(body) : await api.updateCoverLetter(id, body);
      navigate("/", {
        replace: isNew,
        state: { saved: { kind: "cover", id: isNew ? r.id : Number(id) } },
      });
    } catch (e) {
      if (e.status === 402) setLocked(true);
      else setMsg({ type: "error", text: e.message });
    } finally {
      setBusy(false);
    }
  };

  const copyText = async (text, mark) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(mark);
      setTimeout(() => setCopied(null), 1600);
    } catch {
      setMsg({ type: "error", text: "복사하지 못했습니다. 직접 선택해서 복사해주세요." });
    }
  };

  const copyAll = () =>
    copyText(filled.map((t) => `[${t.label}]\n${content[t.key].trim()}`).join("\n\n"), "all");

  const saveImage = async () => {
    if (filled.length === 0) {
      setMsg({ type: "error", text: "먼저 내용을 적어주세요." });
      return;
    }
    setBusy(true);
    try {
      const { default: html2canvas } = await import("html2canvas");
      const canvas = await html2canvas(sheetRef.current, {
        backgroundColor: "#ffffff", scale: 2, logging: false,
      });
      const link = document.createElement("a");
      link.download = `${(title.trim() || "자기소개서").replace(/[\\/:*?"<>|]/g, "")}.png`;
      link.href = canvas.toDataURL("image/png");
      link.click();
      setMsg({ type: "ok", text: "이미지를 저장했습니다." });
    } catch {
      setMsg({ type: "error", text: "이미지를 만들지 못했습니다." });
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!confirm("이 자기소개서를 지울까요?")) return;
    try {
      await api.deleteCoverLetter(id);
      navigate("/cover-letters", { replace: true });
    } catch (e) {
      setMsg({ type: "error", text: e.message });
    }
  };

  if (locked) {
    return (
      <div className="wrap page" style={{ maxWidth: 560 }}>
        <div className="notice">
          이용권이 없어 자기소개서를 열 수 없습니다. 작성한 내용은 그대로 보관됩니다.
        </div>
        {/* 이용권은 학교 코드(목록 화면의 코드 칸)나 개인 구매(/subscribe)로 얻는다. */}
        <div className="row" style={{ gap: 8, marginTop: 14, flexWrap: "wrap" }}>
          <button className="btn btn-primary" onClick={() => navigate("/cover-letters")}>학교 코드 넣기</button>
          <button className="btn" onClick={() => navigate("/subscribe")}>개인 이용권 구매</button>
        </div>
      </div>
    );
  }

  return (
    <div className="wrap page" style={{ maxWidth: 1000 }}>
      {/* 처음 쓰는 학생에게 순서를 짚어 준다. */}
      {tour && <Tour onClose={() => setTour(false)} />}
      <span className="label">{isNew ? "새 자기소개서" : "자기소개서"}</span>
      <h1>{title.trim() || "제목 없음"}</h1>
      <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 0, lineHeight: 1.8 }}>
        항목을 모두 채울 필요는 없습니다.
        {narrow
          ? " 항목을 누르면 펼쳐지고, 아래에 그 항목에 쓸 만한"
          : " 오른쪽에 그 항목에 쓸 만한"}
        <b> 내 일지</b>가 나옵니다.
      </p>

      {msg && <div className={`notice notice-${msg.type}`} style={{ margin: "12px 0" }}>{msg.text}</div>}

      <div className="panel" style={{ marginTop: 12 }}>
        <label className="field" style={{ marginBottom: 0 }}>
          <span className="label">자기소개서 제목</span>
          <input className="input" data-tour="title" value={title} maxLength={120}
            placeholder="제목을 입력해 주세요 (예: ○○기업 지원 자기소개서)"
            aria-label="자기소개서 제목"
            onChange={(e) => setTitle(e.target.value)} />
        </label>
      </div>

      <JobPicker jobs={jobs} value={jobCategory} onChange={setJobCategory} />

      <div className="cl-layout" style={{ marginTop: 14 }}>
        {/* 왼쪽 — 작성 */}
        <div className="panel">
          {shownTemplates.map((t, i) => {
            const text = content[t.key] || "";
            const over = text.length > LIMIT;
            const rv = review[t.key];
            // 좁은 화면에서는 고른 항목만 펼친다. 13개를 다 펼쳐 두면
            // 무엇을 쓰는 중인지도 잃고 스크롤만 하게 된다.
            const open = !narrow || active === t.key;
            return (
              <div className={`cl-item ${open ? "" : "cl-folded"}`} key={t.key}
                data-tour={i === 0 ? "item" : undefined}>
                <div className="cl-head"
                  onClick={narrow ? () => setActive(open ? "" : t.key) : undefined}
                  style={narrow ? { cursor: "pointer" } : undefined}>
                  <span className="cl-no">{i + 1}</span>
                  <span className="cl-title">
                    {t.label}
                    {/* 예전 양식에만 있던 항목. 왜 목록 끝에 따로 있는지
                        알 수 있게 표시해 둔다. */}
                    {t.legacy && (
                      <span style={{ fontSize: 11, fontWeight: 400, marginLeft: 6,
                                     color: "var(--steel-light)" }}>
                        이전 양식
                      </span>
                    )}
                  </span>
                  <span className={`cl-count ${over ? "over" : ""}`}>
                    {/* 접힌 줄에서는 글자 수를 길게 적을 자리가 없다.
                        쓴 항목인지만 한눈에 보이면 된다. */}
                    {open
                      ? `${text.length} / ${LIMIT}자`
                      : text.trim() ? `${text.length}자` : ""}
                  </span>
                  {!open && (
                    <span style={{ marginLeft: 6, fontSize: 15,
                                   color: text.trim()
                                     ? "var(--signal, #f26522)"
                                     : "var(--line)" }}>
                      {text.trim() ? "●" : "○"}
                    </span>
                  )}
                </div>
                {open && (
                <>
                <textarea
                  value={text}
                  onFocus={() => setActive(t.key)}
                  onChange={setItem(t.key)}
                  placeholder="겪은 일과 그때 한 행동을 구체적으로 적으세요"
                  style={active === t.key ? { borderColor: "var(--signal)" } : undefined}
                />
                <div className="cl-tools">
                  <button className={`btn btn-sm ${active === t.key ? "" : "btn-ghost"}`}
                    data-tour={i === 0 ? "materials" : undefined}
                    onClick={() => { setActive(t.key); scrollToPanel(); }}>
                    {active === t.key ? "재료 보는 중" : "이 항목 재료 보기"}
                  </button>
                  {text.trim() && (
                    <button className="btn btn-sm btn-ghost"
                      onClick={() => copyText(text.trim(), t.key)}>
                      {copied === t.key ? "복사했습니다" : "복사"}
                    </button>
                  )}
                  {text.trim() && (
                    <button className="btn btn-sm btn-ghost"
                      disabled={polishing === t.key}
                      onClick={() => runPolish(t.key, text)}>
                      {polishing === t.key ? "다듬는 중…" : "말투 다듬기"}
                    </button>
                  )}
                </div>

                {rv && <ReviewBox result={rv} />}
                {polish[t.key] && (
                  <PolishBox
                    result={polish[t.key]}
                    onApply={() => {
                      setContent((c) => ({ ...c, [t.key]: polish[t.key].text }));
                      setPolish((p) => ({ ...p, [t.key]: null }));
                    }}
                    onClose={() => setPolish((p) => ({ ...p, [t.key]: null }))}
                  />
                )}
                </>
                )}
              </div>
            );
          })}
        </div>

        {/* 오른쪽 — 재료 */}
        <aside className="cl-side">
          <div className="panel" data-tour="panel">
            <div className="row" style={{ alignItems: "flex-start", gap: 8 }}>
              <h3 style={{ flex: 1, minWidth: 0, margin: 0, fontSize: 15 }}>
                이 항목에 쓸 만한 내 기록
              </h3>
              <button className="btn btn-sm btn-ghost" disabled={matBusy}
                onClick={() => loadMaterials(active)}>
                {matBusy ? "분석 중…" : "다시 분석"}
              </button>
            </div>

            <p style={{ fontSize: 12.5, color: "var(--steel-light)", margin: "8px 0 0",
                        lineHeight: 1.6 }}>
              {shownTemplates.find((t) => t.key === active)?.label || ""}
            </p>
            {materials?.loose && (
              <p style={{ fontSize: 12, color: "var(--steel-light)", margin: "6px 0 0",
                          lineHeight: 1.6 }}>
                이 항목은 회사와 앞으로의 일에 관한 글이라, 지난 일을 적은
                일지에는 재료가 거의 없습니다. 아래는 참고할 만한 대목입니다.
              </p>
            )}

            <div style={{ marginTop: 10 }}>
              {matBusy && <p style={{ fontSize: 13 }}>일지를 훑어보는 중…</p>}

              {!matBusy && materials && materials.matches.length === 0 && (
                <p style={{ fontSize: 13, color: "var(--steel)", lineHeight: 1.8 }}>
                  {journalCount === 0 ? (
                    <>
                      아직 쓴 일지가 없습니다.{" "}
                      <a href="/journals/new">첫 기록</a>을 남기면
                      여기에서 자소서 재료를 찾아드립니다.
                    </>
                  ) : (
                    <>
                      일지 {journalCount}개를 훑었지만 이 항목에 맞는 대목을
                      찾지 못했습니다. 이런 경험을 일지에 적어두면 다음에 바로
                      꺼내 쓸 수 있습니다.
                    </>
                  )}
                </p>
              )}

              {!matBusy && materials && materials.matches.map((m, i) => (
                <div className="mat" key={i}>
                  <div className="mat-meta">
                    <span className={`mat-kind mat-kind-${m.kind || "diary"}`}>{m.kind_label}</span>
                    {m.entry_date}
                    {m.tagged && <span className="mat-tag" title="일지를 쓸 때 이 항목에 쓰겠다고 골라 둔 기록">내가 고른 기록</span>}
                  </div>
                  {m.title && <div className="mat-title">{m.title}</div>}
                  {m.field_label && <div className="mat-field">{m.field_label}</div>}
                  <p className="mat-text">{m.summary}</p>
                  {m.job_keywords?.length > 0 && (
                    <div className="mat-job">직업군 관련: {m.job_keywords.join(", ")}</div>
                  )}
                  <div className="mat-tools">
                    <button className="btn btn-sm" onClick={() => setViewer({ id: m.journal_id })}>
                      기록 보기
                    </button>
                    <button className="btn btn-sm" onClick={() => insert(m.original)}>
                      본문에 넣기
                    </button>
                    <button className="btn btn-sm btn-ghost"
                      onClick={() => copyText(m.original, `mat-${i}`)}>
                      {copied === `mat-${i}` ? "복사함" : "복사"}
                    </button>
                    {aiOk?.available && aiOk?.consented && (
                      // 이미 분석한 것은 결과를 접었다 펼 수 있게 한다.
                      // 다시 누르면 또 분석하는 줄 알면 돈이 나갈까 봐 못 누른다.
                      <button className="btn btn-sm btn-ghost" disabled={!!aiBusy}
                        onClick={() => (analysis[m.journal_id]
                          ? setAnalysis((a) => ({ ...a, [m.journal_id]: null }))
                          : analyzeOne(m.journal_id))}>
                        {analysis[m.journal_id] ? "정리 접기" : "AI로 경험 분석"}
                      </button>
                    )}
                  </div>

                  {analysis[m.journal_id] && (
                    <AnalysisBox
                      result={analysis[m.journal_id]}
                      picked={picked.includes(m.journal_id)}
                      onToggle={() => setPicked((p) =>
                        p.includes(m.journal_id)
                          ? p.filter((x) => x !== m.journal_id)
                          : [...p, m.journal_id])}
                      onInsert={(text) => insert(text)}
                    />
                  )}
                </div>
              ))}
            </div>

            {/* 학생이 직접 이 항목에 쓸 기록을 고른다. 이 항목의 카테고리를 달아 둔
                기록이 맨 위에 온다. AI 를 쓰지 않아도 기록을 펼쳐 보고 옮길 수 있다. */}
            <PickedList ids={picked} info={pickedInfo} max={PICK_MAX}
              onOpen={(id) => setViewer({ id })} onRemove={togglePick} />
            <RecordPicker open={pickerOpen} onToggle={() => setPickerOpen(!pickerOpen)}
              tab={pickerTab} onTab={setPickerTab} rows={picker}
              topic={active} topicLabel={activeLabel} categoryLabels={categoryLabels}
              recommended={(materials?.matches || []).map((m) => m.journal_id)}
              picked={picked} onTogglePick={togglePick}
              onView={(id) => setViewer({ id })} />

            {/* AI 는 재료 아래에 둔다. 주인공은 학생이 쓴 일지이고,
                AI 는 그것을 정리해 주는 쪽이다. 상자를 따로 두면
                아무것도 고르지 않았을 때 빈 상자만 자리를 차지한다. */}
            {aiOk && aiOk.available && aiOk.consented && isMotive && (
              <MotivePanel
                topic={active}
                data={qa[active]}
                jobLabel={jobs.find((j) => j.key === jobCategory)?.label || ""}
                busy={aiBusy}
                tick={aiTick}
                essay={essay}
                onMake={makeQuestions}
                onAnswer={setAnswer}
                onWrite={essayFromAnswers}
                onApply={() => { insert(essay.draft); setEssay(null); }}
                onClose={() => setEssay(null)}
              />
            )}
            {aiOk && aiOk.available && !(aiOk.consented && isMotive) && (
              <AiPanel
                status={aiOk}
                busy={aiBusy}
                tick={aiTick}
                picked={picked}
                essay={essay}
                noMaterials={!matBusy && !!materials
                  && materials.matches.length === 0}
                onConsent={async (agree) => {
                  try {
                    await api.setAiConsent(agree);
                    setAiOk(await api.aiStatus());
                    if (!agree) { setAnalysis({}); setPicked([]); setEssay(null); }
                  } catch (e) {
                    setMsg({ type: "error", text: e.message });
                  }
                }}
                onGenerate={makeEssay}
                onApply={() => {
                  insert(essay.draft);
                  setEssay(null);
                }}
                onClose={() => setEssay(null)}
              />
            )}
          </div>

        </aside>
      </div>

      {/* 다 쓰면 [저장] → [전체 검토]로 이어진다. 전체 검토는 글을 대신 쓰지 않고,
          쓴 글을 항목별로 확인해 고칠 부분만 알려 준다(결과는 각 항목 아래에 나온다). */}
      <div className="row cl-actions" style={{ marginTop: 18 }}>
        <button className="btn btn-primary" onClick={save} disabled={busy}>
          {busy && !reviewing ? "처리 중…" : "저장"}
        </button>
        <button className="btn cl-review-btn" onClick={runReview} disabled={busy || filled.length === 0}
          title="쓴 글을 항목별로 확인해 고칠 부분을 알려 줍니다">
          {reviewing ? "검토하는 중…" : "전체 검토"}
        </button>
        <button className="btn" onClick={copyAll} disabled={filled.length === 0}>
          {copied === "all" ? "복사했습니다" : "전체 복사"}
        </button>
        <button className="btn" onClick={saveImage} disabled={busy || filled.length === 0}>
          이미지로 저장
        </button>
        {/* 처음 쓰는 학생이 순서를 다시 볼 수 있게 해 둔다. */}
        <button className="btn btn-ghost" onClick={() => setTour(true)}>
          처음이신가요?
        </button>
        {!isNew ? (
          <DownloadMenu id={id} disabled={busy || filled.length === 0} pdfOk={pdfOk}
            onError={(m) => setMsg({ type: "error", text: m })} />
        ) : (
          // 새 자소서는 아직 서버에 없어 파일로 받을 수 없다. 그래도 자리는 보여 준다 —
          // 안 보이면 "처음이신가요?" 안내의 마지막(6번째) 단계가 짚을 곳이 없어 건너뛰어졌다.
          <button className="btn" data-tour="download" disabled
            title="먼저 저장하면 파일로 받을 수 있습니다">
            파일로 받기 ▾
          </button>
        )}
        {!isNew && (
          <>
            <div className="spacer" />
            <button className="btn btn-ghost" onClick={remove}>지우기</button>
          </>
        )}
      </div>

      <p style={{ fontSize: 12.5, color: "var(--steel-light)", marginTop: 14, lineHeight: 1.7 }}>
        <b>전체 검토</b>는 내가 쓴 글 전체를 확인해 빠진 내용, 글자 수, 고치면 좋을 부분을
        항목마다 알려 주는 피드백입니다. 문장을 대신 써 주지는 않습니다.
        <br />내용이 있는 항목만 복사·저장됩니다. 빈 항목은 빠집니다.
      </p>

      {viewer && (
        <RecordViewer
          id={viewer.id}
          kinds={kinds}
          categoryLabels={categoryLabels}
          topicLabel={activeLabel}
          canAi={!!(aiOk?.available && aiOk?.consented)}
          picked={picked.includes(viewer.id)}
          onTogglePick={() => togglePick(viewer.id)}
          aiBusy={!!aiBusy}
          onClose={() => setViewer(null)}
          onWrite={() => essayFromRecord(viewer.id)}
          onAnalyze={() => { const id = viewer.id; setViewer(null); analyzeOne(id); }}
          onInsert={(text) => { insert(text); setViewer(null); }}
        />
      )}

      {/* 이미지로 저장할 때만 쓰는 판. 화면 밖에 두어 보이지 않는다. */}
      <div className="cl-sheet" ref={sheetRef} aria-hidden="true">
        <h1>{title.trim() || "자기소개서"}</h1>
        <div className="meta">
          {user?.name ? `${user.name} · ` : ""}
          {new Date().toLocaleDateString("ko-KR")}
        </div>
        {filled.map((t) => (
          <section key={t.key}>
            <h2>{t.label}</h2>
            <p>{content[t.key].trim()}</p>
          </section>
        ))}
        <div className="foot">기록해 · diary.ggm.kr</div>
      </div>
    </div>
  );
}

/* 글 점검 결과. 무엇이 빠졌고 무엇을 다듬으면 좋은지 보여준다. */
function ReviewBox({ result }) {
  if (result.ok) {
    return (
      <div className="review">
        <span className="review-ok">✓ {result.summary}</span>
      </div>
    );
  }
  return (
    <div className="review">
      <h5>{result.summary}</h5>
      {result.missing.map((m) => (
        <div className="review-item" key={m.key}>
          <span className="review-tag miss">빠짐</span>
          <span><b>{m.label}</b> — {m.hint}</span>
        </div>
      ))}
      {result.notes.map((n, i) => (
        <div className="review-item" key={i}>
          <span className={`review-tag ${n.kind === "over" ? "over" : ""}`}>
            {n.kind === "over" ? "초과" : "다듬기"}
          </span>
          <span>{n.target && <b>{n.target} </b>}{n.reason}</span>
        </div>
      ))}
    </div>
  );
}

/** 제출용 파일로 내려받기.
 *  화면에서 항목을 하나씩 복사해 붙이면 빠뜨리거나 순서가 뒤바뀐다.
 *  양식이 갖춰진 문서로 바로 받게 한다. */
function DownloadMenu({ id, disabled, pdfOk = true, onError }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState("");

  const get = async (fmt) => {
    setBusy(fmt);
    try {
      await api.downloadCoverLetter(id, fmt);
      setOpen(false);
    } catch (e) {
      onError?.(e.message);
    } finally {
      setBusy("");
    }
  };

  const kinds = [
    ["hwpx", "한글 (hwpx)", "한글에서 열어 고칠 수 있습니다", true],
    ["docx", "워드 (docx)", "워드·구글문서에서 열립니다", true],
    ["pdf", "PDF",
      pdfOk ? "그대로 인쇄하거나 제출할 때"
            : "지금은 만들 수 없습니다. 한글이나 워드로 받아주세요",
      pdfOk],
    ["txt", "텍스트", "어디든 붙여넣기 좋습니다", true],
  ];

  return (
    <span style={{ position: "relative", display: "inline-block" }}>
      <button className="btn" data-tour="download"
        disabled={disabled} onClick={() => setOpen(!open)}>
        파일로 받기 ▾
      </button>

      {open && (
        <>
          {/* 바깥을 누르면 닫히도록 덮개를 깐다. */}
          <div style={{ position: "fixed", inset: 0, zIndex: 20 }}
            onClick={() => setOpen(false)} />
          <div style={{
            position: "absolute", top: "calc(100% + 6px)", left: 0, zIndex: 21,
            background: "#fff", border: "1px solid var(--line)", borderRadius: 10,
            boxShadow: "0 8px 24px rgba(0,0,0,.12)", padding: 6, minWidth: 240,
          }}>
            {kinds.map(([fmt, label, hint, usable]) => (
              <button key={fmt} className="btn btn-ghost" disabled={!!busy || !usable}
                onClick={() => get(fmt)}
                style={{
                  display: "block", width: "100%", textAlign: "left",
                  padding: "8px 10px", border: "none", background: "none",
                }}>
                <b style={{ fontSize: 14,
                            color: usable ? undefined : "var(--steel-light)" }}>
                  {busy === fmt ? "만드는 중…" : label}
                </b>
                <span className="meta" style={{ display: "block", marginTop: 1 }}>
                  {hint}
                </span>
              </button>
            ))}
            <p className="meta" style={{ margin: "6px 10px 4px", lineHeight: 1.6 }}>
              내용을 쓴 항목만 들어갑니다. 항목마다 글자 수도 함께 적힙니다.
            </p>
          </div>
        </>
      )}
    </span>
  );
}

/** 말투 다듬기 결과.
 *  바로 덮어쓰지 않고 보여준 뒤 학생이 고르게 한다. 자기 글이기 때문이다. */
function PolishBox({ result, onApply, onClose }) {
  const clean = !result.changed && result.blocked.length === 0;

  return (
    <div style={{
      marginTop: 8, padding: 10, borderRadius: 8,
      border: "1px solid var(--line)",
      background: result.blocked.length ? "#fdf3f3" : "var(--raised, #f7f5f2)",
    }}>
      {clean ? (
        <p style={{ margin: 0, fontSize: 13, lineHeight: 1.7 }}>
          고칠 곳이 없습니다. 서류에 어울리는 말투입니다.
        </p>
      ) : (
        <>
          {result.notes.map((n, i) => (
            <p key={i} style={{ margin: i ? "6px 0 0" : 0, fontSize: 13,
                                lineHeight: 1.7 }}>
              {n}
            </p>
          ))}

          {result.changed && (
            <div style={{ marginTop: 8, padding: 8, borderRadius: 6,
                          background: "#fff", border: "1px solid var(--line)",
                          fontSize: 13.5, lineHeight: 1.8,
                          whiteSpace: "pre-wrap" }}>
              {result.text}
            </div>
          )}

          <div className="row" style={{ gap: 6, marginTop: 8 }}>
            {result.changed && (
              <button className="btn btn-sm btn-primary" onClick={onApply}>
                이대로 바꾸기
              </button>
            )}
            <button className="btn btn-sm btn-ghost" onClick={onClose}>닫기</button>
          </div>
        </>
      )}

      {clean && (
        <div className="row" style={{ gap: 6, marginTop: 8 }}>
          <button className="btn btn-sm btn-ghost" onClick={onClose}>닫기</button>
        </div>
      )}
    </div>
  );
}

/** AI 가 정리한 경험 하나.
 *
 *  원문을 함께 보여준다. AI 가 무엇을 어떻게 바꿨는지 학생이 직접 봐야
 *  한다. 몰래 다듬어 주면 학생은 자기 글이 어떻게 달라졌는지 모른 채
 *  제출하게 된다. */
function AnalysisBox({ result, picked, onToggle, onInsert }) {
  const [showOriginal, setShowOriginal] = useState(false);
  const exp = result.experience || {};

  const rows = [
    ["상황", exp.situation],
    ["문제", exp.problem],
    ["한 일", exp.action],
    ["결과", exp.result],
    ["배운 점", exp.lesson],
  ].filter(([, v]) => (v || "").trim());

  return (
    <div style={{ marginTop: 8, padding: 10, borderRadius: 8,
                  background: "var(--raised, #f7f5f2)",
                  border: "1px solid var(--line)" }}>
      {result.inappropriate?.length > 0 && (
        <p style={{ margin: "0 0 8px", fontSize: 12.5, lineHeight: 1.7,
                    color: "#9a6700" }}>
          서류에 어울리지 않는 표현을 다듬었습니다:{" "}
          {result.inappropriate.map((x) => x.text).join(", ")}
        </p>
      )}

      {/* AI 가 다듬은 글. 원문과 견줘 볼 수 있게 한다. */}
      <p style={{ margin: 0, fontSize: 13, lineHeight: 1.8, whiteSpace: "pre-wrap" }}>
        {showOriginal ? result.original_content : result.cleaned_content}
      </p>
      <button className="btn btn-sm btn-ghost" style={{ marginTop: 4 }}
        onClick={() => setShowOriginal(!showOriginal)}>
        {showOriginal ? "AI가 다듬은 글 보기" : "내가 쓴 원문 보기"}
      </button>

      {rows.length > 0 && (
        <table style={{ width: "100%", marginTop: 8, fontSize: 12.5 }}>
          <tbody>
            {rows.map(([label, value]) => (
              <tr key={label}>
                <td style={{ width: 56, verticalAlign: "top", padding: "3px 0",
                             color: "var(--steel-light)" }}>
                  {label}
                </td>
                <td style={{ padding: "3px 0", lineHeight: 1.7 }}>{value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {result.skills?.length > 0 && (
        <div style={{ marginTop: 8 }}>
          {result.skills.map((sk, i) => (
            <div key={i} style={{ fontSize: 12.5, lineHeight: 1.7 }}>
              <b>{sk.name}</b>
              {sk.evidence && (
                <span style={{ color: "var(--steel-light)" }}> — {sk.evidence}</span>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="row" style={{ gap: 6, marginTop: 8 }}>
        <button className={`btn btn-sm ${picked ? "" : "btn-ghost"}`}
          onClick={onToggle}>
          {picked ? "초안 재료로 고름 ✓" : "초안 재료로 고르기"}
        </button>
        <button className="btn btn-sm btn-ghost"
          onClick={() => onInsert(result.cleaned_content)}>
          다듬은 글 넣기
        </button>
      </div>
    </div>
  );
}

/** AI 기능 안내와 초안 만들기.
 *
 *  동의를 받기 전에는 무엇이 일어나는지 먼저 알린다.
 *  개인정보처리방침 제7조에 적은 대로다. */
function AiPanel({ status, busy, tick, picked, essay, noMaterials,
                   onConsent, onGenerate, onApply, onClose }) {
  const pickedTotal = picked.length;
  const [open, setOpen] = useState(false);

  // 재료 목록에 이어 붙는다. 별도 상자가 아니므로 위에 줄만 긋는다.
  const wrap = {
    marginTop: 14, paddingTop: 12,
    borderTop: "1px solid var(--line)",
  };

  // 재료를 못 찾았을 때는 AI 가 오히려 더 쓸모 있다.
  // 학생이 직접 일지를 골라 정리할 수 있기 때문이다.
  const hint = noMaterials
    ? "이 항목에 맞는 재료를 못 찾았더라도, 일지를 직접 골라 AI로 정리할 수 있습니다."
    : null;

  if (!status.consented) {
    return (
      <div style={wrap} data-tour="ai">
        <div style={{ padding: 10, borderRadius: 8, background: "#fdf6ec",
                      border: "1px solid #f0dcc0", fontSize: 12.5,
                      lineHeight: 1.8 }}>
          <b>AI로 경험을 정리할 수도 있습니다</b>
          {hint && (
            <p style={{ margin: "4px 0 0", color: "var(--ink)" }}>{hint}</p>
          )}
          <p style={{ margin: "4px 0 0" }}>
            일지를 자기소개서에 쓸 수 있는 문장으로 다듬고, 초안을 만들어
            드립니다. <b>없는 경험이나 성과를 지어내지 않습니다.</b>
          </p>
          <p style={{ margin: "6px 0 0" }}>
            쓰려면 동의가 필요합니다. 분석을 위해{" "}
            <b>작성한 글이 국외(미국)의 AI 서비스로 전송</b>됩니다.
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
              이전 항목 분석을 요청한 글의 본문(개인 식별 정보 제외) ·
              보유 기간 처리 완료 시까지. 동의하지 않아도 자기소개서 작성에
              불이익은 없고, <b>내 정보 → 보안</b>에서 언제든 거둘 수 있습니다.{" "}
              <a href="https://udjschool.ggm.kr/privacy" target="_blank"
                rel="noreferrer">개인정보처리방침 제7조</a>
            </p>
          )}
          <button className="btn btn-sm btn-primary" style={{ marginTop: 8 }}
            onClick={() => onConsent(true)}>
            동의하고 AI 쓰기
          </button>
        </div>
      </div>
    );
  }

  return (
    <div style={wrap} data-tour="ai">
      {busy ? (
        <p style={{ fontSize: 13, margin: 0, lineHeight: 1.7 }}>
          {busy}…{tick > 3 && ` (${tick}초)`}
          <br />
          <span style={{ fontSize: 12, color: "var(--steel-light)" }}>
            30초 정도 걸릴 수 있습니다. 다른 항목을 쓰고 계셔도 됩니다.
          </span>
        </p>
      ) : pickedTotal > 0 ? (
        <>
          <p style={{ fontSize: 12.5, color: "var(--steel)", margin: 0,
                      lineHeight: 1.7 }}>
            이 항목에 쓸 기록 <b>{pickedTotal}개</b>를 골랐습니다. 고른 기록만 근거로 씁니다.
          </p>
          <button className="btn btn-sm btn-primary" style={{ marginTop: 8 }}
            onClick={onGenerate}>
            고른 기록으로 자기소개서 작성하기
          </button>
        </>
      ) : (
        <p style={{ fontSize: 12.5, color: "var(--steel-light)", margin: 0,
                    lineHeight: 1.7 }}>
          {noMaterials
            ? "이 항목에 맞는 재료를 못 찾았습니다. 내 기록에서 쓸 만한 일지를 찾아 AI로 정리해 보세요."
            : "재료의 기록 보기에서 이 내용으로 자기소개서 작성하기를 누르거나, AI로 경험 분석으로 정리한 것을 골라 초안을 만들 수 있습니다."}
        </p>
      )}

      {essay && <EssayBox essay={essay} onApply={onApply} onClose={onClose} />}
    </div>
  );
}


/** AI 가 쓴 초안.
 *
 *  바로 넣지 않고 보여준 뒤 학생이 고르게 한다. 사실 확인 결과도
 *  함께 보여준다. 문제가 있으면 그대로 알리고, 우리가 임의로 고치지 않는다. */
function EssayBox({ essay, onApply, onClose }) {
  return (
    <div style={{ marginTop: 10, padding: 10, borderRadius: 8,
                  border: "1px solid var(--line)", background: "#fff" }}>
      <div style={{ fontSize: 13.5, lineHeight: 1.9, whiteSpace: "pre-wrap" }}>
        {essay.draft}
      </div>

      <p className="meta" style={{ margin: "8px 0 0" }}>
        {essay.character_count}자 / {essay.character_limit}자
      </p>

      {essay.used_records?.length > 0 && (
        <p className="meta" style={{ margin: "6px 0 0", lineHeight: 1.7 }}>
          근거로 쓴 기록:{" "}
          {essay.used_records.map((r) => `${String(r.entry_date).slice(0, 10)} ${r.kind} ${r.title}`.trim())
            .join(" · ")}
        </p>
      )}

      {essay.safe === false && essay.issues?.length > 0 && (
        <div style={{ marginTop: 8, padding: 8, borderRadius: 6,
                      background: "#fdecec", fontSize: 12.5, lineHeight: 1.7 }}>
          <b>확인이 필요합니다</b>
          {essay.issues.map((it, i) => (
            <p key={i} style={{ margin: "4px 0 0" }}>
              {it.text} — {it.reason}
            </p>
          ))}
          <p style={{ margin: "6px 0 0", color: "var(--steel)" }}>
            원문에 없는 내용입니다. 그대로 쓰면 면접에서 답하기 어렵습니다.
          </p>
        </div>
      )}

      {essay.warnings?.length > 0 && (
        <p className="meta" style={{ margin: "8px 0 0", lineHeight: 1.7 }}>
          {essay.warnings.join(" ")}
        </p>
      )}

      <div className="row" style={{ gap: 6, marginTop: 10 }}>
        <button className="btn btn-sm btn-primary" onClick={onApply}>
          본문에 넣기
        </button>
        <button className="btn btn-sm btn-ghost" onClick={onClose}>닫기</button>
      </div>
      <p className="meta" style={{ margin: "6px 0 0", lineHeight: 1.7 }}>
        AI가 쓴 초안입니다. 내 말로 고쳐서 쓰세요.
      </p>
    </div>
  );
}
/** 직업 선택. 검색해서 고르고, 다시 누르면 선택을 푼다.
 *  고른 직업군은 "이 항목에 쓸 만한 내 기록"의 순서와 AI 초안에 쓰인다. */
function JobPicker({ jobs, value, onChange }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(!value);
  const current = jobs.find((j) => j.key === value);
  const shown = q.trim()
    ? jobs.filter((j) => j.label.replace(/·/g, "").includes(q.trim().replace(/·/g, "")))
    : jobs;
  if (!jobs.length) return null;
  return (
    <div className="panel job-picker">
      <div className="row" style={{ alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span className="label" style={{ margin: 0 }}>직업 선택</span>
        {current ? (
          <span className="job-current">{current.label}</span>
        ) : (
          <span className="meta">아직 고르지 않았습니다</span>
        )}
        <div className="spacer" />
        <button type="button" className="btn btn-sm btn-ghost" onClick={() => setOpen(!open)}>
          {open ? "접기" : current ? "바꾸기" : "고르기"}
        </button>
      </div>
      {open && (
        <>
          <p className="meta" style={{ margin: "8px 0 10px", lineHeight: 1.7 }}>
            희망하는 직업군을 고르면, 그 직업과 이어지는 내 기록을 먼저 보여 주고
            AI 초안에도 반영합니다.
          </p>
          <input className="input" value={q} placeholder="직업 검색 (예: 디자인, 개발, 회계)"
            aria-label="직업 검색" onChange={(e) => setQ(e.target.value)} />
          <div className="job-chips" role="radiogroup" aria-label="직업군">
            {shown.map((j) => (
              <button key={j.key} type="button" role="radio" aria-checked={value === j.key}
                className={`job-chip${value === j.key ? " on" : ""}`}
                onClick={() => { onChange(value === j.key ? "" : j.key); if (value !== j.key) setOpen(false); }}>
                {j.label}
              </button>
            ))}
            {shown.length === 0 && <span className="meta">찾는 직업군이 없습니다.</span>}
          </div>
        </>
      )}
    </div>
  );
}

/** 이 항목에 쓰려고 고른 기록. 목록을 접어도 보인다. */
function PickedList({ ids, info, max, onOpen, onRemove }) {
  if (!ids.length) return null;
  return (
    <div className="picked-list">
      <div className="picked-list-head">이 항목에 쓸 기록 <b>{ids.length}</b> / {max}</div>
      {ids.map((id) => {
        const j = info[id];
        return (
          <div key={id} className="picked-item">
            <button type="button" className="picked-item-main" onClick={() => onOpen(id)}>
              <span className="meta">
                {j ? `${String(j.entry_date).slice(0, 10)} · ${j.kind_label}` : "기록"}
              </span>
              <span>{j ? (j.title || j.preview || "제목 없음") : `#${id}`}</span>
            </button>
            <button type="button" className="btn btn-sm btn-ghost" aria-label="빼기"
              onClick={() => onRemove(id)}>×</button>
          </div>
        );
      })}
    </div>
  );
}

const PICKER_TABS = [["all", "전체"], ["class", "수업일지"], ["school", "학교생활일지"]];

/** 내 일지에서 직접 고르기.
 *
 *  지금 쓰는 자소서 항목과 이어진 기록을 먼저 보여 준다.
 *    1) 일지를 쓸 때 이 항목 카테고리를 직접 달아 둔 기록
 *    2) 카테고리는 안 달았지만 내용이 이 항목과 맞아 보이는 기록(추천)
 *    3) 그 밖의 기록 — 카테고리를 안 골랐어도 빠뜨리지 않고 맨 아래에 둔다
 *  체크하면 이 항목에 쓸 기록으로 고르고, 줄을 누르면 내용을 펼쳐 본다. */
function RecordPicker({ open, onToggle, tab, onTab, rows, topic, topicLabel, categoryLabels,
                        recommended, picked, onTogglePick, onView }) {
  const rec = new Set(recommended || []);
  const groups = [[], [], []];
  for (const j of rows || []) {
    if ((j.resume_tags || []).includes(topic)) groups[0].push(j);
    else if (rec.has(j.id)) groups[1].push(j);
    else groups[2].push(j);
  }
  const titles = [
    `이 항목 카테고리를 단 기록`,
    "내용이 이 항목과 맞아 보이는 기록",
    "그 밖의 기록",
  ];

  return (
    <div style={{ marginTop: 12 }}>
      <button className="btn btn-sm" onClick={onToggle} aria-expanded={open}>
        {open ? "목록 접기" : "내 일지에서 직접 고르기"}
      </button>
      {open && (
        <div className="record-picker">
          <div className="record-picker-tabs" role="tablist" aria-label="일지 종류">
            {PICKER_TABS.map(([k, label]) => (
              <button key={k} type="button" role="tab" aria-selected={tab === k}
                className={`record-picker-tab${tab === k ? " on" : ""}`} onClick={() => onTab(k)}>
                {label}
              </button>
            ))}
          </div>
          {topicLabel && <p className="record-picker-topic">지금 항목: {topicLabel}</p>}
          {rows === null && <p className="meta" style={{ margin: 6 }}>불러오는 중…</p>}
          {rows && rows.length === 0 && (
            <p className="meta" style={{ margin: 6, lineHeight: 1.7 }}>
              {tab === "class" ? "수업일지가 없습니다." : tab === "school" ? "학교생활일지가 없습니다." : "아직 쓴 일지가 없습니다."}
              {" "}<a href="/journals/new">첫 기록</a>을 남겨보세요.
            </p>
          )}
          {groups.map((list, gi) => list.length > 0 && (
            <div key={gi}>
              <div className="record-picker-group">{titles[gi]} <span>{list.length}</span></div>
              {list.map((j) => {
                const on = picked.includes(j.id);
                return (
                  <div key={j.id} className={`record-picker-row${on ? " on" : ""}`}>
                    <input type="checkbox" checked={on} aria-label={`${j.title || "기록"} 사용하기`}
                      onChange={() => onTogglePick(j.id)} />
                    <button type="button" className="record-picker-open" onClick={() => onView(j.id)}>
                      <span className="meta">
                        {String(j.entry_date).slice(0, 10)} · {j.kind_label || ""}
                        {gi === 0 && <span className="record-picker-tag">{categoryLabels[topic] ? "카테고리 일치" : ""}</span>}
                        {gi === 1 && <span className="record-picker-tag rec">추천</span>}
                      </span>
                      <span className="record-picker-title">
                        {(j.title || j.preview || j.subject || "내용 보기").slice(0, 40)}
                      </span>
                    </button>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** 기록 하나를 펼쳐 보는 창.
 *  학생이 무엇을 썼는지 그대로 보여 주고, 이 기록만 근거로 초안을 쓰게 한다. */
function RecordViewer({ id, kinds, categoryLabels, topicLabel, canAi, aiBusy,
                        picked, onTogglePick, onClose, onWrite, onAnalyze, onInsert }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState("");
  // 부모가 다시 그려질 때마다 onClose 가 새로 만들어진다. 그걸 의존성에 두면
  // 기록을 계속 다시 불러오므로, 닫기는 ref 로 들고 불러오기는 id 에만 묶는다.
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    setD(null);
    api.journal(id).then(setD).catch((e) => setErr(e.message));
  }, [id]);
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") closeRef.current(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const kind = kinds.find((k) => k.kind === d?.kind);
  const fieldList = kind
    ? [...kind.fields.map((f) => ({ key: f.key, label: f.full_label || f.label })),
       ...(kind.legacy_fields || [])]
    : [];
  const rows = d ? fieldList.filter((f) => (d.content?.[f.key] || "").trim()) : [];
  const whole = rows.map((f) => d.content[f.key].trim()).join("\n\n");

  return (
    <div className="rv-backdrop" role="presentation"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="rv-dialog" role="dialog" aria-modal="true" aria-label="기록 보기">
        <div className="row" style={{ alignItems: "flex-start", gap: 8 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            {d && (
              <div className="meta">
                {kind?.label || d.kind} · {String(d.entry_date).slice(0, 10)}
                {d.subject ? ` · ${d.subject}` : ""}
              </div>
            )}
            <h3 style={{ margin: "4px 0 0" }}>{d ? (d.title || "제목 없음") : "불러오는 중…"}</h3>
          </div>
          <button type="button" className="btn btn-sm btn-ghost" onClick={onClose}>닫기</button>
        </div>

        {err && <div className="notice notice-error" style={{ marginTop: 10 }}>{err}</div>}

        {d?.resume_tags?.length > 0 && (
          <div className="rv-tags">
            {d.resume_tags.map((k) => (
              <span key={k} className="rv-tag">{categoryLabels[k] || k}</span>
            ))}
          </div>
        )}

        <div className="rv-body">
          {d && rows.length === 0 && <p className="meta">적힌 내용이 없습니다.</p>}
          {rows.map((f) => (
            <div key={f.key} className="rv-field">
              <div className="rv-label">{f.label}</div>
              <p>{d.content[f.key]}</p>
            </div>
          ))}
        </div>

        {d && rows.length > 0 && (
          <div className="rv-actions">
            <button type="button" className={`btn ${picked ? "btn-primary" : ""}`}
              aria-pressed={picked} onClick={onTogglePick}>
              {picked ? "✓ 이 항목에 사용 중 (빼기)" : "이 기록 사용하기"}
            </button>
            {canAi ? (
              <button type="button" className="btn" disabled={aiBusy} onClick={onWrite}>
                이 내용으로 자기소개서 작성하기
              </button>
            ) : (
              <span className="meta">AI 기능에 동의하면 이 기록으로 초안을 만들 수 있습니다.</span>
            )}
            {canAi && (
              <button type="button" className="btn btn-sm btn-ghost" disabled={aiBusy} onClick={onAnalyze}>
                AI로 경험 분석
              </button>
            )}
            <button type="button" className="btn btn-sm btn-ghost" onClick={() => onInsert(whole)}>
              원문을 본문에 넣기
            </button>
          </div>
        )}
        {topicLabel && d && rows.length > 0 && (
          <p className="meta" style={{ margin: "8px 0 0", lineHeight: 1.6 }}>
            지금 쓰는 항목: {topicLabel}
          </p>
        )}
      </div>
    </div>
  );
}

/** 지원동기 · 입사 후 목표.
 *
 *  지난 일을 적은 일지에는 "왜 이 회사에" "앞으로 무엇을"의 답이 없다.
 *  그래서 AI 가 1~2학년 기록을 읽고 이 학생에게 맞는 질문을 만들고,
 *  학생이 답한 말로 글을 쓴다. 학생이 카테고리를 고를 필요는 없다. */
function MotivePanel({ topic, data, jobLabel, busy, tick, essay,
                       onMake, onAnswer, onWrite, onApply, onClose }) {
  const questions = data?.questions || [];
  const answers = data?.answers || {};
  const groups = [...new Set(questions.map((q) => q.group))];
  const answered = questions.filter((q) => (answers[q.id] || "").trim()).length;
  const isGoal = topic === "future_goal";

  return (
    <div className="motive" data-tour="ai">
      <h4 style={{ margin: 0, fontSize: 14 }}>
        {isGoal ? "입사 후 목표 — 질문에 답하며 쓰기" : "지원동기 — 질문에 답하며 쓰기"}
      </h4>
      <p className="meta" style={{ margin: "6px 0 0", lineHeight: 1.7 }}>
        1~2학년 때 쓴 학교생활일지와 수업일지를 읽고, 나에게 맞는 질문을 만들어 드립니다.
        {isGoal ? " 단기(입사 후 1~3년)와 장기(5년 이후) 목표를 나눠 묻습니다." : ""}
        {jobLabel ? ` 희망 직업군(${jobLabel})도 반영합니다.` : " 위에서 직업을 고르면 더 잘 맞는 질문이 나옵니다."}
      </p>

      {busy ? (
        <p style={{ fontSize: 13, margin: "10px 0 0", lineHeight: 1.7 }}>
          {busy}…{tick > 3 && ` (${tick}초)`}
        </p>
      ) : (
        <button type="button" className="btn btn-sm btn-primary" style={{ marginTop: 10 }} onClick={onMake}>
          {questions.length ? "질문 다시 만들기" : "내 기록으로 질문 만들기"}
        </button>
      )}

      {groups.map((g) => (
        <div key={g} className="motive-group">
          <div className="motive-group-title">{g}</div>
          {questions.filter((q) => q.group === g).map((q) => (
            <div key={q.id} className="motive-q">
              <label htmlFor={`mq-${q.id}`}>{q.question}</label>
              {q.basis?.length > 0 && (
                <div className="motive-basis">
                  근거: {q.basis.map((b) =>
                    `${String(b.entry_date).slice(0, 10)} ${b.title}${b.evidence ? ` — ${b.evidence}` : ""}`)
                    .join(" / ")}
                </div>
              )}
              <textarea id={`mq-${q.id}`} className="motive-answer" value={answers[q.id] || ""}
                placeholder="떠오르는 대로 편하게 적어 주세요"
                onChange={(e) => onAnswer(q.id, e.target.value)} />
            </div>
          ))}
        </div>
      ))}

      {questions.length > 0 && !busy && (
        <>
          <button type="button" className="btn btn-sm btn-primary" style={{ marginTop: 10 }}
            disabled={!answered} onClick={onWrite}>
            답변으로 자기소개서 작성하기
          </button>
          <p className="meta" style={{ margin: "6px 0 0", lineHeight: 1.6 }}>
            {answered ? `${answered}개 답변을 씁니다.` : "하나 이상 답하면 쓸 수 있습니다."}
            {" "}답에 없는 경험은 만들어 넣지 않습니다.
          </p>
        </>
      )}

      {essay && <EssayBox essay={essay} onApply={onApply} onClose={onClose} />}
    </div>
  );
}
