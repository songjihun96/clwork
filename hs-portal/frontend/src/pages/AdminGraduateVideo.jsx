import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import ChapterEditor from "../components/ChapterEditor";

/** 합격생 영상 구성 관리.
 *
 * 설명회 관리와 **같은 편집기**를 쓴다. 짜는 일이 똑같은데 화면을 두 벌로
 * 두면 한쪽만 고쳐 놓고 잊는다. 다른 것은 어디에 저장하는지와, 영상이
 * 공개여야 하는지 뿐이라 그 둘만 넘긴다.
 *
 * 공개 여부가 설명회와 정반대라는 점이 이 화면의 유일한 함정이다. 설명회
 * 영상은 공개라야 재생되고, 이건 **공개면 안 된다** — 공개로 두면 돈을 안 낸
 * 사람도 특강 목록에서 그냥 본다. 편집기가 챕터마다 그걸 짚어 준다.
 */
const FEED = {
  heading: "영상 구성",
  load: () => api.adminGraduateVideo(),
  save: (body) => api.saveGraduateVideo(body),
  uploadCover: (file) => api.uploadGraduateVideoCover(file),
  wantPublic: false,
};

export default function AdminGraduateVideo() {
  const [msg, setMsg] = useState(null);

  return (
    <div className="wrap" style={{ padding: "34px 0 60px", maxWidth: 860 }}>
      <span className="label">특강 관리</span>
      <h1 style={{ fontSize: 24, margin: "8px 0 6px" }}>합격생 영상 구성</h1>
      <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 0, lineHeight: 1.7 }}>
        결제가 확인된 계정에게만 보이는 영상입니다. 여기에 붙인 영상은
        <Link to="/admin/videos"> 영상 관리</Link>에서 <b>비공개</b>로 두세요 —
        공개로 두면 특강 목록에 그냥 뜹니다. 챕터마다 아래에서 확인해 드립니다.
      </p>

      {msg && (
        <div className={`notice notice-${msg.type}`} style={{ marginBottom: 12 }}>
          {msg.text}
        </div>
      )}

      <ChapterEditor setMsg={setMsg} feed={FEED} />
    </div>
  );
}
