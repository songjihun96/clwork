import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import "../../research-theme.css";

/** 담임 학급 학생의 팀 탈퇴 신청을 승인/반려하는 화면(지시서 §13 —
 * 탈퇴는 학생 마음대로 바로 되지 않고 담임 교사 승인을 거친다). */
export default function TeacherTeamRequests() {
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState(null);

  const load = () => {
    api.listTeamLeaveRequests().then((r) => setItems(r.items)).catch((e) => { setError(e.message); setItems([]); });
  };
  useEffect(load, []);

  const approve = async (id) => {
    setBusyId(id);
    try {
      await api.approveTeamLeave(id);
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusyId(null);
    }
  };

  const reject = async (id) => {
    const note = prompt("반려 사유(선택)") || "";
    setBusyId(id);
    try {
      await api.rejectTeamLeave(id, note);
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusyId(null);
    }
  };

  if (error) {
    return <div className="research-theme wrap page"><div className="notice notice-error">{error}</div></div>;
  }
  if (!items) {
    return <div className="research-theme wrap page"><p>불러오는 중…</p></div>;
  }

  return (
    <div className="research-theme wrap page">
      <Link to="/research/teacher" className="label">← 연구 현황</Link>
      <h1 style={{ marginTop: 8 }}>팀 탈퇴 신청</h1>
      <p style={{ fontSize: 13.5, color: "var(--color-text-secondary)" }}>
        담임 학급 학생이 팀 연구에서 나가겠다고 신청한 목록입니다.
      </p>

      {items.length === 0 ? (
        <div className="empty"><p>대기 중인 신청이 없습니다.</p></div>
      ) : (
        <div style={{ display: "grid", gap: 10, marginTop: 16 }}>
          {items.map((it) => (
            <div key={it.id} className="panel row" style={{ gap: 10, alignItems: "center" }}>
              <span>
                <b>{it.student_name}</b>님이 <b>{it.research_title}</b> 팀에서 나가겠다고 신청했어요
              </span>
              <div className="spacer" />
              <button className="btn btn-sm btn-primary" disabled={busyId === it.id}
                onClick={() => approve(it.id)}>승인</button>
              <button className="btn btn-sm btn-ghost" disabled={busyId === it.id}
                onClick={() => reject(it.id)}>반려</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
