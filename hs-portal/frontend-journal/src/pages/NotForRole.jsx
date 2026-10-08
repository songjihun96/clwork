import { useAuth } from "../auth";

const ROLE_LABEL = {
  admin: "포털 관리자",
  school: "학교",
  teacher: "선생님",
  student: "학생",
};

// 기록해는 학생(작성)과 선생님(확인)을 위한 서비스다.
// 학교·관리자 계정으로 들어오면 왜 쓸 수 없는지 분명히 알려준다.
export default function NotForRole() {
  const { user, logout } = useAuth();
  const label = ROLE_LABEL[user?.role] || "이";

  return (
    <div className="wrap page" style={{ maxWidth: 560 }}>
      <span className="label">이용 안내</span>
      <h1>{label} 계정은 이 서비스를 이용하지 않습니다</h1>

      <p style={{ color: "var(--steel)", lineHeight: 1.85, marginTop: 0 }}>
        기록해는 <b>학생이 학교생활일지·수업일지를 쓰고</b>, <b>선생님이 제출된 기록을 확인</b>하는
        서비스입니다. 학교 정보 관리와 포털 운영은 본 사이트에서 하실 수 있습니다.
      </p>

      <div className="panel" style={{ marginTop: 18 }}>
        <h3>어디로 가면 되나요</h3>
        <ul style={{ margin: 0, paddingLeft: 18, lineHeight: 2, fontSize: 14.5 }}>
          {user?.role === "school" && (
            <li>
              학교 정보 수정·문의 관리 —{" "}
              <a href="https://udjschool.ggm.kr/school-admin">학교 관리자 페이지</a>
            </li>
          )}
          {user?.role === "admin" && (
            <>
              <li>
                포털 운영·구독 승인 —{" "}
                <a href="https://udjschool.ggm.kr/admin">관리자 대시보드</a>
              </li>
              <li>
                제출된 일지 확인은 담당 선생님 계정으로 로그인해주세요.
              </li>
            </>
          )}
          <li>
            우리동네 직업계고 —{" "}
            <a href="https://udjschool.ggm.kr">udjschool.ggm.kr</a>
          </li>
        </ul>
      </div>

      <p style={{ fontSize: 13, color: "var(--steel-light)", marginTop: 18, lineHeight: 1.8 }}>
        학생 또는 선생님 계정이 따로 있으시면{" "}
        <a href="#logout" onClick={(e) => { e.preventDefault(); logout(); }}>
          로그아웃 후 다시 로그인
        </a>
        해주세요.
      </p>
    </div>
  );
}
