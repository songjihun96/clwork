import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { GradePanel } from "./Subscribe";
import { api } from "../api";
import { useAuth } from "../auth";

const MAIN = "https://udjschool.ggm.kr";

export default function Account() {
  const { logout, setUser } = useAuth();
  const navigate = useNavigate();
  const [me, setMe] = useState(null);
  const [subjects, setSubjects] = useState(null);
  const [sub, setSub] = useState(null);
  const [msg, setMsg] = useState(null);
  const [saving, setSaving] = useState(false);
  const [tab, setTab] = useState("info");

  const load = () =>
    api.me().then((d) => { setMe(d); setUser(d); }).catch((e) => setMsg({ type: "error", text: e.message }));

  useEffect(() => {
    load();
    api.journalSubjects().then(setSubjects).catch(() => setSubjects(null));
    api.subscription().then(setSub).catch(() => {});
  }, []);

  // 학생은 학년·반·학과를 직접 고르지 않는다. 이용권 코드로 정해진다.
  const isStudent = me?.role === "student";
  // 반은 자유 입력이라, 칸을 벗어날 때 한 번만 저장한다.
  const [classDraft, setClassDraft] = useState("");
  useEffect(() => { setClassDraft(me?.class_name || ""); }, [me?.class_name]);

  // 담당 학급은 기록해에만 둔다. UDJ 로 보내지 않는다.
  const changeClass = async (body) => {
    setSaving(true);
    setMsg(null);
    try {
      await api.updateMyClass(body);
      await load();
      const s = await api.journalSubjects().catch(() => null);
      setSubjects(s);
      setMsg({ type: "ok", text: "저장했습니다." });
    } catch (e) {
      setMsg({ type: "error", text: e.message });
    } finally {
      setSaving(false);
    }
  };

  const change = async (body) => {
    setSaving(true);
    setMsg(null);
    try {
      await api.updateMe(body);
      await load();
      const s = await api.journalSubjects().catch(() => null);
      setSubjects(s);
      setMsg({ type: "ok", text: "저장했습니다." });
    } catch (e) {
      setMsg({ type: "error", text: e.message });
    } finally {
      setSaving(false);
    }
  };

  if (!me) return <div className="wrap page"><p>불러오는 중…</p></div>;

  const deptOptions = subjects?.departments?.length ? subjects.departments : [];
  const gradeOptions = subjects?.grades?.length ? subjects.grades : [1, 2, 3];

  return (
    <div className="wrap page" style={{ maxWidth: 620 }}>
      <span className="label">내 정보</span>
      <h1>{me.name}</h1>

      <div className="row" style={{ gap: 6, margin: "14px 0 4px" }}>
        {[["info", "기본 정보"], ["security", "보안"], ["danger", "탈퇴"]].map(([k, label]) => (
          <button key={k} className={`btn btn-sm ${tab === k ? "" : "btn-ghost"}`}
            onClick={() => { setTab(k); setMsg(null); }}>{label}</button>
        ))}
      </div>

      {msg && <div className={`notice notice-${msg.type}`} style={{ margin: "12px 0" }}>{msg.text}</div>}

      {tab === "info" && (
        <>
          <div className="panel" style={{ marginTop: 12 }}>
            <h3>계정</h3>
            <Row label="이메일" value={me.email} />
            <div className="field" style={{ marginTop: 12, marginBottom: 0 }}>
              <span className="label">이름</span>
              <NameEditor value={me.name} disabled={saving}
                onSave={(name) => change({ name })} />
            </div>
            <p style={{ fontSize: 12.5, color: "var(--steel-light)", margin: "12px 0 0", lineHeight: 1.7 }}>
              이메일과 휴대폰번호는 본인확인 수단이라{" "}
              <a href={`${MAIN}/account`}>우리동네 직업계고</a>에서 바꿉니다.
              두 사이트가 같은 계정을 씁니다.
            </p>
          </div>

          {/* 학교가 연결되지 않았으면 이 카드를 아예 안 보여 준다.
              예전에는 "재학생 인증하러 가기" 버튼을 띄웠는데, 학생이 스스로
              할 일이 아니라 학교에서 받은 이용권 코드를 넣으면 저절로
              이어진다. 할 수 없는 일을 하라고 시키는 칸이었다. */}
          {me.school_name && (
          <div className="panel">
            <h3>학교</h3>
            <Row label="학교" value={me.school_name} />
            <Row label="재학생 인증"
              value={me.verified ? "인증 완료" : "미인증 — 선생님께 제출할 수 없습니다"} />

            {isStudent ? (
              /* 학생은 직접 고르지 않는다. 이용권 코드를 넣으면
                 코드에 담긴 학급으로 저절로 옮겨진다. 직접 고르게
                 하면 오타가 나고, 반을 잘못 고르면 담당 선생님과
                 이어지지 않는다. */
              <>
                <Row label="학년"
                  value={me.grade ? `${me.grade}학년` : "아직 배정 안 됨"} />
                {/* 학급 이름에 학년이 이미 들어 있는 경우가 많다(예: "2학년 3반").
                    위에서 학년을 따로 보여줬으니, 여기서는 반만 남긴다. */}
                <Row label="반"
                  value={(me.class_name || "").replace(/^\d+학년\s*/, "") || "아직 배정 안 됨"} />
                <Row label="학과" value={me.department || "아직 배정 안 됨"} />
                <p style={{ fontSize: 12.5, color: "var(--steel-light)",
                            margin: "12px 0 0", lineHeight: 1.7 }}>
                  학년·반·학과는 <b>이용권 코드를 넣으면 저절로 정해집니다.</b>
                  {" "}선생님께 받은 코드를 자기소개서 화면에서 넣어주세요.
                  바뀌어야 하는데 그대로라면 담당 선생님께 말씀해 주세요.
                </p>
              </>
            ) : (
              /* 선생님·학교는 직접 적는다. 여기 적은 것이
                 이용권 코드에 담겨 학생에게 옮겨진다. */
              <>
                <div className="field" style={{ marginTop: 14, marginBottom: 10 }}>
                  <span className="label">담당 학과</span>
                  <select className="select" value={me.department || ""} disabled={saving}
                    onChange={(e) => changeClass({ department: e.target.value })}>
                    <option value="">선택 안 함</option>
                    {deptOptions.map((d) => <option key={d} value={d}>{d}</option>)}
                    {me.department && !deptOptions.includes(me.department) && (
                      <option value={me.department}>{me.department}</option>
                    )}
                  </select>
                </div>

                <div className="field" style={{ marginBottom: 10 }}>
                  <span className="label">담당 학년</span>
                  <select className="select" value={me.grade || ""} disabled={saving}
                    onChange={(e) => changeClass({ grade: e.target.value })}>
                    <option value="">선택 안 함</option>
                    {gradeOptions.map((g) => <option key={g} value={g}>{g}학년</option>)}
                  </select>
                </div>

                <div className="field" style={{ marginBottom: 0 }}>
                  <span className="label">담당 반</span>
                  <input className="input" value={classDraft} disabled={saving}
                    placeholder="3반"
                    onChange={(e) => setClassDraft(e.target.value)}
                    onBlur={() => classDraft !== (me.class_name || "")
                      && changeClass({ class_name: classDraft })} />
                </div>

                <p style={{ fontSize: 12.5, color: "var(--steel-light)",
                            margin: "12px 0 0", lineHeight: 1.7 }}>
                  여기 적은 것이 <b>이용권 코드에 담깁니다.</b> 학생이 코드를
                  넣으면 이 학년·반·학과로 배정되고 담당 선생님으로 이어집니다.
                </p>
              </>
            )}

          </div>
          )}

          {sub && (
            <div className="panel">
              <h3>자기소개서 이용권</h3>
              {sub.active ? (
                <>
                  <Row label="종류" value={{ school: "학교 이용권", individual: "개인 이용권",
                    both: "학교 + 개인 이용권", trial: "첫 달 무료" }[sub.access_type] || "이용권"} />
                  {sub.access_type === "trial" && sub.trial?.last_day && (
                    <Row label="무료 이용" value={`${sub.trial.last_day}까지 (${sub.trial.days_left}일 남음)`} />
                  )}
                  {sub.school_seat?.expires_at && (
                    <Row label="학교 이용권" value={`${String(sub.school_seat.expires_at).slice(0, 10)}까지`} />
                  )}
                  {sub.personal?.active && sub.personal.expires_at && (
                    <Row label="개인 이용권" value={`${String(sub.personal.expires_at).slice(0, 10)}까지`} />
                  )}
                </>
              ) : (
                <p style={{ fontSize: 14, color: "var(--steel)", marginTop: 0, lineHeight: 1.8 }}>
                  아직 이용권이 없습니다. 담당 선생님께 받은 <b>학교 코드</b>를 넣거나
                  <b> 개인 이용권</b>을 구매하면 바로 쓸 수 있습니다.
                  일지 작성과 선생님께 제출은 이용권 없이도 계속 무료입니다.
                </p>
              )}
              <div className="row" style={{ gap: 8, marginTop: 10, flexWrap: "wrap" }}>
                <Link className="btn btn-sm" to="/cover-letters">
                  {sub.active ? "자기소개서 쓰러 가기" : "학교 코드 넣기"}
                </Link>
                <Link className="btn btn-sm btn-ghost" to="/subscribe">개인 이용권 · 구매 내역</Link>
              </div>
            </div>
          )}

          {/* 학교 소속이 아닌(개인) 학생만 학년을 직접 정한다. 해마다 저절로 오른다. */}
          {isStudent && sub && !sub.school_managed && <GradePanel onSaved={() => load()} />}

        </>
      )}

      {tab === "security" && (
        <>
          <PasswordPanel onDone={(m) => setMsg(m)} />
          <AiConsentPanel onDone={(m) => setMsg(m)} />
        </>
      )}

      {tab === "danger" && (
        <DeletePanel onDone={() => { logout(); navigate("/login", { replace: true }); }}
          onError={(text) => setMsg({ type: "error", text })} />
      )}
    </div>
  );
}

function Row({ label, value }) {
  return (
    <div style={{ display: "flex", gap: 12, padding: "6px 0", fontSize: 14.5 }}>
      <span style={{ minWidth: 88, color: "var(--steel)", fontWeight: 600 }}>{label}</span>
      <span style={{ flex: 1, minWidth: 0, overflowWrap: "anywhere" }}>{value}</span>
    </div>
  );
}

function NameEditor({ value, onSave, disabled }) {
  const [name, setName] = useState(value);
  useEffect(() => setName(value), [value]);
  const dirty = name.trim() !== value;
  return (
    <div style={{ display: "flex", gap: 8 }}>
      <input className="input" style={{ flex: 1, minWidth: 0 }} value={name} minLength={2}
        onChange={(e) => setName(e.target.value)} />
      <button className="btn btn-sm" style={{ flexShrink: 0, whiteSpace: "nowrap" }}
        disabled={disabled || !dirty || name.trim().length < 2}
        onClick={() => onSave(name.trim())}>저장</button>
    </div>
  );
}

/** AI 사용 동의를 거두는 곳.
 *
 * 동의는 자기소개서 화면에서 받는다 — 실제로 AI 를 쓰려는 순간에 묻는 것이
 * 맞기 때문이다. 하지만 **거두는 일은 그 화면에 있으면 안 된다.** 글을 쓰는
 * 내내 "동의 거두기"가 옆에 붙어 있으면 거슬리기만 하고, 정작 거두려고
 * 마음먹은 사람은 자기소개서를 열지 않는다. 계정 설정이 제자리다.
 *
 * 안내문(개인정보처리방침 제7조)이 "언제든 거둘 수 있다"고 약속하고 있어,
 * 이 화면이 그 약속을 실제로 지키는 자리이기도 하다.
 */
function AiConsentPanel({ onDone }) {
  const [st, setSt] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { api.aiStatus().then(setSt).catch(() => setSt(null)); }, []);
  if (!st) return null;

  const revoke = async () => {
    if (!window.confirm(
      "AI 사용 동의를 거둘까요?\n\n"
      + "지금까지 AI 로 정리해 둔 재료가 지워지고, 자기소개서에서 AI 도움을 "
      + "받을 수 없게 됩니다. 써 둔 글은 그대로 남습니다.")) return;
    setBusy(true);
    try {
      await api.setAiConsent(false);
      setSt(await api.aiStatus());
      onDone({ type: "ok", text: "AI 사용 동의를 거뒀습니다." });
    } catch (e) {
      onDone({ type: "error", text: e.message });
    } finally { setBusy(false); }
  };

  return (
    <div className="panel">
      <h3>AI 사용 동의</h3>
      {st.consented ? (
        <>
          <p style={{ fontSize: 14, color: "var(--steel)", lineHeight: 1.8, marginTop: 0 }}>
            자기소개서를 쓸 때 AI 도움을 받도록 <b>동의한 상태</b>입니다.
            분석을 위해 작성한 글이 국외(미국)의 AI 서비스로 전송되며,
            이름·학교·연락처는 전송 전에 가려서 보냅니다.
          </p>
          <button className="btn btn-sm btn-ghost" onClick={revoke} disabled={busy}>
            {busy ? "처리 중…" : "AI 동의 거두기"}
          </button>
        </>
      ) : (
        <p style={{ fontSize: 14, color: "var(--steel)", lineHeight: 1.8, margin: 0 }}>
          아직 동의하지 않으셨습니다. 동의하지 않아도 자기소개서를 쓰는 데
          불이익은 없습니다. 동의는 자기소개서 화면에서 AI 도움을 처음 쓸 때
          받습니다.
        </p>
      )}
    </div>
  );
}


function PasswordPanel({ onDone }) {
  const [cur, setCur] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (pw !== pw2) {
      onDone({ type: "error", text: "새 비밀번호가 서로 다릅니다." });
      return;
    }
    setBusy(true);
    try {
      await api.changePassword(cur, pw);
      setCur(""); setPw(""); setPw2("");
      onDone({ type: "ok", text: "비밀번호를 바꿨습니다. 우리동네 직업계고에서도 새 비밀번호를 쓰세요." });
    } catch (e2) {
      onDone({ type: "error", text: e2.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="panel" onSubmit={submit} style={{ marginTop: 12 }}>
      <h3>비밀번호 변경</h3>
      <p style={{ fontSize: 13, color: "var(--steel)", marginTop: 0, lineHeight: 1.7 }}>
        두 사이트가 같은 계정을 쓰므로, 여기서 바꾸면 우리동네 직업계고에서도
        새 비밀번호로 로그인합니다.
      </p>
      <label className="field">
        <span className="label">현재 비밀번호</span>
        <input className="input" type="password" value={cur} required
          autoComplete="current-password" onChange={(e) => setCur(e.target.value)} />
      </label>
      <label className="field">
        <span className="label">새 비밀번호 (8자 이상)</span>
        <input className="input" type="password" value={pw} required minLength={8}
          autoComplete="new-password" onChange={(e) => setPw(e.target.value)} />
      </label>
      <label className="field" style={{ marginBottom: 8 }}>
        <span className="label">새 비밀번호 확인</span>
        <input className="input" type="password" value={pw2} required
          autoComplete="new-password" onChange={(e) => setPw2(e.target.value)} />
      </label>
      <button className="btn btn-primary" disabled={busy}>
        {busy ? "변경 중…" : "비밀번호 변경"}
      </button>
    </form>
  );
}

function DeletePanel({ onDone, onError }) {
  const [password, setPassword] = useState("");
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (!confirm("정말 탈퇴할까요? 되돌릴 수 없습니다.")) return;
    setBusy(true);
    try {
      await api.deleteMe(password);
      alert("탈퇴가 완료되었습니다. 그동안 이용해주셔서 감사합니다.");
      onDone();
    } catch (e2) {
      onError(e2.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="panel" onSubmit={submit} style={{ marginTop: 12 }}>
      <h3>회원 탈퇴</h3>
      <div className="notice notice-error" style={{ lineHeight: 1.8 }}>
        <b>탈퇴하면 이렇게 됩니다</b>
        <ul style={{ margin: "8px 0 0", paddingLeft: 18 }}>
          <li>작성한 학교생활일지·수업일지와 자기소개서가 모두 삭제됩니다.</li>
          <li>남은 이용권 기간이 있어도 환불되지 않습니다.</li>
          <li><b>우리동네 직업계고 계정도 함께 삭제</b>됩니다. 같은 계정이기 때문입니다.</li>
          <li>같은 이메일로 다시 가입할 수 있지만, 이전 기록은 복구되지 않습니다.</li>
        </ul>
      </div>

      <label className="row" style={{ alignItems: "flex-start", gap: 8, margin: "14px 0",
        cursor: "pointer" }}>
        <input type="checkbox" checked={checked} style={{ marginTop: 4 }}
          onChange={(e) => setChecked(e.target.checked)} />
        <span style={{ fontSize: 14, lineHeight: 1.7 }}>
          위 내용을 확인했으며, 삭제된 정보는 복구할 수 없음에 동의합니다.
        </span>
      </label>

      <label className="field" style={{ marginBottom: 10 }}>
        <span className="label">비밀번호 확인</span>
        <input className="input" type="password" value={password} required
          autoComplete="current-password" onChange={(e) => setPassword(e.target.value)} />
      </label>

      <button className="btn" style={{ borderColor: "var(--alert)", color: "var(--alert)" }}
        disabled={busy || !checked || !password}>
        {busy ? "처리 중…" : "탈퇴하기"}
      </button>
    </form>
  );
}

/** 결제 내역과 취소·환불.
 *  돈에 관한 일은 사용자가 스스로 확인하고 되돌릴 수 있어야 한다.
 *  전자상거래법상 청약철회도 여기서 받는다. */
