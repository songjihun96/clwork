import { useEffect } from "react";
import { useParams } from "react-router-dom";

const DIARY = "https://diary.ggm.kr";

// 일지 공유 링크는 기록해로 옮겨졌다.
// 예전에 학생이 보낸 링크가 아직 돌아다닐 수 있으므로, 주소를 지우지 않고
// 같은 토큰으로 기록해에 넘겨준다.
export default function JournalShare() {
  const { token } = useParams();
  const target = `${DIARY}/journal-share/${token || ""}`;

  useEffect(() => {
    const t = setTimeout(() => window.location.replace(target), 2000);
    return () => clearTimeout(t);
  }, [target]);

  return (
    <div className="wrap" style={{ maxWidth: 520, padding: "64px 0 80px" }}>
      <span className="label">서비스 이동 안내</span>
      <h1 style={{ fontSize: 24, margin: "8px 0 10px" }}>
        일지 보기가 <b>기록해</b>로 옮겨졌습니다
      </h1>
      <p style={{ color: "var(--steel)", lineHeight: 1.8, marginTop: 0 }}>
        잠시 후 자동으로 이동합니다. 바로 가려면 아래 버튼을 눌러주세요.
      </p>
      <a className="btn btn-signal" href={target} style={{ marginTop: 16 }}>
        기록해에서 열기
      </a>
    </div>
  );
}
