import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";

// 연구는 별도 서비스로 옮겨 갔다. 여기 남은 상품은 자기소개서뿐이다.
const PRODUCTS = [["essay", "자기소개서"]];

/** 학교 계정이 좌석을 사고 학생에게 나눠주는 화면.
 *  학년별로 파는 구조라, 인원수를 적어 신청하면 관리자가 확인 후 승인한다.
 *  자기소개서와 연구는 서로 다른 좌석 풀이라(학교가 하나만 사거나 둘 다
 *  살 수 있다), 상품 탭으로 나눠서 보여준다. */
export default function SchoolSeats() {
  const { user } = useAuth();
  const [product, setProduct] = useState("essay");
  const [tab, setTab] = useState("codes");
  const [info, setInfo] = useState(null);

  useEffect(() => {
    setInfo(null);
    api.schoolSeats(product).then(setInfo).catch(() => setInfo({ active: false }));
  }, [product]);

  const isSchool = user?.role === "school" || user?.role === "admin";

  // 아직 이용권을 사지 않았으면 신청 폼만 보여준다. 좌석이 0인데
  // 코드 발급이나 배정 화면을 띄워봐야 할 수 있는 일이 없다.
  const notYet = info && !info.active;

  const tabs = isSchool
    ? [["codes", "등록 코드"], ["seats", "직접 배정"], ["orders", "신청 내역"]]
    : [["codes", "등록 코드"]];

  const productLabel = PRODUCTS.find(([k]) => k === product)?.[1] || product;

  return (
    <div className="wrap page" style={{ maxWidth: 860 }}>
      <span className="label">{isSchool ? "학교 관리" : "학급 관리"}</span>
      <h1>{productLabel} 이용권</h1>
      <p style={{ color: "var(--steel)", lineHeight: 1.8, marginTop: 0 }}>
        {isSchool
          ? "학교가 인원수만큼 이용권을 사고, 학생에게 나눠줍니다."
          : "학교가 산 이용권을 우리 반 학생들에게 나눠줄 수 있습니다."}
        {" "}일지 작성과 선생님께 제출은 이용권 없이도 계속 무료입니다.
        {isSchool && <> 학생 명단이나 선생님 담당 과목은 <Link to="/school/classes">학급·과목 관리</Link>에서 다룹니다.</>}
      </p>

      <div className="row" style={{ gap: 6, marginTop: 14 }}>
        {PRODUCTS.map(([k, label]) => (
          <button key={k} className={`btn btn-sm ${product === k ? "" : "btn-ghost"}`}
            onClick={() => { setProduct(k); setTab("codes"); }}>{label}</button>
        ))}
      </div>

      {!info ? (
        <p className="meta" style={{ marginTop: 20 }}>불러오는 중…</p>
      ) : notYet && isSchool ? (
        // 학교: 아직 안 샀으면 신청 폼만
        <div style={{ marginTop: 16 }}><OrdersTab product={product} /></div>
      ) : notYet ? (
        // 선생님: 학교가 사기 전에는 할 수 있는 일이 없다
        <div className="panel" style={{ marginTop: 16, lineHeight: 1.8 }}>
          아직 학교가 {productLabel} 이용권을 신청하지 않았습니다.
          <b> 학교 계정에서 먼저 신청</b>해야 등록 코드를 만들 수 있습니다.
        </div>
      ) : (
        <>
          {tabs.length > 1 && (
            <div className="row" style={{ gap: 6, margin: "16px 0" }}>
              {tabs.map(([k, label]) => (
                <button key={k} className={`btn btn-sm ${tab === k ? "" : "btn-ghost"}`}
                  onClick={() => setTab(k)}>{label}</button>
              ))}
            </div>
          )}

          {tab === "codes" && <CodesTab product={product} />}
          {tab === "seats" && isSchool && <SeatsTab product={product} />}
          {tab === "orders" && isSchool && <OrdersTab product={product} />}
        </>
      )}
    </div>
  );
}

function SeatsTab({ product }) {
  const [info, setInfo] = useState(null);
  const [students, setStudents] = useState([]);
  const [picked, setPicked] = useState([]);
  const [q, setQ] = useState("");
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = () => {
    api.schoolSeats(product).then(setInfo).catch((e) => setMsg({ type: "error", text: e.message }));
    // 배정 화면은 한 페이지 안에서 고르는 곳이라 넉넉히 받아온다.
    api.schoolStudents({ limit: 100, product }).then((d) => setStudents(d.items || [])).catch(() => {});
  };
  useEffect(() => { load(); }, [product]);

  const act = async (fn) => {
    setBusy(true); setMsg(null);
    try {
      const r = await fn(picked, product);
      setMsg({ type: "ok", text: r.message });
      setPicked([]);
      load();
    } catch (e) {
      setMsg({ type: "error", text: e.message });
    } finally {
      setBusy(false);
    }
  };

  const toggle = (id) =>
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));

  const shown = students.filter((s) =>
    !q.trim() ||
    s.name.includes(q.trim()) ||
    (s.class_name || "").includes(q.trim()) ||
    String(s.grade || "").includes(q.trim())
  );
  const pickedHeld = picked.filter((id) =>
    students.find((s) => s.user_id === id)?.has_seat);

  if (!info) return <p className="meta">불러오는 중…</p>;

  return (
    <>
      <div className="panel">
        <div className="row" style={{ gap: 20, flexWrap: "wrap" }}>
          <Stat label="구입 좌석" value={info.seats} />
          <Stat label="나눠준 좌석" value={info.used} />
          <Stat label="남은 좌석" value={info.left} highlight />
        </div>
        <p className="meta" style={{ marginTop: 10, lineHeight: 1.7 }}>
          {info.active
            ? `${String(info.expires_at).slice(0, 10)}까지 이용하실 수 있습니다.`
            : "이용 중인 좌석이 없습니다. 신청 내역에서 이용권을 신청해주세요."}
          {" "}1명당 {Number(info.unit_price || 0).toLocaleString()}원입니다.
        </p>
      </div>

      {msg && <div className={`notice notice-${msg.type}`} style={{ marginTop: 12 }}>{msg.text}</div>}

      <div className="panel" style={{ marginTop: 14 }}>
        <div className="row" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <b>학생 {students.length}명</b>
          <input className="input" value={q} placeholder="이름·학년·반으로 찾기"
            style={{ maxWidth: 220 }} onChange={(e) => setQ(e.target.value)} />
          <div className="spacer" />
          {picked.length > 0 && (
            <>
              <span className="meta">{picked.length}명 선택</span>
              {pickedHeld.length === picked.length ? (
                <button className="btn btn-sm" disabled={busy}
                  onClick={() => act(api.revokeSeats)}>좌석 회수</button>
              ) : (
                <button className="btn btn-sm btn-primary" disabled={busy || !info.active}
                  onClick={() => act(api.assignSeats)}>좌석 주기</button>
              )}
              <button className="btn btn-sm btn-ghost" onClick={() => setPicked([])}>해제</button>
            </>
          )}
        </div>

        {shown.length === 0 ? (
          <p className="meta" style={{ marginTop: 10 }}>학생이 없습니다.</p>
        ) : (
          <div style={{ maxHeight: 420, overflowY: "auto", marginTop: 10 }}>
            {shown.map((s) => (
              <label key={s.user_id} className="row"
                style={{ gap: 8, padding: "7px 0", borderTop: "1px solid var(--line)",
                         alignItems: "center", cursor: "pointer" }}>
                <input type="checkbox" checked={picked.includes(s.user_id)}
                  onChange={() => toggle(s.user_id)} />
                <span style={{ minWidth: 90 }}>{s.name}</span>
                <span className="meta">
                  {/* 학급 이름에 이미 학년이 들어 있는 경우가 많다.
                      둘을 그냥 이으면 '1학년 2학년 3반'처럼 겹쳐 보인다. */}
                  {s.class_name
                    || (s.grade ? `${s.grade}학년` : "")}
                </span>
                <div className="spacer" />
                {s.has_seat
                  ? <span className="badge badge-done">이용 중</span>
                  : <span className="meta">—</span>}
              </label>
            ))}
          </div>
        )}

        <p className="meta" style={{ marginTop: 10, lineHeight: 1.7 }}>
          좌석을 회수해도 학생이 <b>작성한 자기소개서는 지워지지 않습니다.</b>
          {" "}새로 쓰거나 고칠 수만 없게 됩니다. 졸업생 좌석을 회수해 신입생에게 넘길 수 있습니다.
        </p>
      </div>
    </>
  );
}

function Stat({ label, value, highlight }) {
  return (
    <div>
      <div className="label">{label}</div>
      <div style={{ fontSize: 26, fontWeight: 800,
                    color: highlight ? "var(--signal, #f26522)" : "inherit" }}>
        {Number(value || 0).toLocaleString()}
      </div>
    </div>
  );
}

function OrdersTab({ product }) {
  const [orders, setOrders] = useState(null);
  const [seats, setSeats] = useState("");
  const [note, setNote] = useState("");
  const [depositor, setDepositor] = useState("");
  const [price, setPrice] = useState(15000);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = () => {
    // 신청 내역 API는 학교 전체를 돌려주므로, 지금 보고 있는 상품 것만 걸러 보여준다.
    api.seatOrders()
      .then((rows) => setOrders(rows.filter((o) => (o.product || "essay") === product)))
      .catch((e) => setMsg({ type: "error", text: e.message }));
    api.schoolSeats(product).then((s) => setPrice(s.unit_price)).catch(() => {});
  };
  useEffect(() => { load(); }, [product]);

  const [quote, setQuote] = useState(null);
  const n = parseInt(seats, 10) || 0;

  // 인원을 적을 때마다 서버에 물어 실제 청구될 금액을 보여준다.
  // 화면에서 따로 계산하면 할인 규칙이 바뀔 때 어긋난다.
  useEffect(() => {
    if (n <= 0) { setQuote(null); return; }
    const t = setTimeout(() => {
      api.seatQuote(n).then(setQuote).catch(() => setQuote(null));
    }, 250);
    return () => clearTimeout(t);
  }, [n]);

  const submit = async () => {
    setBusy(true); setMsg(null);
    try {
      const r = await api.createSeatOrder({
        seats: parseInt(seats, 10) || 0, note, depositor_name: depositor, product,
      });
      setMsg({
        type: "ok",
        text: r.reused
          ? "이미 신청하신 건이 있어 새로 만들지 않았습니다. 아래에서 확인해주세요."
          : "신청했습니다. 아래 계좌로 입금해주세요.",
      });
      setSeats(""); setNote("");
      load();
    } catch (e) {
      setMsg({ type: "error", text: e.message });
    } finally {
      setBusy(false);
    }
  };

  const cancel = async (o) => {
    if (!confirm("신청을 취소할까요?")) return;
    try {
      await api.cancelSeatOrder(o.id);
      load();
    } catch (e) {
      setMsg({ type: "error", text: e.message });
    }
  };

  return (
    <>
      <div className="panel">
        <h3 style={{ marginTop: 0 }}>이용권 신청</h3>
        <p className="meta" style={{ marginTop: 0, lineHeight: 1.7 }}>
          이용할 학생 수를 적어주세요. 학년 단위로 신청하셔도 됩니다.
          <b> 신청하신 인원은 담당자가 확인한 뒤 확정</b>되며, 그때 금액이 조정될 수 있습니다.
        </p>

        <div style={{ display: "grid", gap: 8, marginTop: 12 }}>
          <div>
            <span className="label">이용 인원</span>
            <input className="input" type="number" min="1" value={seats}
              placeholder="예: 200" onChange={(e) => setSeats(e.target.value)} />
          </div>
          <div>
            <span className="label">메모 (선택)</span>
            <input className="input" value={note} placeholder="예: 2학년 전체"
              onChange={(e) => setNote(e.target.value)} />
          </div>
          <div>
            <span className="label">입금하실 분 성함</span>
            <input className="input" value={depositor} placeholder="통장에 찍히는 이름"
              onChange={(e) => setDepositor(e.target.value)} />
          </div>
        </div>

        {quote && (
          <div style={{ background: "var(--raised, #f7f5f2)", borderRadius: 8,
                        padding: 14, marginTop: 12 }}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <span className="meta">
                {quote.seats}명 × {quote.unit_price.toLocaleString()}원
              </span>
              <span>{quote.subtotal.toLocaleString()}원</span>
            </div>
            {quote.discount_percent > 0 && (
              <div className="row" style={{ justifyContent: "space-between", marginTop: 4 }}>
                <span className="meta" style={{ color: "var(--signal, #f26522)" }}>
                  단체 할인 {quote.discount_percent}%
                </span>
                <span style={{ color: "var(--signal, #f26522)" }}>
                  −{quote.discount_amount.toLocaleString()}원
                </span>
              </div>
            )}
            <div className="row" style={{ justifyContent: "space-between", marginTop: 8,
                                          paddingTop: 8, borderTop: "1px solid var(--line)" }}>
              <b>합계 (1년)</b>
              <b style={{ fontSize: 19 }}>{quote.amount.toLocaleString()}원</b>
            </div>

            {quote.tiers?.length > 0 && (
              <p className="meta" style={{ margin: "8px 0 0", lineHeight: 1.7 }}>
                인원이 많을수록 깎아드립니다 —{" "}
                {quote.tiers.map((t) => `${t.min}명 이상 ${t.percent}%`).join(", ")}
              </p>
            )}
            <p className="meta" style={{ margin: "6px 0 0", lineHeight: 1.7 }}>
              담당자가 인원을 확인한 뒤 확정되며, 그때 금액이 조정될 수 있습니다.
            </p>
          </div>
        )}

        {msg && <div className={`notice notice-${msg.type}`} style={{ marginTop: 12 }}>{msg.text}</div>}

        <button className="btn btn-primary" style={{ marginTop: 12 }}
          onClick={submit} disabled={busy || n <= 0}>
          {busy ? "신청 중…" : "신청하기"}
        </button>

        <p className="meta" style={{ marginTop: 10, lineHeight: 1.7 }}>
          승인 전 취소는 전액 환불되고, 이용이 시작된 뒤에는 남은 기간만큼 일할 계산해
          환불합니다. 자세한 내용은 <Link to="/refund">환불 규정</Link>을 봐주세요.
        </p>
      </div>

      {!orders ? <p className="meta" style={{ marginTop: 14 }}>불러오는 중…</p>
        : orders.length === 0 ? null
        : orders.map((o) => (
          <div className="panel" key={o.id} style={{ marginTop: 14 }}>
            <div className="row" style={{ gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
              <b>{o.seats}명</b>
              <span>{Number(o.amount || 0).toLocaleString()}원</span>
              <span className="badge">{o.status_label}</span>
              {o.note && <span className="meta">{o.note}</span>}
              <div className="spacer" />
              <span className="meta">{String(o.created_at).slice(0, 10)}</span>
            </div>

            {o.approved_seats != null && o.approved_seats !== o.seats && (
              <p className="meta" style={{ marginTop: 6 }}>
                담당자 확인 결과 <b>{o.approved_seats}명</b>으로 확정되었습니다.
              </p>
            )}
            {o.admin_note && (
              <p className="meta" style={{ marginTop: 4 }}>담당자 메모: {o.admin_note}</p>
            )}

            {o.status === "pending" && o.bank?.bank_name && (
              <div style={{ background: "var(--raised, #f7f5f2)", borderRadius: 8,
                            padding: 12, marginTop: 10 }}>
                <div className="label">입금 계좌</div>
                <div style={{ fontSize: 15, marginTop: 2 }}>
                  {o.bank.bank_name} <b>{o.bank.bank_account}</b>
                  {o.bank.bank_holder ? ` · ${o.bank.bank_holder}` : ""}
                </div>
                <div className="row" style={{ gap: 6, marginTop: 8, flexWrap: "wrap" }}>
                  <button className="btn btn-sm" onClick={() =>
                    navigator.clipboard?.writeText(o.bank.bank_account)}>계좌 복사</button>
                  <button className="btn btn-sm" onClick={() =>
                    navigator.clipboard?.writeText(String(o.amount))}>금액 복사</button>
                  <button className="btn btn-sm btn-ghost" onClick={() => cancel(o)}>신청 취소</button>
                </div>
                <p className="meta" style={{ margin: "8px 0 0", lineHeight: 1.7 }}>
                  입금자명은 <b>{o.depositor_name || o.deposit_code}</b> 으로 적어주세요.
                  {o.due_at && ` 입금 기한은 ${String(o.due_at).slice(0, 10)}까지입니다.`}
                </p>
              </div>
            )}
          </div>
        ))}
    </>
  );
}

/** 등록 코드.
 *  학생을 한 명씩 체크하는 것은 200명이 넘어가면 쓸 수 없다.
 *  코드를 만들어 나눠주면 학생이 스스로 등록한다. */
const CLASS_NO_OPTIONS = Array.from({ length: 30 }, (_, i) => `${i + 1}반`);

function CodesTab({ product }) {
  const [info, setInfo] = useState(null);
  const [codes, setCodes] = useState(null);
  const [uses, setUses] = useState("");
  const [label, setLabel] = useState("");
  // 학급 정보. 선생님이면 내 담당 학급을 기본으로 채운다.
  // 매번 같은 것을 다시 적게 하면 오타가 난다.
  const [grade, setGrade] = useState("");
  const [classNo, setClassNo] = useState("");
  const [dept, setDept] = useState("");
  const [deptOptions, setDeptOptions] = useState([]);

  useEffect(() => {
    api.me().then((m) => {
      if (m?.role !== "teacher") return;
      setGrade(m.grade ? String(m.grade) : "");
      setClassNo(m.class_name || "");
      setDept(m.department || "");
    }).catch(() => {});
    api.journalSubjects().then((s) => setDeptOptions(s?.departments || [])).catch(() => {});
  }, []);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = () => {
    api.schoolSeats(product).then(setInfo).catch(() => {});
    api.seatCodes(product).then(setCodes).catch((e) => setMsg({ type: "error", text: e.message }));
  };
  useEffect(() => { load(); }, [product]);

  const create = async () => {
    setBusy(true); setMsg(null);
    try {
      const r = await api.createSeatCode(parseInt(uses, 10) || 0, label,
        { grade, class_no: classNo, department: dept, product });
      const where = [r.grade ? `${r.grade}학년` : "", r.class_no, r.department]
        .filter(Boolean).join(" ");
      setMsg({ type: "ok", text:
        `${r.code} 코드를 만들었습니다. 학생들에게 알려주세요.`
        + (where ? ` 이 코드로 등록하면 ${where} 로 배정됩니다.` : "") });
      setUses(""); setLabel("");
      load();
    } catch (e) {
      setMsg({ type: "error", text: e.message });
    } finally {
      setBusy(false);
    }
  };

  const toggle = async (x) => {
    try { await api.toggleSeatCode(x.id); load(); }
    catch (e) { setMsg({ type: "error", text: e.message }); }
  };

  if (!info) return <p className="meta">불러오는 중…</p>;

  return (
    <>
      <div className="panel">
        <div className="row" style={{ gap: 20, flexWrap: "wrap" }}>
          <Stat label="구입 좌석" value={info.seats} />
          <Stat label="등록한 학생" value={info.used} />
          <Stat label="남은 좌석" value={info.left} highlight />
        </div>
        <p className="meta" style={{ marginTop: 10, lineHeight: 1.7 }}>
          {info.active
            ? `${String(info.expires_at).slice(0, 10)}까지 이용하실 수 있습니다.`
            : "이용 중인 좌석이 없습니다. 신청 내역에서 이용권을 먼저 신청해주세요."}
        </p>
      </div>

      <div className="panel" style={{ marginTop: 14 }}>
        <h3 style={{ marginTop: 0 }}>코드 만들기</h3>
        <p className="meta" style={{ marginTop: 0, lineHeight: 1.7 }}>
          코드를 만들어 학생들에게 알려주면, 학생이{" "}
          <b>자기소개서 화면에서 직접 입력</b>해
          이용권을 받습니다. <b>학년·반·학과를 적어 두면 학생이 코드를 넣을 때 그대로
          배정</b>되고, 학생이 직접 고르지 않아도 됩니다.
        </p>

        <div className="row" style={{ gap: 8, marginTop: 12, flexWrap: "wrap" }}>
          <input className="input" type="number" min="1" value={uses} style={{ maxWidth: 130 }}
            placeholder="인원수" onChange={(e) => setUses(e.target.value)} />
          <select className="select" value={grade} style={{ maxWidth: 100 }}
            onChange={(e) => setGrade(e.target.value)}>
            <option value="">학년 선택</option>
            {[1, 2, 3].map((g) => <option key={g} value={g}>{g}학년</option>)}
          </select>
          <select className="select" value={classNo} style={{ maxWidth: 100 }}
            onChange={(e) => setClassNo(e.target.value)}>
            <option value="">반 선택</option>
            {CLASS_NO_OPTIONS.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <select className="select" value={dept} style={{ maxWidth: 170 }}
            onChange={(e) => setDept(e.target.value)}>
            <option value="">학과 없음</option>
            {deptOptions.map((d) => <option key={d} value={d}>{d}</option>)}
            {dept && !deptOptions.includes(dept) && <option value={dept}>{dept}</option>}
          </select>
          <input className="input" value={label} style={{ maxWidth: 170 }}
            placeholder="비고 (비우면 자동)" onChange={(e) => setLabel(e.target.value)} />
          <button className="btn btn-primary" onClick={create}
            disabled={busy || !info.active || !(parseInt(uses, 10) > 0)}>
            {busy ? "만드는 중…" : "코드 만들기"}
          </button>
        </div>

        {msg && <div className={`notice notice-${msg.type}`} style={{ marginTop: 12 }}>{msg.text}</div>}
      </div>

      {codes && codes.length > 0 && (
        <div className="panel" style={{ marginTop: 14 }}>
          <h3 style={{ marginTop: 0 }}>만든 코드</h3>
          {codes.map((x) => (
            <div key={x.id} style={{ padding: "10px 0", borderTop: "1px solid var(--line)" }}>
              <div className="row" style={{ gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                <b style={{ fontFamily: "ui-monospace, Menlo, monospace", fontSize: 18,
                            letterSpacing: "0.06em" }}>
                  {x.code}
                </b>
                {x.label && <span className="badge">{x.label}</span>}
                {!x.is_active && <span className="badge">중지됨</span>}
                <div className="spacer" />
                <span className="meta">{x.used_count} / {x.max_uses}명</span>
                <button className="btn btn-sm" onClick={() => {
                  navigator.clipboard?.writeText(x.code);
                  setMsg({ type: "ok", text: "코드를 복사했습니다." });
                }}>복사</button>
                <button className="btn btn-sm btn-ghost" onClick={() => toggle(x)}>
                  {x.is_active ? "중지" : "다시 켜기"}
                </button>
              </div>
            </div>
          ))}
          <p className="meta" style={{ marginTop: 10, lineHeight: 1.7 }}>
            코드를 <b>중지</b>하면 그 코드로는 더 등록할 수 없습니다. 이미 등록한 학생은
            그대로 씁니다.
          </p>
        </div>
      )}
    </>
  );
}

