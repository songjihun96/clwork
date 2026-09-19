import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { useSeo } from "../seo";

const CATEGORY_ICONS = {
  특성화고: "🏫", 마이스터고: "⚙️", 과학고: "🔬", 외국어고: "🌐",
  국제고: "🌏", 예술고: "🎨", 체육고: "🏅", 자율고: "📘", 일반고: "🎓",
};

const PLAN_BADGE = {
  premium: { label: "프리미엄", color: "var(--plan-premium)" },
  platinum: { label: "플래티넘", color: "var(--plan-platinum)" },
};

export default function Home() {
  useSeo({ title: "", description: "전국 직업계고를 지역·계열로 검색하고, 학교 설명회와 참가 행사, 진로 적성 검사까지 한 곳에서.", path: "/" });
  const navigate = useNavigate();
  const { user } = useAuth();
  // 플랜 마크는 내부용(관리자·학교계정)에게만 보인다.
  // 학생·비로그인에게 보이면 '광고'처럼 인식될 수 있어 숨긴다.
  const showPlanMark = user?.role === "admin" || user?.role === "school";
  const [meta, setMeta] = useState({ school_count: 0, regions: [], categories: [] });
  const [period, setPeriod] = useState("month");
  const [ranking, setRanking] = useState([]);
  const [rankingLoading, setRankingLoading] = useState(true);
  const [categories, setCategories] = useState([]);
  const [articles, setArticles] = useState([]);
  const [quickSearch, setQuickSearch] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [advRegion, setAdvRegion] = useState("");
  const [advCategory, setAdvCategory] = useState("");

  useEffect(() => {
    api.meta().then(setMeta).catch(() => {});
    api.homeCategories().then(setCategories).catch(() => {});
    api.articles(8).then(setArticles).catch(() => {});
  }, []);

  useEffect(() => {
    setRankingLoading(true);
    api.homeRanking(period, 10)
      .then((d) => setRanking(d.items || []))
      .catch(() => setRanking([]))
      .finally(() => setRankingLoading(false));
  }, [period]);

  const [slideIdx, setSlideIdx] = useState(0);
  const slides = ranking.slice(0, 5);
  useEffect(() => setSlideIdx(0), [ranking]);
  useEffect(() => {
    if (slides.length < 2) return;
    const t = setInterval(() => setSlideIdx((i) => (i + 1) % slides.length), 3000);
    return () => clearInterval(t);
  }, [slides.length]);

  const goSearch = (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    navigate(`/search${qs ? `?${qs}` : ""}`);
  };

  const submitQuickSearch = (e) => {
    e.preventDefault();
    goSearch(quickSearch.trim() ? { name: quickSearch.trim() } : {});
  };

  const submitAdvancedSearch = (e) => {
    e.preventDefault();
    goSearch({
      ...(quickSearch.trim() ? { name: quickSearch.trim() } : {}),
      ...(advRegion ? { region: advRegion } : {}),
      ...(advCategory ? { category: advCategory } : {}),
    });
  };

  const top = slides[slideIdx];
  const topSchool = slides[0]; // 통계 카드는 슬라이드와 별개로 1위 학교를 고정해 보여준다

  return (
    <div>
      {/* 1. 히어로 — 왼쪽 검색, 오른쪽에 지금 가장 많이 찾아본 학교를 사진으로 */}
      <section className="wrap" style={{ padding: "48px 0 40px", display: "flex", gap: 48,
        alignItems: "center", flexWrap: "wrap" }}>
        <div style={{ flex: "1 1 380px", minWidth: 0 }}>
          <div style={{ display: "inline-flex", alignItems: "center", gap: 6,
            background: "var(--color-accent-soft)", color: "var(--color-accent)",
            padding: "5px 12px", borderRadius: 999, fontSize: 12.5, fontWeight: 600, marginBottom: 18 }}>
            <span className="msi" style={{ fontSize: 15 }}>school</span> 당신의 미래를 그리는 곳
          </div>
          <h1 style={{ fontSize: 40, lineHeight: 1.2, margin: "0 0 16px" }}>
            내 꿈에 맞는<br /><span style={{ color: "var(--color-accent)" }}>직업계고</span> 찾기
          </h1>
          <p style={{ color: "var(--steel)", fontSize: 16, margin: "0 0 26px", maxWidth: 440, lineHeight: 1.65 }}>
            전국 우수 특성화고·마이스터고 정보를 한눈에. 실무 중심 교육으로 더 빠른 진로를 준비하세요.
          </p>
          <form onSubmit={submitQuickSearch} style={{ position: "relative", maxWidth: 420 }}>
            <span className="msi" style={{ position: "absolute", left: 16, top: "50%",
              transform: "translateY(-50%)", color: "var(--steel-light)" }}>search</span>
            <input
              className="input"
              placeholder="학교명, 학과, 지역으로 검색해보세요"
              value={quickSearch}
              onChange={(e) => setQuickSearch(e.target.value)}
              style={{ padding: "14px 100px 14px 44px", fontSize: 15, boxShadow: "var(--shadow-lift)" }}
            />
            <button type="submit" className="btn btn-signal btn-sm"
              style={{ position: "absolute", right: 6, top: 6, bottom: 6 }}>검색</button>
          </form>
          <div className="row" style={{ marginTop: 14, gap: 4, flexWrap: "wrap" }}>
            <button onClick={() => setShowAdvanced((v) => !v)} className="btn btn-ghost btn-sm">
              세부 검색 {showAdvanced ? "▲" : "▼"}
            </button>
            <button onClick={() => navigate("/quiz")} className="btn btn-ghost btn-sm">
              어떤 학과가 맞을지 모르겠다면? 진로 테스트 →
            </button>
          </div>
          {showAdvanced && (
            <form onSubmit={submitAdvancedSearch} className="row" style={{ gap: 8, marginTop: 10, flexWrap: "wrap", maxWidth: 420 }}>
              <select className="select" value={advRegion} onChange={(e) => setAdvRegion(e.target.value)}
                style={{ flex: "1 1 140px" }}>
                <option value="">지역 전체</option>
                {(meta.regions || []).map((r) => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </select>
              <select className="select" value={advCategory} onChange={(e) => setAdvCategory(e.target.value)}
                style={{ flex: "1 1 140px" }}>
                <option value="">계열 전체</option>
                {(meta.categories || []).map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
              <button type="submit" className="btn btn-signal btn-sm">검색</button>
            </form>
          )}
        </div>

        {top && (
          <div style={{ flex: "1 1 340px", minWidth: 280, height: 380, position: "relative",
            borderRadius: "var(--radius-lg)", overflow: "hidden",
            boxShadow: "var(--shadow-lift)", background: "var(--raised)" }}>
            {slides.map((s, i) => (
              <button key={s.id} onClick={() => navigate(`/schools/${s.id}`)}
                aria-hidden={i !== slideIdx}
                style={{ position: "absolute", inset: 0, width: "100%", height: "100%",
                  border: "none", padding: 0, cursor: "pointer", background: "none",
                  opacity: i === slideIdx ? 1 : 0,
                  transition: "opacity .8s ease",
                  pointerEvents: i === slideIdx ? "auto" : "none" }}>
                <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center",
                  fontSize: 64,
                  ...(s.hero_image
                    ? { backgroundImage: `url(${s.hero_image})`, backgroundSize: "cover", backgroundPosition: "center" }
                    : {}) }}>
                  {!s.hero_image && (CATEGORY_ICONS[s.category] || "🏫")}
                </div>
                <div style={{ position: "absolute", inset: 0,
                  background: "linear-gradient(to top, rgba(0,0,0,.7), transparent 60%)" }} />
                <div style={{ position: "absolute", left: 20, bottom: 18, right: 20, textAlign: "left", color: "#fff" }}>
                  <p style={{ opacity: .8, fontSize: 12.5, margin: "0 0 4px" }}>
                    {{ today: "오늘", month: "이번 달", year: "올해" }[period]} 가장 많이 찾아본 학교 {i + 1}위
                  </p>
                  <h3 style={{ color: "#fff", fontSize: 22, margin: 0 }}>{s.name}</h3>
                </div>
              </button>
            ))}
            {slides.length > 1 && (
              <div style={{ position: "absolute", right: 16, bottom: 16, display: "flex", gap: 6, zIndex: 1 }}>
                {slides.map((s, i) => (
                  <button key={s.id} onClick={(e) => { e.stopPropagation(); setSlideIdx(i); }}
                    aria-label={`${i + 1}번째 학교 보기`}
                    style={{ width: i === slideIdx ? 18 : 7, height: 7, borderRadius: 999, border: "none",
                      padding: 0, cursor: "pointer", transition: "width .2s",
                      background: i === slideIdx ? "#fff" : "rgba(255,255,255,0.5)" }} />
                ))}
              </div>
            )}
          </div>
        )}
      </section>

      {/* 2. 통계 요약 — bento 카드, 마지막 칸은 실시간 랭킹 1위를 강조해 보여준다 */}
      <section style={{ background: "var(--raised)", padding: "56px 0" }}>
        <div className="wrap">
          <SectionHead title="한눈에 보는 직업계고" desc="실제 수록된 학교 데이터로 보여드립니다" />
          <div className="stat-icon-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))" }}>
            <BentoStat icon="apartment" value={(meta.school_count || 0).toLocaleString()} unit="개교" label="전국 학교 수" />
            <BentoStat icon="public" value={meta.regions?.length || 0} unit="개 지역" label="전국 지역" />
            {topSchool ? (
              <div className="stat-icon-card" style={{ textAlign: "left",
                background: "var(--color-accent-soft)", border: "1px solid var(--color-accent)" }}>
                <div className="row" style={{ gap: 8, color: "var(--color-accent)", marginBottom: 10 }}>
                  <span className="msi">trending_up</span>
                  <span style={{ fontSize: 13, fontWeight: 600, color: "var(--steel)" }}>가장 많이 찾아본 학교</span>
                </div>
                <div style={{ fontWeight: 700, fontSize: 17 }}>{topSchool.name}</div>
              </div>
            ) : (
              <BentoStat icon="trending_up" value="—" unit="" label="집계된 조회 기록 없음" />
            )}
          </div>
        </div>
      </section>

      <div className="wrap" style={{ padding: "56px 0 60px", display: "grid", gap: 56 }}>
        {/* 3. 인기 학교 — 사진 대신 계열 아이콘으로 채운 카드(사진 등록은 상위 플랜 전용) */}
        <section>
          <SectionHead
            title="인기 특성화고 · 마이스터고"
            desc="지금 가장 주목받고 있는 학교들을 확인해보세요"
            right={
              <div style={{ display: "flex", gap: 4 }}>
                {[["today", "오늘"], ["month", "이번 달"], ["year", "올해"]].map(([k, label]) => (
                  <button key={k} onClick={() => setPeriod(k)} className={`tab ${period === k ? "active" : ""}`}>
                    {label}
                  </button>
                ))}
              </div>
            }
          />
          {rankingLoading ? (
            <div className="empty"><p>불러오는 중…</p></div>
          ) : ranking.length === 0 ? (
            <div className="empty"><p>아직 집계된 조회 기록이 없어요. 학교를 둘러보면 랭킹이 쌓입니다.</p></div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(230px, 1fr))", gap: 18 }}>
              {ranking.slice(0, 8).map((s) => (
                <button key={s.id} onClick={() => navigate(`/schools/${s.id}`)} className="hover-lift"
                  style={{ display: "flex", flexDirection: "column", textAlign: "left", padding: 0,
                    background: "var(--surface)", border: "1px solid var(--line)",
                    borderRadius: "var(--radius)", overflow: "hidden", cursor: "pointer" }}>
                  <div style={{ position: "relative", aspectRatio: "16/9", background: "var(--raised)",
                    display: "grid", placeItems: "center", fontSize: 40,
                    ...(s.hero_image
                      ? { backgroundImage: `url(${s.hero_image})`, backgroundSize: "cover", backgroundPosition: "center" }
                      : {}) }}>
                    {!s.hero_image && (CATEGORY_ICONS[s.category] || "🏫")}
                    <span style={{ position: "absolute", top: 10, left: 10, background: "rgba(255,255,255,.92)",
                      padding: "3px 9px", borderRadius: 6, fontSize: 11.5, fontWeight: 600 }}>{s.category}</span>
                  </div>
                  <div style={{ padding: 16, flex: 1, display: "flex", flexDirection: "column", gap: 8 }}>
                    <div className="row" style={{ gap: 4, color: "var(--steel)", fontSize: 12.5 }}>
                      <span className="msi" style={{ fontSize: 15 }}>location_on</span>{s.region}
                    </div>
                    <div className="row" style={{ gap: 6 }}>
                      <b style={{ fontSize: 15.5 }}>{s.name}</b>
                      {showPlanMark && PLAN_BADGE[s.plan] && (
                        <span className="badge" style={{ background: PLAN_BADGE[s.plan].color, color: "#fff" }}>
                          {PLAN_BADGE[s.plan].label}
                        </span>
                      )}
                    </div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </section>

        {/* 4. 계열별 바로가기 */}
        <section>
          <SectionHead title="계열별로 찾기" desc="관심 있는 계열을 눌러보세요" />
          <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
            {categories.map((c) => (
              <button
                key={c.category}
                onClick={() => goSearch({ category: c.category })}
                style={{
                  display: "flex", alignItems: "center", gap: 10,
                  background: "var(--surface)", border: "1px solid var(--line)",
                  borderRadius: "999px", padding: "10px 18px", cursor: "pointer",
                  fontSize: 14.5, fontWeight: 500, color: "var(--ink)",
                }}
              >
                <span style={{ fontSize: 18 }}>{CATEGORY_ICONS[c.category] || "🏫"}</span>
                {c.category}
                <span style={{ color: "var(--steel-light)", fontSize: 12.5 }}>{c.count}</span>
              </button>
            ))}
          </div>
        </section>

        {/* 5. 특성화고신문 최신 기사 */}
        {articles.length > 0 && (
          <section>
            <SectionHead
              title="학교 소식"
              desc="특성화고신문에 올라온 학교 소식"
              right={<span className="label">특성화고신문 제공</span>}
            />
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 14 }}>
              {articles.map((a) => (
                <a
                  key={a.id}
                  href={a.url}
                  target="_blank"
                  rel="noreferrer"
                  style={{
                    display: "flex", flexDirection: "column",
                    background: "var(--surface)", border: "1px solid var(--line)",
                    borderRadius: "var(--radius)", overflow: "hidden", textDecoration: "none", color: "inherit",
                  }}
                >
                  {a.thumbnail ? (
                    <img
                      src={a.thumbnail}
                      alt=""
                      loading="lazy"
                      decoding="async"
                      style={{ height: 130, width: "100%", objectFit: "cover",
                               background: "var(--raised)", display: "block" }}
                    />
                  ) : (
                    <div style={{ height: 130, background: "var(--raised)", display: "grid", placeItems: "center", fontSize: 30 }}>📰</div>
                  )}
                  <div style={{ padding: "12px 14px", display: "flex", flexDirection: "column", gap: 6, flex: 1 }}>
                    <div style={{ fontWeight: 600, fontSize: 14, lineHeight: 1.4, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
                      {a.title}
                    </div>
                    {a.summary && (
                      <p style={{ fontSize: 12.5, color: "var(--steel)", margin: 0, lineHeight: 1.5, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
                        {a.summary}
                      </p>
                    )}
                    <div style={{ marginTop: "auto", display: "flex", justifyContent: "space-between", alignItems: "center", paddingTop: 6 }}>
                      <span className="label">특성화고신문 제공</span>
                    </div>
                  </div>
                </a>
              ))}
            </div>
          </section>
        )}

        {/* 6. 진로 테스트 배너 */}
        <section
          style={{
            background: "var(--color-text)",
            borderRadius: "var(--radius-lg)", padding: "32px 30px",
            display: "flex", alignItems: "center", justifyContent: "space-between",
            gap: 20, flexWrap: "wrap",
          }}
        >
          <div>
            <span className="label" style={{ color: "rgba(255,255,255,0.6)" }}>진로 테스트</span>
            <h2 style={{ color: "#fff", fontSize: 22, margin: "6px 0" }}>어떤 학과가 나에게 맞을까?</h2>
            <p style={{ color: "rgba(255,255,255,0.75)", fontSize: 14.5, margin: 0 }}>
              몇 가지 질문에 답하면 나에게 맞는 계열과 통학 가능한 학교를 찾아드려요.
            </p>
          </div>
          <button
            onClick={() => navigate("/quiz")}
            className="btn btn-signal"
            style={{ flexShrink: 0 }}
          >
            진로 테스트 시작하기 →
          </button>
        </section>
      </div>
    </div>
  );
}

function BentoStat({ icon, value, unit, label }) {
  return (
    <div className="stat-icon-card" style={{ textAlign: "left" }}>
      <div className="row" style={{ gap: 8, color: "var(--color-accent)", marginBottom: 10 }}>
        <span className="msi">{icon}</span>
        <span style={{ fontSize: 13, fontWeight: 600, color: "var(--steel)" }}>{label}</span>
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 5 }}>
        <span style={{ fontFamily: "var(--font-display)", fontSize: 30, fontWeight: 800 }}>{value}</span>
        <span style={{ fontSize: 13, color: "var(--steel)" }}>{unit}</span>
      </div>
    </div>
  );
}

function SectionHead({ title, desc, right }) {
  return (
    <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 12, marginBottom: 20, flexWrap: "wrap" }}>
      <div>
        <h2 style={{ fontSize: 22 }}>{title}</h2>
        {desc && <p style={{ fontSize: 13.5, color: "var(--steel)", margin: "4px 0 0" }}>{desc}</p>}
      </div>
      {right}
    </div>
  );
}
