import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useSeo } from "../seo";
import ApplyForm from "../components/ApplyForm";
import Curriculum from "../components/Curriculum";
import LecturerProfile from "../components/LecturerProfile";
import Modal from "../components/Modal";
import PaidPlayer from "../components/PaidPlayer";
import ReviewForm from "../components/ReviewForm";

/** 직업계고 합격한 학생들을 위한 영상 — 안내 · 신청 · 시청.
 *
 * 설명회(Briefing)와 같은 구성이다. 대표 화면, 강의 정보, 커리큘럼, 강사
 * 프로필. 파는 물건이라고 안내가 부실할 이유가 없고, 오히려 무엇을 사는지
 * 사기 전에 더 잘 보여야 한다.
 *
 * 설명회와 다른 점은 하나다 — **커리큘럼의 강의를 눌러 재생할 수 있는지**.
 * 그 판단은 서버가 한다(`source` 가 있으면 산 것). 화면이 "로그인했나 →
 * 신청했나 → 입금됐나"를 스스로 따지면 어느 한 줄이 빠졌을 때 안 산 사람에게
 * 주소가 나간다.
 */
function fmtLong(sec) {
  const s = Math.max(Math.floor(Number(sec) || 0), 0);
  const h = Math.floor(s / 3600);
  const m = Math.round((s % 3600) / 60);
  if (h && m) return `총 ${h}시간 ${m}분`;
  if (h) return `총 ${h}시간`;
  return `총 ${m}분`;
}

export default function GraduateVideo() {
  useSeo({
    title: "직업계고 합격한 학생들을 위한 영상",
    description: "자기소개서·포트폴리오·대학진학 전략까지, 합격 이후를 준비하는 영상.",
    path: "/graduate-video",
  });

  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  // **재생 중인 것을 주소가 아니라 번호로 들고 있는다.**
  // 시청 주소에는 세 시간짜리 티켓이 붙어 있어, 오래 보면 도중에 만료된다.
  // 주소를 붙들고 있으면 그때 그냥 끊기지만, 번호로 들고 있으면 목록을 다시
  // 받아 새 티켓이 붙은 주소로 이어서 틀 수 있다.
  const [at, setAt] = useState(null);         // { ci, ii } — 챕터·강의 번호
  const [reviewing, setReviewing] = useState(false);
  const [asked, setAsked] = useState(false);  // 이번 방문에 이미 물어봤다
  const videoRef = useRef(null);
  const resumeRef = useRef(null);             // 다시 받아올 때 돌아갈 초

  const load = () => api.graduateVideo().then((d) => { setData(d); return d; })
    .catch((e) => { setError(e.message); return null; });
  useEffect(() => { load(); }, []);

  // 티켓이 만료되기 전에 미리 새로 받아 둔다(서버 수명은 3시간).
  useEffect(() => {
    const id = setInterval(() => { load(); }, 150 * 60 * 1000);
    return () => clearInterval(id);
  }, []);

  // 번호로 지금 재생할 것을 찾는다. 목록을 다시 받으면 주소도 저절로 새것이
  // 되므로, 이 한 줄이 티켓 갱신의 전부다.
  const sourceAt = (d, pos) => {
    if (!d || !pos) return null;
    const ch = (d.chapters || [])[pos.ci];
    if (!ch) return null;
    return pos.ii >= 0 ? ((ch.items || [])[pos.ii] || {}).source || null : ch.source || null;
  };
  const now = sourceAt(data, at);

  const seek = (sec) => {
    const el = videoRef.current;
    if (!el) return;
    el.currentTime = sec || 0;
    el.play().catch(() => {});
  };

  // 커리큘럼에서 다른 강의를 고르면 그 초부터 다시 튼다.
  const start = (src, ci = 0, ii = -1) => {
    resumeRef.current = null;
    setAt(src ? { ci, ii } : null);
    setTimeout(() => seek(src?.start), 80);
  };

  // 다 보고 나면 후기를 묻는다.
  //
  // **마지막 것을 끝냈을 때만 묻는다.** 챕터가 여럿인데 1강이 끝날 때마다
  // 물으면 아직 다 보지도 않은 사람에게 세 번 묻는 꼴이 된다. 이미 남긴
  // 사람에게는 다시 안 묻는다(서버가 알려 준다).
  const isLast = (d, pos) => {
    if (!d || !pos) return false;
    const chs = d.chapters || [];
    const playable = [];
    chs.forEach((ch, ci) => {
      if (ch.source) playable.push({ ci, ii: -1 });
      (ch.items || []).forEach((it, ii) => { if (it.source) playable.push({ ci, ii }); });
    });
    const last = playable[playable.length - 1];
    return !!last && last.ci === pos.ci && last.ii === pos.ii;
  };

  const onEnded = () => {
    if (asked || data?.reviewed || !isLast(data, at)) return;
    setAsked(true);
    setReviewing(true);
  };

  // 재생 중 주소가 죽으면(티켓 만료·서버 재시작) 목록을 다시 받아 이어 튼다.
  const onVideoError = async () => {
    const el = videoRef.current;
    resumeRef.current = el ? el.currentTime : 0;
    const fresh = await load();
    const src = sourceAt(fresh, at);
    if (src) setTimeout(() => seek(resumeRef.current || src.start), 120);
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

  const chapters = data.chapters || [];
  // 첫 번째로 재생 가능한 것. 산 사람에게만 생긴다.
  let first = null;
  for (let i = 0; i < chapters.length && !first; i += 1) {
    const ch = chapters[i];
    if (ch.source) { first = { src: ch.source, ci: i, ii: -1 }; break; }
    const j = (ch.items || []).findIndex((it) => it.source);
    if (j >= 0) first = { src: ch.items[j].source, ci: i, ii: j };
  }

  return (
    <div className="wrap" style={{ padding: "24px 0 60px" }}>
      {/* ---- 대표 화면 ---- */}
      <div style={{
        position: "relative", borderRadius: "var(--radius)", overflow: "hidden",
        minHeight: 260,
        background: data.cover
          ? "#0d0d0f"
          : "linear-gradient(135deg, #2b2f3a 0%, #14161c 55%, #3a2320 100%)",
      }}>
        {now?.file_url ? (
          <PaidPlayer ref={videoRef} src={now.file_url} mark={data.watermark}
            onError={onVideoError} onEnded={onEnded} />
        ) : (
          <>
            {data.cover && (
              <img src={data.cover} alt=""
                style={{
                  position: "absolute", inset: 0, width: "100%", height: "100%",
                  objectFit: "cover", opacity: .55,
                }} />
            )}
            <div style={{
              position: "relative", padding: "44px 28px 30px",
              background: "linear-gradient(180deg, rgba(0,0,0,.25), rgba(0,0,0,.85))",
              color: "#fff",
            }}>
              <span style={{ fontSize: 12, letterSpacing: 2, opacity: .8, fontWeight: 700 }}>
                합격 이후
              </span>
              <h1 style={{ fontSize: 30, margin: "6px 0 10px", lineHeight: 1.25 }}>
                {data.headline || "직업계고 합격한 학생들을 위한 영상"}
              </h1>
              <p style={{
                fontSize: 14.5, lineHeight: 1.7, maxWidth: 620,
                opacity: .9, margin: "0 0 18px", whiteSpace: "pre-wrap",
              }}>
                {data.intro
                  || "자기소개서·포트폴리오·취업 후 대학진학 전략까지, 합격 이후를 준비하는 영상입니다."}
              </p>
              <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                {first ? (
                  /* 대표 화면은 설명만 한다. 재생은 아래 커리큘럼의 강의를 눌러 시작한다. */
                  <span className="hero-play-hint">
                    아래 커리큘럼에서 보고 싶은 강의를 누르면 재생됩니다.
                  </span>
                ) : (
                  <span style={{ fontSize: 13.5, opacity: .85 }}>
                    {data.owned
                      ? "영상이 아직 준비되지 않았습니다."
                      : "결제가 확인되면 여기서 바로 재생됩니다."}
                  </span>
                )}
                {data.summary?.duration_sec > 0 && (
                  <span style={{ fontSize: 13, opacity: .8 }}>
                    {fmtLong(data.summary.duration_sec)}
                  </span>
                )}
              </div>
            </div>
          </>
        )}
      </div>

      {now?.file_url && (
        <p style={{ fontSize: 12.5, color: "var(--steel)", margin: "8px 0 0", lineHeight: 1.6 }}>
          화면에 표시되는 이름과 번호 끝자리는 <b>보시는 분의 계정</b>입니다.
          녹화·복제본이 밖으로 돌면 이 표시로 출처가 확인됩니다.
        </p>
      )}

      {/* ---- 강의 정보 ---- */}
      <MetaLine summary={data.summary} owned={data.owned} />

      {/* ---- 커리큘럼 + 강사 ----
        * 설명회와 같은 두 칸 배치. 챕터를 훑어 내리는 동안에도 오른쪽이
        * 따라다녀야 해서, 바깥 칸은 늘어나게 두고 안쪽에 sticky 를 건다.
        */}
      <div className="briefing-cols" style={{
        display: "grid", gap: 20, marginTop: 26,
        gridTemplateColumns: "minmax(0, 1fr) 320px",
      }}>
        <div>
          <Curriculum chapters={chapters} onPlay={start} />
          <Gate data={data} onApplied={load} />
        </div>
        <div>
          <div style={{ position: "sticky", top: 16 }}>
            {/* 산 사람이 보는 화면이라 다른 신청 버튼은 띄우지 않는다. */}
            <LecturerProfile profile={data.lecturer} narrow showCta={false} />
          </div>
        </div>
      </div>

      <style>{`
        @media (max-width: 900px) {
          .briefing-cols { grid-template-columns: 1fr !important; }
          .briefing-cols > div:last-child > div { position: static !important; }
        }
      `}</style>

      {reviewing && (
        <Modal title="보신 소감을 남겨 주세요" onClose={() => setReviewing(false)}>
          <ReviewForm kind="graduate_video_review" title={null}
            intro="다음 영상을 더 낫게 만드는 데 씁니다."
            onDone={() => { setReviewing(false); load(); }}
            onCancel={() => setReviewing(false)} />
        </Modal>
      )}
    </div>
  );
}

/** 강의 정보 한 줄씩. 없는 값은 아예 안 보여 준다. */
function MetaLine({ summary, owned }) {
  const rows = [];
  if (summary?.chapters) {
    rows.push(["🎬", `챕터 ${summary.chapters}개`
      + (summary.lessons ? ` · 강의 ${summary.lessons}개` : "")]);
  }
  if (summary?.duration_sec) rows.push(["🕘", fmtLong(summary.duration_sec)]);
  if (!owned) rows.push(["🔒", "결제가 확인된 계정에서만 재생됩니다"]);
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

/** 지금 이 사람에게 무엇을 보여줄지. 네 갈래뿐이다 —
 *  샀다 / 입금 기다리는 중 / 취소됐다 / 아직 신청 안 했다. */
function Gate({ data, onApplied }) {
  if (data.owned) {
    return (
      <p style={{ fontSize: 13.5, color: "var(--steel)", marginTop: 16, lineHeight: 1.7 }}>
        결제가 확인된 계정입니다. 이 계정으로 로그인하시면 언제든 다시 보실 수 있습니다.
      </p>
    );
  }

  const status = data.application?.status;

  if (status === "received") {
    return (
      <div className="panel" style={{ marginTop: 18 }}>
        <h3>입금을 확인하고 있습니다</h3>
        <p style={{ fontSize: 14, lineHeight: 1.75, margin: 0 }}>
          신청이 접수되었습니다. 안내해 드린 계좌로 입금하시면 확인 후
          <b> 이 화면에서 바로 재생</b>됩니다. 따로 링크를 받으실 필요는 없습니다.
          <br />
          입금하셨는데도 하루가 지나도록 열리지 않으면 연락 주세요.
        </p>
      </div>
    );
  }

  if (status === "cancelled") {
    return (
      <div className="panel" style={{ marginTop: 18 }}>
        <h3>취소된 신청입니다</h3>
        <p style={{ fontSize: 14, lineHeight: 1.75, margin: 0 }}>
          다시 신청하시려면 연락 주세요.
        </p>
      </div>
    );
  }

  return (
    <ApplyForm kind="graduate_video" title="신청폼"
      applicantLabels={["본인", "학부모"]}
      messageLabel="기타 및 문의사항"
      doneNote="입금이 확인되면 이 화면에서 바로 재생됩니다. 지금 로그인한 계정으로 들어오시면 됩니다."
      onApplied={onApplied} />
  );
}
