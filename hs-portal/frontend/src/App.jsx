import { lazy, Suspense, useEffect, useState } from "react";
import { Link, NavLink, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { ROLE_LABEL, api } from "./api";
import { ORG } from "./org";
import { useAuth } from "./auth";
import NoticeCenter from "./components/NoticeCenter";

// 첫 화면에 필요 없는 페이지는 방문할 때 내려받는다 (초기 번들 축소)
const Search = lazy(() => import("./pages/Search"));
const AdminPanel = lazy(() => import("./pages/AdminPanel"));
const SchoolAdmin = lazy(() => import("./pages/SchoolAdmin"));
const Quiz = lazy(() => import("./pages/Quiz"));
// 일지 작성 기능은 diary.ggm.kr 로 분리했다. 이 경로는 안내 후 넘겨주기만 한다.
const JournalMoved = lazy(() => import("./pages/JournalMoved"));
const JournalShare = lazy(() => import("./pages/JournalShare"));
const Events = lazy(() => import("./pages/Events"));
const Shorts = lazy(() => import("./pages/Shorts"));
const VideoPage = lazy(() => import("./pages/VideoPage"));
const AdminVideos = lazy(() => import("./pages/AdminVideos"));
const Briefing = lazy(() => import("./pages/Briefing"));
const Special = lazy(() => import("./pages/Special"));
const AdminBriefing = lazy(() => import("./pages/AdminBriefing"));
const AdminGraduateVideo = lazy(() => import("./pages/AdminGraduateVideo"));
const AdminCareerGuide = lazy(() => import("./pages/AdminCareerGuide"));
const Consulting = lazy(() => import("./pages/Consulting"));
const GraduateVideo = lazy(() => import("./pages/GraduateVideo"));
const CounselingPage = lazy(() => import("./pages/Counseling"));
const AdminApplications = lazy(() => import("./pages/AdminApplications"));
const Favorites = lazy(() => import("./pages/Favorites"));
const Account = lazy(() => import("./pages/Account"));
const ChangePassword = lazy(() => import("./pages/ChangePassword"));
const ChangePhone = lazy(() => import("./pages/ChangePhone"));
const DeleteAccount = lazy(() => import("./pages/DeleteAccount"));
const GuardianConsent = lazy(() => import("./pages/GuardianConsent"));
const FindAccount = lazy(() => import("./pages/FindAccount"));
const Privacy = lazy(() => import("./pages/Privacy"));
const Terms = lazy(() => import("./pages/Terms"));
const Refund = lazy(() => import("./pages/Refund"));
const Signup = lazy(() => import("./pages/Signup"));
const SchoolAdmission = lazy(() => import("./pages/SchoolAdmission"));
const SchoolAccountRequest = lazy(() => import("./pages/SchoolAccountRequest"));
const Interviews = lazy(() => import("./pages/Interviews"));
const InterviewPage = lazy(() => import("./pages/InterviewPage"));
const AdminInterviews = lazy(() => import("./pages/AdminInterviews"));
const Notices = lazy(() => import("./pages/Notices"));

import FloatingButton from "./components/FloatingButton";
import { Toaster } from "./toast";
import FamilySites from "./components/FamilySites";
import PhoneSetupNotice from "./components/PhoneSetupNotice";
import PasswordChangeNotice from "./components/PasswordChangeNotice";
import Login from "./pages/Login";
import SchoolPage from "./pages/SchoolPage";
import Home from "./pages/Home";

function Guard({ role, children }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="wrap" style={{ padding: 60 }}><div className="empty"><p>확인 중…</p></div></div>;
  if (!user) return <Navigate to="/login" replace />;
  if (role && user.role !== role) return <Navigate to="/" replace />;
  return children;
}

function Header() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const location = useLocation();

  // 페이지가 바뀌면 모바일 메뉴를 닫는다
  useEffect(() => { setOpen(false); }, [location.pathname]);

  // 영상(숏츠)은 아직 공개 전이라 관리자에게만 메뉴를 보여준다.
  // 서버도 같은 기준으로 막으므로, 주소를 직접 쳐도 학생에게는 안 열린다.
  const [videosPublic, setVideosPublic] = useState(false);

  useEffect(() => {
    api.videosVisibility()
      .then((r) => setVideosPublic(!!r.public))
      .catch(() => setVideosPublic(false));
  }, []);

  // 아직 준비가 안 된 메뉴는 관리자가 내려 둘 수 있다.
  // 못 받아오면 다 보이는 쪽으로 둔다 — 서버가 잠깐 대답을 못 한다고 해서
  // 메뉴가 통째로 사라지면 그게 더 큰 사고다.
  const [nav, setNav] = useState({});
  useEffect(() => {
    api.navVisibility().then(setNav).catch(() => setNav({}));
  }, []);
  // 관리자에게는 내려 둔 메뉴도 보여 준다. 안 그러면 끄고 나서 자기도
  // 들어갈 길이 없다.
  const navOn = (key) => nav[key] !== false || user?.role === "admin";
  // 숏츠는 공개 전이어도 관리자에게는 보여 준다 — 안 그러면 켜 보기 전까지
  // 관리자조차 들어갈 길이 없다. 서버도 같은 기준으로 막는다.
  const showShorts = videosPublic || user?.role === "admin";

  const close = () => setOpen(false);

  return (
    <header className="header">
      <div className="wrap header-inner">
        <Link to="/" className="brand" onClick={close}>
          <span className="brand-mark">ㅇㅈ</span>
          우리동네 직업계고
        </Link>

        {/* 남은 기간은 **왼쪽 끝**에 둔다. 오른쪽 메뉴 줄에 끼워 두면 메뉴가
            늘어날수록 밀려나고, 좁은 화면에서는 햄버거 안으로 들어가 버려
            "매일 눈에 걸린다"는 목적이 사라진다. */}
        <PlanDday user={user} onClick={close} />

        <div className="header-right">
        <button
          className="nav-toggle"
          aria-label="메뉴 열기"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
        >
          {open ? "✕" : "☰"}
        </button>

        <nav className={`nav ${open ? "open" : ""}`}>
          <NavLink to="/" end onClick={close}>홈</NavLink>
          {/* 아직 준비가 안 된 메뉴는 관리자가 내려 둘 수 있다(관리자 →
            * 공지 관리 → 상단 메뉴). 메뉴만 감출 뿐 주소는 살아 있다 —
            * 특강 안에 컨설팅·상담·영상 신청이 들어 있어서, 통째로 막으면
            * 그쪽으로 걸어 둔 링크까지 죽는다. */}
          {navOn("search") && <NavLink to="/search" onClick={close}>학교 검색</NavLink>}
          {navOn("events") && <NavLink to="/events" onClick={close}>학교 일정</NavLink>}
          {navOn("special") && (
            <NavLink to="/special" onClick={close}>온라인 직업계고 설명회</NavLink>
          )}
          {navOn("interviews") && <NavLink to="/interviews" onClick={close}>학교 인터뷰</NavLink>}
          {showShorts && <NavLink to="/shorts" onClick={close}>숏츠</NavLink>}
          {navOn("quiz") && <NavLink to="/quiz" onClick={close}>진로 테스트</NavLink>}
          {navOn("notices") && <NavLink to="/notices" onClick={close}>공지사항</NavLink>}

          {user?.role === "student" && <NavLink to="/favorites" onClick={close}>내 즐겨찾기</NavLink>}
          {user?.role === "school" && (
            <NavLink to="/my-school" onClick={close}>
              {user.school_level === "middle" ? "진학 지원" : "학교 관리"}
            </NavLink>
          )}
          {/* 관리자 화면은 하나로 둔다. 영상·설명회·신청 관리는 그 안에서 간다 —
            * 관리 메뉴가 상단에 넷씩 늘어서면 정작 학생이 쓸 메뉴가 밀린다. */}
          {user?.role === "admin" && <NavLink to="/admin" onClick={close}>관리자</NavLink>}

          {user ? (
            <>
              <NavLink to="/account" className="who" title="마이페이지" onClick={close}>
                {user.name} · {ROLE_LABEL[user.role]}
              </NavLink>
              <button onClick={() => { close(); logout(); navigate("/"); }}>로그아웃</button>
            </>
          ) : (
            <>
              <NavLink to="/login" onClick={close}>로그인</NavLink>
              <NavLink to="/signup" style={{ color: "var(--signal-deep)", fontWeight: 700 }} onClick={close}>회원가입</NavLink>
            </>
          )}
        </nav>
        <NoticeCenter />
        </div>
      </div>
      {open && <div className="nav-backdrop" onClick={close} />}
    </header>
  );
}

export default function App() {
  return (
    <div className="shell">
      <Header />

      <PhoneSetupNotice />
      <PasswordChangeNotice />

      <main id="main">
      <Suspense fallback={<div className="wrap" style={{ padding: "60px 0" }}>
        <div className="empty"><p>불러오는 중…</p></div>
      </div>}>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/search" element={<Search />} />
        <Route path="/quiz" element={<Quiz />} />
        <Route path="/events" element={<Events />} />
        <Route path="/shorts" element={<Shorts />} />
        <Route path="/shorts/:id" element={<Shorts />} />
        <Route path="/videos/:id" element={<VideoPage />} />
        <Route path="/journal" element={<JournalMoved />} />
        {/* 선생님 화면은 없앴다(선생님 기능은 기록해 몫). 예전 주소로 오면 "*" 가 홈으로 보낸다. */}
        <Route path="/journal-share/:token" element={<JournalShare />} />
        <Route path="/schools/:id" element={<SchoolPage />} />
        <Route path="/schools/:id/admission" element={<SchoolAdmission />} />
        <Route path="/login" element={<Login />} />
        <Route path="/signup" element={<Signup />} />
        <Route path="/school-account-request" element={<SchoolAccountRequest />} />
        <Route path="/change-phone" element={<ChangePhone />} />
        <Route path="/guardian-consent/:token" element={<GuardianConsent />} />
        <Route path="/find-account" element={<FindAccount />} />
        <Route path="/account" element={<Guard><Account /></Guard>} />
        <Route path="/account/password" element={<Guard><ChangePassword /></Guard>} />
        <Route path="/account/delete" element={<Guard><DeleteAccount /></Guard>} />
        <Route path="/favorites" element={<Guard role="student"><Favorites /></Guard>} />
        <Route path="/my-school" element={<Guard role="school"><SchoolAdmin /></Guard>} />
        <Route path="/admin" element={<Guard role="admin"><AdminPanel /></Guard>} />
        <Route path="/admin/videos" element={<Guard role="admin"><AdminVideos /></Guard>} />
        <Route path="/briefing" element={<Briefing />} />
        <Route path="/special" element={<Special />} />
        <Route path="/interviews" element={<Interviews />} />
        <Route path="/interviews/:id" element={<InterviewPage />} />
        <Route path="/notices" element={<Notices />} />
        <Route path="/notices/:id" element={<Notices />} />
        <Route path="/admin/interviews" element={<Guard role="admin"><AdminInterviews /></Guard>} />
        <Route path="/admin/briefing" element={<Guard role="admin"><AdminBriefing /></Guard>} />
        <Route path="/admin/graduate-video" element={<Guard role="admin"><AdminGraduateVideo /></Guard>} />
        <Route path="/admin/career-guide" element={<Guard role="admin"><AdminCareerGuide /></Guard>} />
        <Route path="/consulting" element={<Consulting />} />
        <Route path="/graduate-video" element={<GraduateVideo />} />
        <Route path="/counseling" element={<CounselingPage />} />
        <Route path="/admin/applications" element={<Guard role="admin"><AdminApplications /></Guard>} />
        <Route path="/privacy" element={<Privacy />} />
        <Route path="/terms" element={<Terms />} />
        <Route path="/refund" element={<Refund />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      </Suspense>
      </main>

      <FloatingButton />
      <Toaster />

      <footer style={{ marginTop: "auto", borderTop: "1px solid var(--line)", padding: "24px 0", background: "var(--surface)" }}>
        <div className="wrap" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
            <span className="label" style={{ fontWeight: 700, color: "var(--ink)" }}>{ORG.operator}</span>
            <div style={{ display: "flex", gap: 16 }}>
              <Link to="/terms" className="label" style={{ color: "var(--steel)", fontWeight: 600, textDecoration: "none" }}>
                이용약관
              </Link>
              <Link to="/refund" className="label" style={{ color: "var(--steel)", fontWeight: 600, textDecoration: "none" }}>
                환불 규정
              </Link>
              <Link to="/privacy" className="label" style={{ color: "var(--signal-deep)", fontWeight: 700, textDecoration: "none" }}>
                개인정보처리방침
              </Link>
            </div>
          </div>
          <VisitCounter />
          <div style={{ fontSize: 12, color: "var(--steel-light)", lineHeight: 1.7 }}>
            대표 {ORG.representative} · 사업자등록번호 {ORG.businessNumber}
            {ORG.mailOrderNumber && <> · 통신판매업 신고 {ORG.mailOrderNumber}</>}<br />
            {ORG.address}<br />
            {ORG.contactPhone} · {ORG.contactEmail}<br />
            호스팅 제공 {ORG.hostingProvider}
          </div>

          {/* 패밀리 사이트. 링크를 늘어놓으면 푸터가 길어져 드롭다운으로 둔다. */}
          <div style={{ paddingTop: 14, marginTop: 4, borderTop: "1px solid var(--line)" }}>
            <FamilySites current="udj" />
          </div>

          <div className="label" style={{ color: "var(--steel-light)" }}>
            학교 정보 출처 · 나이스 교육정보 개방 포털 · 지도 OpenStreetMap · 기사 특성화고신문 제공
          </div>
          <div className="label" style={{ color: "var(--steel-light)", marginTop: 2 }}>
            © {new Date().getFullYear()} {ORG.operator}. All rights reserved.
          </div>
        </div>
      </footer>
    </div>
  );
}

const VISITOR_KEY = "udj_visitor_id";

/** 브라우저마다 한 번 만든 임의 값. 누구인지는 알 수 없고, 하루에 같은
 *  사람을 두 번 세지 않는 데만 쓴다. 저장이 막힌 브라우저(사생활 보호
 *  모드)는 그 탭 동안만 쓰는 값을 만든다. */
function visitorId() {
  try {
    let id = localStorage.getItem(VISITOR_KEY);
    if (!id) {
      id = (window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`);
      localStorage.setItem(VISITOR_KEY, id);
    }
    return id;
  } catch {
    return `tmp-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }
}

/** 푸터의 방문자 수. 사이트를 처음 열 때 한 번 센다(서버가 하루 한 번으로 거른다).
 *  못 받아 오면 아무것도 안 띄운다 — 0 명이라고 보이는 것보다 낫다. */
function VisitCounter() {
  const [stats, setStats] = useState(null);
  useEffect(() => {
    api.visit(visitorId()).then(setStats)
      .catch(() => api.visitStats().then(setStats).catch(() => {}));
  }, []);
  if (!stats) return null;
  return (
    <div className="visit-counter" aria-label="방문자 수">
      <span>오늘 <b>{stats.today.toLocaleString()}</b>명</span>
      <span className="visit-sep" aria-hidden="true" />
      <span>누적 <b>{stats.total.toLocaleString()}</b>명</span>
    </div>
  );
}

/** 상단에 띄우는 플랜 남은 기간.
 *
 * 학교는 한 번 결제하고 1년을 쓴다. 그동안 만료일을 기억하고 있는 사람은
 * 없어서, 끊기고 나서야 "왜 안 되지"가 된다. 매일 들어오는 자리에 하루씩
 * 줄어드는 숫자를 두면 그 전에 눈에 걸린다.
 *
 * 남은 날에 따라 색이 바뀐다 — 30일 안쪽부터 눈에 띄게, 지났으면 빨갛게.
 * 무료 플랜이나 기간이 없는 경우에는 아무것도 안 띄운다.
 */
function PlanDday({ user, onClick }) {
  // 로그인 전에는 user 가 없다. 예전에는 로그인한 뒤에만 그리는 자리에
  // 있어서 이걸 안 봐도 됐는데, 왼쪽으로 옮기면서 그 울타리 밖으로 나왔다.
  const d = user?.plan_days_left;
  if (!user || user.role !== "school" || d === null || d === undefined) return null;

  const over = d < 0;
  const soon = d <= 30;
  const color = over ? "var(--color-danger)"
    : soon ? "var(--color-attention)" : "var(--steel)";
  const text = over ? `플랜만료 ${-d}일 지남`
    : d === 0 ? "플랜 오늘 만료" : `플랜만료 D-${d}`;

  return (
    <NavLink to="/my-school" onClick={onClick} className="plan-dday"
      style={{ color, borderColor: color }}
      title={user.plan_expires_at
        ? `${String(user.plan_expires_at).slice(0, 10)}까지`
        : ""}>
      {user.plan_paused ? "일시정지" : text}
    </NavLink>
  );
}
