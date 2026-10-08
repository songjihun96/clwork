import { useRef, useState } from "react";
import { createPortal } from "react-dom";
import { breakPoints, canvasesToPdf, downloadBlob, downloadPng, renderNode, sliceCanvas } from "../exportImage";

/** 진로 테스트 결과 + 추천 학과 챗봇과 나눈 대화를 한 장으로 정리해 내려받는다.
 *
 * 화면의 말풍선을 그대로 찍지 않고 **정리한 문서**를 따로 그린다. 창 크기에
 * 따라 줄이 바뀌거나 단추가 찍히는 일이 없고, 부모님·선생님께 보여 줄 때
 * "무엇을 물어서 무슨 답을 들었는지"가 한눈에 읽혀야 해서다.
 *
 *   · 맨 위: 테스트 결과 요약(어울리는 분야, 관심 분포 상위)
 *   · 계열마다: 알아본 직업, 그리고 질문 → 답
 *   · 오류로 뜬 말풍선은 대화가 아니라 뺀다
 */
const SCALE = 2;

function today() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return { label: `${d.getFullYear()}.${p(d.getMonth() + 1)}.${p(d.getDate())}`,
    file: `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}` };
}

/** 질문 → 답 쌍으로 묶는다. 답이 여러 개 이어지면 이어 붙인다. */
function toPairs(log) {
  const pairs = [];
  for (const m of log || []) {
    if (m.error) continue;
    if (m.role === "user") pairs.push({ q: m.content, job: m.job || "", a: [] });
    else if (pairs.length) pairs[pairs.length - 1].a.push(m.content);
  }
  return pairs.filter((p) => p.a.length);
}

export function hasConversation(logs) {
  return Object.values(logs || {}).some((log) => toPairs(log).length > 0);
}

function Report({ result, logs, date }) {
  const groups = Object.entries(logs || {})
    .map(([group, log]) => [group, toPairs(log)])
    .filter(([, pairs]) => pairs.length);
  const axes = result
    ? [...(result.top_axes || [])].map((a) => [result.axis_labels?.[a] || a, result.scores?.[a]])
    : [];

  return (
    <div className="ccr">
      <div className="ccr-head" data-break>
        <div className="ccr-brand">우리동네 직업계고 · 진로 상담 정리</div>
        <h1>나의 진로 탐색 기록</h1>
        <div className="ccr-date">{date}</div>
      </div>

      {result && (
        <section className="ccr-section" data-break>
          <h2>진로 테스트 결과</h2>
          <p className="ccr-lead">
            나와 어울리는 분야는 <b>{result.departments.map((d) => d.label).join(", ")}</b>
          </p>
          {axes.length > 0 && (
            <ul className="ccr-axes">
              {axes.map(([label, score]) => <li key={label}>{label} <b>{score}점</b></li>)}
            </ul>
          )}
          <div className="ccr-depts">
            {result.departments.map((d, i) => (
              <div key={d.label} className="ccr-dept">
                <b>{i + 1}. {d.label}</b>
                {d.jobs?.length > 0 && <span> — {d.jobs.join(", ")}</span>}
              </div>
            ))}
          </div>
        </section>
      )}

      {groups.map(([group, pairs]) => {
        const jobs = [...new Set(pairs.map((p) => p.job).filter(Boolean))];
        return (
          <section key={group} className="ccr-section">
            {/* 제목 바로 밑에서는 쪽을 자르지 않는다 — 제목만 쪽 끝에 홀로 남는다. */}
            <h2>{group} — AI 도우미와 나눈 이야기</h2>
            {jobs.length > 0 && (
              <p className="ccr-jobs">알아본 직업: {jobs.join(", ")}</p>
            )}
            {pairs.map((p, i) => (
              <div key={i} className="ccr-qa" data-break>
                <div className="ccr-q"><span>Q</span>{p.q}</div>
                <div className="ccr-a"><span>A</span>{p.a.join("\n\n")}</div>
              </div>
            ))}
          </section>
        );
      })}

      <p className="ccr-foot" data-break>
        AI 도우미의 답은 참고용이에요. 자격증과 연봉은 선생님이나 고용24·커리어넷에서 한 번 더 확인해 주세요.
        <br />우리동네 직업계고 · ㅇㅈ
      </p>
    </div>
  );
}

/** [이미지로 저장] [PDF로 저장] 단추. 누르는 순간에만 문서를 화면 밖에 그려 찍는다. */
export default function CareerChatExport({ result, logs, size = "sm", label = "대화 정리 저장" }) {
  const [busy, setBusy] = useState("");
  const [drawing, setDrawing] = useState(false);
  const holder = useRef(null);
  const date = today();

  if (!hasConversation(logs)) return null;

  const run = async (kind) => {
    if (busy) return;
    setBusy(kind);
    setDrawing(true);
    try {
      // 문서가 그려지고 글꼴이 준비될 때까지 한 박자 기다린다. requestAnimationFrame 은
      // 탭이 뒤로 가 있으면 멈춰서 "만드는 중"에 영영 걸리므로 타이머를 쓴다.
      await new Promise((r) => setTimeout(r, 80));
      if (document.fonts?.ready) await document.fonts.ready;
      const node = holder.current?.firstChild;
      if (!node) return;
      const canvas = await renderNode(node, SCALE);
      const name = `우리동네직업계고_진로상담정리_${date.file}`;
      if (kind === "png") {
        await downloadPng(canvas, `${name}.png`);
      } else {
        const pages = sliceCanvas(canvas, breakPoints(node, SCALE));
        downloadBlob(canvasesToPdf(pages), `${name}.pdf`);
      }
    } catch (e) {
      alert(`저장하지 못했어요. 다시 시도해 주세요. (${e.message || e})`);
    } finally {
      setDrawing(false);
      setBusy("");
    }
  };

  const cls = size === "sm" ? "btn btn-sm" : "btn";
  return (
    <>
      <span className="ccr-actions" role="group" aria-label={label}>
        <span className="ccr-actions-label">{label}</span>
        <button type="button" className={cls} disabled={!!busy} onClick={() => run("png")}>
          {busy === "png" ? "만드는 중…" : "이미지"}
        </button>
        <button type="button" className={cls} disabled={!!busy} onClick={() => run("pdf")}>
          {busy === "pdf" ? "만드는 중…" : "PDF"}
        </button>
      </span>
      {drawing && createPortal(
        <div ref={holder} className="ccr-offscreen" aria-hidden="true">
          <Report result={result} logs={logs} date={date.label} />
        </div>,
        document.body,
      )}
    </>
  );
}
