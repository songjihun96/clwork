import { Link } from "react-router-dom";

/** 학교 계정 안내. 로그인·회원가입 화면이 함께 쓴다.
 *
 * 학생 회원가입 화면으로 학교 관리자가 잘못 들어오는 일이 잦다. 가입 양식 맨 아래
 * 한 줄로 두었을 때는 거의 눈에 띄지 않아, 제목 바로 아래에 상자로 올렸다.
 * 학교 계정은 직접 가입할 수 없고 신청(/school-account-request)을 거친다.
 */
export default function SchoolAccountNotice({ style }) {
  return (
    <div className="notice notice-info school-acct-notice" style={style}>
      <span className="msi school-acct-icon" aria-hidden="true">school</span>
      <div className="school-acct-body">
        <b className="school-acct-title">학교 관리자이신가요?</b>
        <p>
          학교 정보를 관리하려면 <b>학교 계정 신청</b>이 필요합니다. 학교 계정은 직접 가입할 수 없고,
          신청하시면 담당자 확인 전화를 드린 뒤 계정을 만들어 보내드립니다.
        </p>
        <Link className="btn btn-ghost btn-sm" to="/school-account-request">
          학교 계정 신청하기
        </Link>
      </div>
    </div>
  );
}
