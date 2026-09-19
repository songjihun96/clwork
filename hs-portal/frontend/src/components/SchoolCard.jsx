import { PLAN_LABEL } from "../api";

const CATEGORY_ICONS = {
  특성화고: "🏫", 마이스터고: "⚙️", 과학고: "🔬", 외국어고: "🌐",
  국제고: "🌏", 예술고: "🎨", 체육고: "🏅", 자율고: "📘", 일반고: "🎓",
};

export function PlanBadge({ plan, visible = true }) {
  // 플랜 마크는 내부용(관리자·학교계정)에게만 노출한다.
  // 학생·비로그인에게 보이면 광고처럼 인식될 수 있어 숨긴다.
  if (!visible) return null;
  if (plan === "platinum") {
    return (
      <span className="badge badge-top" title="플래티넘 플랜">
        <span>추천</span>
      </span>
    );
  }
  if (plan === "premium" || plan === "basic") {
    return <span className="badge">{PLAN_LABEL[plan]}</span>;
  }
  return null;
}

export function QuickInquiryBadge({ available }) {
  // 포털에 학교 계정이 개설되어 답변을 받을 수 있는 학교만 '빠른 문의 가능'.
  if (available) {
    return (
      <span className="badge badge-quick" title="학교가 답변을 등록하면 이메일로 받아보실 수 있습니다">
        ⚡ 빠른 문의 가능
      </span>
    );
  }
  return (
    <span className="badge badge-quick-off" title="이 학교는 아직 포털에 계정을 개설하지 않았습니다">
      빠른 문의 불가
    </span>
  );
}

export function DormBadge({ value }) {
  // 기숙사가 있는 경우에만 표시한다.
  if (value === true) return <span className="badge badge-dorm">기숙사</span>;
  return null;
}

export default function SchoolCard({ school, onOpen, onToggleFavorite, showFavorite, showPlanMark }) {
  // 플랜별 색상 띠·배경도 내부용(관리자·학교계정)에게만 보인다.
  // 학생·비로그인에겐 모든 카드를 동일하게(plan-free 스타일) 보여줘 광고처럼 안 보이게 한다.
  const planClass = showPlanMark ? `plan-${school.plan}` : "plan-free";
  return (
    <div className={`school-card ${planClass}`} onClick={() => onOpen(school.id)}>
      <div className="card-photo" style={school.hero_image ? { backgroundImage: `url(${school.hero_image})` } : undefined}>
        {!school.hero_image && (CATEGORY_ICONS[school.category] || "🏫")}
        <span className="card-photo-badge">{school.category}</span>
        {showFavorite && (
          <button
            className={`card-photo-fav ${school.is_favorite ? "on" : ""}`}
            title={school.is_favorite ? "즐겨찾기에서 빼기" : "즐겨찾기에 넣기"}
            onClick={(e) => {
              e.stopPropagation();
              onToggleFavorite(school);
            }}
          >
            {school.is_favorite ? "★" : "☆"}
          </button>
        )}
      </div>

      <div className="card-main">
        <div className="card-top">
          <span className="card-name">{school.name}</span>
          <PlanBadge plan={school.plan} visible={showPlanMark} />
          <QuickInquiryBadge available={school.can_quick_inquiry} />
        </div>

        {school.slogan && <p className="card-slogan">{school.slogan}</p>}

        <div className="card-specs">
          <span className="spec">
            <b>위치</b>
            {school.region} · {school.address.replace(/^[^ ]+ /, "")}
          </span>
          <span className="spec">
            <b>공학</b>
            {school.coed}
          </span>
          {school.dormitory === true && (
            <span className="spec">
              <b>기숙사</b>
              있음
            </span>
          )}
          {school.phone && (
            <span className="spec">
              <b>전화</b>
              {school.phone}
            </span>
          )}
          {school.foundation && (
            <span className="spec">
              <b>설립</b>
              {school.foundation}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
