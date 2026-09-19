import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useSeo } from "../seo";
import LecturerProfile from "../components/LecturerProfile";
import Curriculum from "../components/Curriculum";
import { toast } from "../toast";
import ReviewForm from "../components/ReviewForm";

/** 온라인 직업계고설명회.
 *
 * 화면을 넷플릭스 시리즈 페이지처럼 잡았다. 위에 큰 대표 화면과 [시청하기],
 * 아래에 회차(챕터) 목록. 강의는 영상 **한 편**이고 챕터는 그 안의 지점이라,
 * 챕터를 누르면 그 초부터 이어서 재생한다.
 *
 * **보기 전에 설문을 받는다.** 누가 어떻게 찾아왔는지가 이 설명회를 어디에
 * 더 알릴지 정하는 유일한 근거라, 시청 전에 반드시 받아야 한다. 다만 한 번
 * 낸 사람에게 다시 묻지 않는다(브라우저에 기억해 둔다) — 매번 물으면 두 번째
 * 부터는 아무 말이나 적고 넘긴다.
 *
 * 다 보고 나면 후기 창이 뜬다.
 */

const SEEN_KEY = "briefing_survey_done";

function fmtTime(sec) {
  const s = Math.max(Math.floor(Number(sec) || 0), 0);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = String(s % 60).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${r}` : `${m}:${r}`;
}

/** "총 4시간 45분" 처럼 사람이 읽는 길이. */
function fmtLong(sec) {
  const s = Math.max(Math.floor(Number(sec) || 0), 0);
  const h = Math.floor(s / 3600);
  const m = Math.round((s % 3600) / 60);
  if (h && m) return `총 ${h}시간 ${m}분`;
  if (h) return `총 ${h}시간`;
  return `총 ${m}분`;
}

export default function Briefing() {
  useSeo({
    title: "온라인 직업계고설명회",
    description: "직업계고가 무엇인지, 어떻게 준비하는지 — 온라인으로 듣는 설명회.",
    path: "/briefing",
  });

  // 숏츠에서 "특강에서 이어 보기"로 넘어오면 어느 영상의 몇 초인지가 주소에 있다.
  const [params] = useSearchParams();
  const wantVideo = Number(params.get("v")) || null;
  const wantAt = Number(params.get("t")) || 0;

  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [allowed, setAllowed] = useState(false);   // 설문을 냈는가
  const [asking, setAsking] = useState(false);     // 설문 창이 떠 있는가
  const [reviewing, setReviewing] = useState(false);
  const [reviewDone, setReviewDone] = useState(false);
  const [now, setNow] = useState(null);   // {file_url, start} — 지금 트는 것
  const videoRef = useRef(null);
  const pending = useRef(null);   // 설문을 내고 나면 틀 것
  const jumped = useRef(false);   // 주소로 넘어온 자동 재생은 한 번만

  useEffect(() => {
    api.briefing().then(setData).catch((e) => setError(e.message));
    try {
      setAllowed(localStorage.getItem(SEEN_KEY) === "1");
    } catch { /* 사생활 보호 모드 등 — 그냥 매번 묻는다 */ }
  }, []);

  // 숏츠에서 넘어온 경우: 그 영상을 쓰는 챕터를 찾아 바로 그 초부터 튼다.
  // 못 찾으면(그 영상이 특강에 안 들어 있으면) 그냥 페이지만 보여 준다 —
  // 엉뚱한 챕터를 트는 것보다 낫다.
  useEffect(() => {
    if (!data || !wantVideo || jumped.current) return;
    jumped.current = true;
    const ch = (data.chapters || []).find((c) => c.video_id === wantVideo);
    const src = ch?.source;
    if (src) start({ ...src, start: wantAt || src.start || 0 });
  }, [data, wantVideo, wantAt]);

  const video = data?.video;
  const chapters = data?.chapters || [];
  // [시청하기]가 틀 것. 기본 영상이 있으면 그것, 없으면 첫 챕터.
  const firstSource = (video?.file_url
    ? { file_url: video.file_url, start: 0 }
    : chapters.find((c) => c.source)?.source) || null;
  const playable = !!firstSource || chapters.some((c) => c.source);

  /** 재생 시작. 설문을 안 냈으면 먼저 받는다.
   *
   * source 는 서버가 정해 준 {file_url, start} 다. 챕터마다 파일이 다를 수
   * 있어서 "몇 초로 옮긴다"만으로는 부족하고, 틀 파일 자체를 바꿔 끼운다.
   */
  const start = (source) => {
    if (!source?.file_url) return;
    if (!allowed) {
      pending.current = source;
      setAsking(true);
      return;
    }
    setNow(source);
    setTimeout(() => {
      const el = videoRef.current;
      if (!el) return;
      el.currentTime = source.start || 0;
      el.play().catch(() => {});
      el.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 80);
  };

  const onSurveyDone = () => {
    try { localStorage.setItem(SEEN_KEY, "1"); } catch { /* 저장 못해도 진행 */ }
    setAllowed(true);
    setAsking(false);
    const wanted = pending.current || firstSource;
    pending.current = null;
    setNow(wanted || null);
    setTimeout(() => {
      const el = videoRef.current;
      if (!el || !wanted) return;
      el.currentTime = wanted.start || 0;
      el.play().catch(() => {});
    }, 80);
  };

  if (error) {
    return <div className="wrap" style={{ padding: 40 }}>
      <div className="notice notice-error">{error}</div>
    </div>;
  }
  if (!data) {
    return <div className="wrap" style={{ padding: 40 }}>
      <p style={{ color: "var(--steel)" }}>불러오는 중…</p>
    </div>;
  }

  return (
    <div className="wrap" style={{ padding: "24px 0 60px" }}>
      {/* ---- 대표 화면 ---- */}
      {/* 배경 순서: 관리자가 올린 대표 이미지 → 첫 챕터 영상의 첫 프레임 →
        * 둘 다 없으면 은은한 그라데이션. 검은 빈 판을 그대로 두면 "고장 났나"
        * 싶게 보인다. */}
      <div style={{
        position: "relative", borderRadius: "var(--radius)", overflow: "hidden",
        minHeight: 260,
        background: data.cover
          ? "#0d0d0f"
          : "linear-gradient(135deg, #2b2f3a 0%, #14161c 55%, #3a2320 100%)",
      }}>
        {now?.file_url ? (
          <video ref={videoRef} key={now.file_url} src={now.file_url} controls autoPlay
            onEnded={() => { if (!reviewDone) setReviewing(true); }}
            style={{ width: "100%", maxHeight: "70vh", display: "block", background: "#000" }} />
        ) : (
          <>
            {data.cover ? (
              <img src={data.cover} alt=""
                style={{
                  position: "absolute", inset: 0, width: "100%", height: "100%",
                  objectFit: "cover", opacity: .55,
                }} />
            ) : firstSource?.file_url ? (
              <video src={firstSource.file_url} preload="metadata" muted
                style={{
                  position: "absolute", inset: 0, width: "100%", height: "100%",
                  objectFit: "cover", opacity: .45,
                }} />
            ) : null}
            <div style={{
              position: "relative", padding: "44px 28px 30px",
              background: "linear-gradient(180deg, rgba(0,0,0,.25), rgba(0,0,0,.85))",
              color: "#fff",
            }}>
              <span style={{
                fontSize: 12, letterSpacing: 2, opacity: .8, fontWeight: 700,
              }}>온라인</span>
              <h1 style={{ fontSize: 30, margin: "6px 0 10px", lineHeight: 1.25 }}>
                {data.headline || "직업계고설명회"}
              </h1>
              <p style={{
                fontSize: 14.5, lineHeight: 1.7, maxWidth: 620,
                opacity: .9, margin: "0 0 18px", whiteSpace: "pre-wrap",
              }}>
                {data.intro
                  || "직업계고가 무엇인지, 우리 아이에게 맞는지, 어떻게 준비하는지 차근차근 짚어 드립니다."}
              </p>
              <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                {playable ? (
                  <button className="btn btn-signal" onClick={() => start(firstSource)}
                    style={{ fontSize: 15, padding: "11px 22px" }}>
                    ▶ 시청하기
                  </button>
                ) : (
                  <span style={{ fontSize: 13.5, opacity: .85 }}>
                    강의 영상이 아직 준비되지 않았습니다.
                  </span>
                )}
                {video?.duration_sec > 0 && (
                  <span style={{ fontSize: 13, opacity: .8 }}>
                    {fmtTime(video.duration_sec)}
                    {chapters.length > 0 && ` · ${chapters.length}개 챕터`}
                  </span>
                )}
              </div>
            </div>
          </>
        )}
      </div>

      {/* ---- 강의 정보 ---- */}
      <MetaLine summary={data.summary} video={video} />

      {/* ---- 커리큘럼 + 강사 ----
        * 두 칸으로 나눈다. 예전에는 커리큘럼이 화면 폭을 다 쓰고 강사가 그
        * 아래에 있었는데, 챕터 목록이 길어 강사를 보려면 한참 내려야 했다.
        * 옆에 두면 둘 다 한눈에 들어오고, 챕터 줄도 짧아져 제목이 더 잘 읽힌다.
        *
        * 오른쪽은 따라다니게(sticky) 둔다 — 챕터를 훑어 내리는 동안에도
        * 신청 버튼이 화면에 남아 있어야 한다.
        */}
      <div className="briefing-cols" style={{
        display: "grid", gap: 20, marginTop: 26,
        gridTemplateColumns: "minmax(0, 1fr) 320px",
      }}>
        <Curriculum chapters={chapters} onPlay={start} />
        {/* 바깥 칸은 줄 높이만큼 늘어나고(그래야 붙어 다닐 여백이 생긴다),
          * 안쪽이 실제로 따라다닌다. 바깥에 바로 sticky 를 걸면 칸 높이가
          * 카드 높이와 같아져서 붙을 자리가 없다. */}
        <div>
          <div style={{ position: "sticky", top: 16 }}>
            <LecturerProfile profile={data.lecturer} narrow />
          </div>
        </div>
      </div>

      <style>{`
        @media (max-width: 900px) {
          .briefing-cols { grid-template-columns: 1fr !important; }
          .briefing-cols > div:last-child > div { position: static !important; }
        }
      `}</style>

      {/* ---- 시청 전 설문 ---- */}
      {asking && (
        <Modal onClose={() => setAsking(false)}>
          <SurveyForm onDone={onSurveyDone} onCancel={() => setAsking(false)} />
        </Modal>
      )}

      {/* ---- 시청 후 후기 ---- */}
      {reviewing && (
        <Modal onClose={() => setReviewing(false)}>
          <ReviewForm kind="briefing_review"
            intro="다음 설명회를 더 낫게 만드는 데 씁니다."
            onDone={() => { setReviewDone(true); setReviewing(false); }}
            onCancel={() => { setReviewDone(true); setReviewing(false); }} />
        </Modal>
      )}
    </div>
  );
}

/** 강의 정보 한 줄씩 — 클래스101처럼 아이콘 + 사실만.
 *
 * 없는 값은 아예 안 보여 준다. "난이도: -" 같은 빈칸은 화면만 채우고
 * 알려 주는 게 없다.
 */
function MetaLine({ summary, video }) {
  const rows = [];
  if (summary?.chapters) {
    rows.push(["🎬", `챕터 ${summary.chapters}개`
      + (summary.lessons ? ` · 강의 ${summary.lessons}개` : "")]);
  }
  if (summary?.duration_sec) rows.push(["🕘", fmtLong(summary.duration_sec)]);
  if (video && !video.file_url) rows.push(["🔒", "영상이 아직 공개되지 않았습니다"]);
  if (!rows.length) return null;

  return (
    <div style={{ display: "grid", gap: 8, margin: "20px 0 0" }}>
      {rows.map(([icon, text], i) => (
        <div key={i} style={{ display: "flex", gap: 10, alignItems: "center",
          fontSize: 14, color: "var(--ink)" }}>
          <span style={{ opacity: .75 }}>{icon}</span>{text}
        </div>
      ))}
    </div>
  );
}

/** 화면 가운데 띄우는 창. 바깥을 눌러도 닫힌다. */
function Modal({ children, onClose }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, zIndex: 90, background: "rgba(0,0,0,.55)",
      display: "grid", placeItems: "center", padding: 16, overflowY: "auto",
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "var(--surface)", borderRadius: "var(--radius)",
        padding: "22px 22px 20px", width: "100%", maxWidth: 460,
        boxShadow: "0 12px 40px rgba(0,0,0,.35)",
      }}>
        {children}
      </div>
    </div>
  );
}

/** 시청 전 설문 — 이미지의 세 항목 그대로. */
function SurveyForm({ onDone, onCancel }) {
  const [form, setForm] = useState({
    found_path: "", found_etc: "", school: "", applicant: "",
    name: "", phone: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const set = (patch) => setForm({ ...form, ...patch });

  const submit = async (e) => {
    e.preventDefault();
    if (!form.found_path || !form.applicant) {
      setError("알게 된 경로와 구분을 선택해 주세요.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.submitApplication({
        kind: "briefing_survey",
        name: form.name.trim() || "(미입력)",
        phone: form.phone.trim() || "-",
        found_path: form.found_path,
        found_etc: form.found_etc.trim(),
        applicant: form.applicant,
        extra: { "근무·재학 중인 중학교": form.school.trim() || "-" },
      });
      toast.ok("신청이 접수되었습니다.");
      onDone();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit}>
      <h3 style={{ border: "none", padding: 0, margin: "0 0 4px" }}>
        시청 전에 한 가지만
      </h3>
      <p style={{ fontSize: 13, color: "var(--steel)", margin: "0 0 16px", lineHeight: 1.6 }}>
        이 설명회를 어디에 더 알릴지 정하는 데 쓰입니다. 한 번만 여쭤봅니다.
      </p>

      <div style={{ display: "grid", gap: 14 }}>
        <div className="field">
          <label className="label">우리동네직업계고를 알게 된 경로</label>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            {["소개", "검색", "기타"].map((v) => (
              <label key={v} style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 14 }}>
                <input type="radio" name="sfound" checked={form.found_path === v}
                  onChange={() => set({ found_path: v })} />
                {v}
              </label>
            ))}
          </div>
          {form.found_path === "기타" && (
            <input className="input" style={{ marginTop: 8 }}
              placeholder="어떻게 알게 되셨나요?"
              value={form.found_etc}
              onChange={(e) => set({ found_etc: e.target.value })} />
          )}
        </div>

        <div className="field">
          <label className="label">근무 또는 재학 중인 중학교</label>
          <input className="input" value={form.school}
            placeholder="예) 양주중학교"
            onChange={(e) => set({ school: e.target.value })} />
        </div>

        <div className="field">
          <label className="label">구분</label>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            {["학생", "교원"].map((v) => (
              <label key={v} style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 14 }}>
                <input type="radio" name="sapp" checked={form.applicant === v}
                  onChange={() => set({ applicant: v })} />
                {v}
              </label>
            ))}
          </div>
        </div>

        {error && <div className="notice notice-error">{error}</div>}

        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn btn-signal" type="submit" disabled={busy}>
            {busy ? "보내는 중…" : "확인하고 시청하기"}
          </button>
          <button className="btn btn-ghost" type="button" onClick={onCancel}>취소</button>
        </div>
      </div>
    </form>
  );
}
