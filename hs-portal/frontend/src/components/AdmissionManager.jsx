import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { errMsg, okMsg } from "../toast";

/* 학교 관리 → 취업/진학 정보 탭.
 * 플래티넘이 아니면 안내 화면만 보인다. 이건 화면 편의일 뿐이고, 실제로
 * 막는 것은 서버다(모든 관리 API 가 플랜 혜택을 다시 확인한다). */

const CUR_YEAR = new Date().getFullYear();
// 졸업은 2월이라 3월 전에는 작년 졸업생이 가장 최근이다.
const DEFAULT_YEAR = new Date().getMonth() < 2 ? CUR_YEAR - 1 : CUR_YEAR;

const EMPTY_STAT = {
  total_graduates: "", four_year_count: "", junior_college_count: "", other_higher_count: "",
  employment_count: "", other_count: "", same_field_count: "", diff_field_count: "",
  is_published: true,
};
const EMPTY_ROW = {
  university_name: "", university_type: "4_YEAR", region: "SEOUL", department_name: "",
  department_category: "ENGINEERING", admission_type: "", student_count: "",
};

export default function AdmissionManager({ onUpgrade }) {
  const [access, setAccess] = useState(null);
  const [dash, setDash] = useState(null);
  const [year, setYear] = useState(DEFAULT_YEAR);
  const [section, setSection] = useState("stats");
  const [msg, setMsg] = useState(null);

  const loadDash = () =>
    api.admissionDashboard().then((d) => {
      setDash(d);
      return d;
    }).catch((e) => setMsg(errMsg(e.message)));

  useEffect(() => {
    api.admissionAccess().then((a) => {
      setAccess(a);
      if (a.allowed) loadDash().then((d) => d?.years?.[0] && setYear(d.years[0].year));
    }).catch((e) => setMsg(errMsg(e.message)));
  }, []);

  if (!access) return <div className="empty"><p>{msg?.text || "불러오는 중…"}</p></div>;
  if (!access.allowed) return <SalesPanel access={access} onUpgrade={onUpgrade} />;
  if (!dash) return <div className="empty"><p>{msg?.text || "불러오는 중…"}</p></div>;

  const L = dash.labels;
  const yearRow = dash.years.find((y) => y.year === year);
  const vocational = dash.settings.effective_school_type === "VOCATIONAL_HIGH";
  const yearOptions = Array.from(new Set([...dash.years.map((y) => y.year), DEFAULT_YEAR, year]))
    .sort((a, b) => b - a);

  const sections = [
    ["stats", "졸업생 기본 통계"],
    ["records", "주요대학 진학 데이터"],
    ["employment", "취업 데이터"],
    ["employers", "주요 취업처"],
    ["import", "Excel 일괄 업로드"],
    ["settings", "공개 설정"],
  ];

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <Dashboard dash={dash} year={year} setYear={setYear} yearOptions={yearOptions}
        yearRow={yearRow} vocational={vocational} />

      <div className="adm-subtabs" role="tablist">
        {sections.map(([k, label]) => (
          <button key={k} role="tab" aria-selected={section === k}
            className={`btn btn-sm ${section === k ? "btn-primary" : "btn-ghost"}`}
            onClick={() => { setSection(k); setMsg(null); }}>
            {label}
          </button>
        ))}
      </div>

      {msg && <div className={`notice notice-${msg.type}`}>{msg.text}</div>}

      {section === "stats" && (
        <StatForm key={year} year={year} stat={yearRow?.stat} vocational={vocational}
          onSaved={() => loadDash()} setMsg={setMsg} />
      )}
      {section === "records" && <RecordsSection year={year} L={L} reload={loadDash} setMsg={setMsg} />}
      {section === "employment" && (
        <EmploymentForm key={year} year={year} L={L} current={yearRow?.employment || {}}
          stat={yearRow?.stat} reload={loadDash} setMsg={setMsg} />
      )}
      {section === "employers" && (
        <div className="panel">
          <h3>주요 취업처</h3>
          <EmployersEditor initial={dash.major_employers || []}
            onSave={async (items) => {
              await api.saveAdmissionEmployers(items);
              await loadDash();
            }} setMsg={setMsg} />
        </div>
      )}
      {section === "import" && <ImportSection reload={loadDash} setMsg={setMsg} />}
      {section === "settings" && (
        <SettingsForm dash={dash} L={L} reload={loadDash} setMsg={setMsg} />
      )}
    </div>
  );
}

/** 주요 취업처 입력 — 주요대학 진학 데이터처럼 표(행)로 입력한다.
 *  - 한 행에 기업 하나. [+ 행 추가] [+ 5행], 행마다 ↑↓ 순서 바꾸기·× 삭제
 *  - 엑셀에서 여러 칸을 복사해 붙여 넣으면 줄마다 행으로 나뉘어 들어간다(첫 칸만 쓴다)
 *  - Enter 를 누르면 다음 행으로 내려간다(마지막 행이면 새 행을 만든다)
 *  적은 순서대로 취업/진학 정보 화면의 '주요 취업처'에 보인다. */
const MAX_EMPLOYERS = 30;

export function EmployersEditor({ initial, onSave, setMsg }) {
  const pad = (list) => (list.length >= 3 ? list : [...list, ...Array(3 - list.length).fill("")]);
  const [rows, setRows] = useState(() => pad([...(initial || [])]));
  const [busy, setBusy] = useState(false);
  const refs = useRef([]);
  const names = rows.map((x) => x.trim()).filter(Boolean);
  const unique = Array.from(new Set(names));
  const dup = names.length - unique.length;

  const focusRow = (i) => setTimeout(() => refs.current[i]?.focus(), 0);
  const setRow = (i, v) => setRows(rows.map((r, j) => (j === i ? v : r)));
  const move = (i, d) => {
    const j = i + d;
    if (j < 0 || j >= rows.length) return;
    const next = [...rows];
    [next[i], next[j]] = [next[j], next[i]];
    setRows(next);
    focusRow(j);
  };
  const remove = (i) => setRows(rows.length > 1 ? rows.filter((_, j) => j !== i) : [""]);

  // 엑셀·표에서 복사한 여러 줄: 줄마다 한 행. 칸이 여러 개면(탭) 첫 칸만 쓴다.
  const onPaste = (i, e) => {
    const text = e.clipboardData.getData("text");
    if (!/[\r\n\t]/.test(text)) return;
    e.preventDefault();
    const lines = text.split(/\r?\n/).map((l) => l.split("\t")[0].trim()).filter(Boolean);
    if (!lines.length) return;
    const next = [...rows];
    lines.forEach((name, k) => {
      if (i + k < next.length && (k === 0 || !next[i + k].trim())) next[i + k] = name;
      else next.splice(i + k, 0, name);
    });
    setRows(next);
    setMsg?.(okMsg(`${lines.length}개 행을 붙여 넣었습니다.`));
  };
  const onKeyDown = (i, e) => {
    if (e.key !== "Enter" || e.nativeEvent.isComposing) return;
    e.preventDefault();
    if (i === rows.length - 1) setRows([...rows, ""]);
    focusRow(i + 1);
  };

  const save = async () => {
    setBusy(true);
    setMsg?.(null);
    try {
      await onSave(unique);
      setRows(pad([...unique]));
      setMsg?.(okMsg(unique.length ? `주요 취업처 ${unique.length}곳을 저장했습니다.` : "주요 취업처를 비웠습니다."));
    } catch (e) {
      setMsg?.(errMsg(e.message));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: "grid", gap: 8 }}>
      <p className="adm-note" style={{ margin: 0 }}>
        졸업생이 많이 취업한 기업을 한 행에 하나씩 적어 주세요(최대 {MAX_EMPLOYERS}곳).
        엑셀에서 여러 칸을 복사해 붙여 넣으면 행으로 나뉘어 들어갑니다. 적은 순서대로 공개 화면에 보입니다.
      </p>
      <div className="adm-table-wrap">
        <table className="table adm-input-table adm-emp-table">
          <thead>
            <tr><th style={{ width: 48 }}>순번</th><th>기업명</th><th style={{ width: 120 }} /></tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td className="adm-emp-no">{i + 1}</td>
                <td>
                  <input className="input" aria-label={`${i + 1}번 기업명`} value={r} maxLength={60}
                    ref={(el) => { refs.current[i] = el; }}
                    placeholder={i === 0 ? "예) 삼성전자" : ""}
                    onChange={(e) => setRow(i, e.target.value)}
                    onPaste={(e) => onPaste(i, e)} onKeyDown={(e) => onKeyDown(i, e)} />
                </td>
                <td style={{ whiteSpace: "nowrap" }}>
                  <button type="button" className="btn btn-ghost btn-sm" aria-label="위로"
                    disabled={i === 0} onClick={() => move(i, -1)}>↑</button>
                  <button type="button" className="btn btn-ghost btn-sm" aria-label="아래로"
                    disabled={i === rows.length - 1} onClick={() => move(i, 1)}>↓</button>
                  <button type="button" className="btn btn-ghost btn-sm" aria-label="행 삭제"
                    onClick={() => remove(i)}>×</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setRows([...rows, ""])}>+ 행 추가</button>
        <button type="button" className="btn btn-ghost btn-sm"
          onClick={() => setRows([...rows, "", "", "", "", ""])}>+ 5행</button>
        <button type="button" className="btn btn-signal btn-sm"
          disabled={busy || unique.length > MAX_EMPLOYERS} onClick={save}>
          {busy ? "저장 중…" : `${unique.length}곳 저장`}
        </button>
        <span className="adm-hint">
          {unique.length > MAX_EMPLOYERS ? `${MAX_EMPLOYERS}곳까지 적을 수 있습니다` : ""}
          {dup > 0 ? ` 같은 기업 ${dup}개는 한 번만 저장됩니다` : ""}
        </span>
      </div>
    </div>
  );
}

function SalesPanel({ access, onUpgrade }) {
  const items = ["대학 진학 통계", "주요 대학", "주요 학과", "대학 권역 분석", "4년제/전문대 분석",
    "연도별 진학 추세", "취업 분야·주요 취업처", "Excel 일괄 업로드", "취업/진학 정보 공개 페이지", "학교 진학 프로필"];
  return (
    <div className="panel adm-sales">
      <p className="adm-sales-lead">우리 학교의 취업/진학 정보를<br />학생과 학부모에게 제공하세요.</p>
      <span className="badge" style={{ background: "var(--plan-platinum)", color: "#fff" }}>PLATINUM</span>
      <ul className="adm-sales-list">
        {items.map((t) => <li key={t}>✓ {t}</li>)}
      </ul>
      {access.plan_paused && (
        <p className="adm-note">현재 플랜이 일시정지 상태라 이용할 수 없습니다. 관리자에게 문의해 주세요.</p>
      )}
      <button className="btn btn-signal" onClick={onUpgrade}>Platinum 시작하기</button>
      <p className="adm-note">학교가 직접 입력한 숫자로만 통계를 만듭니다. 외부 자료를 가져오거나 추정하지 않습니다.</p>
    </div>
  );
}

function Dashboard({ dash, year, setYear, yearOptions, yearRow, vocational }) {
  const st = yearRow?.stat;
  const [newYear, setNewYear] = useState("");
  const n = (v) => (v === null || v === undefined ? "—" : `${Number(v).toLocaleString()}`);
  return (
    <div className="panel">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", alignItems: "end" }}>
        <div>
          <h3 style={{ marginBottom: 4 }}>취업/진학 정보 관리</h3>
          <span className="label">
            데이터 최종 수정일 {dash.last_updated ? dash.last_updated.slice(0, 10).replaceAll("-", ".") : "—"}
          </span>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "end", flexWrap: "wrap" }}>
          <div className="field">
            <label className="label">졸업 연도</label>
            <select className="select" value={year} onChange={(e) => setYear(Number(e.target.value))}>
              {yearOptions.map((y) => <option key={y} value={y}>{y}년</option>)}
            </select>
          </div>
          <div className="field">
            <label className="label">다른 연도 추가</label>
            <div style={{ display: "flex", gap: 4 }}>
              <input className="input" style={{ width: 90 }} inputMode="numeric" placeholder="예: 2021"
                value={newYear} onChange={(e) => setNewYear(e.target.value.replace(/\D/g, "").slice(0, 4))} />
              <button className="btn btn-ghost btn-sm" disabled={newYear.length !== 4}
                onClick={() => { setYear(Number(newYear)); setNewYear(""); }}>이동</button>
            </div>
          </div>
          <Link className="btn btn-ghost btn-sm" to={`/schools/${dash.school.id}/admission`} target="_blank">
            공개 화면 보기
          </Link>
        </div>
      </div>

      <div className="adm-cards" style={{ marginTop: 14 }}>
        <Card label="졸업생" value={n(st?.total_graduates)} />
        <Card label="대학 진학" value={n(st?.admission_count)} />
        {(vocational || st?.employment_count > 0) && <Card label="취업" value={n(st?.employment_count)} />}
        <Card label="기타" value={n(st?.other_count)} />
        <Card label="4년제" value={n(st?.four_year_count)} />
        <Card label="전문대" value={n(st?.junior_college_count)} />
        <Card label="등록 대학" value={n(yearRow?.universities ?? 0)} unit="개" />
        <Card label="등록 학과" value={n(yearRow?.departments ?? 0)} unit="개" />
      </div>
      {yearRow?.warnings?.length > 0 && (
        <ul className="adm-warnings">
          {yearRow.warnings.map((w) => <li key={w}>{w}</li>)}
        </ul>
      )}
      {st && !st.is_published && <p className="adm-note">이 연도는 비공개로 저장되어 공개 화면에 나오지 않습니다.</p>}
    </div>
  );
}

function Card({ label, value, unit = "명" }) {
  return (
    <div className="stat">
      <span className="label">{label}</span>
      <div className="stat-value">{value}{value !== "—" && <small> {unit}</small>}</div>
    </div>
  );
}

function StatForm({ year, stat, vocational, onSaved, setMsg }) {
  const [f, setF] = useState(() => (stat ? {
    ...EMPTY_STAT,
    ...Object.fromEntries(Object.keys(EMPTY_STAT).map((k) => [k, stat[k] ?? EMPTY_STAT[k]])),
  } : EMPTY_STAT));
  const [busy, setBusy] = useState(false);
  const num = (k) => (f[k] === "" || f[k] === null ? 0 : Number(f[k]));
  const adm = num("four_year_count") + num("junior_college_count") + num("other_higher_count");
  const sum = adm + num("employment_count") + num("other_count");
  const g = num("total_graduates");
  const rate = (x) => (g ? `${((x / g) * 100).toFixed(1)}%` : "—");

  const save = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const body = { ...f };
      for (const k of Object.keys(EMPTY_STAT)) {
        if (k === "is_published") continue;
        const opt = k === "same_field_count" || k === "diff_field_count";
        body[k] = f[k] === "" || f[k] === null ? (opt ? null : 0) : Number(f[k]);
      }
      await api.saveAdmissionStat(year, body);
      setMsg(okMsg(`${year}년 기본 통계를 저장했습니다.`));
      onSaved();
    } catch (e) {
      setMsg(errMsg(e.message));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!window.confirm(`${year}년 기본 통계를 지울까요? 대학별 데이터는 남습니다.`)) return;
    try {
      await api.deleteAdmissionStat(year);
      setMsg(okMsg("삭제했습니다."));
      setF(EMPTY_STAT);
      onSaved();
    } catch (e) { setMsg(errMsg(e.message)); }
  };

  const field = (k, label, hint) => (
    <div className="field" key={k}>
      <label className="label">{label}</label>
      <input className="input" inputMode="numeric" value={f[k] ?? ""}
        onChange={(e) => setF({ ...f, [k]: e.target.value.replace(/\D/g, "").slice(0, 6) })} />
      {hint && <span className="adm-hint">{hint}</span>}
    </div>
  );

  return (
    <div className="panel">
      <h3>{year}년 졸업생 기본 통계</h3>
      <div className="adm-form-grid">
        {field("total_graduates", "졸업생 수")}
        {field("four_year_count", "4년제 대학 진학", rate(num("four_year_count")))}
        {field("junior_college_count", "전문대학 진학", rate(num("junior_college_count")))}
        {field("other_higher_count", "기타 교육기관 진학", rate(num("other_higher_count")))}
        {field("employment_count", "취업", rate(num("employment_count")))}
        {field("other_count", "기타 (군입대·미진학 등)", rate(num("other_count")))}
        {vocational && field("same_field_count", "동일계열 진학 (선택)")}
        {vocational && field("diff_field_count", "비동일계열 진학 (선택)")}
      </div>
      <p className={`adm-note ${sum > g ? "adm-bad" : ""}`}>
        대학 진학 {adm.toLocaleString()}명 ({rate(adm)}) · 합계 {sum.toLocaleString()}명 / 졸업생 {g.toLocaleString()}명
        {sum > g && " — 합계가 졸업생 수보다 많습니다."}
        {sum < g && g > 0 && ` · 미입력 ${(g - sum).toLocaleString()}명은 '미입력'으로 표시됩니다.`}
      </p>
      <label style={{ display: "flex", gap: 8, alignItems: "center", margin: "8px 0" }}>
        <input type="checkbox" checked={!!f.is_published}
          onChange={(e) => setF({ ...f, is_published: e.target.checked })} />
        이 연도를 공개 화면에 표시
      </label>
      <div style={{ display: "flex", gap: 8 }}>
        <button className="btn btn-signal" disabled={busy || f.total_graduates === ""} onClick={save}>
          {busy ? "저장 중…" : "저장"}
        </button>
        {stat && <button className="btn btn-ghost" onClick={remove}>이 연도 통계 삭제</button>}
      </div>
    </div>
  );
}

function RowSelect({ value, options, onChange, label }) {
  return (
    <select className="select" aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
      {options.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
    </select>
  );
}

function RecordsSection({ year, L, reload, setMsg }) {
  const [records, setRecords] = useState([]);
  const [rows, setRows] = useState([{ ...EMPTY_ROW }, { ...EMPTY_ROW }, { ...EMPTY_ROW }]);
  const [editing, setEditing] = useState(null);
  const [busy, setBusy] = useState(false);
  const admTypes = useMemo(() => [{ key: "", label: "전형 (선택)" }, ...L.admission_types], [L]);

  const load = () => api.admissionRecords(year).then(setRecords).catch((e) => setMsg(errMsg(e.message)));
  useEffect(() => { load(); }, [year]);

  const setRow = (i, k, v) => setRows(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  const filled = rows.filter((r) => r.university_name.trim() || r.department_name.trim() || r.student_count);

  const submit = async () => {
    if (!filled.length) return setMsg(errMsg("입력한 행이 없습니다."));
    setBusy(true);
    setMsg(null);
    try {
      await api.addAdmissionRecords(filled.map((r) => ({ ...r, year, student_count: Number(r.student_count || 0) })));
      setMsg(okMsg(`${filled.length}행을 등록했습니다.`));
      setRows([{ ...EMPTY_ROW }, { ...EMPTY_ROW }, { ...EMPTY_ROW }]);
      load();
      reload();
    } catch (e) {
      setMsg(errMsg(e.message));
    } finally {
      setBusy(false);
    }
  };

  const saveEdit = async () => {
    try {
      await api.updateAdmissionRecord(editing.id, { ...editing, student_count: Number(editing.student_count) });
      setEditing(null);
      setMsg(okMsg("수정했습니다."));
      load();
      reload();
    } catch (e) { setMsg(errMsg(e.message)); }
  };

  const remove = async (r) => {
    if (!window.confirm(`${r.university_name} ${r.department_name} ${r.student_count}명 행을 지울까요?`)) return;
    try {
      await api.deleteAdmissionRecord(r.id);
      load();
      reload();
    } catch (e) { setMsg(errMsg(e.message)); }
  };

  const togglePublish = async (r) => {
    try {
      await api.updateAdmissionRecord(r.id, { is_published: !r.is_published });
      load();
    } catch (e) { setMsg(errMsg(e.message)); }
  };

  const total = records.reduce((n, r) => n + r.student_count, 0);

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div className="panel">
        <h3>{year}년 주요대학 진학 데이터 입력</h3>
        <p className="adm-note">
          진학한 모든 학생을 적을 필요는 없습니다. 학교가 소개하고 싶은 <b>주요 대학</b>만 대학·학과별 인원으로 적어 주세요.
          학생 이름·학번은 적지 않습니다.
        </p>
        <div className="adm-table-wrap">
          <table className="table adm-input-table">
            <thead>
              <tr><th>대학명</th><th>유형</th><th>지역</th><th>학과</th><th>학과 계열</th><th>전형</th><th>인원</th><th /></tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td><input className="input" aria-label="대학명" value={r.university_name} maxLength={80}
                    onChange={(e) => setRow(i, "university_name", e.target.value)} placeholder="○○대학교" /></td>
                  <td><RowSelect label="대학 유형" value={r.university_type} options={L.university_types}
                    onChange={(v) => setRow(i, "university_type", v)} /></td>
                  <td><RowSelect label="지역" value={r.region} options={L.regions}
                    onChange={(v) => setRow(i, "region", v)} /></td>
                  <td><input className="input" aria-label="학과" value={r.department_name} maxLength={80}
                    onChange={(e) => setRow(i, "department_name", e.target.value)} placeholder="컴퓨터공학과" /></td>
                  <td><RowSelect label="학과 계열" value={r.department_category} options={L.department_categories}
                    onChange={(v) => setRow(i, "department_category", v)} /></td>
                  <td><RowSelect label="전형" value={r.admission_type} options={admTypes}
                    onChange={(v) => setRow(i, "admission_type", v)} /></td>
                  <td><input className="input" aria-label="인원" style={{ width: 70 }} inputMode="numeric"
                    value={r.student_count}
                    onChange={(e) => setRow(i, "student_count", e.target.value.replace(/\D/g, "").slice(0, 5))} /></td>
                  <td>
                    <button className="btn btn-ghost btn-sm" aria-label="행 삭제"
                      onClick={() => setRows(rows.length > 1 ? rows.filter((_, j) => j !== i) : [{ ...EMPTY_ROW }])}>×</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
          <button className="btn btn-ghost btn-sm" onClick={() => setRows([...rows, { ...EMPTY_ROW }])}>+ 행 추가</button>
          <button className="btn btn-ghost btn-sm"
            onClick={() => setRows([...rows, ...Array.from({ length: 5 }, () => ({ ...EMPTY_ROW }))])}>+ 5행</button>
          <button className="btn btn-signal btn-sm" disabled={busy} onClick={submit}>
            {busy ? "등록 중…" : `${filled.length}행 등록`}
          </button>
        </div>
      </div>

      <div className="panel">
        <h3>{year}년 등록된 데이터 <small className="label">({records.length}행 · {total.toLocaleString()}명)</small></h3>
        {records.length === 0 ? (
          <p className="adm-empty">아직 등록된 데이터가 없습니다.</p>
        ) : (
          <div className="adm-table-wrap">
            <table className="table">
              <thead>
                <tr><th>대학</th><th>유형</th><th>지역</th><th>학과</th><th>계열</th><th>인원</th><th>공개</th><th /></tr>
              </thead>
              <tbody>
                {records.map((r) => editing?.id === r.id ? (
                  <tr key={r.id}>
                    <td><input className="input" value={editing.university_name}
                      onChange={(e) => setEditing({ ...editing, university_name: e.target.value })} /></td>
                    <td><RowSelect label="대학 유형" value={editing.university_type} options={L.university_types}
                      onChange={(v) => setEditing({ ...editing, university_type: v })} /></td>
                    <td><RowSelect label="지역" value={editing.region} options={L.regions}
                      onChange={(v) => setEditing({ ...editing, region: v })} /></td>
                    <td><input className="input" value={editing.department_name}
                      onChange={(e) => setEditing({ ...editing, department_name: e.target.value })} /></td>
                    <td><RowSelect label="학과 계열" value={editing.department_category} options={L.department_categories}
                      onChange={(v) => setEditing({ ...editing, department_category: v })} /></td>
                    <td><input className="input" style={{ width: 70 }} inputMode="numeric" value={editing.student_count}
                      onChange={(e) => setEditing({ ...editing, student_count: e.target.value.replace(/\D/g, "") })} /></td>
                    <td />
                    <td style={{ whiteSpace: "nowrap" }}>
                      <button className="btn btn-signal btn-sm" onClick={saveEdit}>저장</button>{" "}
                      <button className="btn btn-ghost btn-sm" onClick={() => setEditing(null)}>취소</button>
                    </td>
                  </tr>
                ) : (
                  <tr key={r.id}>
                    <td>{r.university_name}</td>
                    <td>{r.university_type_label}</td>
                    <td>{r.region_label}</td>
                    <td>{r.department_name}</td>
                    <td>{r.department_category_label}</td>
                    <td>{r.student_count}명</td>
                    <td>
                      <button className="btn btn-ghost btn-sm" onClick={() => togglePublish(r)}>
                        {r.is_published ? "공개" : "비공개"}
                      </button>
                    </td>
                    <td style={{ whiteSpace: "nowrap" }}>
                      <button className="btn btn-ghost btn-sm" onClick={() => setEditing({ ...r })}>수정</button>{" "}
                      <button className="btn btn-ghost btn-sm" onClick={() => remove(r)}>삭제</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function EmploymentForm({ year, L, current, stat, reload, setMsg }) {
  const [f, setF] = useState(() => Object.fromEntries(L.employment_fields.map((x) => [x.key, current[x.key] ?? ""])));
  const total = Object.values(f).reduce((n, v) => n + Number(v || 0), 0);
  const save = async () => {
    try {
      const items = Object.fromEntries(Object.entries(f).map(([k, v]) => [k, Number(v || 0)]));
      await api.saveAdmissionEmployment(year, items);
      setMsg(okMsg(`${year}년 취업 분야를 저장했습니다.`));
      reload();
    } catch (e) { setMsg(errMsg(e.message)); }
  };
  return (
    <div className="panel">
      <h3>{year}년 취업 분야</h3>
      <div className="adm-form-grid">
        {L.employment_fields.map((x) => (
          <div className="field" key={x.key}>
            <label className="label">{x.label}</label>
            <input className="input" inputMode="numeric" value={f[x.key]}
              onChange={(e) => setF({ ...f, [x.key]: e.target.value.replace(/\D/g, "").slice(0, 6) })} />
          </div>
        ))}
      </div>
      <p className={`adm-note ${stat && total > stat.employment_count ? "adm-bad" : ""}`}>
        합계 {total.toLocaleString()}명{stat ? ` / 기본 통계의 취업자 ${stat.employment_count.toLocaleString()}명` : " (기본 통계를 먼저 입력하면 합계를 비교합니다)"}
      </p>
      <button className="btn btn-signal" onClick={save}>저장</button>
    </div>
  );
}

function ImportSection({ reload, setMsg }) {
  const [file, setFile] = useState(null);
  const [report, setReport] = useState(null);
  const [replace, setReplace] = useState(false);
  const [busy, setBusy] = useState(false);

  const download = async (kind, fmt) => {
    try { await api.downloadAdmissionFile(kind, fmt); } catch (e) { setMsg(errMsg(e.message)); }
  };

  const check = async (f = file, rep = replace) => {
    if (!f) return;
    setBusy(true);
    setMsg(null);
    try {
      setReport(await api.importAdmission(f, { replace: rep }));
    } catch (e) {
      setReport(null);
      setMsg(errMsg(e.message));
    } finally {
      setBusy(false);
    }
  };

  const commit = async (skipErrors) => {
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.importAdmission(file, { commit: true, skipErrors, replace });
      setMsg(okMsg(`${r.inserted.toLocaleString()}행을 업로드했습니다.${r.replaced ? ` (기존 ${r.replaced}행 교체)` : ""}`));
      setReport(null);
      setFile(null);
      reload();
    } catch (e) {
      setMsg(errMsg(e.message));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel">
      <h3>Excel / CSV 일괄 업로드</h3>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
        <button className="btn btn-ghost btn-sm" onClick={() => download("template", "xlsx")}>Excel 템플릿 다운로드</button>
        <button className="btn btn-ghost btn-sm" onClick={() => download("template", "csv")}>CSV 템플릿</button>
        <button className="btn btn-ghost btn-sm" onClick={() => download("export", "xlsx")}>등록된 데이터 내보내기</button>
      </div>
      <p className="adm-note">
        열: 연도 · 대학명 · 대학유형(4년제/전문대/기타) · 지역(서울/경기·인천/충청권 … 또는 시·도 이름) ·
        학과 · 학과계열 · 진학자수 · 전형(선택). 2MB, 5,000행까지. 학생 개인정보는 넣지 마세요.
      </p>
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <input type="file" accept=".xlsx,.csv"
          onChange={(e) => { const f = e.target.files?.[0] || null; setFile(f); setReport(null); if (f) check(f); }} />
        <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13.5 }}>
          <input type="checkbox" checked={replace}
            onChange={(e) => { setReplace(e.target.checked); if (file) check(file, e.target.checked); }} />
          파일에 있는 연도의 기존 데이터를 지우고 새로 올리기
        </label>
      </div>

      {busy && <p className="adm-note">확인 중…</p>}
      {report && (
        <div className="adm-report">
          <p><b>총 {report.total.toLocaleString()}개 데이터 발견</b></p>
          <p>정상 {report.valid.toLocaleString()}개 · <span className={report.error_count ? "adm-bad" : ""}>오류 {report.error_count.toLocaleString()}개</span></p>
          {Object.keys(report.years).length > 0 && (
            <p className="adm-note">연도별: {Object.entries(report.years).map(([y, n]) => `${y}년 ${n}명`).join(" · ")}</p>
          )}
          {report.general_errors.length > 0 && (
            <ul className="adm-warnings">{report.general_errors.map((g) => <li key={g}>{g}</li>)}</ul>
          )}
          {report.errors.length > 0 && (
            <details open={report.errors.length <= 10}>
              <summary>오류 확인</summary>
              <ul className="adm-errors">
                {report.errors.map((e) => <li key={e.row}><b>{e.row}행</b> {e.messages.join(", ")}</li>)}
              </ul>
            </details>
          )}
          <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
            <button className="btn btn-signal btn-sm"
              disabled={busy || report.error_count > 0 || report.general_errors.length > 0 || !report.valid}
              onClick={() => commit(false)}>업로드</button>
            {report.error_count > 0 && (
              <button className="btn btn-ghost btn-sm"
                disabled={busy || report.general_errors.length > 0 || !report.valid}
                onClick={() => commit(true)}>오류 행 제외하고 {report.valid}개 업로드</button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function SettingsForm({ dash, L, reload, setMsg }) {
  const [f, setF] = useState({
    visibility: dash.settings.visibility,
    school_type: dash.settings.school_type,
    small_count_threshold: dash.settings.small_count_threshold,
  });
  const save = async () => {
    try {
      await api.saveAdmissionSettings({ ...f, small_count_threshold: Number(f.small_count_threshold) });
      setMsg(okMsg("공개 설정을 저장했습니다."));
      reload();
    } catch (e) { setMsg(errMsg(e.message)); }
  };
  const autoType = L.school_types.find((t) => t.key === dash.settings.effective_school_type)?.label;
  return (
    <div className="panel">
      <h3>공개 설정</h3>
      <fieldset className="adm-radio">
        <legend className="label">공개 범위</legend>
        {L.visibility.map((v) => (
          <label key={v.key}>
            <input type="radio" name="vis" checked={f.visibility === v.key}
              onChange={() => setF({ ...f, visibility: v.key })} />
            {v.label}
          </label>
        ))}
      </fieldset>
      <p className="adm-note">
        '전체 공개'만 검색엔진에 노출됩니다. 비공개여도 학교 계정에서는 미리 볼 수 있습니다.
      </p>
      <div className="adm-form-grid" style={{ marginTop: 10 }}>
        <div className="field">
          <label className="label">학교 유형</label>
          <select className="select" value={f.school_type} onChange={(e) => setF({ ...f, school_type: e.target.value })}>
            <option value="">자동 ({dash.school.category} → {autoType})</option>
            {L.school_types.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
          </select>
        </div>
        <div className="field">
          <label className="label">소수 인원 표시</label>
          <select className="select" value={f.small_count_threshold}
            onChange={(e) => setF({ ...f, small_count_threshold: Number(e.target.value) })}>
            <option value={0}>사용 안 함 (인원 그대로)</option>
            {[2, 3, 5].map((n) => <option key={n} value={n}>{n}명 미만은 "소수 인원"</option>)}
          </select>
        </div>
      </div>
      <button className="btn btn-signal" style={{ marginTop: 12 }} onClick={save}>저장</button>
      {dash.indexable && <p className="adm-note">현재 검색엔진 노출 대상입니다.</p>}
    </div>
  );
}
