import { useEffect, useState } from "react";
import { api } from "../api";

const TABS = [
  ["stats", "현황"],
  ["seats", "학교 이용권"],
  ["unmatched", "미매칭 입금"],
  ["settings", "설정"],
  ["logs", "활동 기록"],
];

export default function Admin() {
  const [tab, setTab] = useState("stats");
  const [pending, setPending] = useState(0);
  const [openUnmatched, setOpenUnmatched] = useState(0);

  // 밀린 미매칭 건이 있으면 탭에 숫자를 띄운다. 그냥 두면 잊힌다.
  useEffect(() => {
    api.unmatchedDeposits("open")
      .then((rows) => setOpenUnmatched(rows.length))
      .catch(() => {});
  }, [tab]);

  return (
    <div className="wrap page" style={{ maxWidth: 860 }}>
      <span className="label">기록해 관리</span>
      <h1>관리자</h1>

      <div className="row" style={{ gap: 6, margin: "14px 0 6px" }}>
        {TABS.map(([k, label]) => (
          <button key={k} className={`btn btn-sm ${tab === k ? "" : "btn-ghost"}`}
            onClick={() => setTab(k)}>
            {label}
            {k === "unmatched" && openUnmatched > 0 && (
              <span className="badge" style={{ marginLeft: 6, background: "var(--alert)",
                color: "#fff" }}>{openUnmatched}</span>
            )}
          </button>
        ))}
      </div>

      {tab === "stats" && <StatsTab />}
      {tab === "seats" && <SeatOrdersTab />}
      {tab === "unmatched" && <UnmatchedTab />}
      {tab === "settings" && <SettingsTab />}
      {tab === "logs" && <LogsTab />}
    </div>
  );
}

/* ---------------- 현황 ---------------- */
function StatsTab() {
  const [d, setD] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.adminStats().then(setD).catch((e) => setError(e.message));
  }, []);

  if (error) return <div className="notice notice-error">{error}</div>;
  if (!d) return <p>불러오는 중…</p>;

  // 값이 없을 수도 있다. 숫자가 아니면 0 으로 본다.
  const n = (v) => (typeof v === "number" ? v : 0);
  const cards = [
    ["회원", n(d.users), "명"],
    ["학생", n(d.students), "명"],
    ["작성된 일지", n(d.journals), "건"],
    ["최근 30일 일지", n(d.journals_30d), "건"],
    ["제출된 일지", n(d.submitted), "건"],
    ["자기소개서", n(d.cover_letters), "건"],
    ["이용권 쓰는 학교", n(d.seat_schools), "곳"],
    ["구입 좌석", n(d.seats_total), "석"],
    ["나눠준 좌석", n(d.seats_used), "석"],
    // 결제 주체가 학교로 바뀌기 전에 개인이 산 것. 기간이 끝나면 사라진다.
    ...(d.subscribers ? [["예전 개인 구독", n(d.subscribers), "명"]] : []),
    ["최근 30일 매출", n(d.revenue_30d).toLocaleString(), "원"],
  ];

  return (
    <>
      {n(d.pending_orders) > 0 && (
        <div className="notice" style={{ marginBottom: 12 }}>
          입금 확인을 기다리는 신청이 <b>{d.pending_orders}건</b> 있습니다.
          구독 결제 탭에서 처리해주세요.
        </div>
      )}
      <div className="panel">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
          gap: 14 }}>
          {cards.map(([label, value, unit]) => (
            <div key={label}>
              <div className="label">{label}</div>
              <div style={{ fontSize: 24, fontWeight: 800, marginTop: 2 }}>
                {value}<span style={{ fontSize: 14, fontWeight: 600, marginLeft: 2 }}>{unit}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

/* ---------------- 설정 ---------------- */
function SettingsTab() {
  const [form, setForm] = useState(null);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.adminSettings().then(setForm).catch((e) => setMsg({ type: "error", text: e.message }));
  }, []);

  if (!form) return <p>불러오는 중…</p>;

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const save = async () => {
    setBusy(true);
    setMsg(null);
    try {
      await api.saveAdminSettings(form);
      setMsg({ type: "ok", text: "저장했습니다." });
    } catch (e) {
      setMsg({ type: "error", text: e.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel">
      <h3>설정</h3>
      {msg && <div className={`notice notice-${msg.type}`} style={{ marginBottom: 12 }}>{msg.text}</div>}

      {/* 결제 방식. 지금 실제로 무엇으로 받고 있는지 함께 보여준다.
          설정과 실제가 다를 수 있어서(토스 키가 없는데 카드 선택 등) 헷갈리기 쉽다. */}
      <label className="field">
        <span className="label">결제 방식</span>
        <select className="input" value={form.payment_method || "auto"}
          onChange={(e) => setForm({ ...form, payment_method: e.target.value })}>
          <option value="auto">자동 — 카드 설정이 있으면 카드, 없으면 무통장</option>
          <option value="bank">무통장 입금만 받기</option>
          <option value="toss">카드 결제(토스)만 받기</option>
        </select>
      </label>

      <p style={{ fontSize: 13, color: "var(--steel)", margin: "-4px 0 14px", lineHeight: 1.7 }}>
        지금 받는 방식: <b>{form.effective === "toss" ? "카드 결제(토스)" : "무통장 입금"}</b>
        {form.payment_method === "toss" && !form.toss_configured && (
          <><br />
          <span style={{ color: "var(--danger, #c02b2b)" }}>
            카드만 받도록 되어 있으나 토스 키가 설정되어 있지 않습니다.
            이 상태로는 결제를 받을 수 없습니다.
          </span></>
        )}
        {form.payment_method === "bank" && form.toss_configured && (
          <><br />토스 키는 그대로 있습니다. 예전에 카드로 결제한 건의 환불은 계속 됩니다.</>
        )}
        {!form.bank_ready && form.effective !== "toss" && (
          <><br />
          <span style={{ color: "var(--danger, #c02b2b)" }}>
            입금 계좌가 비어 있어 결제를 받을 수 없습니다. 아래에 입력해주세요.
          </span></>
        )}
      </p>

      <div className="field">
        <span className="label">결제 방식</span>
        <div style={{ display: "grid", gap: 6, marginTop: 4 }}>
          {[
            ["auto", "자동", "카드 키가 있으면 카드로, 없으면 무통장으로 받습니다."],
            ["bank", "무통장 입금만", "카드 키가 있어도 쓰지 않습니다. 계좌로만 받습니다."],
            ["toss", "카드만", "카드로만 받습니다. 키가 없으면 결제가 막힙니다."],
          ].map(([v, label, hint]) => (
            <label key={v} className="row"
              style={{ alignItems: "flex-start", gap: 8, cursor: "pointer" }}>
              <input type="radio" name="paymethod" value={v} style={{ marginTop: 4 }}
                checked={(form.payment_method || "auto") === v}
                onChange={() => setForm({ ...form, payment_method: v })} />
              <span style={{ fontSize: 14, lineHeight: 1.6 }}>
                <b>{label}</b>
                <span className="meta" style={{ display: "block" }}>{hint}</span>
              </span>
            </label>
          ))}
        </div>

        {/* 지금 실제로 무엇으로 받고 있는지. 설정값과 실제가 다를 수 있어 따로 알려준다. */}
        <p className="meta" style={{ marginTop: 8 }}>
          지금은 <b>{form.effective === "toss" ? "카드 결제" : "무통장 입금"}</b>으로 받고 있습니다.
          {!form.toss_configured && " (카드 키가 설정되어 있지 않습니다)"}
          {!form.bank_ready && " (계좌 정보가 비어 있습니다)"}
        </p>
      </div>

      <label className="field">
        <span className="label">학교 이용권 · 1명당 금액(원)</span>
        <input className="input" type="number" min="0"
          value={form.seat_price ?? 15000} onChange={set("seat_price")} />
        <span className="meta" style={{ display: "block", marginTop: 4 }}>
          학교가 신청할 때 이 금액에 인원수를 곱합니다. 이미 승인된 신청에는 영향이 없습니다.
        </span>
      </label>

      <DiscountBox form={form} setForm={setForm} />

      <ResetBox />

      <label className="field">
        <span className="label">(예전) 개인 구독 월 요금(원)</span>
        <input className="input" inputMode="numeric" value={form.subscription_price}
          onChange={(e) => setForm({ ...form,
            subscription_price: e.target.value.replace(/\D/g, "") })} />
      </label>

      <div style={{ borderTop: "1px solid var(--line)", paddingTop: 14, marginTop: 4 }}>
        <p style={{ fontSize: 13, color: "var(--steel)", margin: "0 0 12px", lineHeight: 1.7 }}>
          무통장 입금 계좌입니다. 결제 화면에 이 정보와 입금 코드가 함께 안내됩니다.
          <b> 비어 있으면 이용자에게 입금할 곳을 안내하지 못합니다.</b>
          {" "}여러 개를 등록하면 신청이 몰릴 때 나눠서 안내합니다.
        </p>
        <AccountList value={form.bank_accounts || []}
          onChange={(list) => setForm({ ...form, bank_accounts: list })} />

        <label className="row" style={{ gap: 8, alignItems: "flex-start",
                                        marginTop: 14, cursor: "pointer" }}>
          <input type="checkbox" style={{ marginTop: 4 }}
            checked={(form.deposit_auto_approve || "off") === "on"}
            onChange={(e) => setForm({ ...form,
              deposit_auto_approve: e.target.checked ? "on" : "off" })} />
          <span style={{ fontSize: 14, lineHeight: 1.6 }}>
            <b>통장 대조에서 자동 승인 허용</b>
            <span className="meta" style={{ display: "block" }}>
              금액이 유일하게 맞고 이름·계좌가 모두 일치하는 건만 자동으로 승인합니다.
              조금이라도 어긋나면 미매칭함으로 갑니다. 익숙해진 뒤에 켜시길 권합니다.
            </span>
          </span>
        </label>

        <label className="field" style={{ marginTop: 14 }}>
          <span className="label">입금 안내 문구 (선택)</span>
          <input className="input" value={form.payment_note || ""} onChange={set("payment_note")}
            placeholder="예: 입금 확인은 평일 오전에 일괄 처리합니다" />
        </label>

        <details style={{ marginTop: 12 }}>
          <summary className="meta" style={{ cursor: "pointer" }}>
            예전 단일 계좌 칸 (위 목록이 비어 있을 때만 쓰입니다)
          </summary>
          {[["bank_name", "은행"], ["bank_account", "계좌번호"],
            ["bank_holder", "예금주"]].map(([k, label]) => (
            <label className="field" key={k}>
              <span className="label">{label}</span>
              <input className="input" value={form[k] || ""} onChange={set(k)} />
            </label>
          ))}
        </details>
      </div>

      <button className="btn btn-primary" onClick={save} disabled={busy}>
        {busy ? "저장 중…" : "저장"}
      </button>
    </div>
  );
}

/* ---------------- 활동 기록 ---------------- */
function LogsTab() {
  const [logs, setLogs] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.auditLogs({ limit: 200 }).then(setLogs).catch((e) => setError(e.message));
  }, []);

  if (error) return <div className="notice notice-error">{error}</div>;
  if (!logs) return <p>불러오는 중…</p>;

  return (
    <div className="panel">
      <h3>활동 기록</h3>
      <p style={{ fontSize: 13, color: "var(--steel)", margin: "0 0 12px", lineHeight: 1.7 }}>
        담당 교사가 아닌 계정이 학생 기록을 열람하거나, 결제·설정을 바꾼 이력입니다.
        「개인정보의 안전성 확보조치 기준」 제8조에 따라 1년간 보관합니다.
      </p>

      {logs.length === 0 ? (
        <p style={{ color: "var(--steel)", fontSize: 14 }}>아직 기록이 없습니다.</p>
      ) : logs.map((l) => (
        <div key={l.id} style={{ padding: "9px 0", borderTop: "1px solid var(--line)",
          fontSize: 13.5, lineHeight: 1.6 }}>
          <span className="badge">{l.action}</span>{" "}
          <b>{l.actor_email || "(삭제된 계정)"}</b>
          <span style={{ color: "var(--steel-light)" }}> · {l.actor_role}</span>
          {l.detail && <div style={{ color: "var(--ink-soft)", marginTop: 2 }}>{l.detail}</div>}
          <div style={{ fontSize: 12, color: "var(--steel-light)", marginTop: 2 }}>
            {String(l.created_at).replace("T", " ").slice(0, 16)}
            {l.ip ? ` · ${l.ip}` : ""}
          </div>
        </div>
      ))}
    </div>
  );
}

/* ---------------- 입금 내역 대조 ----------------
   PG 를 쓰지 않으면 입금 확인을 사람이 해야 한다. 건수가 늘면 이게 제일 지친다.
   통장 거래내역을 복사해 붙여넣으면 대기 주문과 맞춰준다.
   자동으로 승인하지는 않는다. 돈이 걸린 일은 사람이 한 번 보고 눌러야 한다. */
function DepositMatcher({ onApproved }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [accounts, setAccounts] = useState([]);
  const [bankKey, setBankKey] = useState("");
  const [autoOn, setAutoOn] = useState(false);
  const [useAuto, setUseAuto] = useState(false);
  const [password, setPassword] = useState("");
  // 계좌마다 파일을 따로 뽑는 경우가 있어 여러 개를 함께 받는다.
  // [{ name, bankKey, deposits, columns, skipped, headerRow, error }]
  const [files, setFiles] = useState([]);
  const [pendingFiles, setPendingFiles] = useState([]);  // 아직 못 읽은 파일
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState([]);

  // 어느 계좌 내역인지 고를 수 있게 목록을 받아둔다.
  useEffect(() => {
    if (!open) return;
    api.adminSettings()
      .then((st) => {
        const list = st.bank_accounts || [];
        setAccounts(list);
        setBankKey((k) => k || list[0]?.key || "");
        setAutoOn(st.deposit_auto_approve === "on");
      })
      .catch(() => {});
  }, [open]);

  // 고른 파일들을 차례로 읽는다. 하나가 실패해도 나머지는 계속 읽는다.
  const upload = async (list, pw) => {
    const targets = list && list.length ? list : pendingFiles;
    if (!targets.length) return;
    setBusy(true);
    setError("");
    setResult(null);

    const read = [];
    const failed = [];
    for (const f of targets) {
      try {
        const r = await api.parseStatement(f, pw ?? password);
        read.push({
          name: f.name,
          // 기본 계좌는 지금 고른 것. 파일마다 바꿀 수 있다.
          bankKey: bankKey,
          deposits: r.deposits,
          columns: r.columns,
          skipped: r.skipped,
          headerRow: r.header_row,
          text: r.text,
        });
      } catch (e) {
        failed.push({ file: f, message: e.message });
      }
    }

    setFiles((prev) => [...prev, ...read]);
    setPendingFiles(failed.map((x) => x.file));
    if (failed.length) {
      setError(failed.map((x) => `${x.file.name}: ${x.message}`).join("\n"));
    }
    setBusy(false);
  };

  const totalDeposits = files.reduce((a, f) => a + f.deposits.length, 0);

  const run = async () => {
    setBusy(true);
    setError("");
    setDone([]);
    try {
      // 파일로 읽었으면 금액·이름이 이미 나뉘어 있다. 그대로 보내면
      // 글자로 되돌렸다가 다시 읽는 과정에서 생기는 어긋남이 없다.
      // 줄마다 계좌를 달아 두어
      // 서로 다른 은행의 내역을 한 번에 맞춰볼 수 있다.
      const fromFiles = files.flatMap((f) =>
        f.deposits.map((d) => ({
          amount: d.amount, name: d.name || "", line: d.line || "",
          bank_key: f.bankKey || "",
        }))
      );
      setResult(await api.matchDeposits({
        deposits: fromFiles.length ? fromFiles : undefined,
        // 파일이 있으면 붙여넣기 칸은 보지 않는다.
        text: fromFiles.length ? "" : text,
        bank_key: bankKey,
        auto_approve: useAuto,
      }));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  // 통장 대조로 알 수 있는 것은 '돈이 들어왔다'까지다. 인원이 맞는지는
  // 사람이 봐야 하므로, 여기서는 입금 확인만 하고 승인은 학교 이용권
  // 화면으로 넘긴다.
  const approve = async (m) => {
    setBusy(true);
    setError("");
    try {
      await api.confirmSeatDeposit(m.order_id);
      setDone((d) => [...d, m.order_id]);
      onApproved?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const rest = result?.matched.filter((m) => !done.includes(m.order_id)) || [];

  if (!open) {
    return (
      <div style={{ marginBottom: 14 }}>
        <button className="btn btn-sm" onClick={() => setOpen(true)}>
          통장 내역으로 한 번에 확인하기
        </button>
      </div>
    );
  }

  return (
    <div style={{
      border: "1px solid var(--line)", borderRadius: 10,
      padding: 14, marginBottom: 16, background: "var(--raised, #f7f5f2)",
    }}>
      <div className="row" style={{ alignItems: "baseline" }}>
        <b>통장 내역으로 확인하기</b>
        <div className="spacer" />
        <button className="btn btn-sm btn-ghost" onClick={() => setOpen(false)}>닫기</button>
      </div>

      <p className="meta" style={{ margin: "6px 0 10px", lineHeight: 1.7 }}>
        거래내역 파일을 올리거나, 인터넷뱅킹 화면에서 복사해 붙여넣으세요.
        금액과 입금자명으로 대기 중인 주문을 찾아드립니다.{" "}
        <b>승인은 확인하신 뒤 직접 누르셔야 합니다.</b>
      </p>

      {/* 은행에서 받은 파일을 그대로 올린다. 열어서 복사하는 단계가 빠진다.
          계좌마다 파일을 따로 뽑는 경우가 있어 여러 개를 한 번에 받는다. */}
      <div className="field" style={{ marginBottom: 10 }}>
        <span className="label">거래내역 파일 올리기</span>
        <p className="meta" style={{ margin: "0 0 6px", lineHeight: 1.6 }}>
          엑셀(.xlsx)과 csv 를 받습니다. <b>여러 개를 한 번에 고를 수 있습니다.</b>
          {" "}계좌나 은행이 다르면 각각 뽑아서 함께 올리세요.
          카카오뱅크처럼 비밀번호가 걸린 파일이면 비밀번호를 먼저 넣어주세요.
        </p>

        {/* 비밀번호를 파일보다 위에 둔다. 파일을 고르는 순간 읽기 때문에,
            아래에 있으면 비어 있는 채로 읽으려다 실패한다. */}
        <input className="input" type="password" value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="파일 비밀번호 (걸려 있는 경우만)" />

        <input type="file" accept=".xlsx,.xls,.csv,.txt" multiple style={{ marginTop: 8 }}
          onChange={(e) => {
            const list = Array.from(e.target.files || []);
            if (list.length) upload(list);
            e.target.value = "";   // 같은 파일을 다시 고를 수 있게 비운다
          }}
          disabled={busy} />

        {pendingFiles.length > 0 && (
          <button className="btn btn-sm" style={{ marginTop: 8 }} disabled={busy}
            onClick={() => upload(pendingFiles)}>
            {busy ? "읽는 중…" : `비밀번호 넣고 ${pendingFiles.length}개 다시 읽기`}
          </button>
        )}
      </div>

      {files.length > 0 && (
        <div style={{ marginBottom: 10 }}>
          {files.map((f, fi) => (
            <div key={fi} style={{ border: "1px solid var(--line)", borderRadius: 8,
                                   padding: 10, marginBottom: 8, background: "#fff" }}>
              <div className="row" style={{ gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
                <b style={{ fontSize: 13 }}>{f.name}</b>
                <span className="meta">입금 {f.deposits.length}건</span>
                {f.skipped > 0 && <span className="meta">· 출금 {f.skipped}건 제외</span>}
                <div className="spacer" />
                <button className="btn btn-sm btn-ghost"
                  onClick={() => setFiles(files.filter((_, i) => i !== fi))}>
                  빼기
                </button>
              </div>

              {accounts.length > 1 && (
                <div className="row" style={{ gap: 6, alignItems: "center", marginTop: 6 }}>
                  <span className="meta">어느 계좌</span>
                  <select className="input" value={f.bankKey} style={{ maxWidth: 260 }}
                    onChange={(e) => setFiles(files.map((x, i) =>
                      i === fi ? { ...x, bankKey: e.target.value } : x))}>
                    {accounts.map((a) => (
                      <option key={a.key} value={a.key}>
                        {a.bank_name} {a.bank_account}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <p className="meta" style={{ margin: "6px 0 0", lineHeight: 1.6 }}>
                머리글 {f.headerRow}행 · 읽은 열 — {Object.entries(f.columns)
                  .map(([k, v]) => `${{ in_amount: "입금액", out_amount: "출금액",
                    amount: "금액", name: "이름", date: "일시", type: "구분" }[k] || k}: ${v}`)
                  .join(" / ")}
              </p>

              {f.deposits.length > 0 && (
                <div style={{ maxHeight: 120, overflowY: "auto", fontSize: 13, marginTop: 6 }}>
                  {f.deposits.slice(0, 10).map((d, i) => (
                    <div key={i} className="row" style={{ gap: 8, padding: "2px 0" }}>
                      <span className="meta" style={{ minWidth: 110 }}>{d.when}</span>
                      <b>{d.amount.toLocaleString()}원</b>
                      <span>{d.name}</span>
                    </div>
                  ))}
                  {f.deposits.length > 10 && (
                    <p className="meta">외 {f.deposits.length - 10}건</p>
                  )}
                </div>
              )}
            </div>
          ))}

          <p className="meta">
            모두 {totalDeposits}건을 읽었습니다. 금액과 이름이 제대로 읽혔는지 확인하신 뒤
            아래 <b>맞춰보기</b>를 눌러주세요.
          </p>
        </div>
      )}

      {accounts.length > 1 && (
        <div className="field" style={{ marginBottom: 8 }}>
          <span className="label">어느 계좌의 내역인가요</span>
          <select className="input" value={bankKey} onChange={(e) => setBankKey(e.target.value)}>
            {accounts.map((a) => (
              <option key={a.key} value={a.key}>
                {a.bank_name} {a.bank_account}
              </option>
            ))}
          </select>
        </div>
      )}

      {autoOn && (
        <label className="row" style={{ gap: 8, marginBottom: 8, cursor: "pointer" }}>
          <input type="checkbox" checked={useAuto} onChange={(e) => setUseAuto(e.target.checked)} />
          <span style={{ fontSize: 13.5 }}>
            의심스러운 구석이 없는 건은 바로 승인하기
          </span>
        </label>
      )}

      <span className="label" style={{ display: "block", marginBottom: 4 }}>
        {files.length ? "직접 붙여넣기 (파일을 올렸으면 비워두세요)" : "또는 직접 붙여넣기"}
      </span>
      <textarea value={text} onChange={(e) => setText(e.target.value)} rows={5}
        placeholder={"2026-08-20 14:22  입금  5,900  이순신  잔액 1,204,300\n2026-08-20 15:01  입금  17,700  박보검  잔액 1,222,000"}
        style={{ width: "100%", fontSize: 13, fontFamily: "ui-monospace, Menlo, monospace" }} />

      {error && <div className="notice notice-error" style={{ marginTop: 8 }}>{error}</div>}

      <button className="btn btn-sm btn-primary" onClick={run}
        disabled={busy || (!text.trim() && files.length === 0)} style={{ marginTop: 8 }}>
        {busy ? "찾는 중…" : "맞춰보기"}
      </button>

      {result && (
        <div style={{ marginTop: 14 }}>
          {(result.approved?.length || 0) > 0 && (
            <div className="notice notice-ok" style={{ marginBottom: 10 }}>
              {result.approved.length}건을 자동으로 승인했습니다.
            </div>
          )}

          {rest.length === 0 && done.length === 0 && (result.approved?.length || 0) === 0 && (
            <p className="meta">맞는 주문을 찾지 못했습니다.</p>
          )}

          {rest.map((m) => (
            <div key={m.order_id} className="row"
              style={{ gap: 8, padding: "8px 0", borderTop: "1px solid var(--line)",
                       alignItems: "baseline", flexWrap: "wrap" }}>
              <b>{m.amount.toLocaleString()}원</b>
              <span className="meta">{m.user_email}</span>
              <span className="badge">{m.deposit_code}</span>
              {m.other_bank && (
                <span className="badge" style={{ background: "#e7f0f8", color: "#20618f" }}>
                  안내한 계좌와 다름
                </span>
              )}
              {m.name_mismatch && (
                <span className="badge" style={{ background: "#fdf3d7", color: "#9a6700" }}>
                  이름 다름 · 신청 {m.depositor_name} / 입금 {m.statement_name}
                </span>
              )}
              <div className="spacer" />
              <button className="btn btn-sm btn-primary" disabled={busy}
                onClick={() => approve(m)}>
                승인
              </button>
            </div>
          ))}

          {done.length > 0 && (
            <p className="meta" style={{ marginTop: 8 }}>{done.length}건을 승인했습니다.</p>
          )}

          {result.still_pending.length > 0 && (
            <details style={{ marginTop: 8 }}>
              <summary className="meta" style={{ cursor: "pointer" }}>
                아직 입금이 안 들어온 주문 {result.still_pending.length}건
              </summary>
              {result.still_pending.map((sp) => (
                <div key={sp.order_id} className="meta" style={{ padding: "6px 0" }}>
                  {sp.amount.toLocaleString()}원 · {sp.user_email}
                  {sp.depositor_name && ` · 입금자 ${sp.depositor_name}`}
                </div>
              ))}
            </details>
          )}
        </div>
      )}
    </div>
  );
}

/* ---------------- 미매칭 입금함 ----------------
   어느 주문에도 붙지 않은 입금을 계좌 구분 없이 한곳에 모은다.
   안내한 계좌가 아닌 곳으로 들어온 것, 금액이 틀린 것, 모르는 입금이 여기로 온다. */
function UnmatchedTab() {
  const [rows, setRows] = useState(null);
  const [orders, setOrders] = useState([]);
  const [status, setStatus] = useState("open");
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(0);
  const [picking, setPicking] = useState(null);

  const load = () => {
    api.unmatchedDeposits(status).then(setRows)
      .catch((e) => setMsg({ type: "error", text: e.message }));
    // 연결 대상은 학교 이용권 신청이다. 개인 결제는 없어졌다.
    api.adminSeatOrders("pending").then((r) => setOrders(Array.isArray(r) ? r : []))
      .catch(() => {});
  };

  useEffect(() => { load(); }, [status]);

  // 미매칭함에 쌓인 것들을 지금 주문과 다시 맞춰본다.
  // 자동 승인이 켜져 있으면 승인까지, 아니면 '이 주문 같습니다'만 알려준다.
  const rematch = async () => {
    setBusy(-1);
    setMsg(null);
    try {
      const r = await api.rematchUnmatched(true);
      const approved = r.linked.filter((x) => x.approved).length;
      setMsg({
        type: "ok",
        text: r.linked.length === 0
          ? `${r.checked}건을 다시 봤지만 붙는 주문이 없었습니다.`
          : approved > 0
            ? `${approved}건을 승인했습니다.`
            : `${r.linked.length}건에서 맞는 주문을 찾았습니다. 확인하고 연결해주세요.`,
      });
      load();
    } catch (e) {
      setMsg({ type: "error", text: e.message });
    } finally {
      setBusy(0);
    }
  };

  const act = async (item, body) => {
    setBusy(item.id);
    setMsg(null);
    try {
      await api.resolveUnmatched(item.id, body);
      setPicking(null);
      load();
      setMsg({ type: "ok", text: body.action === "link" ? "주문에 연결하고 승인했습니다." : "처리했습니다." });
    } catch (e) {
      setMsg({ type: "error", text: e.message });
    } finally {
      setBusy(0);
    }
  };

  return (
    <div className="panel">
      <h3>미매칭 입금</h3>
      <p style={{ fontSize: 13, color: "var(--steel)", margin: "0 0 12px", lineHeight: 1.7 }}>
        통장 내역 중 어느 주문에도 붙지 않은 입금입니다. <b>계좌를 가리지 않고 모두 모입니다.</b>
        {" "}안내한 계좌가 아닌 곳으로 들어왔거나, 같은 금액의 주문이 여럿이라 고를 수 없었던
        건들입니다.
      </p>

      <div className="row" style={{ gap: 8, marginBottom: 10, alignItems: "center" }}>
        <button className="btn btn-sm btn-primary" disabled={busy === -1}
          onClick={rematch}>
          {busy === -1 ? "다시 맞춰보는 중…" : "다시 맞춰보기"}
        </button>
        <span className="meta" style={{ lineHeight: 1.6 }}>
          그동안 새 주문이 생겼거나 같은 금액이 정리됐으면 이제 붙을 수 있습니다.
        </span>
      </div>

      <div className="row" style={{ gap: 6, marginBottom: 12 }}>
        {[["open", "확인 필요"], ["linked", "연결됨"], ["ignored", "치움"], ["all", "전체"]]
          .map(([k, label]) => (
            <button key={k} className={`btn btn-sm ${status === k ? "" : "btn-ghost"}`}
              onClick={() => setStatus(k)}>{label}</button>
          ))}
      </div>

      {msg && <div className={`notice notice-${msg.type}`} style={{ marginBottom: 12 }}>{msg.text}</div>}

      {!rows ? <p>불러오는 중…</p> : rows.length === 0 ? (
        <p className="meta">
          {status === "open" ? "확인이 필요한 입금이 없습니다." : "해당하는 내역이 없습니다."}
        </p>
      ) : rows.map((r) => (
        <div key={r.id} style={{ padding: "10px 0", borderTop: "1px solid var(--line)" }}>
          <div className="row" style={{ gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
            <b>{r.amount.toLocaleString()}원</b>
            {r.name && <span>{r.name}</span>}
            {r.bank_label && <span className="badge">{r.bank_label}</span>}
            {r.status !== "open" && (
              <span className="badge">{r.status === "linked" ? "연결됨" : "치움"}</span>
            )}
            <div className="spacer" />
            {r.status === "open" ? (
              <div className="row" style={{ gap: 6 }}>
                <button className="btn btn-sm btn-primary" disabled={busy === r.id}
                  onClick={() => setPicking(picking === r.id ? null : r.id)}>
                  주문에 연결
                </button>
                <button className="btn btn-sm btn-ghost" disabled={busy === r.id}
                  onClick={() => {
                    const note = prompt("치우는 이유를 적어주세요. 기록에 남습니다.", "우리 거래가 아님");
                    if (note !== null) act(r, { action: "ignore", note });
                  }}>
                  치우기
                </button>
              </div>
            ) : (
              <button className="btn btn-sm btn-ghost" disabled={busy === r.id}
                onClick={() => act(r, { action: "reopen" })}>
                다시 열기
              </button>
            )}
          </div>

          <div className="meta" style={{ marginTop: 4, lineHeight: 1.6 }}>
            {r.reason}
            <span style={{ display: "block", fontFamily: "ui-monospace, Menlo, monospace" }}>
              {r.line}
            </span>
            {r.linked_order_id && <span>주문 #{r.linked_order_id} 에 연결됨</span>}
            {r.note && <span style={{ display: "block" }}>메모: {r.note}</span>}
          </div>

          {picking === r.id && (
            <div style={{ marginTop: 10, padding: 10, background: "var(--raised, #f7f5f2)",
                          borderRadius: 8 }}>
              <p className="meta" style={{ margin: "0 0 8px" }}>
                어느 주문의 입금인가요? 고르면 그 주문이 <b>바로 승인</b>됩니다.
              </p>
              {orders.length === 0 ? (
                <p className="meta">입금 대기 중인 주문이 없습니다.</p>
              ) : orders.map((o) => (
                <div key={o.id} className="row"
                  style={{ gap: 8, padding: "6px 0", alignItems: "baseline" }}>
                  <span>{o.amount.toLocaleString()}원</span>
                  <span className="meta">{o.school_name || o.requester_email}</span>
                  <span className="meta">{o.seats}명</span>
                  {o.depositor_name && <span className="meta">입금자 {o.depositor_name}</span>}
                  {o.amount !== r.amount && (
                    <span className="badge" style={{ background: "#fdf3d7", color: "#9a6700" }}>
                      금액 다름
                    </span>
                  )}
                  <div className="spacer" />
                  <button className="btn btn-sm" disabled={busy === r.id}
                    onClick={() => {
                      const note = prompt("확인한 내용을 적어주세요. 기록에 남습니다.", "");
                      if (note !== null) act(r, { action: "link", order_id: o.id, note });
                    }}>
                    이 주문
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

/* 입금 계좌 목록 편집. 여러 개를 두면 신청이 몰릴 때 나눠 안내한다. */
function AccountList({ value, onChange }) {
  const rows = Array.isArray(value) ? value : [];

  const update = (i, key, v) =>
    onChange(rows.map((r, idx) => (idx === i ? { ...r, [key]: v } : r)));

  return (
    <div>
      {rows.map((r, i) => (
        <div key={i} style={{ border: "1px solid var(--line)", borderRadius: 8,
                              padding: 10, marginBottom: 8 }}>
          <div className="row" style={{ gap: 8, alignItems: "baseline" }}>
            <b style={{ fontSize: 13 }}>{i + 1}번 계좌</b>
            <div className="spacer" />
            <button className="btn btn-sm btn-ghost"
              onClick={() => onChange(rows.filter((_, idx) => idx !== i))}>
              지우기
            </button>
          </div>
          <div style={{ display: "grid", gap: 6, marginTop: 8 }}>
            <input className="input" placeholder="은행" value={r.bank_name || ""}
              onChange={(e) => update(i, "bank_name", e.target.value)} />
            <input className="input" placeholder="계좌번호" value={r.bank_account || ""}
              onChange={(e) => update(i, "bank_account", e.target.value)} />
            <input className="input" placeholder="예금주" value={r.bank_holder || ""}
              onChange={(e) => update(i, "bank_holder", e.target.value)} />
          </div>
        </div>
      ))}

      <button className="btn btn-sm"
        onClick={() => onChange([...rows, { key: `acc${rows.length + 1}`,
                                            bank_name: "", bank_account: "", bank_holder: "" }])}>
        계좌 추가
      </button>
    </div>
  );
}

/* ---------------- 학교 이용권 신청 ----------------
   학교가 적은 인원과 실제 인원이 다를 수 있어, 승인할 때 인원을 다시 정한다.
   확인 없이 그대로 받으면 인원을 줄여 적는 일을 막을 수 없다. */
function SeatOrdersTab() {
  const [rows, setRows] = useState(null);
  const [status, setStatus] = useState("pending");
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(0);
  const [seats, setSeats] = useState({});

  const load = () =>
    api.adminSeatOrders(status).then((r) => {
      setRows(r);
      // 확인 인원의 기본값은 학교가 적은 인원.
      setSeats(Object.fromEntries(r.map((o) => [o.id, o.approved_seats ?? o.seats])));
    }).catch((e) => setMsg({ type: "error", text: e.message }));

  useEffect(() => { load(); }, [status]);

  const approve = async (o) => {
    const n = parseInt(seats[o.id], 10);
    if (!(n > 0)) return setMsg({ type: "error", text: "인원수를 확인해주세요." });
    if (!confirm(
      `${o.school_name || o.requester_email} · ${n}명\n` +
      `${(n * o.unit_price).toLocaleString()}원으로 승인합니다. 진행할까요?`
    )) return;
    setBusy(o.id); setMsg(null);
    try {
      const note = n !== o.seats ? prompt("인원이 신청과 다릅니다. 사유를 적어주세요.", "") : "";
      if (note === null) { setBusy(0); return; }
      const r = await api.approveSeatOrder(o.id, n, note || "");
      setMsg({ type: "ok", text: r.message });
      load();
    } catch (e) {
      setMsg({ type: "error", text: e.message });
    } finally {
      setBusy(0);
    }
  };

  const reject = async (o) => {
    const note = prompt("반려 사유를 적어주세요. 학교에 안내됩니다.", "");
    if (note === null) return;
    setBusy(o.id);
    try {
      await api.rejectSeatOrder(o.id, note);
      setMsg({ type: "ok", text: "반려했습니다." });
      load();
    } catch (e) {
      setMsg({ type: "error", text: e.message });
    } finally {
      setBusy(0);
    }
  };

  return (
    <div className="panel">
      <h3>학교 이용권 신청</h3>
      <p style={{ fontSize: 13, color: "var(--steel)", margin: "0 0 12px", lineHeight: 1.7 }}>
        학교가 인원수를 적어 신청합니다. <b>실제 인원을 확인한 뒤 승인</b>하세요.
        승인하면 그 인원만큼 좌석이 생기고, 학교가 학생에게 나눠줍니다.
      </p>

      <div className="row" style={{ gap: 6, marginBottom: 12 }}>
        {[["pending", "입금 대기"], ["approved", "승인 완료"],
          ["rejected", "반려"], ["", "전체"]].map(([k, label]) => (
          <button key={k} className={`btn btn-sm ${status === k ? "" : "btn-ghost"}`}
            onClick={() => setStatus(k)}>{label}</button>
        ))}
      </div>

      {msg && <div className={`notice notice-${msg.type}`}>{msg.text}</div>}

      {!rows ? <p className="meta">불러오는 중…</p>
        : rows.length === 0 ? <p className="meta">해당하는 신청이 없습니다.</p>
        : rows.map((o) => (
          <div key={o.id} style={{ padding: "12px 0", borderTop: "1px solid var(--line)" }}>
            <div className="row" style={{ gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
              <b>{o.school_name || `학교 #${o.school_id}`}</b>
              <span className="meta">{o.requester_email}</span>
              <span className="badge">{o.status_label}</span>
              <div className="spacer" />
              <span className="meta">{String(o.created_at).slice(0, 10)}</span>
            </div>

            <div className="meta" style={{ marginTop: 4, lineHeight: 1.7 }}>
              신청 <b>{o.seats}명</b> × {o.unit_price.toLocaleString()}원
              {" = "}{o.amount.toLocaleString()}원 · {o.months}개월
              {o.note && ` · ${o.note}`}
              <span style={{ display: "block" }}>
                입금코드 {o.deposit_code}
                {o.depositor_name && ` · 입금자 ${o.depositor_name}`}
              </span>
            </div>

            {(o.status === "pending" || o.status === "paid") && (
              <div className="row" style={{ gap: 8, marginTop: 10, alignItems: "center",
                                            flexWrap: "wrap" }}>
                <span className="meta">확인한 인원</span>
                <input className="input" type="number" min="1" style={{ maxWidth: 110 }}
                  value={seats[o.id] ?? o.seats}
                  onChange={(e) => setSeats({ ...seats, [o.id]: e.target.value })} />
                <span className="meta">
                  = {((parseInt(seats[o.id], 10) || 0) * o.unit_price).toLocaleString()}원
                </span>
                <div className="spacer" />
                <button className="btn btn-sm btn-primary" disabled={busy === o.id}
                  onClick={() => approve(o)}>승인</button>
                <button className="btn btn-sm btn-ghost" disabled={busy === o.id}
                  onClick={() => reject(o)}>반려</button>
              </div>
            )}

            {o.approved_seats != null && (
              <p className="meta" style={{ marginTop: 6 }}>
                확정 {o.approved_seats}명
                {o.approved_seats !== o.seats && ` (신청 ${o.seats}명에서 조정)`}
                {o.admin_note && ` · ${o.admin_note}`}
              </p>
            )}
          </div>
        ))}
    </div>
  );
}

/** 시험용 자료 초기화.
 *  정식 오픈 전에 만든 좌석·구독·주문을 한 번에 치운다.
 *  되돌릴 수 없어 확인 문구를 정확히 받는다. */
function ResetBox() {
  const [open, setOpen] = useState(false);
  const [word, setWord] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  const run = async () => {
    setBusy(true); setMsg(null);
    try {
      const r = await api.resetSubscriptions(word);
      setMsg({ type: "ok", text: r.message });
      setWord(""); setOpen(false);
    } catch (e) {
      setMsg({ type: "error", text: e.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ border: "1px solid #f2cccc", borderRadius: 8, padding: 12,
                  margin: "14px 0", background: "#fdecec" }}>
      <b style={{ fontSize: 13.5, color: "var(--alert, #c02b2b)" }}>이용권 자료 초기화</b>
      <p className="meta" style={{ margin: "4px 0 0", lineHeight: 1.7 }}>
        시험하며 만든 좌석·등록 코드·구독·주문을 모두 지웁니다.
        <b> 일지와 자기소개서 본문은 지워지지 않습니다.</b> 되돌릴 수 없습니다.
      </p>

      {msg && <div className={`notice notice-${msg.type}`} style={{ marginTop: 8 }}>{msg.text}</div>}

      {!open ? (
        <button className="btn btn-sm" style={{ marginTop: 8 }} onClick={() => setOpen(true)}>
          초기화하기
        </button>
      ) : (
        <div className="row" style={{ gap: 8, marginTop: 8, flexWrap: "wrap" }}>
          <input className="input" value={word} style={{ maxWidth: 160 }}
            placeholder="초기화 라고 입력" onChange={(e) => setWord(e.target.value)} />
          <button className="btn btn-sm" disabled={busy || word.trim() !== "초기화"}
            onClick={run} style={{ color: "var(--alert, #c02b2b)" }}>
            {busy ? "지우는 중…" : "정말 지우기"}
          </button>
          <button className="btn btn-sm btn-ghost" onClick={() => { setOpen(false); setWord(""); }}>
            그만두기
          </button>
        </div>
      )}
    </div>
  );
}

/** 단체 할인 설정.
 *  인원이 많을수록 깎아주는 구간을 관리자가 정한다. 꺼두면 정가로 나간다. */
function DiscountBox({ form, setForm }) {
  const on = (form.seat_discount_enabled || "off") === "on";
  const tiers = Array.isArray(form.seat_discount_tiers) ? form.seat_discount_tiers : [];

  const update = (i, key, v) =>
    setForm({
      ...form,
      seat_discount_tiers: tiers.map((t, idx) =>
        idx === i ? { ...t, [key]: v === "" ? "" : parseInt(v, 10) || 0 } : t),
    });

  return (
    <div style={{ border: "1px solid var(--line)", borderRadius: 8, padding: 12,
                  margin: "14px 0" }}>
      <label className="row" style={{ gap: 8, alignItems: "flex-start", cursor: "pointer" }}>
        <input type="checkbox" style={{ marginTop: 4 }} checked={on}
          onChange={(e) => setForm({ ...form,
            seat_discount_enabled: e.target.checked ? "on" : "off" })} />
        <span style={{ fontSize: 14, lineHeight: 1.6 }}>
          <b>인원 단체 할인 쓰기</b>
          <span className="meta" style={{ display: "block" }}>
            정해둔 인원 이상이면 그 구간의 할인율을 적용합니다. 꺼두면 정가로 나갑니다.
            이미 승인된 신청에는 영향이 없습니다.
          </span>
        </span>
      </label>

      {on && (
        <div style={{ marginTop: 12 }}>
          {tiers.map((t, i) => (
            <div key={i} className="row" style={{ gap: 6, alignItems: "center", marginBottom: 6 }}>
              <input className="input" type="number" min="1" style={{ maxWidth: 110 }}
                value={t.min ?? ""} onChange={(e) => update(i, "min", e.target.value)} />
              <span className="meta">명 이상</span>
              <input className="input" type="number" min="1" max="99" style={{ maxWidth: 90 }}
                value={t.percent ?? ""} onChange={(e) => update(i, "percent", e.target.value)} />
              <span className="meta">% 할인</span>
              <div className="spacer" />
              <button className="btn btn-sm btn-ghost"
                onClick={() => setForm({ ...form,
                  seat_discount_tiers: tiers.filter((_, idx) => idx !== i) })}>
                지우기
              </button>
            </div>
          ))}
          <button className="btn btn-sm"
            onClick={() => setForm({ ...form,
              seat_discount_tiers: [...tiers, { min: "", percent: "" }] })}>
            구간 추가
          </button>
          <p className="meta" style={{ marginTop: 8, lineHeight: 1.7 }}>
            여러 구간에 해당하면 <b>가장 인원이 큰 구간</b>의 할인율을 씁니다.
            예: 50명 5% · 100명 10% 로 두면 200명은 10% 입니다.
          </p>
        </div>
      )}
    </div>
  );
}
