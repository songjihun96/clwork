import { useSeo } from "../seo";
import ApplyForm from "../components/ApplyForm";
import ConsultantProfile from "../components/ConsultantProfile";

/** 직업계고 상담 신청 — 안내 + 신청. */
export default function Counseling() {
  useSeo({
    title: "직업계고 상담신청",
    description: "직업계고와 관련된 다양한 주제의 상담을 전화 또는 온라인(zoom)으로 진행합니다.",
    path: "/counseling",
  });

  return (
    <div className="wrap" style={{ padding: "34px 0 60px", maxWidth: 760 }}>
      <span className="label">상담</span>
      <h1 style={{ fontSize: 26, margin: "8px 0 10px" }}>직업계고 상담신청</h1>
      <p style={{ fontSize: 15, lineHeight: 1.7, color: "var(--steel)", marginTop: 0 }}>
        직업계고와 관련된 다양한 주제의 상담을 진행합니다.
      </p>

      <dl style={{
        display: "grid", gridTemplateColumns: "auto 1fr", gap: "8px 18px",
        margin: "18px 0 0", padding: "16px 18px", fontSize: 14.5,
        borderRadius: "var(--radius-sm)", background: "var(--raised)",
        border: "1px solid var(--line)",
      }}>
        <dt style={{ color: "var(--steel)" }}>진행 방식</dt>
        <dd style={{ margin: 0, fontWeight: 600 }}>전화, 온라인(zoom)</dd>
        <dt style={{ color: "var(--steel)" }}>진행 시간</dt>
        <dd style={{ margin: 0, fontWeight: 600 }}>60분</dd>
        <dt style={{ color: "var(--steel)" }}>비용</dt>
        <dd style={{ margin: 0, fontWeight: 600 }}>100,000원</dd>
      </dl>

      <ApplyForm kind="counseling" title="신청폼"
        applicantLabels={["본인", "학부모"]}
        messageLabel="상담내용"
        messagePlaceholder="자세하게 입력해 주세요. 어떤 주제로 상담받고 싶은지 적어주실수록 준비가 정확해집니다." />

      <ConsultantProfile />
    </div>
  );
}
