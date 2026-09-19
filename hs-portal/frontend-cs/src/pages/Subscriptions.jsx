import { useState } from "react";
import { Empty, Masked, Note, Pager, fmtDate, useList } from "../components/ui";
import { api } from "../api";

/** 기록해 개인 구독 현황. 조회만 한다 — 연장·환불은 관리자 몫이다. */
export default function Subscriptions() {
  const [term, setTerm] = useState("");
  const [q, setQ] = useState("");
  const list = useList(({ limit, offset }) => api.subscriptions({ q, limit, offset }), [q]);

  return (
    <>
      <div className="page-head">
        <h1>개인 구독</h1>
        <p>기록해 자기소개서 구독 현황입니다. 조회만 할 수 있습니다.</p>
      </div>

      <div className="toolbar">
        <input
          placeholder="이름 또는 이메일"
          value={term}
          onChange={(e) => setTerm(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && setQ(term)}
        />
        <button className="btn primary" onClick={() => setQ(term)}>
          찾기
        </button>
      </div>

      <div className="card">
        <Note kind="bad">{list.error}</Note>
        {list.loading ? (
          <Empty>불러오는 중…</Empty>
        ) : list.items.length === 0 ? (
          <Empty>구독 중인 회원이 없습니다.</Empty>
        ) : (
          <>
            <table>
              <thead>
                <tr>
                  <th>이름</th>
                  <th>이메일</th>
                  <th>시작</th>
                  <th>만료</th>
                  <th>상태</th>
                </tr>
              </thead>
              <tbody>
                {list.items.map((s) => (
                  <tr key={s.user_id}>
                    <td><strong>{s.name}</strong></td>
                    <td><Masked value={s.email} /></td>
                    <td className="tiny muted">{fmtDate(s.started_at)}</td>
                    <td>{fmtDate(s.expires_at)}</td>
                    <td>
                      <span className={`badge ${s.active ? "done" : "flat"}`}>
                        {s.active ? "이용 중" : "만료"}
                      </span>
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
