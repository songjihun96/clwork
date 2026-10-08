import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import Modal from "./Modal";
import CareerChatExport from "./CareerChatReport";

/** 추천 학과 챗봇 — 진로 테스트 결과에서 연다.
 *
 * 질문은 두 가지로 받는다.
 *
 *   · **단추 질문**(어떤 일이에요 / 어떻게 돼요 / 자격증 / 첫 월급) — AI 를
 *     부르지 않고 정보표에서 바로 답한다. 가장 많이 눌리는 질문이라 돈이
 *     안 들고, 무엇보다 틀릴 일이 없다.
 *   · **직접 쓴 질문** — Claude 가 같은 정보표를 보고 쉬운 말로 답한다.
 *
 * 단추로 나눈 대화도 기록에 남겨 AI 에게 함께 보낸다. 그래야 "그 자격증은
 * 어려워요?" 같은 되물음이 무엇을 가리키는지 안다.
 *
 * 초봉이 아직 확인되지 않은 직업은 숫자를 지어내지 않고, 어디서 찾아보는지
 * 알려 준다(정보표가 비어 있으면 화면도, AI 도 같은 말을 한다).
 *
 * **대화는 부모(진로 테스트 결과)가 들고 있다**(log / setLog). 창을 닫았다
 * 열어도 이어지고, 여러 계열에서 나눈 대화를 테스트 결과와 함께 한 장으로
 * 정리해 이미지·PDF 로 내려받을 수 있다(CareerChatReport).
 */
const QUICK = [
  ["easy", "어떤 일이에요?"],
  ["path", "어떻게 될 수 있어요?"],
  ["certs", "자격증은요?"],
  ["salary", "첫 월급은요?"],
];

// AI 에게 보낼 때 최근 대화만 넘긴다. 서버가 한 번에 받는 질문 수에 한도가
// 있고, 오래된 이야기는 지금 질문에 별 도움이 안 된다.
const KEEP_MESSAGES = 12;

/** 받침에 맞는 조사를 붙인다. "웹 개발자은(는)"처럼 괄호로 둘 다 적으면
 *  중학생 눈에는 기계가 쓴 글로 읽힌다. 마지막 글자가 한글이 아니면
 *  (영문·숫자) 받침을 알 수 없어 괄호 표기로 둔다. */
function josa(word, withBatchim, without) {
  const ch = (word || "").trim().slice(-1);
  const code = ch.charCodeAt(0) - 0xac00;
  if (Number.isNaN(code) || code < 0 || code > 11171) return `${word}${withBatchim}(${without})`;
  return word + (code % 28 ? withBatchim : without);
}

function answerFromTable(kind, job, lookup) {
  if (!job) return "";
  if (kind === "easy") return `${josa(job.name, "은", "는")} ${josa(job.easy, "이에요", "예요")}.`;
  if (kind === "path") {
    const steps = (job.path || []).map((p, i) => `${i + 1}. ${p}`).join("\n");
    return `${josa(job.name, "이", "가")} 되는 길이에요.\n${steps}` +
      (job.effort ? `\n\n이런 노력이 필요해요: ${job.effort}` : "");
  }
  if (kind === "certs") {
    const certs = job.certs || [];
    return certs.length
      ? `${job.name}에게 도움이 되는 자격증이에요.\n${certs.map((c) => `• ${c}`).join("\n")}`
      : `${josa(job.name, "은", "는")} 꼭 따야 하는 자격증이 따로 없어요. 내가 직접 만든 작품이나 경험이 더 중요해요.`;
  }
  if (kind === "salary") {
    if ((job.salary || "").trim()) {
      return `${job.name}의 첫해 연봉은 ${josa(job.salary, "이에요", "예요")}.` +
        (job.salary_source ? `\n(출처: ${job.salary_source})` : "") +
        "\n회사 크기와 지역에 따라 달라질 수 있어요.";
    }
    const where = (lookup || []).map((x) => x.name).join(", ");
    return `${job.name}의 첫 월급은 회사 크기와 지역에 따라 많이 달라서, 아직 확인된 숫자가 없어요.` +
      (where ? `\n${where}에서 직업 이름으로 찾아보면 알 수 있어요.` : "");
  }
  return "";
}

export default function CareerChat({ group, onClose, log: outerLog, setLog: outerSetLog,
  allLogs, result }) {
  const [guide, setGuide] = useState(null);
  const [error, setError] = useState("");
  const [job, setJob] = useState(null);
  const [ownLog, setOwnLog] = useState([]);    // [{role, content, job?}]
  const log = outerLog ?? ownLog;
  const setLog = outerSetLog ?? setOwnLog;
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef(null);

  useEffect(() => {
    api.careerGuide(group)
      .then((d) => { setGuide(d); setJob(d.jobs?.[0] || null); })
      .catch((e) => setError(e.message));
  }, [group]);

  useEffect(() => { endRef.current?.scrollIntoView({ block: "end" }); }, [log, busy]);

  const push = (...items) => setLog((cur) => [...cur, ...items]);

  const quick = (kind, label) => {
    push({ role: "user", content: `${job.name} — ${label}`, job: job.name },
      { role: "assistant", content: answerFromTable(kind, job, guide?.salary_lookup) });
  };

  const send = async (e) => {
    e?.preventDefault();
    const q = text.trim();
    if (!q || busy) return;
    const next = [...log, { role: "user", content: q, job: job?.name || "" }];
    setLog(next);
    setText("");
    setBusy(true);
    try {
      // 오류로 띄운 말풍선은 대화가 아니다 — AI 에게 넘기면 자기가 한 말인 줄 안다.
      let recent = next.filter((m) => !m.error).slice(-KEEP_MESSAGES)
        .map(({ role, content }) => ({ role, content }));
      // 첫 말은 학생 말이어야 한다(잘라 낸 자리가 답으로 시작하면 한 칸 민다).
      while (recent.length && recent[0].role !== "user") recent = recent.slice(1);
      const r = await api.careerChat(group, recent);
      push({ role: "assistant", content: r.reply });
    } catch (err) {
      push({ role: "assistant", content: err.message || "답을 받지 못했어요. 다시 물어봐 주세요.", error: true });
    } finally {
      setBusy(false);
    }
  };

  const max = guide?.max_chars || 300;

  return (
    <Modal title={`${group} — 직업 알아보기`} onClose={onClose} maxWidth={600}>
      {error && <div className="notice notice-error" style={{ marginTop: 10 }}>{error}</div>}
      {!guide && !error && <p style={{ color: "var(--steel)" }}>불러오는 중…</p>}

      {guide && (
        <>
          <p style={{ fontSize: 13, color: "var(--steel)", margin: "6px 0 10px", lineHeight: 1.7 }}>
            궁금한 직업을 고르고 단추를 누르거나, 아래에 직접 물어보세요.
          </p>

          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {guide.jobs.map((j) => (
              <button key={j.name} type="button"
                className={`btn btn-sm ${job?.name === j.name ? "btn-signal" : "btn-ghost"}`}
                style={job?.name === j.name ? {} : { border: "1px solid var(--line)" }}
                onClick={() => setJob(j)}>
                {j.name}
              </button>
            ))}
          </div>

          {job && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 10 }}>
              {QUICK.map(([kind, label]) => (
                <button key={kind} type="button" className="btn btn-sm"
                  onClick={() => quick(kind, label)}>
                  {label}
                </button>
              ))}
            </div>
          )}

          <div className="career-chat-log">
            {log.length === 0 && (
              <p style={{ fontSize: 13, color: "var(--steel-light)", textAlign: "center", margin: "18px 0" }}>
                여기에 대화가 쌓여요.
              </p>
            )}
            {log.map((m, i) => (
              <div key={i} className={`career-msg career-msg-${m.role}${m.error ? " is-error" : ""}`}>
                {m.content}
              </div>
            ))}
            {busy && <div className="career-msg career-msg-assistant is-typing">생각하는 중…</div>}
            <div ref={endRef} />
          </div>

          {guide.ai_available ? (
            <form onSubmit={send} style={{ display: "flex", gap: 8, marginTop: 10 }}>
              <input className="input" value={text} maxLength={max}
                placeholder="예) 수학을 못해도 할 수 있어요?"
                onChange={(e) => setText(e.target.value)} disabled={busy} />
              <button className="btn btn-signal" type="submit" disabled={busy || !text.trim()}>
                물어보기
              </button>
            </form>
          ) : (
            <p style={{ fontSize: 12.5, color: "var(--steel)", marginTop: 10 }}>
              지금은 직접 묻기를 쓸 수 없어요. 위 단추로 알아보세요.
            </p>
          )}

          <div style={{ marginTop: 10 }}>
            <CareerChatExport result={result} logs={allLogs || { [group]: log }} />
          </div>

          <p style={{ fontSize: 11.5, color: "var(--steel-light)", margin: "10px 0 0", lineHeight: 1.6 }}>
            AI 도우미의 답은 참고용이에요. 자격증과 연봉은 선생님이나
            고용24·커리어넷에서 한 번 더 확인해 주세요.
          </p>
        </>
      )}
    </Modal>
  );
}
