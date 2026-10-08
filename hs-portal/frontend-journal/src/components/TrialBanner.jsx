import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { api } from "../api";

/** 첫 달 무료 안내 띠 (학생 화면 맨 위).
 *
 * - 무료 중이고 남은 날이 7일 이하: "무료 이용 기간이 N일 남았습니다."
 * - 무료가 끝났고 이용권이 없음: "무료 이용 기간이 종료되었습니다."
 * 그 밖(무료 초반, 유료, 학교 이용권, 무료 대상 아님)에는 아무것도 띄우지 않는다.
 *
 * 닫으면 그날 하루는 다시 띄우지 않는다(날짜 열쇠). 상태 판단은 서버가 한다.
 */
export default function TrialBanner() {
  const location = useLocation();
  const [t, setT] = useState(null);
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    api.trialStatus().then(setT).catch(() => {});
  }, [location.pathname === "/subscribe"]);  // 결제하고 돌아오면 다시 본다

  const today = new Date().toISOString().slice(0, 10);
  const key = t ? `trial-banner:${t.status}:${today}` : "";
  useEffect(() => {
    if (!key) return;
    try { setHidden(localStorage.getItem(key) === "1"); } catch { /* 저장소를 못 써도 그냥 보인다 */ }
  }, [key]);

  if (!t || hidden || location.pathname === "/subscribe") return null;
  const ending = t.status === "trial" && t.notice;
  const ended = t.status === "trial_ended";
  if (!ending && !ended) return null;

  const close = () => {
    setHidden(true);
    try { localStorage.setItem(key, "1"); } catch { /* 무시 */ }
  };

  return (
    <div className={`trial-banner${ended ? " ended" : ""}`} role="status">
      <div className="wrap trial-banner-inner">
        <span className="trial-banner-text">
          {ended ? (
            <>
              <b>무료 이용 기간이 종료되었습니다.</b> 계속 자기소개서를 쓰려면 유료 서비스를 이용해 주세요.
              <span className="trial-banner-sub">일지 작성과 선생님께 제출은 계속 무료입니다.</span>
            </>
          ) : t.days_left <= 0 ? (
            <><b>오늘이 무료 이용 마지막 날입니다.</b></>
          ) : (
            <>
              <b>무료 이용 기간이 {t.days_left}일 남았습니다.</b>
              {t.last_day && ` ${Number(t.last_day.slice(5, 7))}월 ${Number(t.last_day.slice(8, 10))}일까지 무료로 이용할 수 있습니다.`}
            </>
          )}
        </span>
        <span className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
          <Link className="btn btn-sm btn-primary" to="/subscribe">{ended ? "이용권 보기" : "미리 이용권 보기"}</Link>
          <button type="button" className="btn btn-sm btn-ghost" onClick={close} aria-label="오늘 그만 보기">닫기</button>
        </span>
      </div>
    </div>
  );
}
