import { useEffect, useState } from "react";
import SchoolNoticeSettings from "../components/SchoolNoticeSettings";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";

/** 학교 계정이 로그인하면 처음 보는 화면. 학생 홈과 같은 첫 화면 모양(lp-*)으로,
 *  숫자를 늘어놓기보다 지금 손이 필요한 것이 먼저 보이게 짰다.
 *  위: 인사·바로 가기·핵심 숫자 + 오른쪽에 '살펴보실 것'과 이용권 카드
 *  아래: 이용권 · 학생과 선생님 · 기록 현황, 공지 알림 설정 */
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

  // 지금 처리해야 할 것들.
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
      to: "/students",
    });
  }

  const n = (v) => Number(v || 0).toLocaleString();

  return (
    <div className="lp home-lp">
      <section className="lp-hero home-hero" aria-labelledby="school-home-title">
        <div className="wrap lp-hero-inner">
          <div>
            <span className="lp-pill">{user?.name || "학교"} 담당자님, 안녕하세요</span>
            <h1 id="school-home-title" className="lp-h1">
              학생들의 기록이<br /><em>얼마나 쌓이고 있는지</em> 봅니다
            </h1>
            <p className="lp-lead">
              일지가 꾸준히 쌓이고 있는지, 이용권이 잘 쓰이고 있는지 한눈에 확인하세요.
            </p>
            <div className="lp-cta-row">
              <Link className="btn btn-primary lp-btn" to="/school/seats">이용권 관리</Link>
              <Link className="btn lp-btn" to="/students">학생 기록 보기</Link>
              <Link className="btn lp-btn" to="/school/classes">학급·과목 관리</Link>
            </div>
            <div className="home-stats">
              <span>학생 <b>{n(d.students)}</b>명</span>
              <span>최근 30일 일지 <b>{n(d.journals_30d)}</b>건</span>
              <span>남은 좌석 <b>{n(d.seats_left)}</b>석</span>
              {todos.length > 0 && <span className="home-feedback">살펴보실 것 {todos.length}건</span>}
            </div>
          </div>

          <div className="lp-hero-visual">
            <div className="lp-card lp-record">
              <div className="lp-card-head">
                <span className={todos.length ? "lp-tag diary" : "lp-tag lesson"}>
                  {todos.length ? `살펴보실 것 ${todos.length}` : "모두 확인"}
                </span>
              </div>
              {todos.length === 0 ? (
                <>
                  <b className="lp-card-title">지금 처리하실 일이 없습니다</b>
                  <p className="lp-muted" style={{ margin: 0 }}>
                    이용권·재학생 인증·선생님 한마디 모두 밀린 것이 없습니다.
                  </p>
                </>
              ) : (
                <ul className="sh-todos">
                  {todos.map((t, i) => (
                    <li key={i}>
                      <b>{t.text}</b>
                      <span className="lp-muted">
                        {t.hint}
                        {t.to && <> <Link to={t.to}>바로 가기 →</Link></>}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <Link to="/school/seats" className="lp-card lp-resume home-card-link">
              <span className="lp-muted-inv">이용권</span>
              <b>
                {d.seat_active
                  ? `${String(d.expires_at).slice(0, 10)}까지 이용할 수 있습니다`
                  : "이용 중인 좌석이 없습니다"}
              </b>
              <div className="lp-chips">
                <span>구입 {n(d.seats)}석</span>
                <span>나눠줌 {n(d.seats_used)}석</span>
                <span>남음 {n(d.seats_left)}석</span>
                {d.seat_active && <span>1명당 {n(d.unit_price)}원</span>}
              </div>
            </Link>
          </div>
        </div>
      </section>

      <section className="lp-section lp-white" aria-labelledby="school-home-status">
        <div className="wrap">
          <span className="lp-eyebrow">우리 학교 현황</span>
          <h2 id="school-home-status" className="lp-h2">이용권 · 학생 · 기록</h2>

          <Group title="이용권">
            <Card label="구입 좌석" value={d.seats} unit="석" />
            <Card label="나눠준 좌석" value={d.seats_used} unit="석" />
            <Card label="남은 좌석" value={d.seats_left} unit="석" highlight />
            <Card label="코드에 남은 자리" value={d.code_left} unit="명" />
          </Group>

          <Group title="학생과 선생님">
            <Card label="학생" value={d.students} unit="명" />
            <Card label="재학생 인증" value={d.verified} unit="명" />
            <Card label="선생님 계정" value={d.teachers} unit="개" />
          </Group>
          <p className="lp-muted" style={{ marginTop: 8 }}>
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
            <p className="lp-muted" style={{ marginTop: 8 }}>
              아직 일지를 한 번도 쓰지 않은 학생이 <b>{n(d.never_wrote)}명</b> 있습니다.
              일지는 이용권과 상관없이 무료라, 미리 쌓아둘수록 3학년 때 쓸 재료가 많아집니다.
            </p>
          )}
        </div>
      </section>

      <section className="lp-section" aria-label="공지 알림 설정">
        <div className="wrap" style={{ maxWidth: 720 }}>
          <SchoolNoticeSettings />
        </div>
      </section>
    </div>
  );
}

function Group({ title, children }) {
  return (
    <div style={{ marginTop: 22 }}>
      <div className="label" style={{ marginBottom: 8 }}>{title}</div>
      <div className="sh-cards">{children}</div>
    </div>
  );
}

function Card({ label, value, unit, highlight }) {
  return (
    <div className="sh-card">
      <div className="lp-muted">{label}</div>
      <div className={`sh-card-value${highlight ? " on" : ""}`}>
        {Number(value || 0).toLocaleString()}
        <span>{unit}</span>
      </div>
    </div>
  );
}
