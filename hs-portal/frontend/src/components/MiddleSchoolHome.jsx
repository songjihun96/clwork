import { useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth";
import NoticeSettings from "./NoticeSettings";

/** 중학교 학교 계정의 첫 화면 — '직업계고 진학 지원'.
 *
 *  중학교 계정의 목적은 학교 홍보가 아니라, 학생들이 직업계고를 알아보고 진학을
 *  준비하도록 돕는 것이다. 그래서 고등학교용 학교 관리(학교 정보·일정 등록·문의·
 *  진학정보 입력·노출 플랜)는 보이지 않고, 서버도 막는다.
 *  여기 있는 카드는 **이미 있는 기능**으로만 이어진다 — 없는 기능을 약속하지 않는다.
 */
const CARDS = [
  { to: "/search", icon: "travel_explore", title: "직업계고 찾기",
    desc: "지역·학과·계열로 특성화고·마이스터고를 찾아보고 학교를 비교합니다." },
  { to: "/events", icon: "event", title: "입학설명회·학교 일정",
    desc: "직업계고가 올린 입학설명회·체험 행사 일정을 확인합니다." },
  { to: "/special", icon: "smart_display", title: "온라인 직업계고 설명회",
    desc: "직업계고가 무엇인지, 어떻게 준비하는지 영상으로 안내합니다." },
  { to: "/interviews", icon: "mic", title: "학교 인터뷰",
    desc: "직업계고 선생님·재학생 인터뷰로 학교 안의 모습을 봅니다." },
  { to: "/quiz", icon: "psychology", title: "진로 테스트",
    desc: "학생이 흥미에 맞는 계열과 학과를 찾아볼 수 있습니다." },
  { to: "/counseling", icon: "support_agent", title: "직업계고 진학 상담",
    desc: "직업계고 진학 상담을 신청할 수 있습니다." },
  { to: "/notices", icon: "campaign", title: "공지사항",
    desc: "우리동네 직업계고 공지를 확인합니다." },
];

export default function MiddleSchoolHome() {
  const { user } = useAuth();
  const [tab, setTab] = useState("home");
  return (
    <div className="wrap" style={{ padding: "34px 0 60px" }}>
      <span className="label">중학교 · 직업계고 진학 지원</span>
      <h1 style={{ fontSize: 26, margin: "8px 0 4px" }}>{user?.school_name || "우리 학교"}</h1>
      <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 0, lineHeight: 1.7 }}>
        학생들이 직업계고를 알아보고 진학을 준비하도록 돕는 자료를 모았습니다.
      </p>

      <div className="tabs" style={{ marginTop: 20 }}>
        <button className={`tab ${tab === "home" ? "active" : ""}`} onClick={() => setTab("home")}>진학 지원</button>
        <button className={`tab ${tab === "notify" ? "active" : ""}`} onClick={() => setTab("notify")}>공지 알림 설정</button>
      </div>

      {tab === "home" ? (
        <div className="mid-grid">
          {CARDS.map((c) => (
            <Link key={c.to} to={c.to} className="mid-card">
              <span className="msi" aria-hidden="true">{c.icon}</span>
              <b>{c.title}</b>
              <small>{c.desc}</small>
            </Link>
          ))}
        </div>
      ) : (
        <div style={{ marginTop: 16 }}><NoticeSettings /></div>
      )}
    </div>
  );
}
