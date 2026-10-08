import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { ORG } from "../org";
import { useSeo } from "../seo";

/** 학교 계정 발급 신청.
 *
 * 학교 계정은 여전히 관리자만 만든다. 이 화면은 그 앞단이다 — 학교가 남기면
 * 운영자가 전화로 확인한 뒤 승인하고, 그때 계정이 메일로 나간다.
 * 로그인 없이 쓰는 화면이다(계정이 없어서 신청하는 것이다).
 */
const REGIONS = ["서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
  "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"];

const EMPTY = {
  school_level: "high", region: "",
  school_id: null, school_name: "", manager_name: "", manager_position: "",
  manager_phone: "", manager_email: "", school_phone: "", call_time: "",
  privacy_consent: false, notice_consent: false,
};

export default function SchoolAccountRequest() {
  const [f, setF] = useState(EMPTY);
  const [notice, setNotice] = useState(null);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useSeo({
    title: "학교 계정 신청",
    description: "직업계고·특성화고 선생님을 위한 학교 계정 발급 신청. 담당자 확인 전화 후 계정을 보내드립니다.",
    path: "/school-account-request",
  });

  useEffect(() => { api.schoolRequestPrivacy().then(setNotice).catch(() => {}); }, []);

  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    if (!f.privacy_consent) return setError("개인정보 수집·이용에 동의해 주세요.");
    if (!f.school_name.trim()) return setError("학교를 선택하거나 학교명을 적어 주세요.");
    if (f.school_level === "middle" && !f.region) return setError("지역을 골라 주세요.");
    setBusy(true);
    try {
      await api.createSchoolRequest({
        ...f,
        school_name: f.school_name.trim(),
        manager_name: f.manager_name.trim(),
        manager_email: f.manager_email.trim(),
      });
      setDone(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <div className="wrap" style={{ maxWidth: 520, padding: "56px 0" }}>
        <span className="label">학교 계정 신청</span>
        <h1 style={{ fontSize: 24, margin: "8px 0 14px" }}>신청이 접수되었습니다</h1>
        <div className="notice notice-success">
          적어 주신 번호로 담당자 확인 전화를 드립니다. 확인이 끝나면 계정 아이디와
          임시 비밀번호를 <b>{f.manager_email}</b> 로 보내드립니다.
        </div>
        <p style={{ fontSize: 13.5, color: "var(--steel)", marginTop: 16, lineHeight: 1.8 }}>
          메일이 보이지 않으면 스팸함을 확인해 주세요. 며칠이 지나도 연락이 없으면
          다시 신청하지 마시고 {ORG.contactPhone} 또는 {ORG.contactEmail} 로 문의해 주세요.
        </p>
        <Link className="btn btn-ghost btn-sm" to="/">홈으로</Link>
      </div>
    );
  }

  return (
    <div className="wrap" style={{ maxWidth: 520, padding: "56px 0" }}>
      <span className="label">학교 계정 신청</span>
      <h1 style={{ fontSize: 26, margin: "8px 0 6px" }}>학교 계정을 신청합니다</h1>
      <p style={{ fontSize: 13.5, color: "var(--steel)", marginTop: 0, lineHeight: 1.8 }}>
        신청하시면 <b>담당자 확인 전화</b>를 드린 뒤 계정을 보내드립니다.
      </p>

      <form onSubmit={submit} style={{ display: "grid", gap: 14, marginTop: 20 }}>
        <fieldset className="level-pick">
          <legend className="label">학교 유형</legend>
          {[["high", "고등학교", "직업계고·특성화고 — 학교 정보·학과·사진, 학교 일정, 문의 답변을 직접 관리합니다."],
            ["middle", "중학교", "직업계고 진학을 준비하는 중학교 — 직업계고 정보 탐색과 진학 지원 자료를 이용합니다."]]
            .map(([k, label, desc]) => (
              <label key={k} className={`level-opt${f.school_level === k ? " on" : ""}`}>
                <input type="radio" name="school_level" value={k} checked={f.school_level === k}
                  onChange={() => setF({ ...f, school_level: k, school_id: null, school_name: "", region: "" })} />
                <span><b>{label}</b><small>{desc}</small></span>
              </label>
            ))}
        </fieldset>

        {f.school_level === "high" ? (
          <SchoolPicker value={f} onPick={(school_id, school_name) =>
            setF({ ...f, school_id, school_name })} />
        ) : (
          <>
            <div className="field">
              <label className="label" htmlFor="mschool">중학교 이름</label>
              <input id="mschool" className="input" value={f.school_name} required maxLength={120}
                onChange={set("school_name")} placeholder="예: 푸른중학교" />
            </div>
            <div className="field">
              <label className="label" htmlFor="mregion">지역</label>
              <select id="mregion" className="input" value={f.region} required onChange={set("region")}>
                <option value="">지역 선택</option>
                {REGIONS.map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
            </div>
          </>
        )}

        <div className="field">
          <label className="label" htmlFor="mname">담당자 이름</label>
          <input id="mname" className="input" value={f.manager_name} required maxLength={40}
            onChange={set("manager_name")} placeholder="예: 김선생" />
        </div>
        <div className="field">
          <label className="label" htmlFor="mpos">직위</label>
          <input id="mpos" className="input" value={f.manager_position} maxLength={40}
            onChange={set("manager_position")} placeholder="예: 교무부장 / 취업담당" />
        </div>
        <div className="field">
          <label className="label" htmlFor="mphone">담당자 휴대전화</label>
          <input id="mphone" className="input" value={f.manager_phone} required inputMode="tel"
            onChange={set("manager_phone")} placeholder="010-0000-0000" />
          <span className="adm-hint">이 번호로 확인 전화를 드립니다.</span>
        </div>
        <div className="field">
          <label className="label" htmlFor="memail">담당자 이메일</label>
          <input id="memail" className="input" type="email" value={f.manager_email} required
            onChange={set("manager_email")} placeholder="office@school.kr" />
          <span className="adm-hint">이 주소가 학교 계정 아이디가 되고, 계정 안내도 여기로 갑니다.</span>
        </div>
        <div className="field">
          <label className="label" htmlFor="sphone">학교 대표번호</label>
          <input id="sphone" className="input" value={f.school_phone} inputMode="tel"
            onChange={set("school_phone")} placeholder="02-000-0000 (선택)" />
        </div>
        <div className="field">
          <label className="label" htmlFor="ctime">통화 가능한 시간대</label>
          <input id="ctime" className="input" value={f.call_time} maxLength={60}
            onChange={set("call_time")} placeholder="예: 평일 오후 2~4시 (선택)" />
        </div>

        {notice && (
          <details className="panel" style={{ margin: 0 }}>
            <summary style={{ cursor: "pointer", fontWeight: 600, fontSize: 14 }}>
              개인정보 수집·이용 안내
            </summary>
            <ul style={{ fontSize: 13, color: "var(--steel)", lineHeight: 1.8, marginBottom: 0 }}>
              <li>수집 항목: {notice.collected.join(", ")}</li>
              <li>이용 목적: {notice.purpose}</li>
              <li>보관 기간: {notice.retention}</li>
              <li>열람 범위: {notice.recipient}</li>
              <li>{notice.right_to_refuse}</li>
            </ul>
          </details>
        )}

        {f.school_level === "high" && notice?.notice_optional && (
          <div className="panel" style={{ margin: 0 }}>
            <label style={{ display: "flex", gap: 8, alignItems: "flex-start", cursor: "pointer" }}>
              <input type="checkbox" checked={f.notice_consent} style={{ marginTop: 3 }}
                onChange={(e) => setF({ ...f, notice_consent: e.target.checked })} />
              <span style={{ fontSize: 13.5, lineHeight: 1.6 }}>
                우리동네직업계고 공지를 이메일·문자로 받는 데(개인정보 수집·이용) 동의합니다. <b>(선택)</b>
              </span>
            </label>
            <ul style={{ fontSize: 12.5, color: "var(--steel)", lineHeight: 1.7, margin: "8px 0 0" }}>
              <li>항목: {notice.notice_optional.items}</li>
              <li>목적: {notice.notice_optional.purpose}</li>
              <li>보관: {notice.notice_optional.retention}</li>
              <li>{notice.notice_optional.right_to_refuse}</li>
            </ul>
          </div>
        )}

        <label style={{ display: "flex", gap: 8, alignItems: "flex-start", cursor: "pointer" }}>
          <input type="checkbox" checked={f.privacy_consent} style={{ marginTop: 3 }}
            onChange={(e) => setF({ ...f, privacy_consent: e.target.checked })} />
          <span style={{ fontSize: 13.5, lineHeight: 1.6 }}>
            개인정보 수집·이용에 동의합니다. <b>(필수)</b>
          </span>
        </label>

        {error && <div className="notice notice-error">{error}</div>}
        <button className="btn btn-signal" disabled={busy}>
          {busy ? "접수 중…" : "신청하기"}
        </button>
      </form>

      <p style={{ fontSize: 13, color: "var(--steel-light)", marginTop: 18, lineHeight: 1.8 }}>
        학생이신가요? <Link to="/signup" style={{ color: "var(--ink)", fontWeight: 600 }}>학생 회원가입</Link>
        {" 을 이용해 주세요."}
      </p>
    </div>
  );
}

/** 학교 검색. 목록에서 고르는 것이 기본이고, 없으면 직접 적게 한다.
 *  고른 학교는 id 가 함께 넘어가서 승인할 때 어느 학교인지 헷갈리지 않는다. */
function SchoolPicker({ value, onPick }) {
  const [q, setQ] = useState("");
  const [list, setList] = useState([]);
  const [open, setOpen] = useState(false);
  const [manual, setManual] = useState(false);
  const timer = useRef(null);

  useEffect(() => {
    if (manual || !q.trim() || q.trim().length < 2) { setList([]); return undefined; }
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      api.schools({ name: q.trim(), size: 8 })
        .then((res) => { setList(res.items || []); setOpen(true); })
        .catch(() => setList([]));
    }, 250);
    return () => clearTimeout(timer.current);
  }, [q, manual]);

  if (manual) {
    return (
      <div className="field">
        <label className="label" htmlFor="sname">학교명 (직접 입력)</label>
        <input id="sname" className="input" value={value.school_name} required maxLength={120}
          onChange={(e) => onPick(null, e.target.value)} placeholder="예: 우리동네고등학교" />
        <span className="adm-hint">
          목록에 없는 학교는 이름을 적어 주세요. 확인 전화 때 함께 확인합니다.{" "}
          <button type="button" className="btn btn-ghost btn-sm"
            onClick={() => { setManual(false); onPick(null, ""); }}>목록에서 찾기</button>
        </span>
      </div>
    );
  }

  return (
    <div className="field" style={{ position: "relative" }}>
      <label className="label" htmlFor="sq">학교 찾기</label>
      {value.school_id ? (
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <b style={{ flex: 1 }}>{value.school_name}</b>
          <button type="button" className="btn btn-ghost btn-sm"
            onClick={() => { onPick(null, ""); setQ(""); }}>다시 고르기</button>
        </div>
      ) : (
        <>
          <input id="sq" className="input" value={q} autoComplete="off"
            onChange={(e) => setQ(e.target.value)} placeholder="학교 이름 두 글자 이상" />
          {open && list.length > 0 && (
            <ul className="school-picker-list">
              {list.map((s) => (
                <li key={s.id}>
                  <button type="button" onClick={() => { onPick(s.id, s.name); setOpen(false); }}>
                    {s.name}<small>{s.region} · {s.category}</small>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <span className="adm-hint">
            {q.trim().length >= 2 && list.length === 0 ? "찾는 학교가 없나요? " : ""}
            <button type="button" className="btn btn-ghost btn-sm"
              onClick={() => { setManual(true); onPick(null, q.trim()); }}>
              학교명 직접 입력
            </button>
          </span>
        </>
      )}
    </div>
  );
}
