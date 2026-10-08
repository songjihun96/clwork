import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { useSeo } from "../seo";
import InquiryModal from "../components/InquiryModal";

/** 학교 홍보 인터뷰 — 학교에 직접 찾아가 찍은 영상 모음.
 *
 * 목록은 누구나 본다. 어떤 학교가 있는지 보여야 가입할 이유가 생긴다.
 * 재생은 회원만 — 상세 화면에서 서버가 로그인한 사람에게만 주소를 준다.
 *
 * 촬영은 학교가 비용을 내고 신청한다. 신청 칸은 **학교 계정에게만** 보인다 —
 * 학생·학부모에게 "돈 내고 찍으세요"가 보일 이유가 없다.
 */
export function fmtDuration(sec) {
  const s = Math.max(Math.floor(Number(sec) || 0), 0);
  if (!s) return "";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = String(s % 60).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${r}` : `${m}:${r}`;
}

export function InterviewThumb({ item, big = false }) {
  const dur = fmtDuration(item.duration_sec);
  return (
    <div className={`iv-thumb${big ? " iv-thumb-big" : ""}`}>
      {item.thumbnail
        ? <img src={item.thumbnail} alt="" loading="lazy" />
        : <span className="iv-thumb-name">{item.school?.name}</span>}
      {dur && <span className="iv-thumb-dur">{dur}</span>}
    </div>
  );
}

export default function Interviews() {
  useSeo({
    title: "학교 홍보 인터뷰",
    description: "직업계고에 직접 찾아가 선생님과 재학생에게 들은 학교 이야기. 회원이면 무료로 볼 수 있습니다.",
    path: "/interviews",
  });
  const { user } = useAuth();
  const location = useLocation();
  const [sp, setSp] = useSearchParams();
  const region = sp.get("region") || "";   // 주소에 남겨 새로고침·공유해도 유지
  const [items, setItems] = useState(null);
  const [regions, setRegions] = useState([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [asking, setAsking] = useState(false);

  // 지역은 서버에서 거른다. 검색어(학교 이름)는 받은 목록 안에서 거른다 — 둘이 함께 걸린다.
  useEffect(() => {
    setError("");
    api.interviews(undefined, region || undefined).then((d) => {
      setItems(d.items || []);
      setRegions(d.regions || []);
      setTotal(d.total ?? (d.items || []).length);
    }).catch((e) => setError(e.message));
  }, [region]);

  const pickRegion = (r) => {
    const next = new URLSearchParams(sp);
    if (r) next.set("region", r); else next.delete("region");
    setSp(next, { replace: true });
  };

  const shown = useMemo(() => (items || []).filter((it) => {
    const t = q.trim();
    if (!t) return true;
    return [it.school?.name, it.title, it.speakers].some((v) => (v || "").includes(t));
  }), [items, q]);

  const next = encodeURIComponent(location.pathname);

  return (
    <div className="wrap" style={{ padding: "34px 0 60px" }}>
      <span className="label" style={{ color: "var(--signal-deep)" }}>학교 탐방</span>
      <h1 style={{ fontSize: 26, margin: "6px 0 4px" }}>학교 홍보 인터뷰</h1>
      <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 0, lineHeight: 1.7 }}>
        직업계고에 직접 찾아가 선생님과 재학생에게 학교 이야기를 들었습니다.
        홈페이지에는 없는, 학교 안의 진짜 모습을 만나 보세요.
      </p>

      {!user && (
        <div className="notice notice-info iv-members-note">
          <span>🔒 인터뷰 영상은 <b>회원만</b> 볼 수 있어요. 가입은 무료예요.</span>
          <span style={{ display: "flex", gap: 6 }}>
            <Link className="btn btn-signal btn-sm" to={`/signup?next=${next}`}>무료 회원가입</Link>
            <Link className="btn btn-ghost btn-sm" to={`/login?next=${next}`}>로그인</Link>
          </span>
        </div>
      )}

      {error && <div className="notice notice-error" style={{ marginTop: 16 }}>{error}</div>}
      {!items && !error && <div className="empty" style={{ marginTop: 20 }}><p>불러오는 중…</p></div>}

      {items && total > 0 && (
        <>
          <div className="iv-regions" role="group" aria-label="지역별 보기">
            <button type="button" className={`iv-region${region ? "" : " on"}`}
              aria-pressed={!region} onClick={() => pickRegion("")}>
              전체 <small>{total}</small>
            </button>
            {regions.map((r) => (
              <button type="button" key={r.region} aria-pressed={region === r.region}
                className={`iv-region${region === r.region ? " on" : ""}`}
                onClick={() => pickRegion(r.region)}>
                {r.region} <small>{r.count}</small>
              </button>
            ))}
          </div>
          <div className="iv-filter">
            <input className="input" value={q} placeholder="학교 이름으로 찾기"
              onChange={(e) => setQ(e.target.value)} aria-label="학교 이름으로 찾기" />
          </div>
        </>
      )}

      {items && total === 0 && (!region || regions.length === 0) && (
        <div className="empty" style={{ marginTop: 20 }}>
          <p>첫 번째 학교 인터뷰를 준비하고 있어요.</p>
        </div>
      )}
      {items && total > 0 && shown.length === 0 && (
        <div className="empty" style={{ marginTop: 20 }}>
          <p>{region && !q.trim() ? `${region} 지역 인터뷰가 아직 없어요.` : "찾는 학교의 인터뷰가 아직 없어요."}</p>
          {region && <button type="button" className="btn btn-ghost btn-sm" onClick={() => pickRegion("")}>전체 지역 보기</button>}
        </div>
      )}

      <div className="iv-grid">
        {shown.map((it) => (
          <Link key={it.id} to={`/interviews/${it.id}`} className="iv-card">
            <InterviewThumb item={it} />
            <div className="iv-card-body">
              <div className="iv-card-school">
                {it.school?.name}
                {it.school?.region && <small>{it.school.region}{it.school.category ? ` · ${it.school.category}` : ""}</small>}
              </div>
              <div className="iv-card-title">{it.title}</div>
              {it.speakers && <div className="iv-card-meta">{it.speakers}</div>}
            </div>
          </Link>
        ))}
      </div>

      {/* 학교 계정 전용. 촬영은 유료라 금액은 협의로 둔다. */}
      {user?.role === "school" && (
      <section className="iv-apply">
        <div>
          <h2>우리 학교도 인터뷰하고 싶다면</h2>
          <p>
            촬영팀이 학교에 방문해 선생님·재학생 인터뷰를 찍고, 이곳에 올려 드립니다.
            촬영은 유료이며 일정과 비용은 신청 후 연락드려 협의합니다.
          </p>
        </div>
        <button type="button" className="btn btn-signal" onClick={() => setAsking(true)}>
          인터뷰 촬영 신청
        </button>
      </section>
      )}

      {asking && (
        <InquiryModal onClose={() => setAsking(false)}
          title="학교 홍보 인터뷰 촬영 신청"
          intro="촬영팀이 학교에 방문해 인터뷰 영상을 만들어 드립니다. 남겨 주시면 일정과 비용을 안내해 드립니다."
          via="학교 홍보 인터뷰 촬영"
          messagePlaceholder="원하시는 촬영 시기, 인터뷰에 참여할 분(교장·학과 선생님·재학생 등), 꼭 담고 싶은 내용을 적어 주세요."
          submitLabel="신청하기" />
      )}
    </div>
  );
}
