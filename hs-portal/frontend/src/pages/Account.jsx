import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ROLE_LABEL } from "../api";
import { useAuth } from "../auth";
import { errMsg, okMsg } from "../toast";

/** 정보 한 줄. 컴포넌트 밖에 두어야 입력 중 리마운트(포커스 소실)가 없다. */
function Row({ label, children }) {
  return (
    <div style={{ display: "flex", gap: 12, padding: "11px 0", borderBottom: "1px solid var(--line)" }}>
      <span className="label" style={{ width: 110, flexShrink: 0, paddingTop: 2 }}>{label}</span>
      <div style={{ flex: 1, minWidth: 0, fontSize: 14.5 }}>{children}</div>
    </div>
  );
}

/** 마이페이지 — 내 등록 정보 확인·수정 + 비밀번호 변경/탈퇴로 이동 */
export default function Account() {
  const { user } = useAuth();
  const [me, setMe] = useState(null);
  const [form, setForm] = useState({ name: "", phone: "" });
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    api.myAccount()
      .then((d) => { setMe(d); setForm({ name: d.name, phone: d.phone || "" }); })
      .catch(() => {});
  }, []);

  if (!user) {
    return (
      <div className="wrap" style={{ maxWidth: 560, padding: "56px 0" }}>
        <div className="empty"><p>로그인이 필요합니다.</p></div>
      </div>
    );
  }
  if (!me) {
    return (
      <div className="wrap" style={{ maxWidth: 560, padding: "56px 0" }}>
        <div className="empty"><p>불러오는 중…</p></div>
      </div>
    );
  }

  const save = async () => {
    setBusy(true); setMsg(null);
    try {
      const d = await api.updateMyAccount({ name: form.name });
      setMe(d);
      setForm({ name: d.name, phone: d.phone || "" });
      setEditing(false);
      setMsg(okMsg("정보를 저장했습니다."));
    } catch (e) {
      setMsg(errMsg(e.message));
    } finally { setBusy(false); }
  };

  const cancel = () => {
    setForm({ name: me.name, phone: me.phone || "" });
    setEditing(false);
    setMsg(null);
  };

  const fmtPhone = (p) => {
    if (!p) return "-";
    if (p.length === 11) return `${p.slice(0, 3)}-${p.slice(3, 7)}-${p.slice(7)}`;
    if (p.length === 10) return `${p.slice(0, 3)}-${p.slice(3, 6)}-${p.slice(6)}`;
    return p;
  };

  return (
    <div className="wrap" style={{ maxWidth: 620, padding: "48px 0 70px" }}>
      <span className="label">내 계정</span>
      <h1 style={{ fontSize: 26, margin: "8px 0 6px" }}>마이페이지</h1>
      <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 0 }}>
        {ROLE_LABEL[me.role]} · {me.email}
      </p>

      {msg && <div className={`notice notice-${msg.type}`} style={{ margin: "14px 0" }}>{msg.text}</div>}

      {/* 등록 정보 */}
      <div className="panel" style={{ marginTop: 18 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
          <h3 style={{ margin: 0 }}>등록 정보</h3>
          {!editing && (
            <button className="btn btn-ghost btn-sm" onClick={() => setEditing(true)}>정보 수정</button>
          )}
        </div>

        <div style={{ marginTop: 10 }}>
          <Row label="아이디(이메일)">
            {me.email}
            <span className="label" style={{ color: "var(--steel-light)", marginLeft: 6 }}>변경 불가</span>
          </Row>

          <Row label="이름">
            {editing ? (
              <input className="input" value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })} />
            ) : me.name}
          </Row>

          <Row label="연락처">
            <span style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <span>{fmtPhone(me.phone)}</span>
              <Link to="/change-phone" className="btn btn-sm btn-ghost">번호 변경</Link>
            </span>
            <span style={{ display: "block", fontSize: 12, color: "var(--steel-light)", marginTop: 4 }}>
              본인확인 수단이라 비밀번호 확인과 문자 인증을 거쳐야 바꿀 수 있습니다.
            </span>
          </Row>

          <Row label="회원 구분">{ROLE_LABEL[me.role]}</Row>

          {me.role === "student" && me.verified_school && (
            <Row label="재학생 인증">
              <span className="badge badge-dorm">{me.verified_school}</span>
              {me.class_name && <span style={{ marginLeft: 6 }}>{me.class_name}</span>}
            </Row>
          )}
          {(me.role === "teacher" || me.role === "school") && me.school_name && (
            <Row label="소속 학교">
              {me.school_name}
              {me.class_name && <span style={{ marginLeft: 6, color: "var(--steel)" }}>{me.class_name}</span>}
            </Row>
          )}
          <Row label="가입일">{me.created_at?.slice(0, 10)}</Row>
        </div>

        {editing && (
          <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
            <button className="btn btn-primary btn-sm" onClick={save} disabled={busy}>
              {busy ? "저장 중…" : "저장"}
            </button>
            <button className="btn btn-ghost btn-sm" onClick={cancel} disabled={busy}>취소</button>
          </div>
        )}
      </div>

      {/* 보안 · 계정 관리 */}
      <div className="panel" style={{ marginTop: 16 }}>
        <h3>계정 관리</h3>
        <div style={{ display: "grid", gap: 8, marginTop: 8 }}>
          <Link to="/account/password" className="account-action">
            <div>
              <b style={{ fontSize: 14.5 }}>비밀번호 변경</b>
              <p style={{ margin: "2px 0 0", fontSize: 12.5, color: "var(--steel)" }}>
                주기적으로 바꾸면 계정을 더 안전하게 지킬 수 있어요.
              </p>
            </div>
            <span style={{ color: "var(--steel-light)", fontSize: 18 }}>›</span>
          </Link>

          <Link to="/account/delete" className="account-action">
            <div>
              <b style={{ fontSize: 14.5, color: "var(--alert)" }}>회원 탈퇴</b>
              <p style={{ margin: "2px 0 0", fontSize: 12.5, color: "var(--steel)" }}>
                계정과 작성한 내용이 모두 삭제되며 되돌릴 수 없습니다.
              </p>
            </div>
            <span style={{ color: "var(--steel-light)", fontSize: 18 }}>›</span>
          </Link>
        </div>
      </div>
    </div>
  );
}
