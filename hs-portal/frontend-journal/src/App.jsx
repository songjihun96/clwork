import { lazy, Suspense } from "react";
import { Link, NavLink, Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import FamilySites from "./components/FamilySites";

const Login = lazy(() => import("./pages/Login"));
const Home = lazy(() => import("./pages/Home"));
const Journals = lazy(() => import("./pages/Journals"));
const JournalEdit = lazy(() => import("./pages/JournalEdit"));
const CoverLetters = lazy(() => import("./pages/CoverLetters"));
const Account = lazy(() => import("./pages/Account"));
const Signup = lazy(() => import("./pages/Signup"));
const Admin = lazy(() => import("./pages/Admin"));
const CoverLetterEdit = lazy(() => import("./pages/CoverLetterEdit"));
const NotForRole = lazy(() => import("./pages/NotForRole"));
const SharedJournal = lazy(() => import("./pages/SharedJournal"));
const Refund = lazy(() => import("./pages/Refund"));
const SchoolSeats = lazy(() => import("./pages/SchoolSeats"));
const SchoolHome = lazy(() => import("./pages/SchoolHome"));
const SchoolClasses = lazy(() => import("./pages/SchoolClasses"));
const StudentRecords = lazy(() => import("./pages/StudentRecords"));
const TeacherObservations = lazy(() => import("./pages/TeacherObservations"));
const Portfolio = lazy(() => import("./pages/Portfolio"));
const PortfolioEditor = lazy(() => import("./pages/PortfolioEditor"));
const SharedPortfolio = lazy(() => import("./pages/SharedPortfolio"));

// 역할별로 쓸 수 있는 화면이 다르다. 서버의 권한 규칙과 정확히 맞춘다.
//   학생   : 일지 작성 · 포트폴리오(자기소개서는 예전 기능으로 남겨 둠)
//   선생님 : 제출된 학생 기록 확인
//   학교·관리자 : 이 서비스 대상이 아니다(본 사이트에서 이용)
// 제출된 학생 기록을 볼 수 있는 역할
export const canViewStudentRecords = (user) =>
  !!user && ["teacher", "school", "admin"].includes(user.role);

export function homeFor(user) {
  if (!user) return "/login";
  if (user.role === "student") return "/";
  if (user.role === "admin") return "/admin";
  // 학교 계정은 학생 기록 대신 우리 학교 현황을 먼저 본다.
  if (user.role === "school") return "/school";
  if (canViewStudentRecords(user)) return "/students";
  return "/unsupported";
}

// 로그인이 필요한 화면을 감싼다. role 을 주면 그 역할만 통과시킨다.
function Guard({ children, role }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="wrap page"><p>불러오는 중…</p></div>;
  if (!user) return <Navigate to="/login" replace />;
  // 권한이 없으면 오류 대신 그 역할이 쓸 수 있는 화면으로 보낸다.
  const allowed = Array.isArray(role) ? role : role ? [role] : null;
  if (allowed && !allowed.includes(user.role)) return <Navigate to={homeFor(user)} replace />;
  return children;
}

export default function App() {
  const { user, logout } = useAuth();
  const isStudent = user && user.role === "student";
  const isTeacher = canViewStudentRecords(user);

  return (
    <>
      <header className="header">
        <div className="wrap header-inner">
          <Link to="/" className="brand">
            기록해 <em>ㅇㅈ</em>
          </Link>
          <nav className="nav">
            {isStudent && (
              <>
                <NavLink to="/" end className={({ isActive }) => (isActive ? "on" : "")}>
                  홈
                </NavLink>
                <NavLink to="/journals" className={({ isActive }) => (isActive ? "on" : "")}>
                  내 기록
                </NavLink>
                {/* 이용권을 자소서·연구로 나눈 뒤(2d32f6b)로는 자소서도 학교가
                    돈을 내고 사는 상품이라, 메뉴에 없으면 산 학교조차 어디서
                    쓰는지 못 찾는다. 포트폴리오·기록 화면 안내 링크만으론
                    부족해 다시 메뉴에 올린다. */}
                <NavLink to="/cover-letters" className={({ isActive }) => (isActive ? "on" : "")}>
                  자기소개서
                </NavLink>
                <NavLink to="/account" className={({ isActive }) => (isActive ? "on" : "")}>
                  내 정보
                </NavLink>
              </>
            )}
            {user?.role === "school" && (
              <NavLink to="/school" end className={({ isActive }) => (isActive ? "on" : "")}>
                우리 학교
              </NavLink>
            )}
            {(user?.role === "school" || user?.role === "teacher") && (
              <NavLink to="/school/seats" className={({ isActive }) => (isActive ? "on" : "")}>
                이용권
              </NavLink>
            )}
            {user?.role === "school" && (
              <NavLink to="/school/classes" className={({ isActive }) => (isActive ? "on" : "")}>
                학급·과목
              </NavLink>
            )}
            {/* 관리자에게는 이 메뉴를 띄우지 않는다. 학생 기록은 민감한
                개인정보라 담당 교사와 학교가 보는 것이고, 관리자는 업무상
                필요할 때만 들어가야 한다. 주소로는 여전히 들어갈 수 있고
                그때는 열람 기록이 남는다.
                예전에는 '학생 기록'과 '학생별 기록 · AI 생기부'가 메뉴 두 개로
                따로 있었는데, 결국 같은 학생 상세 화면으로 이어져 헷갈린다는
                의견이 있어 하나로 합쳤다. */}
            {isTeacher && user?.role !== "admin" && (
              <NavLink to="/students" className={({ isActive }) => (isActive ? "on" : "")}>
                학생 기록
              </NavLink>
            )}
            {/* 관찰 기록은 교사 개인 기록이라 학교·관리자 계정에는 메뉴 자체를
                안 보여준다(학교 계정은 애초에 쓸 수 없다 — 서버가 막는다). */}
            {user?.role === "teacher" && (
              <NavLink to="/observations" className={({ isActive }) => (isActive ? "on" : "")}>
                관찰 기록
              </NavLink>
            )}
            {user?.role === "admin" && (
              <NavLink to="/admin" className={({ isActive }) => (isActive ? "on" : "")}>
                관리
              </NavLink>
            )}
            {user && (
              <a href="#logout" onClick={(e) => { e.preventDefault(); logout(); }}>
                로그아웃
              </a>
            )}
            {!user && <NavLink to="/login">로그인</NavLink>}
          </nav>
        </div>
      </header>

      <main>
        <Suspense fallback={<div className="wrap page"><p>불러오는 중…</p></div>}>
          <Routes>
            {/* 공유 링크. 로그인 없이 열려야 하므로 Guard 를 두지 않는다. */}
            <Route path="/journal-share/:token" element={<SharedJournal />} />
            <Route path="/portfolio-share/:token" element={<SharedPortfolio />} />
            {/* 결제 전에 읽을 수 있어야 하므로 로그인을 요구하지 않는다. */}
            <Route path="/refund" element={<Refund />} />
            <Route path="/login" element={<Login />} />
            <Route path="/signup" element={<Signup />} />
            <Route path="/admin" element={<Guard role="admin"><Admin /></Guard>} />
            <Route path="/" element={<Guard role="student"><Home /></Guard>} />
            <Route path="/journals" element={<Guard role="student"><Journals /></Guard>} />
            <Route path="/journals/new" element={<Guard role="student"><JournalEdit /></Guard>} />
            <Route path="/journals/:id" element={<Guard role="student"><JournalEdit /></Guard>} />
            {/* 재료는 자기소개서 편집 화면으로 합쳤다. 옛 링크는 목록으로 보낸다. */}
            <Route path="/materials" element={<Navigate to="/cover-letters" replace />} />
            <Route path="/account" element={<Guard role="student"><Account /></Guard>} />
            <Route path="/cover-letters" element={<Guard role="student"><CoverLetters /></Guard>} />
            <Route path="/cover-letters/new" element={<Guard role="student"><CoverLetterEdit /></Guard>} />
            <Route path="/cover-letters/:id" element={<Guard role="student"><CoverLetterEdit /></Guard>} />
            <Route path="/portfolio" element={<Guard role="student"><Portfolio /></Guard>} />
            <Route path="/portfolio/:id" element={<Guard role="student"><PortfolioEditor /></Guard>} />
            {/* 개인 결제는 없어졌다. 예전 주소는 자기소개서 화면으로 보낸다.
                거기서 학교에서 받은 등록 코드를 넣는다. */}
            <Route path="/subscribe" element={<Navigate to="/cover-letters" replace />} />
            {/* 이용권은 학교가 산다. 학생에게는 신청 내역이 없다.
                예전에 개인 결제한 계정의 환불은 '내 정보'에서 처리한다.
                옛 주소로 들어오면 그쪽으로 보낸다. */}
            <Route path="/orders" element={<Navigate to="/cover-letters" replace />} />
            <Route path="/school"
              element={<Guard role={["school", "admin"]}><SchoolHome /></Guard>} />
            {/* 이용권은 학교가 산다. 학교 계정만 들어갈 수 있다. */}
            <Route path="/school/seats"
              element={<Guard role={["school", "teacher", "admin"]}><SchoolSeats /></Guard>} />
            {/* 학생 명단·담당 과목 배정은 결제·이용권과 무관해서 따로 뺐다.
                예전엔 '이용권' 메뉴 안 탭으로 섞여 있어 찾기 어려웠다. */}
            <Route path="/school/classes"
              element={<Guard role={["school", "admin"]}><SchoolClasses /></Guard>} />
            <Route path="/payment/result" element={<Navigate to="/cover-letters" replace />} />
            <Route path="/unsupported" element={<Guard><NotForRole /></Guard>} />
            {/* 예전 주소('학생 기록'과 'AI 생기부'가 메뉴 두 개로 나뉘어 있던
                시절의 링크) 호환용. 지금은 /students 하나로 합쳤다. */}
            <Route path="/teacher" element={<Navigate to="/students" replace />} />
            <Route path="/students" element={<Guard role={["teacher", "school", "admin"]}><StudentRecords /></Guard>} />
            <Route path="/students/:id" element={<Guard role={["teacher", "school", "admin"]}><StudentRecords /></Guard>} />
            {/* 관찰 기록은 교사 개인 기록이다 — 학교·관리자 계정은 서버가
                애초에 막으므로(원문 접근 불가) 여기서도 교사만 들여보낸다. */}
            <Route path="/observations" element={<Guard role="teacher"><TeacherObservations /></Guard>} />
            <Route path="/observations/:studentId" element={<Guard role="teacher"><TeacherObservations /></Guard>} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </main>

      <footer className="footer">
        <div className="wrap">
          기록해 · 우리동네 직업계고 부가서비스<br />
          운영 특성화고신문 · 대표 강승구 · 사업자등록번호 214-13-75982<br />
          문의 news@sinmoon.net · 070-7867-7970 ·{" "}
          <a href="https://udjschool.ggm.kr/privacy">개인정보처리방침</a> ·{" "}
          <a href="https://udjschool.ggm.kr/terms">이용약관</a> ·{" "}
          <Link to="/refund">환불 규정</Link>

          <div style={{ marginTop: 14, paddingTop: 14, borderTop: "1px solid var(--line)" }}>
            <FamilySites current="diary" />
          </div>
        </div>
      </footer>
    </>
  );
}
