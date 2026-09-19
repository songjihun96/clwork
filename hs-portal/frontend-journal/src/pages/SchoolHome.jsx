import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";

/** 학교 계정이 로그인하면 처음 보는 화면.
 *  숫자를 늘어놓기보다 지금 손이 필요한 것이 먼저 보이게 짰다. */
export default function SchoolHome() {
  const { user } = useAuth();
  const [d, setD] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.schoolDashboard().then(setD).catch((e) => setError(e.message));
  }, []);

  if (error) {
    return (
      <div className="wrap page">
        <div className="notice notice-error">{error}</div>
      </div>
    );
  }
  if (!d) return <div className="wrap page"><p className="meta">불러오는 중…</p></div>;

  // 지금 처리해야 할 것들. 없으면 아예 띄우지 않는다.
  const todos = [];
  if (d.pending_order) {
    todos.push({
      text: `이용권 ${d.pending_order.seats}명 신청이 ${d.pending_order.status_label} 상태입니다.`,
      hint: `${Number(d.pending_order.amount || 0).toLocaleString()}원 입금 후 승인되면 쓸 수 있습니다.`,
      to: "/school/seats",
    });
  } else if (!d.seat_active) {
    todos.push({
      text: "아직 이용권을 신청하지 않았습니다.",
      hint: "자기소개서 기능을 쓰시려면 인원수를 정해 신청해주세요.",
      to: "/school/seats",
    });
  }
  if (d.seat_active && d.seats_left > 0 && d.code_left === 0) {
    todos.push({
      text: `이용권 ${d.seats_left}자리가 남아 있는데 아무에게도 가지 않았습니다.`,
      hint: "등록 코드를 만들어 학생들에게 나눠주세요.",
      to: "/school/seats",
    });
  }
  if (d.days_left != null && d.days_left <= 30 && d.days_left >= 0) {
    todos.push({
      text: `이용권 만료가 ${d.days_left}일 남았습니다.`,
      hint: "끊기기 전에 연장하시려면 미리 신청해주세요.",
      to: "/school/seats",
    });
  }
  if (d.unverified > 0) {
    todos.push({
      text: `재학생 인증을 받지 않은 학생이 ${d.unverified}명 있습니다.`,
      hint: "인증이 되어야 일지를 선생님께 제출할 수 있습니다. 우리동네 직업계고에서 승인합니다.",
    });
  }
  if (d.awaiting_feedback > 0) {
    todos.push({
      text: `선생님 한마디를 기다리는 일지가 ${d.awaiting_feedback}건 있습니다.`,
      hint: "담당 선생님께 확인을 부탁드리세요.",
    });
  }

  return (
    <div className="wrap page" style={{ maxWidth: 900 }}>
      <span className="label">우리 학교</span>
      <h1>{user?.name || "학교"} 현황</h1>
      <p style={{ color: "var(--steel)", lineHeight: 1.8, marginTop: 0 }}>
        학생들이 일지를 얼마나 쌓고 있는지, 이용권이 잘 쓰이고 있는지 볼 수 있습니다.
      </p>

      {todos.length > 0 && (
        <div className="panel" style={{ marginTop: 16 }}>
          <h3 style={{ marginTop: 0 }}>살펴보실 것</h3>
          {todos.map((t, i) => (
            <div key={i} style={{ padding: "9px 0",
                                  borderTop: i ? "1px solid var(--line)" : "none" }}>
              <div style={{ fontSize: 14.5, lineHeight: 1.6 }}>{t.text}</div>
              <div className="meta" style={{ marginTop: 2, lineHeight: 1.6 }}>
                {t.hint}
                {t.to && <> <Link to={t.to}>바로 가기</Link></>}
              </div>
            </div>
          ))}
        </div>
      )}

      <Group title="이용권">
        <Card label="구입 좌석" value={d.seats} unit="석" />
        <Card label="나눠준 좌석" value={d.seats_used} unit="석" />
        <Card label="남은 좌석" value={d.seats_left} unit="석" highlight />
        <Card label="코드에 남은 자리" value={d.code_left} unit="명" />
      </Group>
      <p className="meta" style={{ marginTop: 6, lineHeight: 1.7 }}>
        {d.seat_active
          ? `${String(d.expires_at).slice(0, 10)}까지 이용하실 수 있습니다. 1명당 ${Number(d.unit_price || 0).toLocaleString()}원입니다.`
          : "이용 중인 좌석이 없습니다."}
        {" "}<Link to="/school/seats">이용권 관리</Link>
      </p>

      <Group title="학생과 선생님">
        <Card label="학생" value={d.students} unit="명" />
        <Card label="재학생 인증" value={d.verified} unit="명" />
        <Card label="선생님 계정" value={d.teachers} unit="개" />
      </Group>
      <p className="meta" style={{ marginTop: 6, lineHeight: 1.7 }}>
        학생 명단 확인이나 선생님별 담당 과목 배정은{" "}
        <Link to="/school/classes">학급·과목 관리</Link>에서 합니다.
      </p>

      <Group title="기록">
        <Card label="쓴 일지" value={d.journals} unit="건" />
        <Card label="최근 30일" value={d.journals_30d} unit="건" />
        <Card label="선생님께 제출" value={d.submitted} unit="건" />
        <Card label="자기소개서" value={d.cover_letters} unit="건" />
      </Group>

      {d.never_wrote > 0 && (
        <p className="meta" style={{ marginTop: 6, lineHeight: 1.7 }}>
          아직 일지를 한 번도 쓰지 않은 학생이 <b>{d.never_wrote}명</b> 있습니다.
          일지는 이용권과 상관없이 무료라, 미리 쌓아둘수록 3학년 때 쓸 재료가 많아집니다.
        </p>
      )}
    </div>
  );
}

function Group({ title, children }) {
  return (
    <div style={{ marginTop: 22 }}>
      <div className="label" style={{ marginBottom: 8 }}>{title}</div>
      <div style={{ display: "grid", gap: 10,
                    gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
        {children}
      </div>
    </div>
  );
}

function Card({ label, value, unit, highlight }) {
  return (
    <div className="panel" style={{ padding: "14px 16px" }}>
      <div className="meta">{label}</div>
      <div style={{ fontSize: 24, fontWeight: 800, marginTop: 2,
                    color: highlight ? "var(--signal, #f26522)" : "inherit" }}>
        {Number(value || 0).toLocaleString()}
        <span style={{ fontSize: 13, fontWeight: 500, marginLeft: 2 }}>{unit}</span>
      </div>
    </div>
  );
}
