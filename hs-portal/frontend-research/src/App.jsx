import { lazy, Suspense } from "react";
import { Link, Navigate, NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { useAuth } from "./auth";
import "./styles.css";
import "./research-theme.css";

/** 연구·논문 서비스.
 *
 * 기록해에서 떼어 나온 별도 사이트다. 계정도 DB 도 완전히 따로다 —
 * 기록해에 로그인돼 있어도 여기서는 다시 가입해야 한다.
 *
 * 화면은 기록해에 있던 연구 화면을 그대로 가져왔다. 옮기면서 새로 그리면
 * 잘 돌던 것이 상하고, 무엇이 바뀐 탓인지 가려내기 어려워진다.
 */

const Login = lazy(() => import("./pages/Login"));
const Signup = lazy(() => import("./pages/Signup"));
const Account = lazy(() => import("./pages/Account"));
const NotForRole = lazy(() => import("./pages/NotForRole"));

const ResearchList = lazy(() => import("./pages/research/ResearchList"));
const ResearchNew = lazy(() => import("./pages/research/ResearchNew"));
const ResearchWorkspace = lazy(() => import("./pages/research/ResearchWorkspace"));
const TeamBoard = lazy(() => import("./pages/research/TeamBoard"));
const ExternalQuestions = lazy(() => import("./pages/research/ExternalQuestions"));
const SharedResearchPortfolio = lazy(() => import("./pages/research/SharedResearchPortfolio"));
const TeacherResearchList = lazy(() => import("./pages/research/TeacherResearchList"));
const TeacherResearchDetail = lazy(() => import("./pages/research/TeacherResearchDetail"));
const TeacherTeamRequests = lazy(() => import("./pages/research/TeacherTeamRequests"));
const TeacherExternalQuestions = lazy(() => import("./pages/research/TeacherExternalQuestions"));

/** 로그인 뒤 어디로 보낼지. 역할마다 첫 화면이 다르다. */
export function homeFor(user) {
  if (!user) return "/login";
  if (user.role === "teacher" || user.role === "admin") return "/research/teacher";
  return "/";
}

function Guard({ children, role }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="wrap" style={{ padding: 40 }}>불러오는 중…</div>;
  if (!user) return <Navigate to="/login" replace />;
  if (role) {
    const allowed = Array.isArray(role) ? role : [role];
    if (!allowed.includes(user.role)) return <Navigate to="/unsupported" replace />;
  }
  return children;
}

function Header() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const isTeacher = user && (user.role === "teacher" || user.role === "admin");

  return (
    <header className="header">
      <div className="wrap header-inner">
        <Link to="/" className="brand">연구·논문</Link>
        <nav className="nav">
          {user && !isTeacher && <NavLink to="/">내 연구</NavLink>}
          {isTeacher && <NavLink to="/research/teacher">학생 연구</NavLink>}
          {isTeacher && <NavLink to="/research/teacher-external-questions">받은 질문</NavLink>}
          {isTeacher && <NavLink to="/research/teacher-team-requests">팀 요청</NavLink>}
          {user ? (
            <>
              <NavLink to="/account" className="who">{user.name || user.email}</NavLink>
              <button className="btn btn-ghost btn-sm"
                onClick={() => { logout(); navigate("/login"); }}>로그아웃</button>
            </>
          ) : (
            <>
              <NavLink to="/login">로그인</NavLink>
              <NavLink to="/signup">가입하기</NavLink>
            </>
          )}
        </nav>
      </div>
    </header>
  );
}

export default function App() {
  return (
    <>
      <Header />
        <main>
          <Suspense fallback={<div className="wrap" style={{ padding: 40 }}>불러오는 중…</div>}>
            <Routes>
              <Route path="/login" element={<Login />} />
              <Route path="/signup" element={<Signup />} />
              {/* 공유 링크는 로그인 없이 열려야 한다. 지도 교사나 부모에게
                  보여줄 때 가입부터 시키면 아무도 안 본다. */}
              <Route path="/research-portfolio-share/:token"
                element={<SharedResearchPortfolio />} />
              <Route path="/unsupported" element={<Guard><NotForRole /></Guard>} />

              <Route path="/" element={<Guard role="student"><ResearchList /></Guard>} />
              <Route path="/account" element={<Guard><Account /></Guard>} />
              <Route path="/research" element={<Navigate to="/" replace />} />
              <Route path="/research/new" element={<Guard role="student"><ResearchNew /></Guard>} />
              <Route path="/research/teacher"
                element={<Guard role={["teacher", "admin"]}><TeacherResearchList /></Guard>} />
              <Route path="/research/teacher/:studentId"
                element={<Guard role={["teacher", "admin"]}><TeacherResearchDetail /></Guard>} />
              <Route path="/research/teacher-team-requests"
                element={<Guard role={["teacher", "admin"]}><TeacherTeamRequests /></Guard>} />
              <Route path="/research/teacher-external-questions"
                element={<Guard role={["teacher", "admin"]}><TeacherExternalQuestions /></Guard>} />
              <Route path="/research/:id"
                element={<Guard role="student"><ResearchWorkspace /></Guard>} />
              <Route path="/research/:id/team"
                element={<Guard role="student"><TeamBoard /></Guard>} />
              <Route path="/research/:id/questions"
                element={<Guard role="student"><ExternalQuestions /></Guard>} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
      </main>
    </>
  );
}
