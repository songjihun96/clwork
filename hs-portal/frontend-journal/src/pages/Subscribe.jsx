import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";

/** 자기소개서 이용권 — 학교 코드와 개인 구매.
 *
 * 이용권을 얻는 길은 둘이다.
 *   · 학교 구매: 선생님께 받은 코드를 넣는다(자기소개서 화면의 코드 칸).
 *   · 개인 구매: 여기서 직접 결제한다. 결제가 확정되면 계정에 바로 붙고,
 *     선생님·학교 승인은 필요 없다. 카드는 결제 즉시, 계좌 입금은 입금을
 *     확인한 뒤 열린다.
 *
 * 학생은 대부분 미성년자라 보호자 동의와 보호자 연락처를 받는다(민법 제5조).
 */
const ACCESS_LABEL = {
  school: "학교 이용권",
  individual: "개인 이용권",
  both: "학교 이용권 + 개인 이용권",
  trial: "첫 달 무료 이용 중",
  none: "이용권 없음",
};

function won(n) {
  return `${Number(n || 0).toLocaleString()}원`;
}

function loadToss() {
  if (window.TossPayments) return Promise.resolve(window.TossPayments);
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://js.tosspayments.com/v1/payment";
    s.onload = () => (window.TossPayments ? resolve(window.TossPayments) : reject(new Error("결제창을 불러오지 못했습니다.")));
    s.onerror = () => reject(new Error("결제창을 불러오지 못했습니다. 잠시 뒤 다시 시도해주세요."));
    document.head.appendChild(s);
  });
}

export default function Subscribe() {
  const [sub, setSub] = useState(null);
  const [orders, setOrders] = useState([]);
  const [months, setMonths] = useState(12);
  const [method, setMethod] = useState("");
  const [depositor, setDepositor] = useState("");
  const [guardian, setGuardian] = useState("");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [bankOrder, setBankOrder] = useState(null);

  const load = () => {
    api.subscription().then((s) => {
      setSub(s);
      const pm = s.personal?.pay_methods || {};
      setMethod((m) => m || (pm.card ? "card" : pm.bank ? "bank" : ""));
    }).catch((e) => setMsg({ type: "error", text: e.message }));
    api.myPersonalOrders().then((r) => {
      setOrders(r || []);
      setBankOrder((r || []).find((o) => o.method === "bank" && o.status === "pending") || null);
    }).catch(() => {});
  };
  useEffect(load, []);

  if (!sub) return <div className="wrap page"><p>불러오는 중…</p></div>;

  const plans = sub.personal?.plans || [];
  const pm = sub.personal?.pay_methods || {};
  const plan = plans.find((p) => p.months === months) || plans[plans.length - 1];
  const canBuy = pm.card || pm.bank;

  const buy = async (e) => {
    e.preventDefault();
    if (busy) return;
    setMsg(null);
    if (!consent || !guardian.trim()) {
      setMsg({ type: "error", text: "보호자 동의에 체크하고 보호자 연락처를 적어주세요." });
      return;
    }
    setBusy(true);
    try {
      const o = await api.createPersonalOrder({
        months: plan.months, method, depositor_name: depositor.trim(),
        minor_consent: consent, guardian_contact: guardian.trim(),
      });
      if (method === "bank") {
        setBankOrder(o);
        load();
        return;
      }
      const TossPayments = await loadToss();
      const origin = window.location.origin;
      await TossPayments(o.toss.client_key).requestPayment("카드", {
        amount: o.toss.amount,
        orderId: o.toss.order_id,
        orderName: o.toss.order_name,
        customerName: o.toss.customer_name,
        customerEmail: o.toss.customer_email || undefined,
        successUrl: `${origin}/payment/result`,
        failUrl: `${origin}/payment/result?fail=1`,
      });
    } catch (err) {
      // 결제창을 닫으면 여기로 온다. 주문은 결제 대기로 남았다가 결과 화면에서 닫힌다.
      setMsg({ type: "error", text: err.message || "결제를 진행하지 못했습니다." });
    } finally {
      setBusy(false);
    }
  };

  const cancel = async (id) => {
    if (!confirm("이 주문을 취소할까요?")) return;
    try {
      await api.cancelPersonalOrder(id);
      setBankOrder(null);
      load();
    } catch (err) {
      setMsg({ type: "error", text: err.message });
    }
  };

  return (
    <div className="wrap page" style={{ maxWidth: 720 }}>
      <span className="label">이용권</span>
      <h1 style={{ marginTop: 4 }}>자기소개서 이용권</h1>
      <p style={{ color: "var(--steel)", lineHeight: 1.8, marginTop: 0 }}>
        일지 작성과 선생님께 제출은 계속 무료입니다. 자기소개서만 이용권이 필요합니다.
      </p>

      {msg && <div className={`notice notice-${msg.type}`} style={{ margin: "12px 0" }}>{msg.text}</div>}

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>내 이용권</h3>
        <div className="sub-status">
          <span className={`badge ${sub.active ? "badge-done" : ""}`}>{ACCESS_LABEL[sub.access_type] || "이용권 없음"}</span>
          {sub.personal?.active && sub.personal.expires_at && (
            <span className="meta">개인 이용권 {String(sub.personal.expires_at).slice(0, 10)}까지</span>
          )}
          {sub.school_seat?.expires_at && (
            <span className="meta">학교 이용권 {String(sub.school_seat.expires_at).slice(0, 10)}까지</span>
          )}
          {sub.trial?.status === "trial" && sub.trial.last_day && (
            <span className="meta">무료 {sub.trial.last_day}까지 · {sub.trial.days_left}일 남음</span>
          )}
        </div>
        {sub.trial?.status === "trial" && (
          <p className="meta" style={{ margin: "10px 0 0", lineHeight: 1.7 }}>
            지금은 첫 달 무료 기간이라 자기소개서를 쓸 수 있습니다. 무료 기간이 끝나기 전에
            아래에서 이용권을 사 두면 남은 무료 기간과 상관없이 결제일부터 이용 기간이 시작됩니다.
          </p>
        )}
        {sub.trial?.status === "trial_ended" && (
          <div className="notice trial-ended-box" style={{ marginTop: 10 }}>
            <b>무료 이용 기간이 종료되었습니다.</b> 계속 이용하려면 아래에서 이용권을 구매하거나 학교 코드를 넣어 주세요.
          </div>
        )}
        {sub.active && (
          <Link className="btn btn-sm btn-primary" to="/cover-letters" style={{ marginTop: 12 }}>
            자기소개서 쓰러 가기
          </Link>
        )}
      </div>

      <div className="sub-ways">
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>학교에서 받은 코드가 있어요</h3>
          <p className="meta" style={{ lineHeight: 1.7 }}>
            학교가 이용권을 샀다면 선생님께 받은 코드를 넣으세요. 학년·반은 학교가 관리합니다.
          </p>
          <Link className="btn btn-sm" to="/cover-letters">코드 넣으러 가기</Link>
        </div>

        <form className="panel" onSubmit={buy}>
          <h3 style={{ marginTop: 0 }}>개인으로 구매할게요</h3>
          <p className="meta" style={{ lineHeight: 1.7, marginTop: 0 }}>
            학교·선생님 없이 바로 쓸 수 있습니다. 결제가 끝나면 계정에 이용권이 붙습니다.
          </p>

          {!canBuy ? (
            <p className="notice">지금은 개인 구매를 받지 않습니다. 학교에 문의해 주세요.</p>
          ) : bankOrder ? (
            <BankGuide order={bankOrder} onCancel={() => cancel(bankOrder.id)} />
          ) : (
            <>
              <div className="sub-plans" role="radiogroup" aria-label="이용 기간">
                {plans.map((p) => (
                  <label key={p.months} className={`sub-plan${plan?.months === p.months ? " on" : ""}`}>
                    <input type="radio" name="plan" checked={plan?.months === p.months}
                      onChange={() => setMonths(p.months)} />
                    <b>{p.label}</b>
                    <span>{won(p.amount)}</span>
                  </label>
                ))}
              </div>

              <div className="field" style={{ marginTop: 12 }}>
                <span className="label">결제 방법</span>
                <div className="row" style={{ gap: 14, flexWrap: "wrap" }}>
                  {pm.card && (
                    <label className="row" style={{ gap: 6 }}>
                      <input type="radio" name="method" checked={method === "card"}
                        onChange={() => setMethod("card")} /> 카드 결제 (바로 열림)
                    </label>
                  )}
                  {pm.bank && (
                    <label className="row" style={{ gap: 6 }}>
                      <input type="radio" name="method" checked={method === "bank"}
                        onChange={() => setMethod("bank")} /> 계좌 입금 (입금 확인 후 열림)
                    </label>
                  )}
                </div>
              </div>

              {method === "bank" && (
                <label className="field">
                  <span className="label">입금하시는 분 이름</span>
                  <input className="input" value={depositor} maxLength={40}
                    placeholder="통장에 찍힐 이름 (부모님 이름 등)"
                    onChange={(e) => setDepositor(e.target.value)} />
                </label>
              )}

              <label className="field">
                <span className="label">보호자 연락처</span>
                <input className="input" value={guardian} maxLength={120}
                  placeholder="010-0000-0000 또는 이메일"
                  onChange={(e) => setGuardian(e.target.value)} />
              </label>
              <label className="row sub-consent">
                <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
                <span>
                  보호자(법정대리인)의 동의를 받고 결제합니다. 만 19세 미만은 보호자 동의 없이
                  결제하면 취소될 수 있습니다. <Link to="/refund">환불 규정</Link>
                </span>
              </label>

              <button className="btn btn-primary" disabled={busy || !method || !plan}
                style={{ marginTop: 12, width: "100%" }}>
                {busy ? "진행 중…" : `${won(plan?.amount)} ${method === "bank" ? "입금 신청하기" : "결제하기"}`}
              </button>
            </>
          )}
        </form>
      </div>

      {!sub.school_managed && <GradePanel />}

      {orders.length > 0 && (
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>개인 구매 내역</h3>
          {orders.map((o) => (
            <div key={o.id} className="sub-order">
              <div>
                <b>{o.months}개월 · {won(o.amount)}</b>
                <span className="meta"> · {o.method === "card" ? "카드" : "계좌 입금"} · {String(o.created_at).slice(0, 10)}</span>
              </div>
              <span className={`badge ${o.status === "approved" ? "badge-done" : o.status === "pending" ? "badge-new" : ""}`}>
                {o.status_label}
              </span>
              {o.receipt_url && <a className="meta" href={o.receipt_url} target="_blank" rel="noreferrer">영수증</a>}
              {o.can_cancel && (
                <button type="button" className="btn btn-sm btn-ghost" onClick={() => cancel(o.id)}>취소</button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function BankGuide({ order, onCancel }) {
  const b = order.bank || {};
  return (
    <div className="sub-bank">
      <p style={{ marginTop: 0 }}><b>아래 계좌로 입금해 주세요.</b> 입금을 확인하면 이용권이 열립니다.</p>
      <dl>
        <dt>금액</dt><dd><b>{won(order.amount)}</b> ({order.months}개월)</dd>
        <dt>계좌</dt><dd>{b.bank_name} {b.bank_account} ({b.bank_holder})</dd>
        <dt>입금자명</dt><dd>{order.depositor_name || "-"}</dd>
        <dt>신청 번호</dt><dd>{order.deposit_code}</dd>
        {order.due_at && <><dt>입금 기한</dt><dd>{String(order.due_at).slice(0, 10)}</dd></>}
      </dl>
      {order.payment_note && <p className="meta">{order.payment_note}</p>}
      <button type="button" className="btn btn-sm btn-ghost" onClick={onCancel}>이 신청 취소</button>
    </div>
  );
}

/** 개인 학생의 학년. 한 번 정하면 해마다 3월 새 학년도에 저절로 올라간다.
 *  학교를 통해 쓰는 학생은 선생님이 정하므로 이 칸이 없다. */
export function GradePanel({ onSaved }) {
  const [me, setMe] = useState(null);
  const [grade, setGrade] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");

  useEffect(() => {
    api.schoolProfile().then((m) => { setMe(m); setGrade(m.grade ? String(m.grade) : ""); }).catch(() => {});
  }, []);
  if (!me) return null;

  const save = async () => {
    if (!grade) return;
    setBusy(true);
    setNote("");
    try {
      const m = await api.setMyGrade(Number(grade));
      setMe(m);
      setNote("저장했습니다. 다음 학년도(3월)부터는 저절로 올라갑니다.");
      onSaved?.(m);
    } catch (e) {
      setNote(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel">
      <h3 style={{ marginTop: 0 }}>내 학년</h3>
      <p className="meta" style={{ lineHeight: 1.7, marginTop: 0 }}>
        개인으로 이용하는 학생은 학년을 직접 정합니다. 한 번 정하면 매년 3월 새 학년도에
        자동으로 올라갑니다(3학년까지).
      </p>
      <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
        <select className="select" value={grade} onChange={(e) => setGrade(e.target.value)}
          aria-label="학년" style={{ width: "auto" }}>
          <option value="">학년 선택</option>
          {[1, 2, 3].map((g) => <option key={g} value={g}>{g}학년</option>)}
        </select>
        <button type="button" className="btn btn-sm" disabled={busy || !grade} onClick={save}>저장</button>
        {me.grade_auto && <span className="meta">지금 {me.grade}학년 · 자동으로 올라가는 중</span>}
      </div>
      {note && <p className="meta" style={{ margin: "8px 0 0" }}>{note}</p>}
    </div>
  );
}
