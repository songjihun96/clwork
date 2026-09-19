import Modal from "./Modal";
import InquiryForm from "./InquiryForm";

/** 학교·기관이 남기는 신청 창.
 *
 * 들어오는 길이 둘인데 **무엇을 신청하는지가 다르다.**
 *   · 특강 페이지 카드  — 오프라인 직업계고설명회 신청
 *   · 오른쪽 아래 버튼  — 교육·컨설팅 문의
 *
 * 묻는 항목은 똑같아서(지역·학교·담당자·연락처·요청사항) 폼은 한 벌로 두고,
 * 제목과 안내만 부르는 쪽이 정한다. 어느 길로 들어왔는지는 신청에 함께
 * 적어 보낸다 — 안 그러면 관리자가 목록에서 둘을 구분할 수 없다.
 */
export default function InquiryModal({
  onClose,
  title = "교육·컨설팅 문의",
  intro = "학교·기관을 대상으로 하는 직업계고 교육과 컨설팅을 진행합니다. 남겨주시면 연락드리겠습니다.",
  via = "교육·컨설팅 문의",
  messagePlaceholder,
  submitLabel,
}) {
  return (
    <Modal title={title} onClose={onClose}>
      <p style={{ fontSize: 13.5, color: "var(--steel)", margin: "6px 0 16px", lineHeight: 1.7 }}>
        {intro}
      </p>
      <InquiryForm via={via} onDone={() => {}}
        messagePlaceholder={messagePlaceholder} submitLabel={submitLabel} />
    </Modal>
  );
}
