import { useEffect } from "react";
import { Link } from "react-router-dom";
import { useSeo } from "../seo";

const DIARY_URL = "https://diary.ggm.kr";

// 일지·일기 기능은 별도 서비스(diary.ggm.kr)로 분리했다.
// 기존 즐겨찾기나 검색 결과로 들어오는 사람이 있으므로 주소를 지우지 않고
// 안내 후 넘겨준다.
export default function JournalMoved() {
  useSeo({
    title: "학교생활 일지 - 기록해로 이동",
    description: "학교생활 일지와 수업 일지는 기록해(diary.ggm.kr)에서 이용할 수 있습니다.",
    path: "/journal",
  });

  useEffect(() => {
    // 잠깐 안내를 보여준 뒤 넘긴다. 바로 튕기면 무슨 일인지 모른다.
    const t = setTimeout(() => {
      window.location.replace(DIARY_URL);
    }, 2500);
    return () => clearTimeout(t);
  }, []);

  return (
    <div className="wrap" style={{ maxWidth: 520, padding: "64px 0 80px" }}>
      <span className="label">서비스 이동 안내</span>
      <h1 style={{ fontSize: 25, margin: "8px 0 10px" }}>
        일지 기능이 <b>기록해</b>로 옮겨졌습니다
      </h1>
      <p style={{ color: "var(--steel)", lineHeight: 1.8, marginTop: 0 }}>
        학교생활 일기와 수업 일지는 이제 별도 서비스에서 이용합니다.
        우리동네 직업계고 계정을 그대로 쓸 수 있고, 그동안 쓴 기록도 모두 남아 있습니다.
      </p>

      <div className="notice" style={{ marginTop: 18, lineHeight: 1.8 }}>
        잠시 후 자동으로 이동합니다. 바로 가려면 아래 버튼을 눌러주세요.
      </div>

      <a className="btn btn-signal" href={DIARY_URL} style={{ marginTop: 18 }}>
        기록해로 이동하기
      </a>

      <p style={{ fontSize: 13, color: "var(--steel-light)", marginTop: 20, lineHeight: 1.8 }}>
        선생님 계정은 이곳 <Link to="/teacher">선생님 페이지</Link>에서
        학생들이 제출한 일지를 그대로 확인하실 수 있습니다.
      </p>
    </div>
  );
}
