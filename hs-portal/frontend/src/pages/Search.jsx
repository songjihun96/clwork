import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import SchoolCard from "../components/SchoolCard";
import SchoolDetailView from "../components/SchoolDetailView";

import CompareTray from "../components/CompareTray";
import { useSeo } from "../seo";

// 지도는 지도 보기를 눌렀을 때만 내려받는다 (leaflet 약 150KB)
const MapView = lazy(() => import("../components/MapView"));

const EMPTY = { name: "", region: "", sigungu: "", gu: "", category: "", coed: "", dept_field: "" };

// 한 페이지에 보여줄 학교 수. 백엔드 기본값과 맞춰둔다.
const PAGE_SIZE = 20;

export default function Search() {
  useSeo({ title: "학교 검색", description: "지역·계열·남녀공학으로 전국 직업계고를 검색하고 지도로 살펴보세요.", path: "/search" });
  const { user } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  // 메인 화면에서 ?name= 또는 ?category= 로 넘어온 값을 초기 필터로 쓴다.
  const initialFilters = {
    name: searchParams.get("name") || "",
    region: searchParams.get("region") || "",
    sigungu: searchParams.get("sigungu") || "",
    gu: searchParams.get("gu") || "",
    category: searchParams.get("category") || "",
    coed: searchParams.get("coed") || "",
    dept_field: searchParams.get("dept_field") || "",
  };

  const [meta, setMeta] = useState({ regions: [], categories: [], coed_options: [], school_count: 0, dept_fields: [], dept_field_enabled: false });
  const [sigunguList, setSigunguList] = useState([]);
  const [filters, setFilters] = useState(initialFilters);
  const [applied, setApplied] = useState(initialFilters);
  const [sort, setSort] = useState("recommended");
  const [page, setPage] = useState(1);
  const [data, setData] = useState({ items: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [openId, setOpenId] = useState(null);
  const [view, setView] = useState("list");
  const [mapItems, setMapItems] = useState([]);
  const [compare, setCompare] = useState([]);

  useEffect(() => {
    api.meta().then(setMeta).catch(() => {});
  }, []);

  // 시/도가 바뀌면 그 지역의 시/군/구 목록을 불러온다.
  useEffect(() => {
    if (!filters.region) {
      setSigunguList([]);
      return;
    }
    api.sigungu(filters.region).then(setSigunguList).catch(() => setSigunguList([]));
  }, [filters.region]);

  // 선택한 시에 구가 있으면 목록을 준다.
  const guOptions =
    (sigunguList.find((sg) => sg.city === filters.sigungu) || {}).districts || [];

  // 서버는 sigungu 하나만 받는다. 구를 골랐으면 '수원시 장안구'로 합치고,
  // 안 골랐으면 '수원시'만 보내 그 시 전체가 잡히게 한다.
  const toQuery = (f) => {
    const { gu, sigungu, ...rest } = f;
    return { ...rest, sigungu: gu ? `${sigungu} ${gu}` : sigungu };
  };

  const load = useCallback(() => {
    setLoading(true);
    api
      .schools({ ...toQuery(applied), sort, page, size: PAGE_SIZE })
      .then((d) => {
        setData(d);
        setError("");
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [applied, sort, page]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (view === "map") {
      // 필터가 바뀌면 이전 핀이 잠깐이라도 남지 않게 먼저 비운다.
      setMapItems([]);
      api.schoolsForMap(toQuery(applied)).then(setMapItems).catch(() => setMapItems([]));
    }
  }, [view, applied]);

  const submit = (e) => {
    e?.preventDefault();
    setPage(1);
    setApplied(filters);
  };

  const reset = () => {
    setFilters(EMPTY);
    setApplied(EMPTY);
    setPage(1);
  };

  const toggleFavorite = async (school) => {
    if (!user) {
      navigate("/login");
      return;
    }
    if (school.is_favorite) await api.removeFavorite(school.id);
    else await api.addFavorite(school.id);
    load();
  };

  const toggleCompare = (school) => {
    setCompare((prev) => {
      if (prev.find((s) => s.id === school.id)) return prev.filter((s) => s.id !== school.id);
      if (prev.length >= 3) return prev;
      return [...prev, school];
    });
  };

  const totalPages = Math.max(1, Math.ceil(data.total / PAGE_SIZE));
  const activeCount = useMemo(
    () => Object.values(applied).filter(Boolean).length,
    [applied]
  );

  return (
    <>
      <section style={{ background: "var(--surface)", borderBottom: "1px solid var(--line)", padding: "48px 0 40px" }}>
        <div className="wrap">
          <span className="label">
            ㅇㅈ · 우리동네 직업계고
          </span>
          <h1 style={{ fontSize: 34, margin: "10px 0 10px", lineHeight: 1.25, color: "var(--ink)" }}>
            나에게 맞는 학교, 여기서 만나요
          </h1>
          <p style={{ color: "var(--steel)", fontSize: 15, margin: 0, lineHeight: 1.6 }}>
            나이스 교육정보 개방 포털의 학교 정보를 바탕으로
            {meta.school_count > 0 && ` ${meta.school_count.toLocaleString()}개 학교를`} 지역·계열 조건으로 찾아보세요.
          </p>
          <button
            onClick={() => navigate("/quiz")}
            className="btn btn-signal"
            style={{ marginTop: 20, display: "inline-flex", alignItems: "center", gap: 8 }}
          >
            어떤 학과가 맞을지 모르겠다면? 진로 테스트 해보기 →
          </button>
        </div>
      </section>

      <div className="wrap" style={{ marginTop: -24, position: "relative", zIndex: 5 }}>
        <form className="searchbar" onSubmit={submit}>
          <div className="filter-grid">
            <div className="field">
              <label className="label" htmlFor="f-name">학교 이름</label>
              <input
                id="f-name"
                className="input"
                placeholder="예: 공업, 미래산업"
                value={filters.name}
                onChange={(e) => setFilters({ ...filters, name: e.target.value })}
              />
            </div>

            <div className="field">
              <label className="label" htmlFor="f-region">지역 (시/도)</label>
              <select
                id="f-region"
                className="select"
                value={filters.region}
                onChange={(e) => setFilters({ ...filters, region: e.target.value, sigungu: "", gu: "" })}
              >
                <option value="">전체</option>
                {meta.regions.map((r) => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </select>
            </div>

            <div className="field">
              <label className="label" htmlFor="f-sigungu">시/군/구</label>
              <select
                id="f-sigungu"
                className="select"
                value={filters.sigungu}
                onChange={(e) => setFilters({ ...filters, sigungu: e.target.value, gu: "" })}
                disabled={!filters.region}
              >
                <option value="">{filters.region ? "전체" : "시/도 먼저 선택"}</option>
                {sigunguList.map((sg) => (
                  <option key={sg.city} value={sg.city}>{sg.city}</option>
                ))}
              </select>
            </div>

            {/* 구가 여러 개인 큰 시만 2단계로 고를 수 있게 한다.
                구를 고르지 않으면 그 시 전체가 검색된다. */}
            {guOptions.length > 0 && (
              <div className="field">
                <label className="label" htmlFor="f-gu">구 (선택)</label>
                <select
                  id="f-gu"
                  className="select"
                  value={filters.gu}
                  onChange={(e) => setFilters({ ...filters, gu: e.target.value })}
                >
                  <option value="">{filters.sigungu} 전체</option>
                  {guOptions.map((g) => (
                    <option key={g} value={g}>{g}</option>
                  ))}
                </select>
              </div>
            )}

            <div className="field">
              <label className="label" htmlFor="f-cat">학교 계열</label>
              <select
                id="f-cat"
                className="select"
                value={filters.category}
                onChange={(e) => setFilters({ ...filters, category: e.target.value })}
              >
                <option value="">전체</option>
                {meta.categories.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </div>

            {meta.dept_field_enabled && meta.dept_fields.length > 0 && (
              <div className="field">
                <label className="label" htmlFor="f-dept">학과 계열</label>
                <select
                  id="f-dept"
                  className="select"
                  value={filters.dept_field}
                  onChange={(e) => setFilters({ ...filters, dept_field: e.target.value })}
                >
                  <option value="">전체</option>
                  {meta.dept_fields.map((f) => (
                    <option key={f.key} value={f.key}>{f.label}</option>
                  ))}
                </select>
              </div>
            )}

            <div className="field">
              <label className="label" htmlFor="f-coed">남녀공학</label>
              <select
                id="f-coed"
                className="select"
                value={filters.coed}
                onChange={(e) => setFilters({ ...filters, coed: e.target.value })}
              >
                <option value="">전체</option>
                {meta.coed_options.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </div>

          </div>

          {/* 버튼은 필터 그리드 밖에 둔다. 필터가 몇 개든 항상 오른쪽 아래에 붙는다. */}
          <div className="filter-actions">
            {activeCount > 0 && (
              <button className="btn btn-ghost" type="button" onClick={reset}>
                초기화
              </button>
            )}
            <button className="btn btn-signal" type="submit">검색</button>
          </div>
        </form>
      </div>

      <main className="wrap" style={{ padding: "24px 0 60px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14, flexWrap: "wrap" }}>
          <span className="label">
            검색 결과 {data.total.toLocaleString()}개
          </span>

          <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
            <div style={{ display: "flex", gap: 2 }}>
              <button
                className={`btn btn-sm ${view === "list" ? "" : "btn-ghost"}`}
                onClick={() => setView("list")}
              >
                목록
              </button>
              <button
                className={`btn btn-sm ${view === "map" ? "" : "btn-ghost"}`}
                onClick={() => setView("map")}
              >
                지도
              </button>
            </div>
            <select
              className="select"
              style={{ width: "auto", fontSize: 13 }}
              value={sort}
              onChange={(e) => {
                setSort(e.target.value);
                setPage(1);
              }}
              aria-label="정렬 기준"
            >
              <option value="recommended">추천순</option>
              <option value="name">이름순</option>
            </select>
          </div>
        </div>

        {/* 대가를 받고 노출 순서를 정하는 사실을 알린다(표시광고법 제3조). */}
        {sort === "recommended" && (
          <p
            className="label"
            style={{ color: "var(--steel)", margin: "6px 2px 0", lineHeight: 1.6 }}
          >
            추천순은 제휴 학교를 먼저 보여준 뒤 이름 순으로 정렬됩니다.
            제휴 여부와 무관한 순서로 보시려면 이름순을 선택해주세요.
          </p>
        )}

        {error && <div className="notice notice-error" style={{ marginBottom: 14 }}>{error}</div>}

        {view === "map" ? (
          <Suspense fallback={<div className="empty"><p>지도를 불러오는 중…</p></div>}>
                {/* 좌표가 없는 학교는 지도에 찍을 수 없어 조용히 빠진다. 그 사실을 알린다. */}
                {mapItems.length > 0 && data.total > mapItems.length && (
                  <p className="label" style={{ color: "var(--steel)", margin: "0 0 8px" }}>
                    검색 결과 {data.total}곳 중 {mapItems.length}곳만 표시됩니다.
                    나머지 {data.total - mapItems.length}곳은 위치 정보가 없어 목록에서 확인해주세요.
                  </p>
                )}
                {/* 걸러 낸 학교에 좌표가 하나도 없으면 지도가 텅 빈다. 아무 말도
                  * 안 하면 "검색이 깨졌다"로 읽힌다 — 실제로 시/군/구를 고른
                  * 순간 결과가 다 사라진 것처럼 보인다는 이야기를 들었다.
                  * 찾은 건 있는데 찍을 수 없을 뿐임을 분명히 하고, 목록으로
                  * 갈 길도 같이 준다. */}
                {!loading && mapItems.length === 0 && (
                  <div className="empty" style={{ marginBottom: 12 }}>
                    {data.total > 0 ? (
                      <>
                        <h3>지도에 표시할 수 있는 학교가 없습니다</h3>
                        <p>
                          조건에 맞는 학교 {data.total}곳을 찾았지만, 아직 위치 정보가
                          없어 지도에 찍을 수 없습니다. 목록에서는 그대로 보실 수 있습니다.
                        </p>
                        <button className="btn btn-sm" style={{ marginTop: 10 }}
                          onClick={() => setView("list")}>
                          목록으로 보기
                        </button>
                      </>
                    ) : (
                      <>
                        <h3>조건에 맞는 학교가 없습니다</h3>
                        <p>필터를 하나씩 풀어보면 결과가 넓어집니다.</p>
                      </>
                    )}
                  </div>
                )}
                {mapItems.length > 0 && <MapView items={mapItems} onOpen={setOpenId} />}
              </Suspense>
        ) : loading ? (
          <div className="empty"><p>불러오는 중…</p></div>
        ) : data.items.length === 0 ? (
          <div className="empty">
            <h3>조건에 맞는 학교가 없습니다</h3>
            <p>
              {meta.school_count === 0
                ? "학교 데이터가 아직 수집되지 않았습니다. 서버에서 python -m app.import_neis 를 실행하세요."
                : "필터를 하나씩 풀어보면 결과가 넓어집니다."}
            </p>
          </div>
        ) : (
          <>
            <div className="card-list">
              {data.items.map((s) => (
                <div key={s.id} className="card-wrap" style={{ position: "relative" }}>
                  <SchoolCard
                    school={s}
                    onOpen={setOpenId}
                    onToggleFavorite={toggleFavorite}
                    showFavorite={!user || user.role === "student"}
                    showPlanMark={user?.role === "admin" || user?.role === "school"}
                  />
                  <button
                    className="btn btn-ghost btn-sm compare-btn"
                    onClick={() => toggleCompare(s)}
                  >
                    {compare.find((c) => c.id === s.id) ? "비교 취소" : "비교 담기"}
                  </button>
                </div>
              ))}
            </div>

            {totalPages > 1 && <Pagination page={page} totalPages={totalPages} onChange={setPage} />}
          </>
        )}
      </main>

      {compare.length > 0 && (
        <CompareTray items={compare} onClear={() => setCompare([])} onRemove={toggleCompare} />
      )}

      {openId && (
        <div className="modal-backdrop" onClick={() => setOpenId(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <SchoolDetailView schoolId={openId} embedded />
            <div style={{ padding: "0 28px 24px" }}>
              <button className="btn btn-ghost" onClick={() => setOpenId(null)}>닫기</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

/** 페이지 번호를 눌러 바로 이동한다. 현재 페이지 주변만 보여주고
 *  나머지는 …으로 줄인다(전체가 몇 페이지든 버튼 줄이 길어지지 않는다). */
function Pagination({ page, totalPages, onChange }) {
  const pages = [];
  const add = (n) => pages.push(n);
  add(1);
  for (let n = page - 1; n <= page + 1; n++) if (n > 1 && n < totalPages) add(n);
  if (totalPages > 1) add(totalPages);
  const shown = [...new Set(pages)].sort((a, b) => a - b);

  return (
    <div style={{ display: "flex", gap: 4, justifyContent: "center", marginTop: 28, alignItems: "center" }}>
      <button className="btn btn-ghost btn-sm" disabled={page === 1} onClick={() => onChange(page - 1)}
        aria-label="이전 페이지" style={{ width: 34, padding: 0 }}>
        <span className="msi" style={{ fontSize: 18 }}>chevron_left</span>
      </button>
      {shown.map((n, i) => (
        <span key={n} style={{ display: "flex", alignItems: "center", gap: 4 }}>
          {i > 0 && n - shown[i - 1] > 1 && <span style={{ padding: "0 2px", color: "var(--steel-light)" }}>…</span>}
          <button
            className={`btn btn-sm ${n === page ? "btn-signal" : "btn-ghost"}`}
            style={{ width: 34, padding: 0 }}
            onClick={() => onChange(n)}
          >
            {n}
          </button>
        </span>
      ))}
      <button className="btn btn-ghost btn-sm" disabled={page === totalPages} onClick={() => onChange(page + 1)}
        aria-label="다음 페이지" style={{ width: 34, padding: 0 }}>
        <span className="msi" style={{ fontSize: 18 }}>chevron_right</span>
      </button>
    </div>
  );
}
