import { useState } from "react";
import { api } from "../api";
import { Empty, Modal, Note, PLAN_LABEL, Pager, fmtDateTime, useList } from "../components/ui";

export default function Orders() {
  const [status, setStatus] = useState("pending");
  const [term, setTerm] = useState("");
  const [q, setQ] = useState("");
  const [confirming, setConfirming] = useState(null);

  const list = useList(
    ({ limit, offset }) => api.orders({ status, q, limit, offset }),
    [status, q]
  );

  return (
    <>
      <div className="page-head">
        <h1>학교 주문</h1>
        <p>입금 확인까지 하시면 됩니다. 플랜을 켜는 최종 승인은 관리자가 합니다.</p>
      </div>

      <div className="toolbar">
        {[
          ["pending", "입금 대기"],
          ["paid", "입금 확인"],
          ["approved", "승인 완료"],
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
        <input
          placeholder="학교명 또는 입금코드"
          value={term}
          onChange={(e) => setTerm(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && setQ(term)}
        />
        <button className="btn" onClick={() => setQ(term)}>찾기</button>
      </div>

      <div className="card">
        <Note kind="bad">{list.error}</Note>
        {list.loading ? (
          <Empty>불러오는 중…</Empty>
        ) : list.items.length === 0 ? (
          <Empty>해당하는 주문이 없습니다.</Empty>
        ) : (
          <>
            <table>
              <thead>
                <tr>
                  <th>학교</th>
                  <th>플랜</th>
                  <th className="num">금액</th>
                  <th>입금코드</th>
                  <th>상태</th>
                  <th>신청일</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {list.items.map((o) => (
                  <tr key={o.id}>
                    <td><strong>{o.school_name}</strong></td>
                    <td>
                      {PLAN_LABEL[o.plan] || o.plan}
                      <span className="muted tiny"> · {o.months}개월</span>
                    </td>
                    <td className="num">{o.amount.toLocaleString()}원</td>
                    <td className="masked">{o.deposit_code || "—"}</td>
                    <td>
                      <span
                        className={`badge ${
                          o.status === "pending"
                            ? "wait"
                            : o.status === "paid"
                            ? "hold"
                            : o.status === "approved"
                            ? "done"
                            : "flat"
                        }`}
                      >
                        {o.status_label}
                      </span>
                    </td>
                    <td className="tiny muted">{fmtDateTime(o.created_at)}</td>
                    <td>
                      {o.status === "pending" ? (
                        <button className="btn sm go" onClick={() => setConfirming(o)}>
                          입금 확인
                        </button>
                      ) : o.status === "paid" ? (
                        <span className="tiny muted">관리자 승인 대기</span>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pager {...list} onMove={list.move} />
          </>
        )}
      </div>

      {confirming && (
        <ConfirmDialog
          order={confirming}
          onClose={() => setConfirming(null)}
          onDone={() => {
            setConfirming(null);
            list.reload();
          }}
        />
      )}
    </>
  );
}

function ConfirmDialog({ order, onClose, onDone }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      await api.confirmPaid(order.id, note.trim());
      onDone();
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  };

  return (
    <Modal
      title="입금 확인"
      sub={`${order.school_name} · ${order.amount.toLocaleString()}원`}
      onClose={onClose}
      foot={
        <>
          <button className="btn" onClick={onClose}>그만두기</button>
          <button className="btn go" onClick={submit} disabled={busy}>
            {busy ? "처리 중…" : "입금 확인으로 바꾸기"}
          </button>
        </>
      }
    >
      <Note kind="bad">{error}</Note>
      <Note kind="info">
        통장에 실제로 들어온 것을 보고 눌러주세요. 이 단계에서는 플랜이 켜지지 않습니다.
        관리자가 최종 승인을 해야 학교에 적용됩니다.
      </Note>
      <div className="field">
        <label>입금코드</label>
        <div className="masked">{order.deposit_code || "—"}</div>
      </div>
      <div className="field">
        <label>메모 (선택 · 기록에 남습니다)</label>
        <input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="예: 국민은행 3/12 입금, 입금자 김OO"
          onKeyDown={(e) => e.key === "Enter" && submit()}
        />
      </div>
    </Modal>
  );
}
