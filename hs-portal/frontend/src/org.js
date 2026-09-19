// ============================================================
//  운영 기관 정보
//  실제 오픈 전에 이 파일의 값만 채우면 사이트 전체(푸터,
//  개인정보처리방침 등)에 반영됩니다.
//  [ ] 로 표시된 곳이 아직 정해지지 않은 값입니다.
// ============================================================

export const ORG = {
  // 서비스/기관 이름
  serviceName: "우리동네 직업계고",
  operator: "특성화고신문",

  // 사업자 정보 (푸터 표기용)
  businessNumber: "214-13-75982",
  representative: "강승구",

  // 개인정보 보호책임자 (담당자)
  privacyOfficerName: "송지훈",
  privacyOfficerTitle: "개인정보 보호책임자",
  privacyOfficerEmail: "songjihun96@naver.com",
  privacyOfficerPhone: "010-5749-9632",

  // 기관 연락처/주소
  contactEmail: "news@sinmoon.net",
  contactPhone: "070-7867-7970",
  address: "경기도 양주시 고암동 128-2 대영빌딩 4층 4-1호",

  // 전자상거래법 제10조 표시 항목
  // 호스팅서비스 제공자 상호 (법정 표시 의무)
  hostingProvider: "네이버클라우드 주식회사",
  // 통신판매업 신고번호. 신고 후 번호를 넣으면 푸터에 자동 표시된다.
  // 아직 신고 전이면 빈 문자열로 두면 표시되지 않는다.
  mailOrderNumber: "",

  // 개인정보처리방침 시행일 (오픈일)
  privacyEffectiveDate: "2026-09-07",
};

// 아직 안 채운 값이 있는지 확인용 (오픈 전 점검에 사용 가능)
export function hasUnfilledOrgValues() {
  return Object.values(ORG).some(
    (v) => typeof v === "string" && v.startsWith("[") && v.endsWith("]")
  );
}
