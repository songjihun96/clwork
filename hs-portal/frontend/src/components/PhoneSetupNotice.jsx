import { Link, useLocation } from "react-router-dom";
import { useAuth } from "../auth";

// 휴대폰 인증 도입 이전에 가입한 회원은 번호가 없을 수 있다.
// 번호가 없으면 아이디 찾기·비밀번호 재설정을 쓸 수 없으므로 등록을 안내한다.
export default function PhoneSetupNotice() {
  const { user } = useAuth();
  const { pathname } = useLocation();

  if (!user) return null;
  if (user.phone) return null;
  // 학교·관리자 계정은 관리자가 따로 관리하므로 학생에게만 띄운다.
  if (user.role !== "student") return null;
  // 등록하러 가는 화면에서는 띄우지 않는다.
  if (pathname === "/change-phone") return null;

  return (
    <div
      style={{
        background: "var(--surface)",
        borderBottom: "1px solid var(--line)",
        padding: "10px 0",
      }}
    >
      <div
        className="wrap"
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          flexWrap: "wrap",
          fontSize: 13.5,
          color: "var(--ink-soft)",
        }}
      >
        <span>
          휴대폰번호가 등록되어 있지 않습니다. 등록해두시면 아이디·비밀번호를 잊었을 때
          직접 찾을 수 있습니다.
        </span>
        <Link to="/change-phone" className="btn btn-sm">번호 등록하기</Link>
      </div>
    </div>
  );
}
