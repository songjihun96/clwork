import { Link, useLocation } from "react-router-dom";
import { useAuth } from "../auth";

/** 임시 비밀번호로 발급된 계정에 바꾸라고 알린다.
 *
 * 학교 계정 신청을 승인하면 임시 비밀번호가 메일·전화로 나간다. 그 값을
 * 그대로 계속 쓰면, 메일함을 본 사람 누구나 학교 계정으로 들어올 수 있다.
 * 막지는 않고(급할 때 일을 먼저 하게) 매 화면 위에 띄운다.
 */
export default function PasswordChangeNotice() {
  const { user } = useAuth();
  const { pathname } = useLocation();

  if (!user || !user.must_change_password) return null;
  if (pathname === "/account/password") return null;

  return (
    <div style={{ background: "var(--color-warning-bg)", borderBottom: "1px solid var(--line)", padding: "10px 0" }}>
      <div className="wrap" style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        gap: 12, flexWrap: "wrap", fontSize: 13.5, color: "var(--ink-soft)",
      }}>
        <span>
          임시 비밀번호로 로그인했습니다. 다른 사람이 쓰지 못하도록 새 비밀번호로 바꿔 주세요.
        </span>
        <Link to="/account/password" className="btn btn-sm">비밀번호 바꾸기</Link>
      </div>
    </div>
  );
}
