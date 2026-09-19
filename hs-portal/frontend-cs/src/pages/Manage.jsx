import { useEffect, useState } from "react";
import { api } from "../api";
import { Empty, Modal, Note, fmtDateTime } from "../components/ui";

const TABS = [
  ["devices", "기기 승인"],
  ["agents", "상담원"],
  ["ips", "사무실 IP"],
  ["audit", "활동 기록"],
];

export default function Manage() {
  const [tab, setTab] = useState("devices");

  return (
    <>
      <div className="page-head">
        <h1>기기·상담원 관리</h1>
        <p>관리자만 볼 수 있는 화면입니다.</p>
      </div>

      <div className="toolbar">
        {TABS.map(([v, label]) => (
          <button
            key={v}
            className={`btn ${tab === v ? "primary" : ""}`}
            onClick={() => setTab(v)}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "devices" && <Devices />}
      {tab === "agents" && <Agents />}
      {tab === "ips" && <OfficeIps />}
      {tab === "audit" && <Audit />}
    </>
  );
}

function Devices() {
  const [status, setStatus] = useState("pending");
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(0);

  const load = () => {
    setError("");
    api
      .devices(status)
      .then((d) => setItems(d.items))
      .catch((e) => setError(e.message));
  };
  useEffect(() => { load(); }, [status]);

  const act = async (id, fn) => {
    setBusy(id);
    setError("");
    try {
      await fn();
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(0);
    }
  };

  return (
    <div className="card">
      <h2>
        기기 승인
        <span className="tiny muted" style={{ fontWeight: 400 }}>
          상담원이 알려준 코드와 같은지 확인하고 승인하세요.
        </span>
      </h2>

      <div className="toolbar">
        {[
          ["pending", "승인 대기"],
          ["approved", "사용 중"],
          ["revoked", "중지됨"],
          ["", "전체"],
        ].map(([v, label]) => (
          <button
            key={v}
            className={`btn sm ${status === v ? "primary" : ""}`}
            onClick={() => setStatus(v)}
          >
            {label}
          </button>
        ))}
      </div>

      <Note kind="bad">{error}</Note>

      {items == null ? (
        <Empty>불러오는 중…</Empty>
      ) : items.length === 0 ? (
        <Empty>해당하는 기기가 없습니다.</Empty>
      ) : (
        <table>
          <thead>
            <tr>
              <th>코드</th>
              <th>상담원</th>
              <th>기기</th>
              <th>IP</th>
              <th>마지막 접속</th>
              <th>상태</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((d) => (
              <tr key={d.id}>
                <td>
                  <strong style={{ fontFamily: "ui-monospace, Menlo, monospace" }}>
                    {d.code}
                  </strong>
                </td>
                <td>
                  {d.user_name}
                  <div className="tiny muted">{d.user_email}</div>
                </td>
                <td style={{ maxWidth: 220 }}>
                  {d.label || <span className="muted tiny">이름 없음</span>}
                  <div
                    className="tiny muted"
                    style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                    title={d.user_agent}
                  >
                    {d.user_agent}
                  </div>
                </td>
                <td className="tiny masked">{d.last_ip || d.first_ip}</td>
                <td className="tiny muted">{fmtDateTime(d.last_seen_at)}</td>
                <td>
                  <span
                    className={`badge ${
                      d.status === "approved" ? "done" : d.status === "pending" ? "wait" : "stop"
                    }`}
                  >
                    {d.status === "approved"
                      ? "사용 중"
                      : d.status === "pending"
                      ? "승인 대기"
                      : "중지됨"}
                  </span>
                </td>
                <td>
                  <div className="btn-row">
                    {d.status !== "approved" && (
                      <button
                        className="btn sm go"
                        disabled={busy === d.id}
                        onClick={() => act(d.id, () => api.decideDevice(d.id, "approved"))}
                      >
                        승인
                      </button>
                    )}
                    {d.status === "approved" && (
                      <button
                        className="btn sm danger"
                        disabled={busy === d.id}
                        onClick={() => act(d.id, () => api.decideDevice(d.id, "revoked"))}
                      >
                        중지
                      </button>
                    )}
                    <button
                      className="btn sm"
                      disabled={busy === d.id}
                      onClick={() => act(d.id, () => api.deleteDevice(d.id))}
                    >
                      삭제
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function Agents() {
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(0);

  const load = () => {
    setError("");
    api
      .agents()
      .then((d) => setItems(d.items))
      .catch((e) => setError(e.message));
  };
  useEffect(() => { load(); }, []);

  const toggle = async (a) => {
    setBusy(a.id);
    setError("");
    setMsg("");
    try {
      await api.updateAgent(a.id, { is_active: !a.is_active });
      setMsg(
        a.is_active
          ? `${a.name} 계정을 중지했습니다. 등록된 기기도 함께 끊었습니다.`
          : `${a.name} 계정을 다시 열었습니다. 기기는 새로 승인해야 합니다.`
      );
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(0);
    }
  };

  return (
    <div className="card">
      <h2>
        상담원
        <span className="spacer" style={{ flex: 1 }} />
        <button className="btn go sm" onClick={() => setAdding(true)}>
          상담원 추가
        </button>
      </h2>

      <Note kind="bad">{error}</Note>
      <Note kind="good">{msg}</Note>

      {items == null ? (
        <Empty>불러오는 중…</Empty>
      ) : items.length === 0 ? (
        <Empty>등록된 상담원이 없습니다.</Empty>
      ) : (
        <table>
          <thead>
            <tr>
              <th>이름</th>
              <th>이메일</th>
              <th className="num">승인된 기기</th>
              <th>상태</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((a) => (
              <tr key={a.id}>
                <td>
                  <strong>{a.name}</strong>
                </td>
                <td>{a.email}</td>
                <td className="num">{a.devices}</td>
                <td>
                  <span className={`badge ${a.is_active ? "done" : "stop"}`}>
                    {a.is_active ? "사용 중" : "중지"}
                  </span>
                </td>
                <td>
                  <button className="btn sm" disabled={busy === a.id} onClick={() => toggle(a)}>
                    {a.is_active ? "사용 중지" : "다시 열기"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {adding && (
        <AddAgent
          onClose={() => setAdding(false)}
          onDone={(name) => {
            setAdding(false);
            setMsg(`${name} 계정을 만들었습니다. 첫 로그인 후 본인이 비밀번호를 바꿔야 합니다.`);
            load();
          }}
        />
      )}
    </div>
  );
}

function AddAgent({ onClose, onDone }) {
  const [form, setForm] = useState({ name: "", email: "", password: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!form.name || !form.email || form.password.length < 8) {
      setError("이름·이메일과 8자 이상 비밀번호를 입력해주세요.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.createAgent(form);
      onDone(form.name);
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  };

  return (
    <Modal
      title="상담원 추가"
      sub="상담 사이트에서만 쓰는 계정입니다. 본 사이트 관리자 권한은 없습니다."
      onClose={onClose}
      foot={
        <>
          <button className="btn" onClick={onClose}>
            그만두기
          </button>
          <button className="btn go" onClick={submit} disabled={busy}>
            {busy ? "만드는 중…" : "만들기"}
          </button>
        </>
      }
    >
      <Note kind="bad">{error}</Note>
      <div className="field">
        <label>이름</label>
        <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
      </div>
      <div className="field">
        <label>이메일</label>
        <input
          type="email"
          value={form.email}
          onChange={(e) => setForm({ ...form, email: e.target.value })}
        />
      </div>
      <div className="field">
        <label>첫 비밀번호 (8자 이상)</label>
        <input
          value={form.password}
          onChange={(e) => setForm({ ...form, password: e.target.value })}
        />
        <p className="tiny muted" style={{ margin: "4px 0 0" }}>
          본인에게 직접 전달하고, 첫 로그인 후 바꾸게 하세요.
        </p>
      </div>
    </Modal>
  );
}

function OfficeIps() {
  const [ips, setIps] = useState("");
  const [yourIp, setYourIp] = useState("");
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .officeIps()
      .then((d) => {
        setIps(d.ips);
        setYourIp(d.your_ip);
      })
      .catch((e) => setError(e.message));
  }, []);

  const save = async () => {
    setBusy(true);
    setError("");
    setMsg("");
    try {
      const r = await api.setOfficeIps(ips);
      setIps(r.ips);
      setMsg("저장했습니다.");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <h2>사무실 IP</h2>
      <Note kind="bad">{error}</Note>
      <Note kind="good">{msg}</Note>

      <Note kind="info">
        여기 등록한 곳에서 접속하면 기기 승인 없이 바로 쓸 수 있습니다. 비워두면 모든 접속이
        기기 승인 대상이 됩니다. 여러 개는 쉼표로 나누고, 대역은 <code>1.2.3.0/24</code>처럼
        적습니다.
      </Note>

      <div className="field">
        <label>허용할 IP</label>
        <textarea
          value={ips}
          onChange={(e) => setIps(e.target.value)}
          placeholder="예: 203.0.113.7, 198.51.100.0/24"
          style={{ minHeight: 70 }}
        />
      </div>

      <p className="tiny muted">
        지금 접속한 IP는 <strong className="masked">{yourIp || "확인 중"}</strong> 입니다.
        사무실에서 이 화면을 보고 계시면 이 값을 넣으면 됩니다. 다만 인터넷 회선이 고정 IP가
        아니면 주소가 바뀔 수 있습니다.
      </p>

      <button className="btn go" onClick={save} disabled={busy} style={{ marginTop: 10 }}>
        {busy ? "저장 중…" : "저장"}
      </button>
    </div>
  );
}

function Audit() {
  const [items, setItems] = useState(null);
  const [actor, setActor] = useState("");
  const [term, setTerm] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    setError("");
    api
      .audit({ actor, limit: 100 })
      .then((d) => setItems(d.items))
      .catch((e) => setError(e.message));
  }, [actor]);

  return (
    <div className="card">
      <h2>활동 기록</h2>
      <Note kind="info">
        상담원이 개인정보를 열어보거나 무언가를 고칠 때마다 한 줄씩 쌓입니다. 1년간
        보관됩니다.
      </Note>

      <div className="toolbar">
        <input
          placeholder="상담원 이메일"
          value={term}
          onChange={(e) => setTerm(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && setActor(term)}
        />
        <button className="btn" onClick={() => setActor(term)}>
          거르기
        </button>
      </div>

      <Note kind="bad">{error}</Note>

      {items == null ? (
        <Empty>불러오는 중…</Empty>
      ) : items.length === 0 ? (
        <Empty>기록이 없습니다.</Empty>
      ) : (
        <table>
          <thead>
            <tr>
              <th>시각</th>
              <th>상담원</th>
              <th>한 일</th>
              <th>대상</th>
              <th>IP</th>
            </tr>
          </thead>
          <tbody>
            {items.map((r) => (
              <tr key={r.id}>
                <td className="tiny muted">{fmtDateTime(r.created_at)}</td>
                <td className="tiny">{r.actor_email}</td>
                <td>
                  {ACTION_LABEL[r.action] || r.action}
                  {r.detail && <div className="tiny muted">{r.detail}</div>}
                </td>
                <td className="tiny muted">
                  {r.target_type}
                  {r.target_id ? ` #${r.target_id}` : ""}
                </td>
                <td className="tiny masked">{r.ip}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

const ACTION_LABEL = {
  "cs.login": "로그인",
  "cs.login_blocked": "로그인 차단",
  "cs.device_request": "기기 승인 요청",
  "cs.device_decide": "기기 승인·중지",
  "cs.device_delete": "기기 삭제",
  "cs.reveal_contact": "연락처 원본 열람",
  "cs.password_reset_sent": "비밀번호 재설정 코드 발송",
  "cs.school_update": "학교 정보 수정",
  "cs.inquiry_answer": "문의 답변",
  // 후기 기능은 없앴지만, 없애기 전에 쌓인 감사 로그가 그대로 남아 있다.
  // 이 두 줄을 지우면 옛 기록이 영문 코드로 보이므로 읽기 위해 남겨 둔다.
  "cs.review_hide": "후기 숨김",
  "cs.review_unhide": "후기 공개 복구",
  "cs.verification_decide": "재학생 인증 처리",
  "cs.order_confirm_paid": "입금 확인",
  "cs.agent_create": "상담원 계정 생성",
  "cs.agent_update": "상담원 계정 변경",
  "cs.office_ips_set": "사무실 IP 변경",
};
