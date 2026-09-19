import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { activeOptions, labelOf, useCallCenter } from "../callcenter";
import { Empty, Modal, Note, Pager, fmtDateTime, useList } from "../components/ui";

/** 상담 목록. 전화든 홈페이지 문의든 여기로 모인다.
 *
 *  기본 화면은 '미처리'다. 전체 목록은 훑을 일이 드물고, 상담원이 아침에
 *  열었을 때 봐야 하는 것은 아직 안 끝난 건이기 때문이다.
 */

// 이름은 관리자가 바꿀 수 있으므로 서버(전화 설정)에서 받아 쓴다.
// 반면 색은 코드값에 묶어 둔다. 색까지 설정으로 빼면 "완료가 빨간색"인
// 화면을 만들 수 있게 되고, 그건 도움이 되지 않는다.
const STATUS_BADGE = {
  NEW: "wait",
  RECEIVED: "wait",
  IN_PROGRESS: "hold",
  WAITING: "hold",
  PROCESSING: "hold",
  COMPLETED: "done",
  HOLD: "stop",
};

const CHANNEL_LABEL = {
  PHONE: "전화",
  HOMEPAGE: "홈페이지",
  EMAIL: "이메일",
  OTHER: "기타",
};

export default function Consultations() {
  const cc = useCallCenter();
  const statusOpts = cc?.options?.statuses || [];
  const priorityOpts = cc?.options?.priorities || [];
  const [status, setStatus] = useState("open");
  const [channel, setChannel] = useState("");
  const [mine, setMine] = useState(false);
  const [open, setOpen] = useState(null);
  const [types, setTypes] = useState([]);
  const [counselors, setCounselors] = useState([]);

  useEffect(() => {
    api.inquiryTypes().then((r) => setTypes(r.items || [])).catch(() => {});
    api.counselors().then((r) => setCounselors(r.items || [])).catch(() => {});
  }, []);

  const list = useList(
    ({ limit, offset }) => api.consultations({ status, channel, mine, limit, offset }),
    [status, channel, mine]
  );

  return (
    <>
      <div className="page-head">
        <h1>상담</h1>
        <p>전화 상담과 홈페이지 문의가 같은 목록으로 모입니다.</p>
      </div>

      <div className="toolbar">
        {[
          ["open", "미처리"],
          ["COMPLETED", "완료"],
          ["", "전체"],
        ].map(([v, label]) => (
          <button key={v} className={`btn ${status === v ? "primary" : ""}`}
                  onClick={() => setStatus(v)}>
            {label}
          </button>
        ))}
        <select value={channel} onChange={(e) => setChannel(e.target.value)} aria-label="채널">
          <option value="">모든 채널</option>
          {Object.entries(CHANNEL_LABEL).map(([v, l]) => (
            <option key={v} value={v}>{l}</option>
          ))}
        </select>
        <button className={`btn ${mine ? "primary" : ""}`} onClick={() => setMine(!mine)}>
          내 상담만
        </button>
      </div>

      <div className="card">
        <Note kind="bad">{list.error}</Note>
        {list.loading ? (
          <Empty>불러오는 중…</Empty>
        ) : list.items.length === 0 ? (
          <Empty>{status === "open" ? "미처리 상담이 없습니다." : "상담이 없습니다."}</Empty>
        ) : (
          <>
            <table>
              <thead>
                <tr>
                  <th>제목</th>
                  <th>고객</th>
                  <th>채널</th>
                  <th>유형</th>
                  <th>담당</th>
                  <th>상태</th>
                  <th>접수</th>
                </tr>
              </thead>
              <tbody>
                {list.items.map((x) => (
                  <tr key={x.id} className="row-click" onClick={() => setOpen(x)}>
                    <td>
                      {x.priority === "URGENT" && (
                        <span className="badge stop">{labelOf(priorityOpts, "URGENT")}</span>
                      )}{" "}
                      {x.subject || <span className="muted tiny">제목 없음</span>}
                    </td>
                    <td>{x.customer_name || <span className="muted tiny">—</span>}</td>
                    <td className="tiny">{CHANNEL_LABEL[x.channel] || x.channel}</td>
                    <td className="tiny muted">{x.inquiry_type_name || "미분류"}</td>
                    <td className="tiny">{x.counselor_name || <span className="muted">미배정</span>}</td>
                    <td>
                      <span className={`badge ${STATUS_BADGE[x.status] || "flat"}`}>
                        {labelOf(statusOpts, x.status)}
                      </span>
                    </td>
                    <td className="tiny muted">{fmtDateTime(x.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pager {...list} onMove={list.move} />
          </>
        )}
      </div>

      {open && (
        <Detail
          row={open}
          types={types}
          counselors={counselors}
          statusOpts={statusOpts}
          priorityOpts={priorityOpts}
          onClose={() => setOpen(null)}
          onSaved={() => {
            setOpen(null);
            list.reload();
          }}
        />
      )}
    </>
  );
}

function Detail({ row, types, counselors, statusOpts, priorityOpts, onClose, onSaved }) {
  const { user } = useAuth();
  const [form, setForm] = useState({
    subject: row.subject || "",
    content: row.content || "",
    result: row.result || "",
    status: row.status,
    priority: row.priority,
    inquiry_type_id: row.inquiry_type_id || "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      await api.updateConsultation(row.id, {
        customer_id: row.customer_id,
        call_log_id: row.call_log_id,
        channel: row.channel,
        inquiry_type_id: form.inquiry_type_id ? Number(form.inquiry_type_id) : null,
        subject: form.subject.trim(),
        content: form.content.trim(),
        result: form.result.trim(),
        status: form.status,
        priority: form.priority,
      });
      onSaved();
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  };

  const takeIt = async () => {
    setError("");
    try {
      await api.assignConsultation(row.id, user.id);
      onSaved();
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <Modal
      title={row.subject || "상담"}
      sub={`${CHANNEL_LABEL[row.channel] || row.channel} · ${fmtDateTime(row.created_at)} · ${
        row.customer_name || "고객 미지정"
      }`}
      onClose={onClose}
      foot={
        <>
          <button className="btn" onClick={onClose}>닫기</button>
          {row.counselor_id !== user.id && (
            <button className="btn" onClick={takeIt}>내가 맡기</button>
          )}
          <button className="btn go" onClick={save} disabled={busy}>
            {busy ? "저장 중…" : "저장"}
          </button>
        </>
      }
    >
      <Note kind="bad">{error}</Note>

      <div className="field">
        <label htmlFor="d-subject">제목</label>
        <input id="d-subject" value={form.subject}
               onChange={(e) => setForm({ ...form, subject: e.target.value })} />
      </div>

      <div className="grid2">
        <div className="field">
          <label htmlFor="d-type">문의 유형</label>
          <select id="d-type" value={form.inquiry_type_id}
                  onChange={(e) => setForm({ ...form, inquiry_type_id: e.target.value })}>
            <option value="">선택 안 함</option>
            {types.filter((t) => t.is_active || t.id === row.inquiry_type_id).map((t) => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="d-pri">우선순위</label>
          <select id="d-pri" value={form.priority}
                  onChange={(e) => setForm({ ...form, priority: e.target.value })}>
            {activeOptions(priorityOpts, row.priority).map((o) => (
              <option key={o.code} value={o.code}>{o.label}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="field">
        <label htmlFor="d-content">상담 내용</label>
        <textarea id="d-content" value={form.content}
                  onChange={(e) => setForm({ ...form, content: e.target.value })} />
      </div>

      <div className="field">
        <label htmlFor="d-result">처리 결과</label>
        <textarea id="d-result" value={form.result}
                  onChange={(e) => setForm({ ...form, result: e.target.value })} />
      </div>

      <div className="grid2">
        <div className="field">
          <label htmlFor="d-status">상태</label>
          <select id="d-status" value={form.status}
                  onChange={(e) => setForm({ ...form, status: e.target.value })}>
            {activeOptions(statusOpts, row.status).map((o) => (
              <option key={o.code} value={o.code}>{o.label}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label>담당 상담원</label>
          <div className="masked">
            {counselors.find((c) => c.id === row.counselor_id)?.name || "미배정"}
          </div>
        </div>
      </div>
    </Modal>
  );
}
