import { useSeo } from "../seo";
import ApplyForm from "../components/ApplyForm";
import ConsultantProfile from "../components/ConsultantProfile";

/** 직업계고 3년Plan 컨설팅 안내 + 신청. */
export default function Consulting() {
  useSeo({
    title: "직업계고 3년Plan 컨설팅",
    description: "졸업 후 취업할 회사의 선택지가 넓어지도록, 3년간의 학교생활을 함께 설계합니다.",
    path: "/consulting",
  });

  return (
    <div className="wrap" style={{ padding: "34px 0 60px", maxWidth: 760 }}>
      <span className="label">컨설팅</span>
      <h1 style={{ fontSize: 26, margin: "8px 0 10px" }}>직업계고 3년Plan 컨설팅</h1>
      <p style={{ fontSize: 15, lineHeight: 1.7, color: "var(--steel)", marginTop: 0 }}>
        직업계고 졸업 후 취업할 수 있는 회사의 선택지가 넓어질 수 있도록,
        3년간의 학교생활을 규모 있고 건설적으로 설계할 수 있도록 돕는 컨설팅입니다.
      </p>

      <dl style={{
        display: "grid", gridTemplateColumns: "auto 1fr", gap: "8px 18px",
        margin: "18px 0 0", padding: "16px 18px", fontSize: 14.5,
        borderRadius: "var(--radius-sm)", background: "var(--raised)",
        border: "1px solid var(--line)",
      }}>
        <dt style={{ color: "var(--steel)" }}>진행 방식</dt>
        <dd style={{ margin: 0, fontWeight: 600 }}>온라인 (zoom)</dd>
        <dt style={{ color: "var(--steel)" }}>진행 시간</dt>
        <dd style={{ margin: 0, fontWeight: 600 }}>90분</dd>
        <dt style={{ color: "var(--steel)" }}>비용</dt>
        <dd style={{ margin: 0, fontWeight: 600 }}>300,000원</dd>
      </dl>

      <ApplyForm kind="plan_consulting" title="신청폼"
        applicantLabels={["본인", "학부모"]} />

      <ConsultantProfile />
    </div>
  );
}
