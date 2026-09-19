import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import SchoolDetailView from "../components/SchoolDetailView";
import { useSeo } from "../seo";

/** 상세 페이지. 모달과 같은 내용을 쓴다. (홈·새 탭에서 진입) */
export default function SchoolPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [school, setSchool] = useState(null);

  useSeo({
    title: school ? school.name : "학교 정보",
    description: school
      ? `${school.name}${school.category ? " · " + school.category : ""}${school.region ? " · " + school.region : ""} — 학교 설명회와 참가 행사, 문의를 확인하세요.`
      : undefined,
    path: `/schools/${id}`,
  });

  const goBack = () => {
    // 이전 페이지가 있으면 뒤로, 없으면(새 탭 등) 검색으로
    if (window.history.length > 1) navigate(-1);
    else navigate("/search");
  };

  return (
    <div className="wrap" style={{ padding: "24px 0 60px" }}>
      <button
        onClick={goBack}
        className="btn btn-ghost btn-sm"
        style={{ marginBottom: 14 }}
      >
        ← 뒤로
      </button>
      <SchoolDetailView schoolId={Number(id)} onLoaded={setSchool} />
    </div>
  );
}
