import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { api } from "./api";
import { useAuth } from "./auth";
import { CallCenterProvider, useCallCenter } from "./callcenter";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Users from "./pages/Users";
import Schools from "./pages/Schools";
import Inquiries from "./pages/Inquiries";
import Verifications from "./pages/Verifications";
import Orders from "./pages/Orders";
import Subscriptions from "./pages/Subscriptions";
import Manage from "./pages/Manage";
import Calls from "./pages/Calls";
import Customers from "./pages/Customers";
import Consultations from "./pages/Consultations";
import Statistics from "./pages/Statistics";
import PhoneSettings from "./pages/PhoneSettings";

/** 어떤 경로로 들어왔는지 늘 보여준다.
 *  상담원이 지금 사무실인지 등록 기기인지 알고 있어야, 밖에서 열었을 때
 *  스스로 조심하게 된다. */
function AccessTag({ me }) {
  if (!me) return null;
  const title = me.ip ? `접속 IP ${me.ip}` : undefined;
  if (me.is_admin) {
    return (
      <span className="access admin" title={title}>
        <span className="dot" />
        관리자
      </span>
    );
  }
  if (me.how === "device") {
    return (
      <span className="access device" title={title}>
        <span className="dot" />
        등록 기기
      </span>
    );
  }
  return (
    <span className="access" title={title}>
      <span className="dot" />
      사무실 접속
    </span>
  );
}

/** 상단 바의 전화 상태.
 *  어느 화면에 있든 전화가 왔다는 것은 알아야 한다. 그래서 이 배지는
 *  /calls 가 아니라 상단 바에 붙어 있다. */
function PhoneTag() {
  const cc = useCallCenter();
  if (!cc) return null;
  if (cc.ringing) {
    return (
      <NavLink to="/calls" className="phonetag ring">
        <span className="dot" />
        전화 수신 중 · {cc.ringing.phone_number}
      </NavLink>
    );
  }
  if (cc.inCall) {
    return (
      <NavLink to="/calls" className="phonetag busy">
        <span className="dot" />
        통화 중
      </NavLink>
    );
  }
  const status = cc.me?.availability_status || "OFFLINE";
  const label = { AVAILABLE: "상담 가능", AWAY: "자리 비움", OFFLINE: "오프라인", BUSY: "통화 중" };
  return (
    <NavLink to="/calls" className={`phonetag ${status === "AVAILABLE" ? "ready" : ""}`}>
      <span className="dot" />
      {label[status] || status}
    </NavLink>
  );
}

function Shell() {
  const { user, logout } = useAuth();
  const [counts, setCounts] = useState(null);
  const [phone, setPhone] = useState(null);
  const location = useLocation();

  // 대기 건수는 화면을 옮길 때마다 새로 읽는다. 처리하면 바로 줄어야 한다.
  useEffect(() => {
    if (!user) return;
    api.summary().then(setCounts).catch(() => {});
    api.phoneSummary().then(setPhone).catch(() => {});
  }, [user, location.pathname]);

  const item = (to, label, n) => (
    <NavLink to={to} className={({ isActive }) => (isActive ? "on" : "")} end={to === "/"}>
      <span>{label}</span>
      {n > 0 && <span className="count">{n}</span>}
    </NavLink>
  );

  return (
    <>
      <div className="statusbar">
        <span className="brand">
          <span>ㅇㅈ</span> 상담 지원
        </span>
        <AccessTag me={user} />
        <PhoneTag />
        <span className="spacer" />
        <span className="who">{user.name}</span>
        <button onClick={logout}>로그아웃</button>
      </div>

      <div className="shell">
        <aside className="rail">
          <nav>
            {item("/", "할 일")}
            <div className="group">전화</div>
            {item("/calls", "전화 상담", (phone?.calls_ringing || 0) + (phone?.calls_in_progress || 0))}
            {item("/consultations", "상담", phone?.consultations_open)}
            {item("/customers", "고객")}
            <div className="group">상담</div>
            {item("/inquiries", "문의", counts?.inquiries_pending)}
            {item("/verifications", "재학생 인증", counts?.verifications_pending)}
            <div className="group">자료</div>
            {item("/users", "회원")}
            {item("/schools", "학교")}
            <div className="group">결제</div>
            {item("/orders", "학교 주문", counts?.orders_pending)}
            {item("/subscriptions", "개인 구독")}
            <div className="group">기록</div>
            {item("/statistics", "통계")}
            {user.is_admin && (
              <>
                <div className="group">관리자</div>
                {item("/settings", "전화 설정")}
                {item("/manage", "기기·상담원")}
              </>
            )}
          </nav>
        </aside>

        <main className="main">
          <Routes>
            <Route path="/" element={<Dashboard counts={counts} />} />
            <Route path="/calls" element={<Calls />} />
            {/* 상담원 화면은 /calls 하나다. 같은 화면을 두 벌 만들면
                한쪽만 고쳐지는 날이 온다. */}
            <Route path="/counselor" element={<Navigate to="/calls" replace />} />
            <Route path="/customers" element={<Customers />} />
            <Route path="/consultations" element={<Consultations />} />
            <Route path="/statistics" element={<Statistics />} />
            <Route path="/inquiries" element={<Inquiries />} />
            <Route path="/verifications" element={<Verifications />} />
            <Route path="/users" element={<Users />} />
            <Route path="/schools" element={<Schools />} />
            <Route path="/orders" element={<Orders />} />
            <Route path="/subscriptions" element={<Subscriptions />} />
            <Route
              path="/settings"
              element={user.is_admin ? <PhoneSettings /> : <Navigate to="/" replace />}
            />
            <Route
              path="/manage"
              element={user.is_admin ? <Manage /> : <Navigate to="/" replace />}
            />
            <Route path="/admin" element={<Navigate to="/manage" replace />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </>
  );
}

export default function App() {
  const { user, loading } = useAuth();

  if (loading) {
    return <div className="empty" style={{ paddingTop: 80 }}>불러오는 중…</div>;
  }
  if (!user) return <Login />;

  // 로그인한 뒤에만 실시간 통로를 연다. 로그인 화면에서 WebSocket 을 열면
  // 인증 없이 두드리는 꼴이 되고, 서버는 그걸 계속 거절한다.
  return (
    <CallCenterProvider>
      <Shell />
    </CallCenterProvider>
  );
}
