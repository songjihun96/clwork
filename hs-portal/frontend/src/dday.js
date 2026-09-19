/** 일정까지 남은 날짜 표시.
 *
 * 학교 상세·학교 일정·즐겨찾기·학교 관리 네 화면이 같은 뱃지를 쓴다.
 * 예전에는 각자 같은 삼항식을 복사해 두고 있었는데, 그러다 보니 학교
 * 일정과 학교 관리에서는 당일(D-DAY) 분기가 빠진 채로 남아 정작 제일
 * 눈에 띄어야 할 오늘 일정이 14일 이내와 똑같이 보였다. 한곳에 둔다.
 */

/** 뱃지 색을 정하는 class. styles.css 의 .dday / .near / .today / .past 와 짝. */
export function ddayClass(d) {
  if (d < 0) return "dday past";      // 지난 일정 — 흐리게
  if (d === 0) return "dday today";   // 오늘 — 검정 바탕
  if (d <= 14) return "dday near";    // 2주 안 — 주황
  return "dday";                       // 그 외 — 회색
}

export function ddayText(d) {
  if (d === 0) return "D-DAY";
  return d > 0 ? `D-${d}` : `D+${Math.abs(d)}`;
}
