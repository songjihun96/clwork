import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useSeo } from "../seo";
import InquiryModal from "../components/InquiryModal";

/** 특강 — 강의로 보는 것과, 사람이 직접 봐 주는 것.
 *
 * 앞으로 특강이 더 생겨도 상단 메뉴를 늘리지 않고 여기 카드로 붙인다.
 *
 * **신청 페이지도 여기서 간다.** 컨설팅·상담·합격생 영상은 주소만 만들어
 * 두고 어디서도 링크를 안 걸어 두었더니, 만든 사람 말고는 들어갈 길이
 * 없었다. 무료로 보는 것과 유료 서비스를 한 화면에 두되, 사이에
 * 줄을 그어 "여기서부터는 유료"임을 분명히 한다.
 *
 * 문의도 신청 카드 한 칸으로 둔다. 떠 있는 버튼에도 같은 폼이 붙어 있지만,
 * 그 버튼은 관리자가 꺼 둘 수도 있고 역할에 따라 안 보이기도 한다. 개인이
 * 신청하는 것들 옆에 나란히 두면 "학교로도 부를 수 있구나"가 그 자리에서
 * 읽힌다. 다만 이 칸만은 페이지를 옮기지 않고 **그 자리에서 창을 띄운다** —
 * 옆 카드들과 달리 따로 볼 안내가 없고 바로 적으면 끝나는 일이라, 화면을
 * 갈아 끼우면 돌아올 길만 생긴다.
 *
 * 숏츠는 여기 두지 않는다. 짧게 훑는 것과 길게 듣는 것은 보러 오는 마음이
 * 달라서, 한 칸 더 들어가게 하면 그냥 안 본다. 상단 메뉴에서 바로 간다.
 */

/** 사람이 직접 봐 주는 것들. 금액은 서버(applications.py)가 정하지만
 *  카드에 적는 값은 안내일 뿐이라 여기 둔다 — 바뀌면 두 곳을 같이 고친다. */
const SERVICES = [
  {
    to: "/consulting",
    badge: "컨설팅",
    title: "직업계고 3년Plan 컨설팅",
    desc: "졸업 후 취업할 회사의 선택지가 넓어지도록, 3년간의 학교생활을 함께 설계합니다.",
    meta: "온라인(zoom) · 90분 · 300,000원",
  },
  {
    to: "/counseling",
    badge: "상담",
    title: "직업계고 상담신청",
    desc: "직업계고와 관련된 다양한 주제의 상담을 진행합니다.",
    meta: "전화 또는 온라인(zoom) · 60분 · 100,000원",
  },
  {
    to: "/graduate-video",
    badge: "영상",
    title: "직업계고 합격한 학생들을 위한 영상",
    desc: "자기소개서·포트폴리오·취업 후 대학진학 전략까지, 합격 이후를 준비하는 영상입니다.",
    meta: "100,000원",
  },
  {
    key: "inquiry",          // to 대신 key — 이 칸은 창을 띄운다
    badge: "학교·기관",
    title: "오프라인 직업계고설명회 신청",
    desc: "전문강사가 학교에 직접 방문해 오프라인 직업계고 설명회를 진행합니다.",
    meta: "협의 후 결정",
  },
];
export default function Special() {
  useSeo({
    title: "온라인 직업계고 설명회",
    description: "직업계고가 무엇인지 온라인으로 듣습니다. 컨설팅·상담·합격생 영상도 여기서 신청합니다.",
    path: "/special",
  });

  const [briefing, setBriefing] = useState(null);
  const [lectures, setLectures] = useState(null);
  const [picked, setPicked] = useState(null);

  useEffect(() => {
    api.briefing().then(setBriefing).catch(() => setBriefing(null));
    api.lectures().then(setLectures).catch(() => setLectures([]));
  }, []);

  const hasBriefing = !!(briefing?.chapters?.length || briefing?.video);

  const cards = [
    hasBriefing && {
      to: "/briefing",
      badge: "온라인",
      title: briefing.headline || "직업계고설명회",
      desc: briefing.intro
        || "직업계고가 무엇인지, 우리 아이에게 맞는지 차근차근 짚어 드립니다.",
      meta: [briefing.summary?.chapters ? `챕터 ${briefing.summary.chapters}개` : "",
        "회원 전용 · 무료"].filter(Boolean).join(" · "),
    },
  ].filter(Boolean);

  return (
    <div className="wrap" style={{ padding: "34px 0 60px" }}>
      <h1 style={{ fontSize: 26, margin: "0 0 4px" }}>온라인 직업계고 설명회</h1>
      <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 0 }}>
        직업계고 진로·취업 이야기를 영상으로 만나보세요.
      </p>

      {cards.length > 0 && <CardGrid cards={cards} />}

      {/* 특강 카드. 누르면 영상 상세로 가고, 긴 영상은 오른쪽 챕터로 나눠 본다.
          비어 있을 때 큰 빈 상자로 화면을 채우지 않는다 — 한 줄만 둔다. */}
      {lectures && lectures.length > 0 && (
        <div className="iv-grid" style={{ marginTop: cards.length ? 16 : 20 }}>
          {lectures.map((v) => <LectureCard key={v.id} lecture={v} />)}
        </div>
      )}
      {lectures && lectures.length === 0 && cards.length === 0 && (
        <p className="lecture-empty">준비 중인 특강이 곧 올라옵니다.</p>
      )}

      <section style={{ marginTop: 36, paddingTop: 26, borderTop: "1px solid var(--line)" }}>
        <h2 style={{ fontSize: 20, margin: "0 0 4px" }}>유료 서비스</h2>
        <CardGrid cards={SERVICES} onPick={setPicked} />
      </section>

      {picked === "inquiry" && (
        <InquiryModal onClose={() => setPicked(null)}
          title="오프라인 직업계고설명회 신청"
          intro="전문강사가 학교에 직접 방문해 오프라인 직업계고 설명회를 진행합니다."
          via="오프라인 설명회"
          messagePlaceholder="대상(학생·학부모·선생님)과 인원, 원하시는 시기를 적어주세요. 장소와 시간도 함께 적어주시면 준비가 빠릅니다."
          submitLabel="신청하기" />
      )}
    </div>
  );
}

function fmtLength(sec) {
  const s = Math.max(Math.floor(Number(sec) || 0), 0);
  if (!s) return "";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h ? `${h}시간 ${m}분` : `${m}분`;
}

/** 특강 카드 하나. 썸네일이 없으면 제목을 크게 깔아 빈 판처럼 안 보이게 한다. */
function LectureCard({ lecture: v }) {
  const date = v.created_at ? String(v.created_at).slice(0, 10).replaceAll("-", ".") : "";
  return (
    <Link to={`/videos/${v.id}`} className="iv-card">
      <div className="iv-thumb">
        {v.thumbnail
          ? <img src={v.thumbnail} alt="" loading="lazy" />
          : <span className="iv-thumb-name">{v.title}</span>}
        {v.duration_sec > 0 && <span className="iv-thumb-dur">{fmtLength(v.duration_sec)}</span>}
      </div>
      <div className="iv-card-body">
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
          {v.category && <span className="badge badge-cat">{v.category}</span>}
          <span className="lecture-members">회원 전용</span>
        </div>
        <div className="iv-card-title">{v.title}</div>
        {v.description && <p className="lecture-desc">{v.description}</p>}
        <div className="iv-card-meta">
          {[v.chapter_count ? `${v.chapter_count}개 파트` : "", date].filter(Boolean).join(" · ")}
        </div>
      </div>
    </Link>
  );
}

/** 카드는 두 가지다 — 페이지로 넘어가는 것(to)과 그 자리에서 창을 띄우는
 *  것(key). 겉모습은 같아야 해서 속만 갈라 끼운다. */
function CardGrid({ cards, onPick }) {
  const box = {
    display: "block", width: "100%", textAlign: "left",
    padding: 18, borderRadius: "var(--radius-sm)",
    border: "1px solid var(--line)", background: "var(--surface)",
    color: "inherit", textDecoration: "none", font: "inherit", cursor: "pointer",
  };

  const body = (c) => (
    <>
      <span className="badge badge-cat">{c.badge}</span>
      <div style={{ fontWeight: 700, fontSize: 17, margin: "10px 0 6px" }}>
        {c.title}
      </div>
      <p style={{
        fontSize: 13.5, color: "var(--steel)", margin: 0, lineHeight: 1.6,
        display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical",
        overflow: "hidden",
      }}>{c.desc}</p>
      {c.meta && (
        <div style={{ fontSize: 12.5, color: "var(--steel)", marginTop: 10 }}>
          {c.meta}
        </div>
      )}
    </>
  );

  return (
    <div style={{
      display: "grid", gap: 14, marginTop: 20,
      gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
    }}>
      {cards.map((c) => (c.to ? (
        <Link key={c.to} to={c.to} style={box}>{body(c)}</Link>
      ) : (
        <button key={c.key} type="button" style={box}
          onClick={() => onPick && onPick(c.key)}>{body(c)}</button>
      )))}
    </div>
  );
}
