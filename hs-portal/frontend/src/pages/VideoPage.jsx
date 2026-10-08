import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useSeo } from "../seo";

function fmt(sec) {
  if (sec === null || sec === undefined) return "";
  const s = Math.max(Math.floor(Number(sec)), 0);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = String(s % 60).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

/** "약 20분". 챕터 목록에서 길이를 대강 알려 줄 때. */
function about(sec) {
  const m = Math.round((Number(sec) || 0) / 60);
  if (m <= 0) return "";
  return m >= 60 ? `약 ${Math.floor(m / 60)}시간 ${m % 60 ? `${m % 60}분` : ""}`.trim() : `약 ${m}분`;
}

/** 지금 재생 위치가 들어 있는 챕터. 끝 시각은 서버가 채워 준 값(effective_end_sec)을 쓴다. */
function chapterAt(chapters, t) {
  for (let i = chapters.length - 1; i >= 0; i -= 1) {
    const c = chapters[i];
    const end = c.effective_end_sec ?? Infinity;
    if (t >= c.start_sec && t < end) return c.id;
  }
  return null;
}

/** 롱폼 보기.
 *
 * 숏츠에서 넘어올 때 ?t=204.12 를 달고 온다. 그 초부터 재생하는 것이
 * 이 화면의 존재 이유다 — 새로고침해도 유지돼야 해서 주소에 담는다.
 *
 * 긴 영상은 관리자가 챕터(파트)로 나눠 둘 수 있다. 파일을 자르지 않고
 * 시각으로만 나누므로, 챕터를 누르면 같은 영상에서 그 초로 옮겨 이어 본다.
 * 오른쪽 목록은 재생 위치를 따라 지금 챕터를 표시한다.
 */
export default function VideoPage() {
  const { id } = useParams();
  const [params] = useSearchParams();
  const [video, setVideo] = useState(null);
  const [error, setError] = useState("");
  const [current, setCurrent] = useState(null);   // 지금 재생 중인 챕터 id
  const videoRef = useRef(null);
  const seeked = useRef(false);
  const pendingSeek = useRef(null);
  const location = useLocation();

  const startAt = Number(params.get("t") || params.get("start") || 0);

  useSeo({
    title: video ? video.title : "영상",
    description: video?.description || undefined,
    path: `/videos/${id}`,
  });

  useEffect(() => {
    seeked.current = false;
    setCurrent(null);
    api.video(id).then(setVideo).catch((e) => setError(e.message));
    api.countVideoView(id).catch(() => {});
  }, [id]);

  const chapters = video?.chapters || [];

  // 메타데이터가 준비돼야 currentTime 이 먹는다. 한 번만 옮긴다 —
  // 이후 사용자가 되감았을 때 다시 끌고 오면 안 된다.
  const onLoaded = () => {
    const el = videoRef.current;
    if (!el) return;
    if (pendingSeek.current !== null) {
      el.currentTime = pendingSeek.current;
      pendingSeek.current = null;
      el.play().catch(() => {});
      return;
    }
    if (seeked.current || !startAt) return;
    el.currentTime = Math.min(startAt, el.duration || startAt);
    seeked.current = true;
    el.play().catch(() => {});
  };

  const onTime = () => {
    const el = videoRef.current;
    if (!el || !chapters.length) return;
    const now = chapterAt(chapters, el.currentTime);
    if (now !== current) setCurrent(now);
  };

  const jump = (c) => {
    const el = videoRef.current;
    setCurrent(c.id);
    if (!el) return;
    // 아직 메타데이터를 못 받았으면 받는 대로 옮긴다.
    if (el.readyState < 1) {
      pendingSeek.current = c.start_sec;
      return;
    }
    el.currentTime = c.start_sec;
    el.play().catch(() => {});
  };

  if (error) {
    return <div className="wrap" style={{ padding: 40 }}>
      <div className="notice notice-error">{error}</div>
    </div>;
  }
  if (!video) {
    return <div className="wrap" style={{ padding: 40 }}><div className="empty"><p>불러오는 중…</p></div></div>;
  }

  const next = encodeURIComponent(location.pathname + location.search);
  const player = video.file_url ? (
    <video
      ref={videoRef}
      src={video.file_url}
      controls
      controlsList="nodownload"
      onContextMenu={(e) => e.preventDefault()}
      playsInline
      onLoadedMetadata={onLoaded}
      onTimeUpdate={onTime}
      onSeeked={onTime}
      style={{ width: "100%", borderRadius: "var(--radius)", background: "#000",
        aspectRatio: "16 / 9", display: "block" }}
    />
  ) : video.login_required ? (
    // 설명회·학교 인터뷰에 쓰인 영상은 회원만 본다. 서버가 주소를 안 준다.
    <div className="members-lock">
      <div className="members-lock-icon" aria-hidden="true">🔒</div>
      <p>이 영상은 회원만 볼 수 있어요. 가입은 무료예요.</p>
      <div className="members-lock-actions">
        <Link className="btn btn-signal" to={`/signup?next=${next}`}>무료 회원가입</Link>
        <Link className="btn btn-ghost" to={`/login?next=${next}`}>로그인</Link>
      </div>
    </div>
  ) : (
    <div className="empty"><p>영상 파일이 없습니다.</p></div>
  );

  return (
    <div className="wrap" style={{ padding: "24px 0 60px" }}>
      {video.is_lecture ? (
        <Link to="/special" className="btn btn-ghost btn-sm" style={{ marginBottom: 14 }}>
          ← 온라인 직업계고 설명회
        </Link>
      ) : (
        <Link to="/shorts" className="btn btn-ghost btn-sm" style={{ marginBottom: 14 }}>
          ← 숏츠로
        </Link>
      )}

      <div className={chapters.length ? "vp-layout" : undefined}>
        <div className="vp-main">
          {player}

          <h1 style={{ fontSize: 22, margin: "16px 0 4px" }}>{video.title}</h1>
          <p style={{ color: "var(--steel)", fontSize: 13.5, marginTop: 0 }}>
            조회 {(video.view_count || 0).toLocaleString()}회
            {video.duration_sec ? ` · ${fmt(video.duration_sec)}` : ""}
            {chapters.length ? ` · ${chapters.length}개 파트` : ""}
          </p>
          {startAt > 0 && (
            <div className="notice notice-info" style={{ marginTop: 6 }}>
              숏츠에 나온 <b>{fmt(startAt)}</b> 지점부터 재생합니다.
            </div>
          )}
          {video.description && (
            <p className="prose" style={{ marginTop: 12 }}>{video.description}</p>
          )}
        </div>

        {chapters.length > 0 && (
          <aside className="vp-chapters" aria-label="챕터">
            <div className="vp-chapters-head">
              챕터 <span>{chapters.length}</span>
            </div>
            <ol>
              {chapters.map((c, i) => {
                const len = c.effective_end_sec != null ? c.effective_end_sec - c.start_sec : null;
                const on = current === c.id;
                return (
                  <li key={c.id}>
                    <button type="button" className={`vp-chapter${on ? " on" : ""}`}
                      aria-current={on ? "true" : undefined}
                      disabled={!video.file_url}
                      onClick={() => jump(c)}>
                      <span className="vp-chapter-no">{String(i + 1).padStart(2, "0")}</span>
                      <span className="vp-chapter-body">
                        <span className="vp-chapter-title">{c.title}</span>
                        <span className="vp-chapter-time">
                          {fmt(c.start_sec)}{len ? ` · ${about(len)}` : ""}
                        </span>
                      </span>
                      {on && <span className="vp-chapter-now">재생 중</span>}
                    </button>
                  </li>
                );
              })}
            </ol>
            {!video.file_url && video.login_required && (
              <p className="vp-chapters-note">로그인하면 파트를 골라 볼 수 있어요.</p>
            )}
          </aside>
        )}
      </div>

      {video.shorts?.length > 0 && (
        <div className="panel" style={{ marginTop: 22 }}>
          <h3>이 영상에서 나온 숏츠</h3>
          <div style={{ display: "grid", gap: 10,
            gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))" }}>
            {video.shorts.map((s) => (
              <Link key={s.id} to={`/shorts/${s.id}`} className="panel"
                style={{ marginTop: 0, textDecoration: "none", color: "inherit", padding: 12 }}>
                <div style={{ fontWeight: 600, fontSize: 14, lineHeight: 1.4 }}>{s.title}</div>
                {s.source_start_time !== null && s.source_start_time !== undefined && (
                  <div style={{ fontSize: 12, color: "var(--steel)", marginTop: 4 }}>
                    원본 {fmt(s.source_start_time)} 지점
                  </div>
                )}
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
