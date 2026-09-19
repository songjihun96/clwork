import { Link } from "react-router-dom";

/** 상담원이 아침에 처음 보는 화면.
 *  통계가 아니라 '지금 손이 필요한 것'만 큰 숫자로 둔다. */
export default function Dashboard({ counts }) {
  const cards = [
    { to: "/inquiries", k: "답변 안 한 문의", n: counts?.inquiries_pending },
    { to: "/verifications", k: "대기 중인 재학생 인증", n: counts?.verifications_pending },
    { to: "/orders", k: "입금 확인이 필요한 주문", n: counts?.orders_pending },
    { to: "/schools", k: "30일 안에 만료되는 플랜", n: counts?.plans_expiring },
  ];
  const total = cards.reduce((a, c) => a + (c.n || 0), 0);

  return (
    <>
      <div className="page-head">
        <h1>할 일</h1>
        <p>
          {counts == null
            ? "불러오는 중입니다."
            : total === 0
            ? "지금 처리할 것이 없습니다."
            : `처리를 기다리는 항목이 ${total}건 있습니다.`}
        </p>
      </div>

      <div className="queue">
        {cards.map((c) => (
          <Link key={c.to + c.k} to={c.to}>
            <div className={`n ${c.n ? "" : "zero"}`}>{counts == null ? "–" : c.n ?? 0}</div>
            <div className="k">{c.k}</div>
          </Link>
        ))}
      </div>

      <div className="card" style={{ marginTop: 20 }}>
        <h2>알아두실 것</h2>
        <ul style={{ margin: 0, paddingLeft: 18, color: "var(--muted)", fontSize: 13.5 }}>
          <li style={{ marginBottom: 6 }}>
            회원 연락처는 기본적으로 가려져 있습니다. <strong>원본 보기</strong>를 누르면 열람
            기록이 남습니다.
          </li>
          <li style={{ marginBottom: 6 }}>
            입금 확인까지가 상담 업무입니다. 플랜을 실제로 켜는 <strong>최종 승인</strong>은
            관리자가 합니다.
          </li>
        </ul>
      </div>
    </>
  );
}
