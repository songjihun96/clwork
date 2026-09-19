import { useState } from "react";
import { api } from "../api";
import { Empty, Masked, Note, Pager, fmtDateTime, useList } from "../components/ui";

export default function Verifications() {
  const [status, setStatus] = useState("pending");
  const [busy, setBusy] = useState(0);
  const [error, setError] = useState("");

  const list = useList(
    ({ limit, offset }) => api.verifications({ status, limit, offset }),
    [status]
  );

  const decide = async (id, decision) => {
    setBusy(id);
    setError("");
    try {
      await api.decideVerification(id, decision);
      list.reload();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(0);
    }
  };

  return (
    <>
      <div className="page-head">
        <h1>재학생 인증</h1>
        <p>승인하면 그 학생이 해당 학교 재학생으로 등록됩니다.</p>
      </div>

      <div className="toolbar">
        {[
          ["pending", "대기"],
          ["approved", "승인"],
          ["rejected", "거절"],
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
        <Note kind="bad">{error || list.error}</Note>
        {list.loading ? (
          <Empty>불러오는 중…</Empty>
        ) : list.items.length === 0 ? (
          <Empty>
            {status === "pending" ? "대기 중인 인증 신청이 없습니다." : "해당하는 신청이 없습니다."}
          </Empty>
        ) : (
          <>
            <table>
              <thead>
                <tr>
                  <th>학생</th>
                  <th>학교</th>
                  <th>학급</th>
                  <th>본인이 적은 내용</th>
                  <th>신청일</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {list.items.map((v) => (
                  <tr key={v.id}>
                    <td>
                      <strong>{v.student}</strong>
                      <div>
                        <Masked value={v.student_email} />
                      </div>
                    </td>
                    <td>{v.school_name}</td>
                    <td>{v.class_name || <span className="muted tiny">—</span>}</td>
                    <td style={{ maxWidth: 240 }}>{v.note || <span className="muted tiny">—</span>}</td>
                    <td className="tiny muted">{fmtDateTime(v.created_at)}</td>
                    <td>
                      {v.status === "pending" ? (
                        <div className="btn-row">
                          <button
                            className="btn sm go"
                            disabled={busy === v.id}
                            onClick={() => decide(v.id, "approved")}
                          >
                            승인
                          </button>
                          <button
                            className="btn sm danger"
                            disabled={busy === v.id}
                            onClick={() => decide(v.id, "rejected")}
                          >
                            거절
                          </button>
                        </div>
                      ) : (
                        <span className={`badge ${v.status === "approved" ? "done" : "flat"}`}>
                          {v.status === "approved" ? "승인" : "거절"}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pager {...list} onMove={list.move} />
          </>
        )}
      </div>
    </>
  );
}
