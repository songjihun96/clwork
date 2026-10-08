import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";

/** 카드 결제창에서 돌아오는 자리.
 *
 * 성공: 토스가 paymentKey·orderId·amount 를 붙여 보낸다. 서버가 승인해야만
 *       이용권이 붙는다(여기서 붙인다고 믿지 않는다).
 * 실패·취소: 주문을 닫아 두고 까닭을 보여 준다.
 */
export default function PaymentResult() {
  const [search] = useSearchParams();
  const [state, setState] = useState({ status: "working" });
  const done = useRef(false);   // StrictMode 에서 두 번 부르지 않게

  useEffect(() => {
    if (done.current) return;
    done.current = true;
    const orderId = search.get("orderId") || "";
    if (search.get("fail")) {
      if (orderId) api.failPersonalCard(orderId).catch(() => {});
      setState({ status: "fail", text: search.get("message") || "결제를 마치지 못했습니다." });
      return;
    }
    const paymentKey = search.get("paymentKey");
    const amount = Number(search.get("amount"));
    if (!paymentKey || !orderId || !amount) {
      setState({ status: "fail", text: "결제 정보가 없습니다." });
      return;
    }
    api.confirmPersonalCard(paymentKey, orderId, amount)
      .then((r) => setState({ status: "ok", order: r.order, sub: r.subscription }))
      .catch((e) => setState({ status: "fail", text: e.message }));
  }, [search]);

  return (
    <div className="wrap page" style={{ maxWidth: 520 }}>
      <div className="panel" style={{ textAlign: "center" }}>
        {state.status === "working" && <p>결제를 확인하고 있습니다…</p>}
        {state.status === "ok" && (
          <>
            <div className="saved-check" aria-hidden="true">✓</div>
            <h2 style={{ margin: "0 0 6px" }}>결제가 완료되었습니다</h2>
            <p className="meta" style={{ lineHeight: 1.7 }}>
              개인 이용권 {state.order?.months}개월이 계정에 붙었습니다.
              {state.sub?.personal?.expires_at && ` ${String(state.sub.personal.expires_at).slice(0, 10)}까지 쓸 수 있습니다.`}
            </p>
            <Link className="btn btn-primary" to="/cover-letters">자기소개서 쓰러 가기</Link>
          </>
        )}
        {state.status === "fail" && (
          <>
            <h2 style={{ margin: "0 0 6px" }}>결제가 완료되지 않았습니다</h2>
            <p className="meta" style={{ lineHeight: 1.7 }}>{state.text} 이용권은 붙지 않았습니다. 카드 승인 문자를 받으셨다면 고객센터로 알려 주세요.</p>
            <Link className="btn" to="/subscribe">다시 시도하기</Link>
          </>
        )}
      </div>
    </div>
  );
}
