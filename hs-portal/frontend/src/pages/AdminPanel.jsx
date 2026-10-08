import { Fragment, useEffect, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { Link } from "react-router-dom";
import NoticeManager from "../components/NoticeManager";
import { kstDate } from "../components/NoticeSettings";
import { ApplicationsPanel } from "./AdminApplications";
import { api, PLAN_LABEL, ROLE_LABEL } from "../api";
import { errMsg, okMsg, toast } from "../toast";

const PLAN_COLORS = { 무료: "#b6c0c8", 베이직: "#6ba3d6", 프리미엄: "#7b61c7", 플래티넘: "#ffc53d" };

function OrdersTab({ orders, reload }) {
  const [msg, setMsg] = useState(null);

  const approve = async (id) => {
    try {
      const r = await api.approveOrder(id);
      setMsg(okMsg(`승인 완료 — ${PLAN_LABEL[r.plan]} 플랜이 ${r.expires_at}까지 적용됩니다.`));
      reload();
    } catch (e) {
      setMsg(errMsg(e.message));
    }
  };

  const reject = async (id) => {
    const reason = prompt("반려 사유를 적어주세요. 학교 담당자에게 그대로 보입니다.");
    if (reason === null) return;
    await api.rejectOrder(id, reason);
    reload();
  };

  const markPaid = async (id) => {
    try { await api.markOrderPaid(id); setMsg(okMsg("입금 확인으로 표시했습니다.")); reload(); }
    catch (e) { setMsg(errMsg(e.message)); }
  };

  const expire = async (id) => {
    if (!window.confirm("기한 내 미입금으로 만료 처리할까요?")) return;
    await api.expireOrder(id);
    reload();
  };

  const openDoc = async (id, kind) => {
    try { await api.openOrderDoc(id, kind, true); }
    catch (e) { setMsg(errMsg(e.message)); }
  };

  // 입금 대기 + 입금 확인된 건이 처리 대상
  const pending = orders.filter((o) => o.status === "pending" || o.status === "paid");
  const isOverdue = (o) => o.status === "pending" && o.due_at && new Date(o.due_at) < new Date();

  return (
    <div style={{ display: "grid", gap: 16 }}>
      {msg && <div className={`notice notice-${msg.type}`}>{msg.text}</div>}

      <div className="panel">
        <h3>승인 대기 ({pending.length})</h3>
        {pending.length === 0 ? (
          <p style={{ fontSize: 13.5, color: "var(--steel)", margin: 0 }}>처리할 신청이 없습니다.</p>
        ) : (
          <table className="table">
            <thead>
              <tr><th>신청일</th><th>학교</th><th>플랜</th><th>입금 코드</th><th>금액</th><th>기한</th><th>상태</th><th></th></tr>
            </thead>
            <tbody>
              {pending.map((o) => (
                <tr key={o.id}>
                  <td>{o.created_at.slice(0, 10)}</td>
                  <td style={{ fontWeight: 600 }}>{o.school_name}</td>
                  <td>{PLAN_LABEL[o.plan]} · {o.months}개월</td>
                  <td style={{ fontFamily: "var(--font-mono)", fontWeight: 700 }}>{o.deposit_code}</td>
                  <td style={{ fontFamily: "var(--font-mono)" }}>{o.amount.toLocaleString()}원</td>
                  <td style={{ color: isOverdue(o) ? "var(--alert)" : undefined, fontSize: 12.5 }}>
                    {o.due_at ? o.due_at.slice(0, 10) : "-"}{isOverdue(o) ? " (초과)" : ""}
                  </td>
                  <td>
                    <span className={`badge ${o.status === "paid" ? "badge-dorm" : ""}`}>{o.status_label}</span>
                  </td>
                  <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    {o.status === "pending" && (
                      <><button className="btn btn-ghost btn-sm" onClick={() => markPaid(o.id)}>입금 확인</button>{" "}</>
                    )}
                    <button className="btn btn-signal btn-sm" onClick={() => approve(o.id)}>승인</button>{" "}
                    <button className="btn btn-ghost btn-sm" onClick={() => openDoc(o.id, "quote")}>견적서</button>{" "}
                    <button className="btn btn-ghost btn-sm" onClick={() => openDoc(o.id, "contract")}>계약서</button>{" "}
                    <button className="btn btn-ghost btn-sm" onClick={() => reject(o.id)}>반려</button>{" "}
                    <button className="btn btn-ghost btn-sm" onClick={() => expire(o.id)}>만료</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="panel">
        <h3>전체 신청 내역</h3>
        <table className="table">
          <thead>
            <tr><th>신청일</th><th>학교</th><th>플랜</th><th>금액</th><th>상태</th></tr>
          </thead>
          <tbody>
            {orders.map((o) => (
              <tr key={o.id}>
                <td>{o.created_at.slice(0, 10)}</td>
                <td>{o.school_name}</td>
                <td>{PLAN_LABEL[o.plan]} · {o.months}개월</td>
                <td style={{ fontFamily: "var(--font-mono)" }}>{o.amount.toLocaleString()}원</td>
                <td>
                  <span className={`badge ${o.status === "approved" ? "badge-dorm" : ""}`}>
                    {o.status_label}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** 상단 메뉴 공개 여부.
 *
 * 아직 준비가 안 된 메뉴를 내려 두는 곳이다(영상을 다 찍기 전의 설명회처럼).
 * 배포로 메뉴를 넣었다 뺐다 하면 그때마다 zip 을 다시 올려야 해서, 결국
 * 준비가 덜 된 채로 열어 두게 된다.
 *
 * 누르면 **바로 저장한다.** 스위치를 내리고 [저장]을 또 눌러야 하면 내린 줄
 * 알고 나가는 사람이 생긴다.
 */
function NavVisibilityPanel() {
  const [items, setItems] = useState(null);
  const [busy, setBusy] = useState("");

  useEffect(() => {
    api.adminNavVisibility().then((d) => setItems(d.items || [])).catch(() => {});
  }, []);
  if (!items) return null;

  const toggle = async (key, visible) => {
    const label = items.find((x) => x.key === key)?.label || "";
    setBusy(key);
    try {
      const d = await api.saveNavVisibility({ [key]: visible });
      setItems(d.items || []);
      toast.ok(`${label} 메뉴를 ${visible ? "보이게 했습니다" : "감췄습니다"}.`);
    } catch (e) {
      toast.error(e.message);
      // 실패했으면 스위치가 혼자 움직인 상태다. 서버 값으로 되돌린다.
      api.adminNavVisibility().then((d) => setItems(d.items || [])).catch(() => {});
    } finally { setBusy(""); }
  };

  return (
    <div className="panel">
      <h3 style={{ margin: 0 }}>상단 메뉴</h3>
      <p style={{ fontSize: 13, color: "var(--steel)", margin: "6px 0 12px", lineHeight: 1.7 }}>
        아직 준비가 안 된 메뉴를 내려 둡니다. <b>메뉴만 사라지고 주소는 살아
        있어서</b>, 이미 걸어 둔 링크로는 계속 들어올 수 있습니다.
        관리자에게는 내려 둔 메뉴도 계속 보입니다.
      </p>
      <div style={{ display: "grid", gap: 10, maxWidth: 420 }}>
        {items.map((it) => (
          <div key={it.key} style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ flex: 1, fontSize: 14 }}>{it.label}</span>
            {!it.visible && (
              <span className="badge" style={{ fontSize: 11.5 }}>감춤</span>
            )}
            <label className="toggle-switch">
              <input type="checkbox" checked={it.visible} disabled={busy === it.key}
                onChange={(e) => toggle(it.key, e.target.checked)} />
              <span className="toggle-track"><span className="toggle-thumb" /></span>
            </label>
          </div>
        ))}
      </div>
      <p style={{ fontSize: 12.5, color: "var(--steel-light)", margin: "12px 0 0", lineHeight: 1.7 }}>
        숏츠는 여기가 아니라 <b>영상 관리</b>에서 켭니다 — 그쪽은 메뉴뿐 아니라
        영상까지 함께 잠급니다.
      </p>
    </div>
  );
}

function FloatingButtonPanel() {
  const [form, setForm] = useState(null);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { api.adminFloatingButton().then(setForm).catch(() => {}); }, []);
  if (!form) return null;

  const save = async (patch = {}) => {
    setBusy(true); setMsg(null);
    const next = { ...form, ...patch };
    try {
      const d = await api.saveFloatingButton(next);
      setForm(d);
      setMsg(okMsg(d.enabled ? "버튼을 켰습니다." : "설정을 저장했습니다."));
    } catch (e) {
      setMsg(errMsg(e.message));
      api.adminFloatingButton().then(setForm).catch(() => {});
    } finally { setBusy(false); }
  };

  const toggleRole = (role, on) => {
    const roles = on
      ? [...new Set([...(form.roles || []), role])]
      : (form.roles || []).filter((r) => r !== role);
    setForm({ ...form, roles });
  };

  const ROLES = [["guest", "로그인 안 한 방문자"], ["school", "학교 계정"],
    ["teacher", "선생님"], ["student", "학생"]];
  const ACTIONS = [
    ["link", "등록한 주소 열기", "누르면 아래 주소가 새 탭으로 열립니다."],
    ["inquiry", "교육·컨설팅 문의 폼 띄우기",
      "보던 화면 위에 문의 폼이 뜹니다. 접수된 문의는 신청 관리에서 봅니다."],
  ];

  return (
    <div className="panel">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
        <h3 style={{ margin: 0 }}>바로가기 버튼 (오른쪽 아래)</h3>
        <label className="toggle-switch">
          <input type="checkbox" checked={form.enabled}
            onChange={(e) => save({ enabled: e.target.checked })} />
          <span className="toggle-track"><span className="toggle-thumb" /></span>
        </label>
      </div>
      <p style={{ fontSize: 13, color: "var(--steel)", margin: "6px 0 12px", lineHeight: 1.6 }}>
        켜면 화면 오른쪽 아래에 동그란 버튼이 뜹니다. 누르면 무엇을 할지는 아래에서 고릅니다.
      </p>

      {msg && <div className={`notice notice-${msg.type}`} style={{ marginBottom: 12 }}>{msg.text}</div>}

      <div style={{ display: "grid", gap: 12, maxWidth: 480 }}>
        <div className="field">
          <label className="label">누르면 무엇을 할지</label>
          <div style={{ display: "grid", gap: 8, marginTop: 4 }}>
            {ACTIONS.map(([key, label, hint]) => (
              <label key={key} style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 13.5 }}>
                <input type="radio" name="fab-action" style={{ marginTop: 3 }}
                  checked={(form.action || "link") === key}
                  onChange={() => setForm({ ...form, action: key })} />
                <span>
                  {label}
                  <span style={{ display: "block", color: "var(--steel-light)", fontSize: 12.5 }}>{hint}</span>
                </span>
              </label>
            ))}
          </div>
        </div>
        {(form.action || "link") === "link" && (
          <div className="field">
            <label className="label">연결할 주소</label>
            <input className="input" value={form.url} placeholder="https://example.com"
              onChange={(e) => setForm({ ...form, url: e.target.value })} />
            <span className="label" style={{ color: "var(--steel-light)" }}>
              http:// 또는 https:// 로 시작해야 합니다.
            </span>
          </div>
        )}
        <div className="field">
          <label className="label">버튼 문구</label>
          <input className="input" value={form.label} maxLength={30} placeholder="예: 문의하기"
            onChange={(e) => setForm({ ...form, label: e.target.value })} />
        </div>
        <div className="field">
          <label className="label">누구에게 보일지</label>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginTop: 4 }}>
            {ROLES.map(([key, label]) => (
              <label key={key} style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13.5 }}>
                <input type="checkbox" checked={(form.roles || []).includes(key)}
                  onChange={(e) => toggleRole(key, e.target.checked)} />
                {label}
              </label>
            ))}
          </div>
        </div>
        <div>
          <button className="btn btn-primary btn-sm" onClick={() => save()} disabled={busy}>
            {busy ? "저장 중…" : "저장"}
          </button>
        </div>
      </div>
    </div>
  );
}

function BankInfoPanel() {
  const [form, setForm] = useState(null);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { api.adminBankInfo().then(setForm).catch(() => {}); }, []);
  if (!form) return null;

  const save = async () => {
    setBusy(true); setMsg(null);
    try {
      await api.saveBankInfo(form);
      setMsg(okMsg("입금 계좌 정보를 저장했습니다. 견적서와 학교 안내에 바로 반영됩니다."));
    } catch (e) {
      setMsg(errMsg(e.message));
    } finally { setBusy(false); }
  };

  const f = (k, label, ph = "") => (
    <div className="field">
      <label className="label">{label}</label>
      <input className="input" value={form[k] ?? ""} placeholder={ph}
        onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
    </div>
  );

  return (
    <div className="panel">
      <h3>입금 계좌 설정</h3>
      <p style={{ fontSize: 13, color: "var(--steel)", margin: "0 0 12px", lineHeight: 1.6 }}>
        학교에 안내되는 입금 계좌입니다. 견적서·거래명세서와 학교 화면에 그대로 표시됩니다.
      </p>
      {msg && <div className={`notice notice-${msg.type}`} style={{ marginBottom: 12 }}>{msg.text}</div>}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12 }}>
        {f("bank_name", "은행명", "예: 농협")}
        {f("bank_account", "계좌번호", "예: 301-1234-5678-91")}
        {f("bank_holder", "예금주", "특성화고신문")}
        {f("due_days", "입금 기한(일)", "14")}
      </div>
      <div className="field" style={{ marginTop: 12 }}>
        <label className="label">안내 문구</label>
        <textarea className="textarea" rows={2} value={form.payment_note ?? ""}
          onChange={(e) => setForm({ ...form, payment_note: e.target.value })} />
      </div>
      <button className="btn btn-primary btn-sm" onClick={save} disabled={busy} style={{ marginTop: 10 }}>
        {busy ? "저장 중…" : "저장"}
      </button>
    </div>
  );
}

function PlanManageTab() {
  const [prices, setPrices] = useState([]);
  const [edited, setEdited] = useState({});
  const [editedYear, setEditedYear] = useState({});
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  const [perkKeys, setPerkKeys] = useState({});   // { plan: [key, ...] }
  const [catalog, setCatalog] = useState([]);

  const load = () => api.adminPlanPrices().then((d) => {
    setPrices(d);
    setEdited(Object.fromEntries(d.map((p) => [p.plan, p.price_per_month])));
    setEditedYear(Object.fromEntries(d.map((p) => [p.plan, p.price_per_year])));
    setPerkKeys(Object.fromEntries(d.map((p) => [p.plan, p.perk_keys || []])));
  }).catch(() => {});

  const [baseFeatures, setBaseFeatures] = useState([]);
  useEffect(() => {
    api.perkCatalog().then((d) => {
      setCatalog(d.perks || []);
      setBaseFeatures(d.base_features || []);
    }).catch(() => {});
  }, []);
  useEffect(() => { load(); }, []);

  const save = async (plan) => {
    const price = Number(edited[plan]);
    const year = Number(editedYear[plan]);
    if (!Number.isFinite(price) || price < 0 || !Number.isFinite(year) || year < 0) {
      return setMsg(errMsg("0 이상의 숫자를 입력하세요."));
    }
    setBusy(true); setMsg(null);
    try {
      // 월·연을 한 번에 저장한다. 따로 누르게 하면 한쪽만 바꿔 놓고 나가서
      // 월 가격과 연 가격이 서로 안 맞는 상태가 남는다.
      await api.setPlanPrice(plan, price, "month");
      await api.setPlanPrice(plan, year, "year");
      setMsg(okMsg("가격을 저장했습니다."));
      load();
    } catch (e) {
      setMsg(errMsg(e.message));
    } finally {
      setBusy(false);
    }
  };

  // 토글하면 바로 저장한다
  const togglePerk = async (plan, key, on) => {
    const cur = perkKeys[plan] || [];
    const next = on ? [...new Set([...cur, key])] : cur.filter((k) => k !== key);
    setPerkKeys({ ...perkKeys, [plan]: next });   // 화면 먼저 반영
    try {
      await api.setPlanPerks(plan, next);
      setMsg(null);
    } catch (e) {
      setMsg(errMsg(e.message));
      load();  // 실패하면 서버 값으로 되돌린다
    }
  };

  const resetPerks = async (plan, label) => {
    if (!window.confirm(`${label} 혜택을 기본값으로 되돌릴까요?`)) return;
    setBusy(true);
    try { await api.resetPlanPerks(plan); load(); }
    finally { setBusy(false); }
  };

  return (
    <div style={{ display: "grid", gap: 16 }}>
    <BankInfoPanel />
    <div className="panel">
      <h3>플랜 가격 설정</h3>
      <p style={{ fontSize: 13, color: "var(--steel)", margin: "0 0 14px", lineHeight: 1.6 }}>
        학교가 신청하는 플랜의 가격입니다. 바꾸면 플랜 안내와 결제 금액에 바로 반영됩니다.
        <br />
        <b>연간 결제</b>는 12개월이 찰 때마다 적용됩니다 — 15개월이면 연 1회 + 월 3회로 셉니다.
      </p>
      {msg && <div className={`notice notice-${msg.type}`} style={{ marginBottom: 12 }}>{msg.text}</div>}

      <div className="plan-price-grid">
        <span className="label" />
        <span className="label">월간 결제 서비스 비용</span>
        <span className="label">연간 결제 서비스 비용</span>
        <span />
        {prices.filter((p) => p.plan !== "free").map((p) => {
          // 1년치가 월 가격 × 12 보다 비싸면 대개 잘못 적은 것이다.
          const full = Number(edited[p.plan] || 0) * 12;
          const year = Number(editedYear[p.plan] || 0);
          const odd = year > 0 && full > 0 && year > full;
          return (
            <Fragment key={p.plan}>
              <span style={{ fontWeight: 600 }}>{p.label}</span>
              <div>
                <input className="input" type="number" min="0" step="1000"
                  value={edited[p.plan] ?? ""}
                  onChange={(e) => setEdited({ ...edited, [p.plan]: e.target.value })} />
              </div>
              <div>
                <input className="input" type="number" min="0" step="10000"
                  value={editedYear[p.plan] ?? ""}
                  onChange={(e) => setEditedYear({ ...editedYear, [p.plan]: e.target.value })} />
                <span className="label" style={{ color: odd ? "var(--color-danger)" : "var(--steel-light)" }}>
                  {odd
                    ? `월 결제 ${full.toLocaleString()}원보다 비쌉니다`
                    : (year > 0 && full > 0
                      ? `월 결제 대비 ${(full - year).toLocaleString()}원 저렴`
                      : "비워 두면 월 가격 × 12")}
                </span>
              </div>
              <button className="btn btn-ghost btn-sm" onClick={() => save(p.plan)} disabled={busy}>
                저장
              </button>
            </Fragment>
          );
        })}
      </div>
    </div>

    <div className="panel">
      <h3>플랜 혜택 설정</h3>
      <p style={{ fontSize: 13, color: "var(--steel)", margin: "0 0 12px", lineHeight: 1.6 }}>
        플랜별로 제공할 <b>유료 혜택</b>을 켜고 끄세요. <b>토글을 바꾸면 바로 저장</b>되고,
        학교가 보는 화면과 실제 기능에 즉시 반영됩니다.
      </p>
      <div className="notice notice-info" style={{ marginBottom: 14 }}>
        <b>모든 플랜 기본 제공(토글 대상 아님)</b> —{" "}
        {baseFeatures.map((f) => f.label).join(" · ")}
      </div>
      <div style={{ display: "grid", gap: 18 }}>
        {prices.map((pl) => (
          <div key={pl.plan} style={{ border: "1px solid var(--line)", borderRadius: "var(--radius)", padding: "12px 14px" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginBottom: 10 }}>
              <span style={{ fontWeight: 700 }}>
                {pl.label}
                <span className="label" style={{ color: "var(--steel-light)", marginLeft: 8 }}>
                  {(perkKeys[pl.plan] || []).length}개 제공
                </span>
              </span>
              <button className="btn btn-ghost btn-sm" onClick={() => resetPerks(pl.plan, pl.label)} disabled={busy}>
                기본값으로
              </button>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 4 }}>
              {catalog.map((item) => {
                const on = (perkKeys[pl.plan] || []).includes(item.key);
                return (
                  <div key={item.key}
                    style={{ display: "flex", alignItems: "center", justifyContent: "space-between",
                             gap: 8, padding: "5px 8px", borderRadius: 8,
                             background: on ? "var(--surface)" : "transparent" }}>
                    <span style={{ fontSize: 13.5, color: on ? "var(--ink)" : "var(--steel-light)" }}>
                      {item.label}
                    </span>
                    <label className="toggle-switch">
                      <input
                        type="checkbox"
                        checked={on}
                        onChange={(e) => togglePerk(pl.plan, item.key, e.target.checked)}
                      />
                      <span className="toggle-track"><span className="toggle-thumb" /></span>
                    </label>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
    </div>
  );
}

function ArticleManageTab() {
  const [articles, setArticles] = useState([]);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ url: "", title: "", summary: "", thumbnail: "", school_id: "" });

  const load = () => api.articles(30).then(setArticles).catch(() => {});
  useEffect(() => { load(); }, []);

  const runCrawl = async () => {
    setBusy(true); setMsg(null);
    try {
      const r = await api.crawlArticles();
      if (r.ok) {
        setMsg(okMsg(`수집 완료 — 스캔 ${r.scanned}건, 신규 ${r.added}건, 학교매칭 ${r.matched}건`));
        load();
      } else {
        setMsg(errMsg(`수집 실패: ${r.error || "서버에서 특성화고신문 접근이 막혔을 수 있습니다."}`));
      }
    } catch (e) {
      setMsg(errMsg(e.message));
    } finally {
      setBusy(false);
    }
  };

  const runRematch = async () => {
    setBusy(true); setMsg(null);
    try {
      const r = await api.rematchArticles();
      if (r.ok) {
        setMsg(okMsg(`재매칭 완료 — ${r.updated}건 갱신, 총 ${r.total_matched}건 학교 연결됨`));
        load();
      } else {
        setMsg(errMsg(`재매칭 실패: ${r.error}`));
      }
    } catch (e) {
      setMsg(errMsg(e.message));
    } finally {
      setBusy(false);
    }
  };

  const runDedupe = async () => {
    if (!confirm("제목이 같은 중복 기사를 정리합니다. 계속할까요?")) return;
    setBusy(true); setMsg(null);
    try {
      const r = await api.dedupeArticles();
      if (r.ok) {
        setMsg(okMsg(`중복 제거 완료 — ${r.removed}건 삭제`));
        load();
      } else {
        setMsg(errMsg(`중복 제거 실패: ${r.error}`));
      }
    } catch (e) {
      setMsg(errMsg(e.message));
    } finally {
      setBusy(false);
    }
  };

  const addManual = async () => {
    if (!form.url.trim() || !form.title.trim()) {
      return setMsg(errMsg("원문 링크와 제목은 필수입니다."));
    }
    setBusy(true); setMsg(null);
    try {
      const body = { ...form, school_id: form.school_id ? Number(form.school_id) : null };
      await api.addManualArticle(body);
      setMsg(okMsg("기사를 등록했습니다."));
      setForm({ url: "", title: "", summary: "", thumbnail: "", school_id: "" });
      load();
    } catch (e) {
      setMsg(errMsg(e.message));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id) => {
    if (!confirm("이 기사를 삭제할까요?")) return;
    try {
      await api.deleteArticle(id);
      load();
    } catch (e) {
      setMsg(errMsg(e.message));
    }
  };

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div className="panel">
        <h3>기사 자동 수집</h3>
        <p style={{ fontSize: 13, color: "var(--steel)", margin: "0 0 12px", lineHeight: 1.6 }}>
          특성화고신문에서 기사를 가져와 제목의 학교명과 자동 연결합니다.
          평소에는 6시간마다 자동 수집되며, 아래 버튼으로 지금 즉시 수집할 수도 있습니다.
        </p>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button className="btn btn-signal btn-sm" onClick={runCrawl} disabled={busy}>
            {busy ? "처리 중…" : "지금 수집하기"}
          </button>
          <button className="btn btn-ghost btn-sm" onClick={runRematch} disabled={busy}>
            학교 재매칭
          </button>
          <button className="btn btn-ghost btn-sm" onClick={runDedupe} disabled={busy}>
            중복 정리
          </button>
        </div>
        <p style={{ fontSize: 12, color: "var(--steel-light)", margin: "10px 0 0", lineHeight: 1.5 }}>
          · 학교 재매칭: 줄임말·개명된 학교명을 다시 연결합니다<br />
          · 중복 정리: 제목이 같은 중복 기사를 하나만 남깁니다
        </p>
      </div>

      <div className="panel">
        <h3>기사 직접 등록</h3>
        <div style={{ display: "grid", gap: 8 }}>
          <input className="input" placeholder="원문 링크 (필수)" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} />
          <input className="input" placeholder="제목 (필수)" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          <input className="input" placeholder="요약 (선택)" value={form.summary} onChange={(e) => setForm({ ...form, summary: e.target.value })} />
          <input className="input" placeholder="썸네일 이미지 주소 (선택)" value={form.thumbnail} onChange={(e) => setForm({ ...form, thumbnail: e.target.value })} />
          <input className="input" placeholder="연결할 학교 ID (선택, 비우면 제목으로 매칭)" value={form.school_id} onChange={(e) => setForm({ ...form, school_id: e.target.value })} />
          <button className="btn btn-ghost btn-sm" onClick={addManual} disabled={busy} style={{ justifySelf: "start" }}>
            기사 등록
          </button>
        </div>
      </div>

      {msg && <div className={`notice notice-${msg.type}`}>{msg.text}</div>}

      <div className="panel">
        <h3>등록된 기사 ({articles.length})</h3>
        {articles.length === 0 ? (
          <div className="empty"><p>아직 수집된 기사가 없습니다.</p></div>
        ) : (
          <div style={{ display: "grid", gap: 8 }}>
            {articles.map((a) => (
              <div key={a.id} style={{ display: "flex", gap: 10, alignItems: "center", padding: "8px 0", borderBottom: "1px solid var(--line)", minWidth: 0 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  {/* 모바일에서는 말줄임보다 줄바꿈이 낫다. 한글 제목은 잘리면 알아볼 수 없다. */}
                  <div style={{ fontSize: 13.5, fontWeight: 600, overflowWrap: "anywhere" }}>{a.title}</div>
                  <div style={{ fontSize: 12, color: "var(--steel-light)", overflowWrap: "anywhere" }}>
                    {a.school_name ? `🏫 ${a.school_name}` : "미연결"} · {a.source === "manual" ? "직접등록" : "자동수집"}
                    {a.published_at ? ` · ${a.published_at}` : ""}
                  </div>
                </div>
                <button className="btn btn-ghost btn-sm" onClick={() => remove(a.id)} style={{ flexShrink: 0 }}>삭제</button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function SchoolManageTab() {
  const [search, setSearch] = useState("");
  const [results, setResults] = useState([]);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const [categories, setCategories] = useState([]);
  const [catMsg, setCatMsg] = useState(null);
  const [deptFilter, setDeptFilter] = useState(null);   // 학과 계열 필터 설정
  const [deptMsg, setDeptMsg] = useState(null);
  const [deptBusy, setDeptBusy] = useState(false);

  const loadCategories = () => api.categoryVisibility().then(setCategories).catch(() => {});
  const loadDeptFilter = () => api.deptFieldFilter().then(setDeptFilter).catch(() => {});
  useEffect(() => {
    loadCategories();
    loadDeptFilter();
  }, []);

  const toggleDeptFilter = async (enabled) => {
    setDeptMsg(null);
    try {
      await api.setDeptFieldFilter(enabled);
      await loadDeptFilter();
    } catch (e) {
      setDeptMsg(errMsg(e.message));
    }
  };

  const rebuildDeptFields = async () => {
    setDeptBusy(true);
    setDeptMsg(null);
    try {
      const r = await api.rebuildDeptFields();
      await loadDeptFilter();
      setDeptMsg(okMsg(`${r.changed}개 학교의 계열을 다시 매겼습니다.`));
    } catch (e) {
      setDeptMsg(errMsg(e.message));
    } finally {
      setDeptBusy(false);
    }
  };

  const toggleCategory = async (category, visible) => {
    setCatMsg(null);
    // 낙관적 업데이트: 화면을 먼저 바꾸고 서버에 반영
    setCategories((prev) =>
      prev.map((c) =>
        c.category === category
          ? { ...c, visible, shown: visible ? c.count : 0, hidden: visible ? 0 : c.count }
          : c
      )
    );
    try {
      await api.toggleCategoryVisibility(category, visible);
      await loadCategories();
    } catch (e) {
      setCatMsg(errMsg(e.message));
      loadCategories();
    }
  };

  const doSearch = async () => {
    const r = await api.schools({ name: search, size: 10, include_hidden: true });
    setResults(r.items);
  };

  const pick = async (school) => {
    setSelected(school);
    setMsg(null);
    const d = await api.school(school.id);
    setDetail(d);
  };

  const refresh = async () => {
    if (selected) {
      const d = await api.school(selected.id);
      setDetail(d);
    }
  };

  const resetProfile = async () => {
    if (!confirm(`'${selected.name}'의 상세정보(소개·시설·취업률·학생수·소개영상·학교일정)를 모두 비웁니다.\n\n기본정보(이름·주소·전화·좌표)와 학과·기숙사 여부·대표 이미지, 플랜은 유지됩니다. 계속할까요?`)) return;
    setBusy(true);
    setMsg(null);
    try {
      await api.resetSchoolProfile(selected.id);
      setMsg(okMsg("상세정보를 초기화했습니다."));
      await refresh();
    } catch (e) {
      setMsg(errMsg(e.message));
    } finally {
      setBusy(false);
    }
  };

  const resetPlan = async () => {
    if (!confirm(`'${selected.name}'의 플랜을 무료로 되돌리고 플랜신청 내역을 지웁니다. 계속할까요?`)) return;
    setBusy(true);
    setMsg(null);
    try {
      await api.resetSchoolPlan(selected.id);
      setMsg(okMsg("플랜을 무료로 초기화했습니다."));
      await refresh();
    } catch (e) {
      setMsg(errMsg(e.message));
    } finally {
      setBusy(false);
    }
  };

  const toggleVisible = async () => {
    setBusy(true); setMsg(null);
    try {
      const next = !detail.is_visible;
      await api.toggleSchoolVisibility(selected.id, next);
      setMsg(okMsg(next ? "이제 사용자에게 보입니다." : "사용자에게서 숨겼습니다."));
      await refresh();
    } catch (e) {
      setMsg(errMsg(e.message));
    } finally {
      setBusy(false);
    }
  };

  const togglePause = async () => {
    setBusy(true); setMsg(null);
    try {
      const next = !detail.plan_paused;
      await api.pausePlan(selected.id, next);
      setMsg(okMsg(next ? "플랜을 일시정지했습니다." : "플랜 정지를 해제했습니다."));
      await refresh();
    } catch (e) {
      setMsg(errMsg(e.message));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div className="panel">
        <h3>학과 계열 필터</h3>
        <p style={{ fontSize: 13, color: "var(--steel)", margin: "0 0 12px", lineHeight: 1.6 }}>
          학과명을 IT·디자인·조리 같은 계열로 자동 분류해, 검색 화면에 &lsquo;학과 계열&rsquo; 필터를
          띄웁니다. 끄면 필터가 사라집니다.
        </p>
        {deptMsg && <div className={`notice notice-${deptMsg.type}`} style={{ marginBottom: 12 }}>{deptMsg.text}</div>}
        {deptFilter && (
          <>
            <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 0", borderTop: "1px solid var(--line)" }}>
              <span style={{ flex: 1, minWidth: 0 }}>
                <b>검색에 학과 계열 필터 표시</b>
                <span className="label" style={{ display: "block", color: "var(--steel-light)", marginTop: 2 }}>
                  전체 {deptFilter.total}개 중 {deptFilter.tagged}개 학교에 계열이 매겨져 있습니다.
                </span>
              </span>
              <label className="toggle-switch" style={{ flexShrink: 0 }}>
                <input
                  type="checkbox"
                  checked={deptFilter.enabled}
                  onChange={(e) => toggleDeptFilter(e.target.checked)}
                />
                <span className="toggle-track"><span className="toggle-thumb" /></span>
              </label>
            </div>

            {deptFilter.fields.length > 0 && (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 10 }}>
                {deptFilter.fields.map((f) => (
                  <span key={f.key} className="badge">{f.label}</span>
                ))}
              </div>
            )}

            <button
              className="btn btn-sm btn-ghost"
              style={{ marginTop: 12 }}
              disabled={deptBusy}
              onClick={rebuildDeptFields}
            >
              {deptBusy ? "다시 매기는 중…" : "계열 다시 매기기"}
            </button>
            <span className="label" style={{ display: "block", color: "var(--steel-light)", marginTop: 6 }}>
              학과 정보를 새로 수집했거나 분류가 어긋날 때 누르세요.
            </span>
          </>
        )}
      </div>

      <div className="panel">
        <h3>계열별 노출 일괄 설정</h3>
        <p style={{ fontSize: 13, color: "var(--steel)", margin: "0 0 12px", lineHeight: 1.6 }}>
          계열 전체를 한 번에 켜고 끌 수 있습니다. 스위치를 끄면 그 계열 학교가 사용자 검색에서 사라집니다.
        </p>
        {catMsg && <div className={`notice notice-${catMsg.type}`} style={{ marginBottom: 12 }}>{catMsg.text}</div>}
        <div style={{ display: "grid", gap: 4 }}>
          {categories.map((c) => (
            <div
              key={c.category}
              style={{
                display: "flex", alignItems: "center", gap: 12,
                padding: "10px 4px", borderBottom: "1px solid var(--line)",
              }}
            >
              <span style={{ flex: 1, fontWeight: 500 }}>
                {c.category}
                <span style={{ color: "var(--steel-light)", fontSize: 12.5, marginLeft: 6 }}>
                  {c.visible
                    ? `${c.count}개 노출 중`
                    : c.hidden === c.count
                    ? `${c.count}개 전체 숨김`
                    : `${c.shown}개 노출 · ${c.hidden}개 숨김`}
                </span>
              </span>
              <label className="toggle-switch">
                <input
                  type="checkbox"
                  checked={c.visible}
                  onChange={(e) => toggleCategory(c.category, e.target.checked)}
                />
                <span className="toggle-track"><span className="toggle-thumb" /></span>
              </label>
            </div>
          ))}
        </div>
      </div>

      <div className="panel">
        <h3>학교 찾기</h3>
        <div style={{ display: "flex", gap: 6 }}>
          <input
            className="input"
            placeholder="학교 이름 일부를 입력"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && doSearch()}
          />
          <button className="btn btn-ghost" onClick={doSearch}>검색</button>
        </div>
        {results.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 12 }}>
            {results.map((s) => (
              <button
                key={s.id}
                className="badge"
                style={{
                  cursor: "pointer",
                  background: selected?.id === s.id ? "var(--signal-deep)" : "var(--paper)",
                  color: selected?.id === s.id ? "#fff" : "var(--steel)",
                }}
                onClick={() => pick(s)}
              >
                {s.name} · {s.region}
              </button>
            ))}
          </div>
        )}
      </div>

      {detail && (
        <div className="panel">
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
            <h3 style={{ border: "none", padding: 0, margin: 0 }}>{detail.name}</h3>
            <span className="badge badge-cat">{detail.category}</span>
            <span className="badge">{PLAN_LABEL[detail.plan]}</span>
            <PlanExpiry days={detail.plan_days_left} at={detail.plan_expires_at} />
            {detail.is_visible === false && (
              <span className="badge" style={{ background: "var(--steel)", color: "#fff" }}>숨김</span>
            )}
            {detail.plan_paused && (
              <span className="badge" style={{ background: "var(--alert)", color: "#fff" }}>플랜 정지</span>
            )}
          </div>

          {msg && <div className={`notice notice-${msg.type}`} style={{ marginBottom: 14 }}>{msg.text}</div>}

          <div className="kv-grid" style={{ marginBottom: 18 }}>
            <div><span className="label">소개</span><dd>{detail.slogan || "—"}</dd></div>
            <div><span className="label">학과</span><dd>{detail.departments.length ? `${detail.departments.length}개` : "—"}</dd></div>
            <div><span className="label">취업률</span><dd>{detail.employment_rate != null ? `${detail.employment_rate}%` : "—"}</dd></div>
            <div><span className="label">기숙사</span><dd>{detail.dormitory === true ? "있음" : detail.dormitory === false ? "없음" : "미확인"}</dd></div>
            <div><span className="label">학교일정</span><dd>{detail.events.length}개</dd></div>
            <div><span className="label">현재 플랜</span><dd>{PLAN_LABEL[detail.plan]}</dd></div>
            <div>
              <span className="label">만료</span>
              <dd>
                {detail.plan_expires_at
                  ? `${String(detail.plan_expires_at).slice(0, 10)} (${
                    detail.plan_days_left < 0 ? `${-detail.plan_days_left}일 지남`
                      : detail.plan_days_left === 0 ? "오늘까지"
                        : `D-${detail.plan_days_left}`}) `
                  : "—"}
              </dd>
            </div>
          </div>

          <div style={{ display: "grid", gap: 12 }}>
            <SchoolRegionEmployers key={detail.id} detail={detail} onSaved={refresh} setMsg={setMsg} />
            <SchoolLevelContact key={`lc-${detail.id}`} detail={detail} onSaved={refresh} setMsg={setMsg} />

            <div style={{ border: "1px solid var(--line)", borderRadius: "var(--radius)", padding: 14 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 4 }}>사용자 노출</div>
                  <p style={{ fontSize: 12.5, color: "var(--steel)", margin: 0, lineHeight: 1.5 }}>
                    {detail.is_visible === false
                      ? "지금 이 학교는 사용자 검색에 나오지 않습니다."
                      : "이 학교는 사용자 검색에 노출되고 있습니다."}
                  </p>
                </div>
                <label className="toggle-switch">
                  <input
                    type="checkbox"
                    checked={detail.is_visible !== false}
                    onChange={toggleVisible}
                    disabled={busy}
                  />
                  <span className="toggle-track"><span className="toggle-thumb" /></span>
                </label>
              </div>
            </div>

            <div style={{ border: "1px solid var(--line)", borderRadius: "var(--radius)", padding: 14 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 4 }}>플랜 일시정지</div>
                  <p style={{ fontSize: 12.5, color: "var(--steel)", margin: 0, lineHeight: 1.5 }}>
                    켜면 플랜 등급은 유지한 채 유료 혜택(색상 강조·기사 우선 노출)만 멈춥니다.
                    {detail.plan === "free" && " 무료 플랜은 해당 없음."}
                  </p>
                </div>
                <label className="toggle-switch">
                  <input
                    type="checkbox"
                    checked={!!detail.plan_paused}
                    onChange={togglePause}
                    disabled={busy || detail.plan === "free"}
                  />
                  <span className="toggle-track"><span className="toggle-thumb" /></span>
                </label>
              </div>
            </div>

            <div style={{ border: "1px solid var(--line)", borderRadius: "var(--radius)", padding: 14 }}>
              <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 4 }}>상세정보 초기화</div>
              <p style={{ fontSize: 12.5, color: "var(--steel)", margin: "0 0 10px", lineHeight: 1.5 }}>
                학교가 채운 소개·시설·취업률·학생수·소개영상·학교일정을 비웁니다. 학과·기숙사 여부·대표 이미지는 남습니다.
                기본정보(이름·주소·전화·좌표)와 플랜은 그대로 둡니다.
              </p>
              <button className="btn btn-ghost btn-sm" onClick={resetProfile} disabled={busy}>
                상세정보 초기화
              </button>
            </div>

            <div style={{ border: "1px solid var(--line)", borderRadius: "var(--radius)", padding: 14 }}>
              <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 4 }}>플랜 초기화</div>
              <p style={{ fontSize: 12.5, color: "var(--steel)", margin: "0 0 10px", lineHeight: 1.5 }}>
                이 학교를 무료 플랜으로 되돌리고 만료일·플랜신청 내역을 지웁니다.
                상세정보는 건드리지 않습니다.
              </p>
              <button className="btn btn-ghost btn-sm" onClick={resetPlan} disabled={busy || detail.plan === "free"}>
                {detail.plan === "free" ? "이미 무료 플랜" : "플랜 초기화"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/** 학교급(중·고)과 우리동네직업계고 담당 선생님. 중학교로 바꾸면 공개 목록에서 숨겨진다. */
function SchoolLevelContact({ detail, onSaved, setMsg }) {
  const [level, setLevel] = useState(detail.school_level || "high");
  const [c, setC] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.adminSchoolContact(detail.id)
      .then((r) => setC(r.contact || { name: "", position: "", email: "", phone: "", is_active: true, consent: false }))
      .catch(() => setC({ name: "", position: "", email: "", phone: "", is_active: true, consent: false }));
  }, [detail.id]);
  const box = { border: "1px solid var(--line)", borderRadius: "var(--radius)", padding: 14 };
  const saveLevel = async () => {
    if (level === "middle" && !window.confirm("중학교로 바꾸면 이 학교는 직업계고 공개 목록에서 숨겨지고, 학교 계정은 중학교 화면으로 바뀝니다. 바꿀까요?")) return;
    setBusy(true);
    try { await api.setSchoolLevel(detail.id, level); setMsg(okMsg("학교급을 바꿨습니다.")); onSaved(); }
    catch (e) { setMsg(errMsg(e.message)); } finally { setBusy(false); }
  };
  const saveContact = async () => {
    setBusy(true);
    try { const r = await api.saveAdminSchoolContact(detail.id, c); setC(r.contact); setMsg(okMsg("담당 선생님을 저장했습니다.")); }
    catch (e) { setMsg(errMsg(e.message)); } finally { setBusy(false); }
  };
  const cs = (k) => (e) => setC({ ...c, [k]: e.target.value });
  return (
    <>
      <div style={box}>
        <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 8 }}>학교급</div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <select className="input" style={{ width: "auto" }} value={level} onChange={(e) => setLevel(e.target.value)}>
            <option value="high">고등학교</option>
            <option value="middle">중학교</option>
          </select>
          <button className="btn btn-sm" disabled={busy || level === (detail.school_level || "high")} onClick={saveLevel}>학교급 저장</button>
          <span style={{ fontSize: 12.5, color: "var(--steel)" }}>중학교 학교 계정은 진학 지원 화면만 쓰고, 고등학교 관리 기능은 막힙니다.</span>
        </div>
      </div>
      {(detail.school_level || "high") === "high" && c && (
        <div style={box}>
          <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 4 }}>우리동네직업계고 담당 선생님</div>
          <p style={{ fontSize: 12.5, color: "var(--steel)", margin: "0 0 8px" }}>
            '우리동네직업계고 공지'를 이메일·문자로 받는 분입니다. <b>공지 수신 동의가 있어야 보냅니다.</b>
            {" "}{c.consent_at
              ? `현재: 동의 ${kstDate(c.consent_at)}(${({ school: "학교 화면", request: "계정 신청서", admin: "운영자 확인" })[c.consent_source] || "기록"})`
              : "현재: 동의 없음(발송 제외)"}
          </p>
          <div className="nm-grid">
            <input className="input" placeholder="이름" value={c.name} maxLength={40} onChange={cs("name")} />
            <input className="input" placeholder="직위" value={c.position} maxLength={40} onChange={cs("position")} />
            <input className="input" placeholder="이메일" value={c.email} maxLength={120} onChange={cs("email")} />
            <input className="input" placeholder="휴대폰" value={c.phone} maxLength={30} onChange={cs("phone")} />
          </div>
          <div style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 8, flexWrap: "wrap" }}>
            <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13.5 }}>
              <input type="checkbox" checked={c.is_active} onChange={(e) => setC({ ...c, is_active: e.target.checked })} />
              발송 대상(끄면 공지를 보내지 않음)
            </label>
            <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13.5 }}>
              <input type="checkbox" checked={!!c.consent} onChange={(e) => setC({ ...c, consent: e.target.checked })} />
              담당 선생님 본인에게 공지 수신 동의를 받았음
            </label>
            <button className="btn btn-sm" disabled={busy} onClick={saveContact}>담당 선생님 저장</button>
          </div>
        </div>
      )}
    </>
  );
}

/** 학교 계정 목록: 학교급·이용 상태로 거르고 학교명·학교코드·담당자·이메일로 찾는다.
 *  승인 대기·승인 완료는 '학교 계정 신청' 탭에서 거른다. */
function SchoolAccountsTab() {
  const [level, setLevel] = useState("");
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [data, setData] = useState(null);
  const [msg, setMsg] = useState(null);
  const load = () => api.adminSchoolAccounts({ level, status, q: q.trim() })
    .then(setData).catch((e) => setMsg(errMsg(e.message)));
  useEffect(() => { load(); }, [level, status]);
  const changeLevel = async (row, v) => {
    if (v === "middle" && !window.confirm(`${row.school_name}을(를) 중학교로 바꾸면 공개 목록에서 숨겨집니다. 바꿀까요?`)) return;
    try { await api.setSchoolLevel(row.school_id, v); setMsg(okMsg("학교급을 바꿨습니다.")); load(); }
    catch (e) { setMsg(errMsg(e.message)); }
  };
  return (
    <div className="panel">
      <h3>학교 계정</h3>
      <p style={{ fontSize: 13, color: "var(--steel)", marginTop: -4, lineHeight: 1.7 }}>
        기존 학교는 모두 고등학교로 들어 있습니다. 중학교 계정이 고등학교로 잘못 잡혀 있으면 여기서 바로 바꿉니다.
        {data && ` · 고등학교 ${data.counts.high} · 중학교 ${data.counts.middle}`}
      </p>
      {msg && <div className={`notice notice-${msg.type}`} style={{ marginBottom: 10 }}>{msg.text}</div>}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: 12 }}>
        {[["", "전체"], ["high", "고등학교"], ["middle", "중학교"]].map(([k, l]) => (
          <button key={k} className={`btn btn-sm ${level === k ? "btn-primary" : "btn-ghost"}`} onClick={() => setLevel(k)}>{l}</button>
        ))}
        <select className="select" style={{ width: "auto" }} value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">전체 상태</option>
          <option value="active">이용중</option>
          <option value="inactive">이용중지</option>
        </select>
        <input className="input" style={{ width: 220 }} value={q} placeholder="학교명·학교코드·담당자·이메일"
          onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && load()} />
        <button className="btn btn-ghost btn-sm" onClick={load}>찾기</button>
      </div>
      {!data ? <p className="label">불러오는 중…</p> : data.items.length === 0 ? (
        <p className="label">해당하는 학교 계정이 없습니다.</p>
      ) : (
        <div className="nm-table-wrap">
          <table className="table">
            <thead><tr><th>학교</th><th>학교급</th><th>지역</th><th>담당자</th><th>아이디(이메일)</th><th>상태</th><th>공지 알림 메일</th></tr></thead>
            <tbody>
              {data.items.map((r) => (
                <tr key={r.user_id}>
                  <td><b>{r.school_name}</b>{r.school_code && <small className="label"> {r.school_code}</small>}</td>
                  <td>
                    <select className="select" style={{ width: "auto" }} value={r.school_level}
                      onChange={(e) => changeLevel(r, e.target.value)} aria-label={`${r.school_name} 학교급`}>
                      <option value="high">고등학교</option>
                      <option value="middle">중학교</option>
                    </select>
                  </td>
                  <td>{r.region}</td>
                  <td>{r.manager_name}</td>
                  <td>{r.email}</td>
                  <td>{r.is_active ? <span className="badge badge-done">이용중</span> : <span className="badge">이용중지</span>}</td>
                  <td className="label">{r.notice_email || "로그인 메일"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

const SCHOOL_REGIONS = ["서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
  "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"];

/** 학교 지역. 학교 검색·인터뷰 지역 필터에 쓰인다.
 *  (주요 취업처는 학교가 '취업/진학 정보' 탭에서만 입력한다.) */
function SchoolRegionEmployers({ detail, onSaved, setMsg }) {
  const [region, setRegion] = useState(detail.region || "");
  const [busy, setBusy] = useState(false);
  const saveRegion = async () => {
    setBusy(true);
    setMsg(null);
    try {
      await api.updateSchool(detail.id, { region });
      setMsg(okMsg(`지역을 '${region}'(으)로 바꿨습니다.`));
      onSaved();
    } catch (e) {
      setMsg(errMsg(e.message));
    } finally {
      setBusy(false);
    }
  };
  const box = { border: "1px solid var(--line)", borderRadius: "var(--radius)", padding: 14 };
  return (
    <>
      <div style={box}>
        <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 8 }}>학교 지역</div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <select className="input" style={{ width: "auto" }} value={region}
            onChange={(e) => setRegion(e.target.value)}>
            {!SCHOOL_REGIONS.includes(region) && <option value={region}>{region || "(없음)"}</option>}
            {SCHOOL_REGIONS.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
          <button className="btn btn-sm" disabled={busy || !region || region === detail.region}
            onClick={saveRegion}>지역 저장</button>
          <span style={{ fontSize: 12.5, color: "var(--steel)" }}>학교 검색·인터뷰 지역 필터에 쓰입니다.</span>
        </div>
      </div>
    </>
  );
}

function AccountsTab({ users, reload }) {
  const [form, setForm] = useState({ email: "", password: "", name: "", school_id: "" });
  const [search, setSearch] = useState("");
  const [found, setFound] = useState([]);
  const [picked, setPicked] = useState(null);
  const [msg, setMsg] = useState(null);

  // 계정 검색(개인정보 보호: 검색해야만 학생·학교 계정이 보인다)
  const [acctQuery, setAcctQuery] = useState("");
  const [acctResults, setAcctResults] = useState(users);
  const [searched, setSearched] = useState(false);

  // users prop(관리자 계정만)이 바뀌면 기본 목록으로 반영
  useEffect(() => {
    if (!searched) setAcctResults(users);
  }, [users, searched]);

  const searchAccounts = async () => {
    const query = acctQuery.trim();
    if (!query) {
      setSearched(false);
      setAcctResults(users);
      return;
    }
    try {
      const r = await api.adminUsers({ q: query });
      setAcctResults(r);
      setSearched(true);
    } catch (e) {
      setMsg(errMsg(e.message));
    }
  };

  const doSearch = async () => {
    const r = await api.schools({ name: search, size: 8, include_hidden: true });
    setFound(r.items);
  };

  const create = async () => {
    setMsg(null);
    try {
      await api.createSchoolAccount({ ...form, school_id: Number(form.school_id) });
      setMsg(okMsg(`${picked.name} 계정을 만들었습니다. 아이디와 비밀번호를 학교 담당자에게 전달하세요.`));
      setForm({ email: "", password: "", name: "", school_id: "" });
      setPicked(null);
      setFound([]);
      setSearch("");
      reload();
    } catch (e) {
      setMsg(errMsg(e.message));
    }
  };

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div className="panel">
        <h3>학교 계정 만들기</h3>
        <div className="notice notice-info" style={{ marginBottom: 14 }}>
          학교 계정은 여기서만 만들 수 있습니다. 학교를 먼저 찾아 연결한 뒤 계정 정보를 입력하세요.
        </div>

        <div style={{ display: "grid", gap: 12 }}>
          <div className="field">
            <label className="label">1. 학교 찾기</label>
            <div style={{ display: "flex", gap: 6 }}>
              <input
                className="input" value={search} placeholder="학교 이름 일부를 입력"
                onChange={(e) => setSearch(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && doSearch()}
              />
              <button className="btn btn-ghost" onClick={doSearch}>검색</button>
            </div>
          </div>

          {found.length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {found.map((s) => (
                <button
                  key={s.id}
                  className="badge"
                  style={{
                    cursor: "pointer",
                    background: picked?.id === s.id ? "var(--signal-deep)" : "var(--paper)",
                    color: picked?.id === s.id ? "#fff" : "var(--steel)",
                  }}
                  onClick={() => {
                    setPicked(s);
                    setForm({ ...form, school_id: s.id });
                  }}
                >
                  {s.name} · {s.region}
                </button>
              ))}
            </div>
          )}

          {picked && (
            <>
              <div className="notice notice-ok">선택된 학교: {picked.name} ({picked.address})</div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
                <div className="field">
                  <label className="label">2. 담당자 이름</label>
                  <input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
                </div>
                <div className="field">
                  <label className="label">3. 로그인 이메일</label>
                  <input className="input" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
                </div>
                <div className="field">
                  <label className="label">4. 임시 비밀번호</label>
                  <input className="input" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
                </div>
              </div>
              <div>
                <button className="btn btn-signal" onClick={create}
                  disabled={!form.email || !form.password || !form.name}>
                  계정 만들기
                </button>
              </div>
            </>
          )}
          {msg && <div className={`notice notice-${msg.type}`}>{msg.text}</div>}
        </div>
      </div>

      <div className="panel">
        <h3>계정 찾기</h3>
        <p style={{ fontSize: 13, color: "var(--steel)", margin: "0 0 12px", lineHeight: 1.6 }}>
          개인정보 보호를 위해 학생·학교 계정은 검색해야 표시됩니다.
          이름·이메일·연락처로 찾으세요.
        </p>
        <div style={{ display: "flex", gap: 6 }}>
          <input
            className="input"
            placeholder="이름, 이메일, 또는 연락처"
            value={acctQuery}
            onChange={(e) => setAcctQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && searchAccounts()}
          />
          <button className="btn btn-ghost btn-sm" onClick={searchAccounts}>검색</button>
          {searched && (
            <button className="btn btn-ghost btn-sm" onClick={() => { setAcctQuery(""); setSearched(false); setAcctResults(users); }}>
              초기화
            </button>
          )}
        </div>
      </div>

      <div className="panel">
        <h3>
          {searched ? `검색 결과 (${acctResults.length})` : `관리자 계정 (${acctResults.length})`}
        </h3>
        {!searched && (
          <p style={{ fontSize: 12.5, color: "var(--steel-light)", margin: "0 0 12px" }}>
            학생·학교 계정을 보려면 위에서 검색하세요.
          </p>
        )}
        {acctResults.length === 0 ? (
          <div className="empty"><p>일치하는 계정이 없습니다.</p></div>
        ) : (
        <table className="table">
          <thead>
            <tr><th>이름</th><th>이메일</th><th>연락처</th><th>구분</th><th>연결 학교</th><th>가입일</th><th></th></tr>
          </thead>
          <tbody>
            {acctResults.map((u) => (
              <tr key={u.id} style={{ opacity: u.is_active ? 1 : 0.45 }}>
                <td style={{ fontWeight: 600 }}>{u.name}</td>
                <td style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>{u.email}</td>
                <td style={{ fontSize: 12.5 }}>{u.phone || "—"}</td>
                <td><span className="badge">{ROLE_LABEL[u.role]}</span></td>
                <td>{u.school_name || "—"}</td>
                <td>{u.created_at.slice(0, 10)}</td>
                <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                  {u.role !== "admin" && (
                    <>
                      <button className="btn btn-ghost btn-sm" style={{ marginRight: 6 }}
                        onClick={async () => {
                          const np = window.prompt(`${u.name} 계정의 새 비밀번호를 입력하세요 (8자 이상).`);
                          if (np == null) return;
                          if (np.length < 8) { alert("비밀번호는 8자 이상이어야 합니다."); return; }
                          try {
                            await api.adminResetPassword(u.id, np);
                            alert("비밀번호를 초기화했습니다. 새 비밀번호를 담당자에게 전달하세요.");
                          } catch (e) { alert(e.message); }
                        }}>
                        비번 초기화
                      </button>
                      <button className="btn btn-ghost btn-sm"
                        onClick={async () => {
                          await api.toggleUser(u.id, !u.is_active);
                          // 검색 상태면 재검색, 아니면 목록 새로고침
                          if (searched) searchAccounts(); else reload();
                        }}>
                        {u.is_active ? "정지" : "해제"}
                      </button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        )}
      </div>
    </div>
  );
}

function StatsTab({ stats }) {
  const planData = Object.entries(stats.plan_distribution).map(([name, value]) => ({ name, value }));
  const regionData = Object.entries(stats.region_distribution).map(([name, 학교수]) => ({ name, 학교수 }));
  const quiz = stats.quiz_stats || {};
  const [downloading, setDownloading] = useState(false);

  const download = async () => {
    setDownloading(true);
    try { await api.downloadAdminStats(); }
    catch (e) { window.alert(e.message); }
    finally { setDownloading(false); }
  };

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div style={{ display: "flex", justifyContent: "flex-end", flexWrap: "wrap" }}>
        <button className="btn btn-ghost btn-sm" onClick={download} disabled={downloading}>
          {downloading ? "생성 중…" : "⬇ 현황 리포트 (CSV)"}
        </button>
      </div>
      <div className="stat-grid">
        <div className="stat">
          <span className="label">등록 학교</span>
          <div className="stat-value">{stats.school_count.toLocaleString()}</div>
        </div>
        <div className="stat">
          <span className="label">학생 회원</span>
          <div className="stat-value">{stats.student_count.toLocaleString()}</div>
        </div>
        <div className="stat">
          <span className="label">학교 계정</span>
          <div className="stat-value">{stats.school_account_count.toLocaleString()}</div>
        </div>
        <div className="stat" style={{ borderLeft: "4px solid var(--signal)" }}>
          <span className="label">이번 달 결제 완료</span>
          <div className="stat-value">{stats.monthly_revenue.toLocaleString()}<small> 원</small></div>
          {stats.revenue?.this_month && (
            <div style={{ fontSize: 12, color: "var(--steel)", marginTop: 4 }}>
              {stats.revenue.this_month.orders}건
              {stats.revenue.this_month.refunds > 0 && ` · 환불 −${stats.revenue.this_month.refunds.toLocaleString()}원`}
              {" · "}지난달 {stats.revenue.last_month.net.toLocaleString()}원
            </div>
          )}
        </div>
        <div className="stat" style={{ borderLeft: stats.pending_orders ? "4px solid var(--alert)" : undefined }}>
          <span className="label">승인 대기</span>
          <div className="stat-value">{stats.pending_orders}<small> 건</small></div>
        </div>
      </div>

      <div className="panel">
        <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
          <h3 style={{ margin: 0 }}>진로 적성 테스트 참여</h3>
          <span style={{ flex: 1 }} />
          {/* 결과 화면의 "AI에게 물어보기"가 말하는 초봉·자격증은 이 표에서 나온다. */}
          <Link to="/admin/career-guide" className="btn btn-sm">진로 챗봇 정보표 →</Link>
        </div>
        <p style={{ fontSize: 13, color: "var(--steel)", marginTop: 6 }}>
          비회원 참여도 함께 집계됩니다. (기록이 시작된 시점부터 누적)
        </p>
        <div className="stat-grid">
          {[["오늘", quiz.today], ["이번 달", quiz.month], ["올해", quiz.year], ["전체", quiz.total]].map(([label, v]) => (
            <div className="stat" key={label}>
              <span className="label">{label}</span>
              <div className="stat-value">{(v || 0).toLocaleString()}<small> 명</small></div>
            </div>
          ))}
        </div>
        <p className="label" style={{ marginTop: 8, color: "var(--steel-light)" }}>
          회원 {(quiz.members || 0).toLocaleString()}명 · 비회원 {(quiz.guests || 0).toLocaleString()}명
        </p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1.4fr", gap: 12 }}>
        <div className="panel">
          <h3>플랜 분포</h3>
          <div style={{ height: 230 }}>
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={planData} dataKey="value" nameKey="name" innerRadius={48} outerRadius={78} paddingAngle={2}>
                  {planData.map((e) => <Cell key={e.name} fill={PLAN_COLORS[e.name]} />)}
                </Pie>
                <Tooltip contentStyle={{ border: "1px solid #dbe1e6", borderRadius: 4, fontSize: 13 }} />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "center" }}>
            {planData.map((p) => (
              <span key={p.name} style={{ fontSize: 11.5, display: "flex", alignItems: "center", gap: 4 }}>
                <i style={{ width: 8, height: 8, background: PLAN_COLORS[p.name], display: "inline-block" }} />
                {p.name} {p.value}
              </span>
            ))}
          </div>
        </div>

        <div className="panel">
          <h3>지역별 학교 수</h3>
          <div style={{ height: 260 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={regionData} margin={{ top: 5, right: 5, bottom: 5, left: -22 }}>
                <CartesianGrid strokeDasharray="2 4" stroke="#dbe1e6" vertical={false} />
                <XAxis dataKey="name" tick={{ fontSize: 10.5, fill: "#8a99a6" }} tickLine={false} axisLine={{ stroke: "#dbe1e6" }} interval={0} />
                <YAxis tick={{ fontSize: 11, fill: "#8a99a6" }} tickLine={false} axisLine={false} allowDecimals={false} />
                <Tooltip contentStyle={{ border: "1px solid #dbe1e6", borderRadius: 4, fontSize: 13 }} cursor={{ fill: "rgba(255,197,61,0.12)" }} />
                <Bar dataKey="학교수" fill="#ff7a59" radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      <div className="panel">
        <h3>조회수 상위 학교</h3>
        <table className="table">
          <thead><tr><th>순위</th><th>학교</th><th>플랜</th><th style={{ textAlign: "right" }}>조회수</th></tr></thead>
          <tbody>
            {stats.top_viewed.map((s, i) => (
              <tr key={s.name}>
                <td className="label">{String(i + 1).padStart(2, "0")}</td>
                <td style={{ fontWeight: 600 }}>{s.name}</td>
                <td><span className="badge">{s.plan}</span></td>
                <td style={{ textAlign: "right", fontFamily: "var(--font-mono)" }}>{s.views.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** 학교 계정 발급 신청.
 *
 * 학교가 남긴 신청서를 보고 전화로 확인한 뒤 승인한다. 승인하는 순간 학교
 * 계정이 만들어지고 임시 비밀번호가 메일로 나간다 — 되돌릴 수 없으니 한 번
 * 더 묻는다. 담당자 연락처가 들어 있는 화면이라 관리자만 연다.
 */
function SchoolRequestsTab({ onCount }) {
  const [rows, setRows] = useState([]);
  const [statuses, setStatuses] = useState([]);
  const [filter, setFilter] = useState("");
  const [level, setLevel] = useState("");
  const [msg, setMsg] = useState(null);
  const [issued, setIssued] = useState(null);   // 승인 직후 임시 비밀번호
  const [notes, setNotes] = useState({});

  const load = () => api.adminSchoolRequests(filter || undefined, level || undefined).then((d) => {
    setRows(d.items);
    setStatuses(d.statuses);
    if (onCount) onCount(d.open_count);
  }).catch((e) => setMsg(errMsg(e.message)));

  useEffect(() => { load(); }, [filter, level]);

  const setStatus = async (r, status) => {
    setMsg(null);
    try {
      await api.updateSchoolRequest(r.id, { status, admin_note: notes[r.id] ?? r.admin_note });
      load();
    } catch (e) { setMsg(errMsg(e.message)); }
  };

  const saveNote = async (r) => {
    try {
      await api.updateSchoolRequest(r.id, { admin_note: notes[r.id] ?? "" });
      setMsg(okMsg("메모를 저장했습니다."));
      load();
    } catch (e) { setMsg(errMsg(e.message)); }
  };

  const approve = async (r) => {
    const ok = window.confirm(
      `[${r.school_level_label}] ${r.school_name} 학교 계정을 만들까요?\n\n아이디: ${r.manager_email}\n`
      + (r.school_level === "middle" && !r.school_matched
        ? "중학교는 학교 목록에 없어 숨김 학교로 함께 만들어집니다(공개 목록에는 나오지 않습니다).\n" : "")
      + "임시 비밀번호가 이 주소로 발송됩니다. 되돌릴 수 없습니다.");
    if (!ok) return;
    setMsg(null);
    try {
      const res = await api.approveSchoolRequest(r.id);
      setIssued({ ...res, school_name: r.school_name });
      load();
    } catch (e) { setMsg(errMsg(e.message)); }
  };

  const remove = async (r) => {
    if (!window.confirm(`${r.school_name} 신청서를 지울까요? 담당자 연락처도 함께 지워집니다.`)) return;
    try {
      await api.deleteSchoolRequest(r.id);
      load();
    } catch (e) { setMsg(errMsg(e.message)); }
  };

  return (
    <div style={{ display: "grid", gap: 16 }}>
      {issued && (
        <div className="panel" style={{ borderColor: "var(--signal)" }}>
          <h3>{issued.school_name} 계정을 만들었습니다</h3>
          <div className="kv-grid">
            <div><span className="label">아이디</span><dd>{issued.email}</dd></div>
            <div>
              <span className="label">임시 비밀번호</span>
              <dd><code style={{ fontSize: 16, fontWeight: 700, letterSpacing: 1 }}>{issued.temp_password}</code></dd>
            </div>
          </div>
          <p style={{ fontSize: 13, lineHeight: 1.7, color: issued.mail_sent ? "var(--steel)" : "var(--color-danger)" }}>
            {issued.mail_sent
              ? "안내 메일을 보냈습니다. 전화로도 알려 주시면 확실합니다."
              : `메일이 발송되지 않았습니다(${issued.mail_error}). 위 임시 비밀번호를 전화로 알려 주세요.`}
            {" 학교는 첫 로그인에서 비밀번호를 바꿔야 합니다."}
          </p>
          <button className="btn btn-ghost btn-sm" onClick={() => setIssued(null)}>닫기</button>
        </div>
      )}

      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <select className="select" style={{ width: "auto" }} value={filter}
          onChange={(e) => setFilter(e.target.value)}>
          <option value="">전체 상태</option>
          <option value="open">승인 대기</option>
          {statuses.map((s) => <option key={s.key} value={s.key}>{s.key === "approved" ? "승인 완료" : s.label}</option>)}
        </select>
        <div style={{ display: "flex", gap: 4 }} role="group" aria-label="학교 유형">
          {[["", "전체"], ["high", "고등학교"], ["middle", "중학교"]].map(([k, label]) => (
            <button key={k} className={`btn btn-sm ${level === k ? "btn-primary" : "btn-ghost"}`}
              onClick={() => setLevel(k)}>{label}</button>
          ))}
        </div>
        <button className="btn btn-ghost btn-sm" onClick={load}>새로고침</button>
      </div>

      {msg && <div className={`notice notice-${msg.type}`}>{msg.text}</div>}

      {rows.length === 0 ? (
        <div className="empty"><p>신청이 없습니다.</p></div>
      ) : rows.map((r) => (
        <div className="panel" key={r.id}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
            <div>
              <h3 style={{ marginBottom: 4 }}>
                <span className={`badge ${r.school_level === "middle" ? "badge-dorm" : "badge-cat"}`}
                  style={{ marginRight: 6 }}>{r.school_level_label}</span>
                {r.school_name}
                {!r.school_matched && <span className="badge" style={{ marginLeft: 8 }}>학교 미연결</span>}
                <span className={`badge ${r.status === "approved" ? "badge-dorm" : ""}`}
                  style={{ marginLeft: 6 }}>{r.status_label}</span>
              </h3>
              <span className="label">
                {r.school_matched ? `${r.school_region} · ${r.school_category}`
                  : r.school_level === "middle" ? `${r.region || "지역 미입력"} · 중학교(승인 시 숨김 학교로 만들어짐)`
                    : "목록에 없는 학교 (직접 입력)"}
                {" · 접수 "}{(r.created_at || "").slice(0, 16).replace("T", " ")}
              </span>
            </div>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "flex-start" }}>
              {r.status !== "approved" && (
                <>
                  <button className="btn btn-ghost btn-sm" onClick={() => setStatus(r, "called")}>통화 완료</button>
                  <button className="btn btn-ghost btn-sm" onClick={() => setStatus(r, "rejected")}>반려</button>
                  <button className="btn btn-signal btn-sm" onClick={() => approve(r)}>승인하고 계정 발급</button>
                </>
              )}
              <button className="btn btn-ghost btn-sm" onClick={() => remove(r)}>삭제</button>
            </div>
          </div>

          <div className="kv-grid" style={{ marginTop: 12 }}>
            <div>
              <span className="label">담당자</span>
              <dd>{r.manager_name}{r.manager_position ? ` · ${r.manager_position}` : ""}</dd>
            </div>
            <div>
              <span className="label">휴대전화</span>
              <dd><a href={`tel:${r.manager_phone}`}>{r.manager_phone}</a></dd>
            </div>
            <div><span className="label">이메일 (아이디)</span><dd>{r.manager_email}</dd></div>
            <div><span className="label">학교 대표번호</span><dd>{r.school_phone || "—"}</dd></div>
            <div><span className="label">통화 가능 시간</span><dd>{r.call_time || "—"}</dd></div>
            {r.school_level !== "middle" && (
              <div><span className="label">공지 수신 동의(선택)</span><dd>{r.notice_consent ? "동의" : "동의 안 함"}</dd></div>
            )}
            <div>
              <span className="label">안내 메일</span>
              <dd>{r.status !== "approved" ? "—" : r.mail_sent ? "발송됨" : `실패: ${r.mail_error}`}</dd>
            </div>
          </div>

          {r.existing_accounts.length > 0 && (
            <div className="notice notice-info" style={{ marginTop: 10 }}>
              이 학교에는 이미 학교 계정이 있습니다:{" "}
              {r.existing_accounts.map((a) => `${a.email}${a.is_active ? "" : " (정지)"}`).join(", ")}.
              담당자가 바뀐 경우가 아니면 기존 계정의 비밀번호를 재설정해 주세요.
            </div>
          )}
          {!r.school_matched && r.status !== "approved" && r.school_level !== "middle" && (
            <LinkSchool request={r} onDone={load} setMsg={setMsg} />
          )}

          <div style={{ display: "flex", gap: 6, marginTop: 10 }}>
            <input className="input" placeholder="통화 내용·반려 사유 메모"
              value={notes[r.id] ?? r.admin_note} maxLength={300}
              onChange={(e) => setNotes({ ...notes, [r.id]: e.target.value })} />
            <button className="btn btn-ghost btn-sm" onClick={() => saveNote(r)}>메모 저장</button>
          </div>
        </div>
      ))}
    </div>
  );
}

/** 목록에 없는 학교로 신청한 건에 실제 학교를 이어 준다. 승인은 학교가
 *  연결되어야만 된다 — 어느 학교의 계정인지 모르는 계정을 만들 수는 없다. */
function LinkSchool({ request, onDone, setMsg }) {
  const [q, setQ] = useState(request.school_name || "");
  const [list, setList] = useState([]);

  const search = async () => {
    try {
      const res = await api.schools({ name: q.trim(), size: 8 });
      setList(res.items || []);
      if ((res.items || []).length === 0) {
        setMsg(errMsg("검색 결과가 없습니다. 학교 관리에서 먼저 등록해 주세요."));
      }
    } catch (e) { setMsg(errMsg(e.message)); }
  };

  const link = async (id) => {
    try {
      await api.linkSchoolRequest(request.id, id);
      setMsg(okMsg("학교를 연결했습니다. 이제 승인할 수 있습니다."));
      onDone();
    } catch (e) { setMsg(errMsg(e.message)); }
  };

  return (
    <div style={{ marginTop: 10, paddingTop: 10, borderTop: "1px solid var(--line)" }}>
      <span className="label">승인하려면 실제 학교를 연결해 주세요</span>
      <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
        <input className="input" value={q} onChange={(e) => setQ(e.target.value)}
          placeholder="학교 이름으로 검색" />
        <button className="btn btn-ghost btn-sm" onClick={search}>검색</button>
      </div>
      {list.length > 0 && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 6 }}>
          {list.map((s) => (
            <button key={s.id} className="btn btn-ghost btn-sm" onClick={() => link(s.id)}>
              {s.name} <small>{s.region}</small>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function AdminPanel() {
  const [tab, setTab] = useState("stats");
  const [subPending, setSubPending] = useState(0);
  const [reqPending, setReqPending] = useState(0);
  const [stats, setStats] = useState(null);
  const [orders, setOrders] = useState([]);
  const [users, setUsers] = useState([]);

  const load = () => {
    api.adminStats().then(setStats);
    api.adminOrders().then(setOrders);
    api.adminUsers().then(setUsers);
  };

  useEffect(() => { load(); }, []);

  if (!stats) return <div className="wrap" style={{ padding: 60 }}><div className="empty"><p>불러오는 중…</p></div></div>;

  const pending = orders.filter((o) => o.status === "pending").length;

  return (
    <div className="wrap" style={{ padding: "34px 0 60px" }}>
      <span className="label">포털 관리</span>
      <h1 style={{ fontSize: 26, margin: "8px 0 20px" }}>관리자 대시보드</h1>

      <div className="tabs">
        <button className={`tab ${tab === "stats" ? "active" : ""}`} onClick={() => setTab("stats")}>현황</button>
        <button className={`tab ${tab === "orders" ? "active" : ""}`} onClick={() => setTab("orders")}>
          플랜 승인 {pending > 0 && <span className="badge" style={{ background: "var(--alert)", color: "#fff", borderColor: "var(--alert)", marginLeft: 4 }}>{pending}</span>}
        </button>
        <button className={`tab ${tab === "subs" ? "active" : ""}`} onClick={() => setTab("subs")}>
          구독 결제 {subPending > 0 && <span className="badge" style={{ background: "var(--alert)", color: "#fff", borderColor: "var(--alert)", marginLeft: 4 }}>{subPending}</span>}
        </button>
        <button className={`tab ${tab === "screq" ? "active" : ""}`} onClick={() => setTab("screq")}>
          학교 계정 신청 {reqPending > 0 && <span className="badge" style={{ background: "var(--alert)", color: "#fff", borderColor: "var(--alert)", marginLeft: 4 }}>{reqPending}</span>}
        </button>
        <button className={`tab ${tab === "accounts" ? "active" : ""}`} onClick={() => setTab("accounts")}>계정 관리</button>
        <button className={`tab ${tab === "schools" ? "active" : ""}`} onClick={() => setTab("schools")}>학교 관리</button>
        <button className={`tab ${tab === "plans" ? "active" : ""}`} onClick={() => setTab("plans")}>플랜 관리</button>
        <button className={`tab ${tab === "articles" ? "active" : ""}`} onClick={() => setTab("articles")}>기사 관리</button>
        <button className={`tab ${tab === "scaccounts" ? "active" : ""}`} onClick={() => setTab("scaccounts")}>학교 계정</button>
        <button className={`tab ${tab === "notices" ? "active" : ""}`} onClick={() => setTab("notices")}>공지 관리</button>
        <button className={`tab ${tab === "vocnotices" ? "active" : ""}`} onClick={() => setTab("vocnotices")}>우리동네직업계고 공지</button>
        <button className={`tab ${tab === "apply" ? "active" : ""}`} onClick={() => setTab("apply")}>신청 관리</button>
        <button className={`tab ${tab === "special" ? "active" : ""}`} onClick={() => setTab("special")}>특강 관리</button>
      </div>

      {tab === "screq" && <SchoolRequestsTab onCount={setReqPending} />}
      {tab === "apply" && <ApplicationsPanel />}
      {tab === "special" && <SpecialTab />}
      {tab === "stats" && <StatsTab stats={stats} />}
      {tab === "orders" && <OrdersTab orders={orders} reload={load} />}
      {tab === "subs" && <SubscriptionTab onCount={setSubPending} />}
      {tab === "accounts" && <AccountsTab users={users} reload={load} />}
      {tab === "schools" && <SchoolManageTab />}
      {tab === "plans" && (
        <div style={{ display: "grid", gap: 16 }}>
          <PlanExpiryPanel />
          <PlanGrantPanel />
          <PlanManageTab />
        </div>
      )}
      {tab === "articles" && <ArticleManageTab />}
      {tab === "notices" && (
        <div style={{ display: "grid", gap: 16 }}>
          <NavVisibilityPanel />
          <FloatingButtonPanel />
          <NoticeManager kind="board" />
        </div>
      )}
      {tab === "vocnotices" && <NoticeManager kind="vocational" />}
      {tab === "scaccounts" && <SchoolAccountsTab />}
    </div>
  );
}


/* ---------------- 구독 결제 (자기소개서 이용권) ---------------- */
/** 카드 결제는 자동 승인되므로, 여기서 손댈 것은 무통장 입금 건이다. */
function SubscriptionTab({ onCount }) {
  // 구독 결제는 기록해로 옮겨졌다. 이곳에서는 안내만 한다.
  useEffect(() => { if (onCount) onCount(0); }, [onCount]);
  return (
    <div className="panel">
      <h3>구독 결제</h3>
      <p style={{ fontSize: 14.5, color: "var(--steel)", lineHeight: 1.85, marginTop: 0 }}>
        자기소개서 이용권 결제는 <b>기록해</b>에서 관리합니다.
        무통장 입금 승인, 요금·계좌 설정, 이용 현황을 그곳에서 확인하실 수 있습니다.
        같은 관리자 계정으로 로그인됩니다.
      </p>
      <a className="btn btn-signal" href="https://diary.ggm.kr/admin"
         target="_blank" rel="noreferrer">
        기록해 관리자로 이동
      </a>
    </div>
  );
}

/* ---------------- 무상 플랜 지급 ---------------- */
/** 관리자가 학교에 체험용 플랜을 직접 준다.
 *  결제 없이 주는 것이라 누가 언제 줬는지 기록이 남는다. */
function PlanGrantPanel() {
  const [keyword, setKeyword] = useState("");
  const [found, setFound] = useState([]);
  const [target, setTarget] = useState(null);
  const [status, setStatus] = useState(null);   // 고른 학교의 현재 플랜 상태
  const [plan, setPlan] = useState("premium");
  const [months, setMonths] = useState(1);
  const [reason, setReason] = useState("");
  const [grants, setGrants] = useState([]);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  const loadGrants = () => api.planGrants().then(setGrants).catch(() => {});
  useEffect(() => { loadGrants(); }, []);

  // 학교를 고르면 지금 어떤 플랜을 쓰는지 먼저 확인한다.
  // 결제 고객에게 상위 플랜을 주면 남은 기간이 사라지므로 미리 막아야 한다.
  useEffect(() => {
    if (!target) { setStatus(null); return; }
    setStatus(null);
    api.schoolPlanStatus(target.id).then(setStatus).catch(() => setStatus(null));
  }, [target]);

  // 결제 중이면 그 등급 이하만 고를 수 있다.
  const PLAN_RANK = { basic: 1, premium: 2, platinum: 3 };
  const allowed = ["basic", "premium", "platinum"].filter(
    (p) => !status || PLAN_RANK[p] <= status.max_rank
  );

  useEffect(() => {
    if (allowed.length > 0 && !allowed.includes(plan)) setPlan(allowed[allowed.length - 1]);
  }, [status]);

  const search = async () => {
    if (!keyword.trim()) return;
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.schools({ name: keyword.trim(), size: 10, include_hidden: true });
      setFound(r.items || []);
      if ((r.items || []).length === 0) setMsg(errMsg("찾은 학교가 없습니다."));
    } catch (e) {
      setMsg(errMsg(e.message));
    } finally {
      setBusy(false);
    }
  };

  const grant = async () => {
    if (!target) return;
    const extend = status && status.days_left > 0;
    if (!confirm(
      `${target.name}에 ${PLAN_LABEL[plan]} ${months}개월을 무상으로 지급할까요?\n\n` +
      (extend
        ? `현재 ${status.expires_at}까지 이용 중이며, 그 뒤에 ${months}개월이 더해집니다.`
        : `기간이 끝나면 자동으로 무료 플랜으로 돌아갑니다.`)
    )) return;
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.grantPlan(target.id, { plan, months, reason: reason.trim() });
      setMsg(okMsg(`${r.school}에 지급했습니다. ${String(r.expires_at).slice(0, 10)}까지 이용합니다.`));
      setTarget(null);
      setStatus(null);
      setFound([]);
      setKeyword("");
      setReason("");
      await loadGrants();
    } catch (e) {
      setMsg(errMsg(e.message));
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (g) => {
    const why = prompt("회수 사유를 적어주세요. 기록에 남습니다.", "체험 종료");
    if (why === null) return;
    setBusy(true);
    try {
      await api.revokePlan(g.school_id, why);
      await loadGrants();
      setMsg(okMsg(`${g.school_name}의 플랜을 회수했습니다.`));
    } catch (e) {
      setMsg(errMsg(e.message));
    } finally {
      setBusy(false);
    }
  };

  const active = grants.filter((g) => g.active);

  return (
    <div className="panel">
      <h3>무상 플랜 지급</h3>
      <p style={{ fontSize: 13, color: "var(--steel)", margin: "0 0 12px", lineHeight: 1.7 }}>
        학교에 체험용으로 플랜을 줍니다. 결제 없이 적용되며,
        <b> 기간이 끝나면 자동으로 무료 플랜으로 돌아갑니다.</b>
        이미 이용 중인 학교는 남은 기간 뒤에 이어 붙습니다.
      </p>

      {msg && <div className={`notice notice-${msg.type}`} style={{ marginBottom: 12 }}>{msg.text}</div>}

      <div className="row" style={{ gap: 6 }}>
        <input className="input" style={{ maxWidth: 220 }} value={keyword}
          placeholder="학교 이름으로 찾기"
          onKeyDown={(e) => e.key === "Enter" && search()}
          onChange={(e) => setKeyword(e.target.value)} />
        <button className="btn btn-sm" onClick={search} disabled={busy}>찾기</button>
      </div>

      {found.length > 0 && (
        <div style={{ marginTop: 10 }}>
          {found.map((s) => (
            <label key={s.id} className="row" style={{ gap: 8, padding: "7px 0",
              borderTop: "1px solid var(--line)", cursor: "pointer", alignItems: "center" }}>
              <input type="radio" name="grant-school" checked={target?.id === s.id}
                onChange={() => setTarget(s)} />
              <span style={{ flex: 1, minWidth: 0 }}>
                <b>{s.name}</b>
                <span className="label" style={{ color: "var(--steel-light)", marginLeft: 6 }}>
                  {s.region} · {s.category}
                </span>
              </span>
            </label>
          ))}
        </div>
      )}

      {target && (
        <div style={{ marginTop: 14, paddingTop: 14, borderTop: "1px solid var(--line)" }}>
          {status && (
            <div className={`notice ${status.is_paid ? "notice-error" : ""}`}
                 style={{ marginBottom: 12, fontSize: 13.5, lineHeight: 1.75 }}>
              현재 <b>{status.plan_label}</b>
              {status.days_left > 0
                ? ` · ${status.expires_at}까지 (${status.days_left}일 남음)`
                : " · 기간 없음"}
              {status.is_free_trial && " · 무료 체험 중"}
              {status.is_paid && (
                <>
                  <br />
                  <b>결제해서 이용 중인 학교입니다.</b> 상위 플랜을 지금 주면
                  남은 {status.days_left}일이 사라지므로,
                  <b> {status.plan_label} 이하로만</b> 기간을 연장할 수 있습니다.
                </>
              )}
            </div>
          )}
          <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
            <span style={{ fontWeight: 700 }}>{target.name}</span>
            <select className="select" style={{ width: "auto" }} value={plan}
              onChange={(e) => setPlan(e.target.value)}>
              {allowed.map((p) => (
                <option key={p} value={p}>{PLAN_LABEL[p]}</option>
              ))}
            </select>
            <select className="select" style={{ width: "auto" }} value={months}
              onChange={(e) => setMonths(Number(e.target.value))}>
              {[1, 2, 3, 6, 12].map((m) => <option key={m} value={m}>{m}개월</option>)}
            </select>
            <input className="input" style={{ maxWidth: 200 }} value={reason}
              placeholder="사유 (예: 영업 체험)"
              onChange={(e) => setReason(e.target.value)} />
            <button className="btn btn-sm" onClick={grant} disabled={busy}>
              {busy ? "처리 중…" : "지급"}
            </button>
          </div>
        </div>
      )}

      <div style={{ marginTop: 18, paddingTop: 14, borderTop: "1px solid var(--line)" }}>
        <h4 style={{ fontSize: 14, margin: "0 0 8px" }}>
          지급 이력 {active.length > 0 && `(이용 중 ${active.length}곳)`}
        </h4>
        {grants.length === 0 ? (
          <p style={{ fontSize: 13.5, color: "var(--steel)" }}>아직 지급한 이력이 없습니다.</p>
        ) : grants.map((g) => (
          <div key={g.id} style={{ display: "flex", gap: 10, alignItems: "flex-start",
            padding: "9px 0", borderTop: "1px solid var(--line)", fontSize: 13.5,
            minWidth: 0, flexWrap: "wrap" }}>
            <div style={{ flex: 1, minWidth: 160 }}>
              <b>{g.school_name}</b> · {g.plan_label} {g.months}개월
              <div style={{ fontSize: 12, color: "var(--steel-light)", marginTop: 2 }}>
                {g.starts_on} ~ {g.expires_on}
                {g.reason ? ` · ${g.reason}` : ""}
                {g.granted_by ? ` · ${g.granted_by}` : ""}
              </div>
            </div>
            {g.revoked_at ? (
              <span className="badge" style={{ flexShrink: 0 }}>회수됨</span>
            ) : g.active ? (
              <>
                <span className="badge badge-done" style={{ flexShrink: 0 }}>이용 중</span>
                <button className="btn btn-sm btn-ghost" disabled={busy}
                  onClick={() => revoke(g)}>회수</button>
              </>
            ) : (
              <span className="badge" style={{ flexShrink: 0 }}>기간 만료</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}


/** 특강 관리 — 영상과 설명회는 화면이 커서 각자 페이지로 둔다.
 *
 * 여기서는 들어가는 문만 낸다. 탭 안에 통째로 끼워 넣으면 화면이 두 겹으로
 * 겹치고(제목·설정줄이 두 번), 주소로 바로 열 수도 없어진다.
 */
function SpecialTab() {
  const cards = [
    { to: "/admin/videos", title: "영상 관리",
      desc: "롱폼을 올리고 그 안에서 숏츠를 올려 붙입니다. 숏츠가 롱폼의 어느 구간에서 나왔는지 소리로 찾습니다." },
    { to: "/admin/briefing", title: "설명회 관리",
      desc: "온라인 직업계고설명회의 강사 프로필과 강의 구성(영상·챕터)을 관리합니다." },
    { to: "/admin/graduate-video", title: "합격생 영상 구성",
      desc: "결제가 확인된 계정에게만 보이는 영상입니다. 챕터마다 재생할 영상을 붙입니다." },
    { to: "/admin/interviews", title: "학교 홍보 인터뷰",
      desc: "학교에 찾아가 찍은 인터뷰를 학교별로 올립니다. 회원만 볼 수 있습니다." },
  ];
  return (
    <>
    <div style={{ display: "grid", gap: 12,
      gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))" }}>
      {cards.map((c) => (
        <Link key={c.to} to={c.to} className="panel"
          style={{ display: "block", color: "inherit", textDecoration: "none" }}>
          <h3 style={{ border: "none", padding: 0, margin: "0 0 6px" }}>{c.title} →</h3>
          <p style={{ fontSize: 13.5, color: "var(--steel)", margin: 0, lineHeight: 1.65 }}>
            {c.desc}
          </p>
        </Link>
      ))}
    </div>
    <VisitStatsPanel />
    </>
  );
}

/** 사이트 방문자 수. 화면 아래에 "오늘 · 누적"으로 나가는 숫자다.
 *  이 기능을 넣기 전의 방문을 더해 두고 싶으면 누적 시작값을 넣는다. */
function VisitStatsPanel() {
  const [d, setD] = useState(null);
  const [base, setBase] = useState("");
  const [msg, setMsg] = useState("");
  useEffect(() => {
    api.adminVisitStats().then((r) => { setD(r); setBase(String(r.base)); }).catch(() => {});
  }, []);
  if (!d) return null;
  const save = async () => {
    try {
      const r = await api.saveVisitBase(Math.max(parseInt(base, 10) || 0, 0));
      setD(r);
      setMsg("저장했습니다.");
    } catch (e) {
      setMsg(e.message);
    }
  };
  return (
    <div className="panel" style={{ marginTop: 16 }}>
      <h3 style={{ border: "none", padding: 0, margin: "0 0 6px" }}>방문자 수</h3>
      <p style={{ fontSize: 13.5, color: "var(--steel)", margin: "0 0 10px", lineHeight: 1.65 }}>
        사이트 아래에 보이는 숫자입니다. 오늘 <b>{d.today.toLocaleString()}</b>명 ·
        누적 <b>{d.total.toLocaleString()}</b>명 (브라우저당 하루 1회, 봇 제외)
      </p>
      {d.days.length > 0 && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", fontSize: 12, color: "var(--steel)", marginBottom: 10 }}>
          {d.days.slice(0, 14).map((x) => (
            <span key={x.day} className="badge">{x.day.slice(5).replace("-", "/")} {x.count}</span>
          ))}
        </div>
      )}
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <label className="label" htmlFor="visit-base">누적 시작값</label>
        <input id="visit-base" className="input" type="number" min={0} value={base}
          onChange={(e) => setBase(e.target.value)} style={{ width: 140 }} />
        <button className="btn btn-sm" onClick={save}>저장</button>
        {msg && <span style={{ fontSize: 12.5, color: "var(--steel)" }}>{msg}</span>}
      </div>
    </div>
  );
}

/** 학교 플랜이 며칠 남았는지.
 *
 * 만료일만 적어 두면 관리자가 오늘 날짜를 세어야 한다. 며칠 남았는지를
 * 같이 보여줘야 "곧 끝나겠네"가 그 자리에서 읽힌다.
 *
 * 무료 플랜이나 기간이 없으면 아무것도 안 그린다.
 */
function PlanExpiry({ days, at }) {
  if (days === null || days === undefined) return null;
  const over = days < 0;
  const soon = days <= 30;
  const bg = over ? "var(--color-danger)"
    : soon ? "var(--color-attention)" : "var(--steel)";
  const text = over ? `만료 ${-days}일 지남`
    : days === 0 ? "오늘 만료" : `만료 D-${days}일`;
  return (
    <span className="badge" style={{ background: bg, color: "#fff", borderColor: bg }}
      title={at ? `${String(at).slice(0, 10)}까지` : ""}>
      {text}
    </span>
  );
}

/** 유료 플랜이 걸린 학교를 **만료가 가까운 순서로** 늘어놓는다.
 *
 * 학교 하나를 검색해 눌러야 만료일이 보이면, 정작 알아야 할 "이번 달에
 * 끝나는 곳이 어디인가"를 알 수 없다. 끝나는 순서로 세워 두면 그게 보인다.
 *
 * 끝난 곳은 **아래에 따로** 모은다. 돌고 있는 것과 섞으면 "지금 챙길 곳"이
 * 흐려진다. 연장을 놓친 학교를 나중에라도 찾을 수 있게, 서버가 무료로
 * 되돌릴 때 끝난 날과 어떤 플랜이었는지를 남겨 둔다.
 */
function PlanExpiryPanel() {
  const [data, setData] = useState(null);
  const [soonOnly, setSoonOnly] = useState(false);

  useEffect(() => {
    api.planExpiry(soonOnly ? 30 : 0).then(setData).catch(() => setData(null));
  }, [soonOnly]);

  if (!data) return null;
  const items = data.items || [];

  return (
    <div className="panel">
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
        <h3 style={{ margin: 0 }}>플랜 만료 현황</h3>
        {data.expiring_30 > 0 && (
          <span className="badge" style={{
            background: "var(--color-attention)", color: "#fff",
            borderColor: "var(--color-attention)",
          }}>
            30일 안쪽 {data.expiring_30}곳
          </span>
        )}
        {data.expired_count > 0 && (
          <span className="badge" style={{
            background: "var(--color-danger)", color: "#fff",
            borderColor: "var(--color-danger)",
          }}>
            끝난 곳 {data.expired_count}곳
          </span>
        )}
        <span style={{ flex: 1 }} />
        <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13.5 }}>
          <input type="checkbox" checked={soonOnly}
            onChange={(e) => setSoonOnly(e.target.checked)} />
          곧 끝나는 곳만
        </label>
      </div>

      <p style={{ fontSize: 12.5, color: "var(--steel)", margin: "8px 0 0", lineHeight: 1.7 }}>
        만료일이 지나면 자동으로 무료 플랜이 되고 <b>아래 “끝난 곳”</b>으로 내려갑니다.
      </p>

      {items.length === 0 ? (
        <p style={{ fontSize: 14, color: "var(--steel)", margin: "12px 0 0" }}>
          {soonOnly ? "30일 안쪽에 끝나는 학교가 없습니다."
            : "기간이 걸린 유료 플랜 학교가 없습니다."}
        </p>
      ) : (
        <div style={{ overflowX: "auto", marginTop: 12 }}>
          <table className="table">
            <thead>
              <tr>
                <th>학교</th><th>지역</th><th>플랜</th><th>만료일</th><th>남은 기간</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.school_id}>
                  <td>
                    {it.school_name}
                    {it.paused && (
                      <span className="badge" style={{ marginLeft: 6 }}>정지</span>
                    )}
                  </td>
                  <td>{it.region || "—"}</td>
                  <td>{it.plan_label}</td>
                  <td>{String(it.expires_at).slice(0, 10)}</td>
                  <td><PlanExpiry days={it.days_left} at={it.expires_at} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {(data.expired || []).length > 0 && (
        <div style={{ marginTop: 22, paddingTop: 16, borderTop: "1px solid var(--line)" }}>
          <h4 style={{ margin: "0 0 4px", fontSize: 15 }}>끝난 곳</h4>
          <p style={{ fontSize: 12.5, color: "var(--steel)", margin: "0 0 10px", lineHeight: 1.7 }}>
            기간이 지나 무료 플랜으로 돌아간 학교입니다. 최근에 끝난 순서입니다.
          </p>
          <div style={{ overflowX: "auto" }}>
            <table className="table">
              <thead>
                <tr><th>학교</th><th>지역</th><th>플랜</th><th>끝난 날</th><th>지난 기간</th></tr>
              </thead>
              <tbody>
                {data.expired.map((it) => (
                  <tr key={it.school_id}>
                    <td>{it.school_name}</td>
                    <td>{it.region || "—"}</td>
                    <td>{it.plan_label}</td>
                    <td>{String(it.expired_at).slice(0, 10)}</td>
                    <td>
                      <span className="badge" style={{
                        background: "var(--color-danger)", color: "#fff",
                        borderColor: "var(--color-danger)",
                      }}>
                        {it.days_ago === 0 ? "오늘" : `${it.days_ago}일 지남`}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
