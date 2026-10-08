import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useSeo } from "../seo";
import { BarList, Donut, RankList, TrendChart, pct } from "../components/AdmissionCharts";

/** 학교 취업/진학 정보 공개 페이지 (플래티넘 학교가 공개한 경우만 열린다).
 *  [진학 정보] [취업 정보] [주요 취업처] 세 갈래로 나눠 보여 준다.
 *  권한·공개 범위는 서버가 판단한다. 여기서는 받은 것만 그린다. */
export default function SchoolAdmission() {
  const { id } = useParams();
  const [sp, setSp] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const filters = {
    year: sp.get("year") || "",
    university_type: sp.get("university_type") || "",
    region: sp.get("region") || "",
    department_category: sp.get("department_category") || "",
  };
  const key = JSON.stringify(filters);

  useEffect(() => {
    setError(null);
    // filters 는 매 렌더 새 객체라 key(문자열)로 바뀐 때만 다시 받는다.
    api.schoolAdmission(id, filters).then(setData).catch((e) => { setData(null); setError(e.message); });
  }, [id, key]);

  const s = data?.summary;
  useSeo({
    title: data ? `${data.school.name} 취업/진학 정보` : "학교 취업/진학 정보",
    description: data && s
      ? `${data.school.name}(${data.school_type_label}) ${data.selected_years.join("·")}년 졸업생 ${s.total_graduates}명 기준 대학 진학률 ${pct(s.admission_rate)}, 4년제 ${pct(s.four_year_rate)}, 전문대 ${pct(s.junior_college_rate)}. 학교가 직접 입력한 진학 통계입니다.`
      : undefined,
    path: `/schools/${id}/admission`,
    // 전체 공개가 아니거나 못 여는 페이지는 검색엔진에 싣지 않는다.
    noindex: !data || !data.indexable,
  });

  const setFilter = (k, v) => {
    const next = new URLSearchParams(sp);
    if (v) next.set(k, v); else next.delete(k);
    // 주소를 바꿔도 "학교 상세에서 왔다"는 표시(state)는 들고 간다.
    setSp(next, { replace: true, state: location.state });
  };

  // 학교 상세에서 들어왔으면 뒤로 가고, 아니면(공유 링크 등) 현재 기록을 학교 상세로
  // 바꿔 끼운다. 새 기록을 쌓으면 상세의 '뒤로'가 다시 여기로 와서 두 화면을
  // 끝없이 오간다(2026-09-19 신고).
  const backToSchool = (e) => {
    e.preventDefault();
    if (location.state?.from === "school") navigate(-1);
    else navigate(`/schools/${id}`, { replace: true });
  };
  const backLink = (
    <Link to={`/schools/${id}`} onClick={backToSchool} className="btn btn-ghost btn-sm"
      style={{ alignSelf: "flex-start" }}>← 학교 정보</Link>
  );

  if (error) {
    return (
      <div className="wrap" style={{ padding: "40px 0 60px" }}>
        {backLink}
        <div className="empty" style={{ marginTop: 20 }}>
          <p>{error}</p>
          {/로그인/.test(error) && <Link className="btn btn-signal btn-sm" to="/login">로그인</Link>}
        </div>
      </div>
    );
  }
  if (!data) return <div className="wrap" style={{ padding: 60 }}><div className="empty"><p>불러오는 중…</p></div></div>;

  const L = data.labels;
  const vocational = data.school_type === "VOCATIONAL_HIGH";
  const showEmployment = vocational || (s && s.employment_count > 0);
  const yearLabel = data.selected_year === "recent3"
    ? `최근 ${data.selected_years.length}개년(${data.selected_years.join("·")}) 졸업생 기준`
    : data.selected_years.length ? `${data.selected_years[0]}년 졸업생 기준` : "";
  const filtered = data.filters.university_type || data.filters.region || data.filters.department_category;

  return (
    <div className="wrap adm-page" style={{ padding: "24px 0 60px" }}>
      {backLink}

      <header className="adm-head">
        <div>
          <span className="label">취업/진학 정보</span>
          <h1>{data.school.name}</h1>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            <span className="badge badge-cat">{data.school_type_label}</span>
            <span className="badge">{data.school.region}</span>
            {data.visibility !== "PUBLIC" && <span className="badge">미리보기 · {labelOf(L.visibility, data.visibility)}</span>}
          </div>
        </div>
        {yearLabel && <p className="adm-basis">{yearLabel}</p>}
      </header>

      <nav className="adm-jump" aria-label="바로 가기">
        <a href="#adm-admission">진학 정보</a>
        <a href="#adm-employment">취업 정보</a>
        <a href="#adm-employers">주요 취업처</a>
      </nav>

      <h2 className="adm-section-title" id="adm-admission">진학 정보</h2>
      {data.years.length === 0 ? (
        <div className="empty"><p>아직 공개된 진학 데이터가 없습니다.</p></div>
      ) : (
        <>
          <div className="adm-filters" role="group" aria-label="진학 정보 필터">
            <select className="select" value={data.selected_year} aria-label="연도"
              onChange={(e) => setFilter("year", e.target.value)}>
              {data.years.map((y) => <option key={y} value={String(y)}>{y}년 졸업</option>)}
              {data.years.length > 1 && <option value="recent3">최근 3개년 합계</option>}
            </select>
            <FilterSelect label="대학 유형" value={filters.university_type} options={L.university_types}
              onChange={(v) => setFilter("university_type", v)} />
            <FilterSelect label="지역" value={filters.region} options={L.regions}
              onChange={(v) => setFilter("region", v)} />
            <FilterSelect label="학과 계열" value={filters.department_category} options={L.department_categories}
              onChange={(v) => setFilter("department_category", v)} />
            {filtered && (
              <button className="btn btn-ghost btn-sm" onClick={() => {
                const next = new URLSearchParams();
                if (filters.year) next.set("year", filters.year);
                setSp(next, { replace: true, state: location.state });
              }}>필터 해제</button>
            )}
          </div>

          <SummaryCards s={s} showEmployment={showEmployment} />

          <div className="adm-grid">
            <div className="panel">
              <Donut title="졸업 후 진로" data={data.path_distribution} />
            </div>
            <div className="panel">
              <Donut title="대학 진학 유형" data={data.type_distribution} />
            </div>
          </div>

          {filtered && (
            <p className="adm-note">
              필터는 대학·학과별 입력 자료(아래 차트와 순위)에만 적용됩니다.
              위 요약은 학교 전체 졸업생 기준입니다. · 필터 결과 {data.record_total.toLocaleString()}명
            </p>
          )}

          <div className="adm-grid">
            <div className="panel"><BarList title="진학 대학 권역" data={data.region_distribution} /></div>
            <div className="panel"><BarList title="진학 학과 계열" data={data.category_distribution} /></div>
          </div>

          <div className="adm-grid">
            <div className="panel">
              <RankList title="주요 진학 대학" items={data.top_universities} subKey="university_type_label" />
            </div>
            <div className="panel">
              <RankList title="주요 진학 학과" items={data.top_departments} subKey="department_category_label" />
            </div>
          </div>

          {vocational && (
            <div className="panel">
              <Donut title="진학 계열 (고교 전공 기준)" empty="동일·비동일 계열이 입력되지 않았습니다."
                data={sameFieldData(s)} />
            </div>
          )}

          <div className="panel"><TrendChart trend={data.trend} showEmployment={showEmployment} /></div>

          <div className="adm-grid">
            <Recent3 r={data.recent3} showEmployment={showEmployment} />
            <Profile p={data.profile} />
          </div>
        </>
      )}

      <h2 className="adm-section-title" id="adm-employment">취업 정보</h2>
      {data.years.length > 0 && showEmployment ? (
        <div className="adm-grid">
          <div className="panel">
            <h4 className="adm-chart-title">취업 현황</h4>
            <dl className="adm-kv">
              <div><dt>취업자</dt><dd>{s ? `${s.employment_count.toLocaleString()}명` : "—"}</dd></div>
              <div><dt>취업률 (졸업생 대비)</dt><dd>{pct(s?.employment_rate)}</dd></div>
              {data.recent3?.available && <div><dt>최근 3년 취업률</dt><dd>{pct(data.recent3.employment_rate)}</dd></div>}
            </dl>
            {yearLabel && <p className="adm-note">{yearLabel}</p>}
          </div>
          <div className="panel">
            <BarList title="취업 분야" data={data.employment_fields}
              empty="취업 분야가 입력되지 않았습니다." />
          </div>
        </div>
      ) : (
        <div className="empty"><p>아직 공개된 취업 데이터가 없습니다.</p></div>
      )}

      <h2 className="adm-section-title" id="adm-employers">주요 취업처</h2>
      {(data.major_employers || []).length > 0 ? (
        <div className="panel">
          <ol className="adm-employers">
            {data.major_employers.map((name) => <li key={name}>{name}</li>)}
          </ol>
          <p className="adm-note">졸업생이 취업한 주요 기업입니다. 학교가 직접 입력했습니다.</p>
        </div>
      ) : (
        <div className="empty"><p>아직 입력된 주요 취업처가 없습니다.</p></div>
      )}

      <div className="adm-disclaimer">
        {data.disclaimer.map((t) => <p key={t}>※ {t}</p>)}
        {data.small_count_threshold > 0 && (
          <p>※ {data.small_count_threshold}명 미만인 대학·학과는 인원 대신 "소수 인원"으로 표시합니다.</p>
        )}
        {data.last_updated && <p>데이터 최종 수정일 {fmtDate(data.last_updated)}</p>}
      </div>
    </div>
  );
}

function FilterSelect({ label, value, options, onChange }) {
  return (
    <select className="select" value={value} aria-label={label} onChange={(e) => onChange(e.target.value)}>
      <option value="">{label} 전체</option>
      {options.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
    </select>
  );
}

function SummaryCards({ s, showEmployment }) {
  if (!s) return null;
  const cards = [
    { label: "졸업생", value: `${s.total_graduates.toLocaleString()}명` },
    { label: "대학 진학", value: `${s.admission_count.toLocaleString()}명`, sub: pct(s.admission_rate) },
    { label: "4년제", value: `${s.four_year_count.toLocaleString()}명`, sub: pct(s.four_year_rate) },
    { label: "전문대", value: `${s.junior_college_count.toLocaleString()}명`, sub: pct(s.junior_college_rate) },
    s.other_higher_count > 0 && { label: "기타 교육기관", value: `${s.other_higher_count.toLocaleString()}명`, sub: pct(s.other_higher_rate) },
    showEmployment && { label: "취업", value: `${s.employment_count.toLocaleString()}명`, sub: pct(s.employment_rate) },
  ].filter(Boolean);
  return (
    <div className="adm-cards">
      {cards.map((c) => (
        <div className="stat" key={c.label}>
          <span className="label">{c.label}</span>
          <div className="stat-value">{c.value}</div>
          {c.sub && <div className="adm-card-sub">졸업생 대비 {c.sub}</div>}
        </div>
      ))}
    </div>
  );
}

function sameFieldData(s) {
  if (!s || (s.same_field_count == null && s.diff_field_count == null)) return [];
  const same = s.same_field_count || 0;
  const diff = s.diff_field_count || 0;
  const t = same + diff;
  if (!t) return [];
  return [
    { key: "same", label: "동일계열 진학", count: same, percent: Math.round((same * 1000) / t) / 10 },
    { key: "diff", label: "비동일계열 진학", count: diff, percent: Math.round((diff * 1000) / t) / 10 },
  ].filter((d) => d.count);
}

function Recent3({ r, showEmployment }) {
  const n = r.year_count || 0;
  const title = r.complete ? "최근 3년 지표" : `최근 ${n}개년 지표`;
  return (
    <div className="panel">
      <h4 className="adm-chart-title">{r.available ? title : "최근 3년 지표"}</h4>
      {!r.available ? (
        <p className="adm-empty">{r.message}</p>
      ) : (
        <>
          <dl className="adm-kv">
            <div><dt>대학 진학률</dt><dd>{pct(r.admission_rate)}</dd></div>
            <div><dt>4년제 진학률</dt><dd>{pct(r.four_year_rate)}</dd></div>
            <div><dt>전문대 진학률</dt><dd>{pct(r.junior_college_rate)}</dd></div>
            {showEmployment && <div><dt>취업률</dt><dd>{pct(r.employment_rate)}</dd></div>}
            <div>
              <dt>수도권 대학 진학 비율</dt>
              <dd>{pct(r.capital_area_ratio)}</dd>
            </div>
          </dl>
          <p className="adm-note">
            기준 연도 {r.years.join("·")} · 졸업생 {r.total_graduates.toLocaleString()}명 · 학교 직접 입력 자료.
            {r.capital_area_basis > 0 && ` 수도권 비율은 대학별로 입력된 ${r.capital_area_basis.toLocaleString()}명 기준입니다.`}
            {!r.complete && " 3개년 자료가 모두 입력되지 않아 입력된 연도만으로 계산했습니다."}
          </p>
        </>
      )}
    </div>
  );
}

function Profile({ p }) {
  return (
    <div className="panel">
      <h4 className="adm-chart-title">학교 진학 프로필</h4>
      <dl className="adm-kv">
        <div><dt>학교 유형</dt><dd>{p.school_type_label}</dd></div>
        {p.available ? (
          <>
            <div><dt>기준 연도 졸업생</dt><dd>{p.total_graduates.toLocaleString()}명 ({p.years.join("·")})</dd></div>
            <div>
              <dt>{p.school_type === "VOCATIONAL_HIGH" ? "주요 진로 경로" : "주요 진학 경로"}</dt>
              <dd>{p.main_paths.join(" / ") || "—"}</dd>
            </div>
            <div><dt>주요 진학 권역</dt><dd>{p.main_regions.join(" · ") || "—"}</dd></div>
            <div><dt>주요 학과 계열</dt><dd>{p.main_categories.join(" · ") || "—"}</dd></div>
            <div><dt>주요 진학 대학</dt><dd>{p.main_universities.join(", ") || "—"}</dd></div>
          </>
        ) : (
          <div><dt>진학 자료</dt><dd>{p.message}</dd></div>
        )}
      </dl>
      <p className="adm-note">
        {p.school_type === "VOCATIONAL_HIGH"
          ? "직업계고는 취업과 진학을 함께 준비하는 학교입니다. 진학률만으로 학교를 견주기보다 취업 분야와 함께 보세요."
          : "일반고는 대학 진학을 중심으로 교육과정이 짜여 있습니다. 관심 계열의 진학 사례를 함께 확인하세요."}
      </p>
    </div>
  );
}

const labelOf = (list, key) => (list.find((x) => x.key === key) || {}).label || key;
const fmtDate = (iso) => (iso ? iso.slice(0, 10).replaceAll("-", ".") : "");
