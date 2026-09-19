import { useState } from "react";
import { api } from "../api";
import { Empty, Masked, Modal, Note, Pager, fmtDateTime, useList } from "../components/ui";

export default function Inquiries() {
  const [status, setStatus] = useState("pending");
  const [open, setOpen] = useState(null);

  const list = useList(({ limit, offset }) => api.inquiries({ status, limit, offset }), [status]);

  return (
    <>
      <div className="page-head">
        <h1>문의</h1>
        <p>답변은 학교 메일 계정으로, 없으면 포털 계정으로 대신 나갑니다.</p>
      </div>

      <div className="toolbar">
        {[
          ["pending", "답변 대기"],
          ["answered", "답변 완료"],
          ["", "전체"],
        ].map(([v, label]) => (
          <button
            key={v}
            className={`btn ${status === v ? "primary" : ""}`}
            onClick={() => setStatus(v)}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="card">
        <Note kind="bad">{list.error}</Note>
        {list.loading ? (
          <Empty>불러오는 중…</Empty>
        ) : list.items.length === 0 ? (
          <Empty>{status === "pending" ? "답변을 기다리는 문의가 없습니다." : "문의가 없습니다."}</Empty>
        ) : (
          <>
            <table>
              <thead>
                <tr>
                  <th>학교</th>
                  <th>문의자</th>
                  <th>내용</th>
                  <th>상태</th>
                  <th>접수</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {list.items.map((q) => (
                  <tr key={q.id} className="row-click" onClick={() => setOpen(q)}>
                    <td>{q.school_name}</td>
                    <td>
                      {q.asker_name || <span className="muted tiny">이름 없음</span>}
                      <div>
                        <Masked value={q.contact_email} />
                      </div>
                    </td>
                    <td style={{ maxWidth: 320 }}>
                      <div
                        style={{
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {q.question}
                      </div>
                    </td>
                    <td>
                      {q.status === "pending" ? (
                        <span className="badge wait">답변 대기</span>
                      ) : q.delivery_status === "failed" ? (
                        <span className="badge stop">발송 실패</span>
                      ) : q.delivery_status === "not_configured" ? (
                        <span className="badge hold">메일 미설정</span>
                      ) : (
                        <span className="badge done">답변 완료</span>
                      )}
                    </td>
                    <td className="tiny muted">{fmtDateTime(q.created_at)}</td>
                    <td>
                      <button className="btn sm">{q.status === "pending" ? "답변" : "보기"}</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pager {...list} onMove={list.move} />
          </>
        )}
      </div>

      {open && (
        <Answer
          inquiry={open}
          onClose={() => setOpen(null)}
          onDone={() => {
            setOpen(null);
            list.reload();
          }}
        />
      )}
    </>
  );
}

function Answer({ inquiry, onClose, onDone }) {
  const [text, setText] = useState(inquiry.answer || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const done = inquiry.status === "answered";

  const send = async () => {
    if (!text.trim()) {
      setError("답변 내용을 적어주세요.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const r = await api.answerInquiry(inquiry.id, text.trim());
      if (!r.sent) {
        setError(r.message);
        setBusy(false);
        return;
      }
      onDone();
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  };

  return (
    <Modal
      title={`${inquiry.school_name} 문의`}
      sub={`${inquiry.asker_name || "이름 없음"} · ${fmtDateTime(inquiry.created_at)}`}
      onClose={onClose}
      foot={
        <>
          <button className="btn" onClick={onClose}>
            닫기
          </button>
          <button className="btn go" onClick={send} disabled={busy}>
            {busy ? "보내는 중…" : done ? "다시 보내기" : "답변 보내기"}
          </button>
        </>
      }
    >
      <Note kind="bad">{error}</Note>
      {inquiry.delivery_status === "failed" && inquiry.delivery_error && (
        <Note kind="warn">지난번 발송이 실패했습니다: {inquiry.delivery_error}</Note>
      )}

      <div className="field">
        <label>받는 사람</label>
        <div className="masked">
          {inquiry.contact_email}
          {inquiry.contact_phone ? ` · ${inquiry.contact_phone}` : ""}
        </div>
        <p className="tiny muted" style={{ margin: "4px 0 0" }}>
          답변 메일은 가려지지 않은 실제 주소로 나갑니다. 화면에만 가려 보입니다.
        </p>
      </div>

      <div className="field">
        <label>문의 내용</label>
        <div
          style={{
            background: "var(--raised)",
            border: "1px solid var(--line)",
            borderRadius: 6,
            padding: "10px 12px",
            whiteSpace: "pre-wrap",
            fontSize: 13.5,
          }}
        >
          {inquiry.question}
        </div>
      </div>

      <div className="field">
        <label htmlFor="ans">답변</label>
        <textarea
          id="ans"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="문의하신 내용에 대해 안내드립니다."
        />
      </div>
    </Modal>
  );
}
