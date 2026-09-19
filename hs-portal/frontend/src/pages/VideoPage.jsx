import { useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
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

/** 롱폼 보기.
 *
 * 숏츠에서 넘어올 때 ?t=204.12 를 달고 온다. 그 초부터 재생하는 것이
 * 이 화면의 존재 이유다 — 새로고침해도 유지돼야 해서 주소에 담는다.
 */
export default function VideoPage() {
  const { id } = useParams();
  const [params] = useSearchParams();
  const [video, setVideo] = useState(null);
  const [error, setError] = useState("");
  const videoRef = useRef(null);
  const seeked = useRef(false);

  const startAt = Number(params.get("t") || params.get("start") || 0);

  useSeo({
    title: video ? video.title : "영상",
    description: video?.description || undefined,
    path: `/videos/${id}`,
  });

  useEffect(() => {
    seeked.current = false;
    api.video(id).then(setVideo).catch((e) => setError(e.message));
    api.countVideoView(id).catch(() => {});
  }, [id]);

  // 메타데이터가 준비돼야 currentTime 이 먹는다. 한 번만 옮긴다 —
  // 이후 사용자가 되감았을 때 다시 끌고 오면 안 된다.
  const onLoaded = () => {
    const el = videoRef.current;
    if (!el || seeked.current || !startAt) return;
    el.currentTime = Math.min(startAt, el.duration || startAt);
    seeked.current = true;
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

  return (
    <div className="wrap" style={{ padding: "24px 0 60px" }}>
      <Link to="/shorts" className="btn btn-ghost btn-sm" style={{ marginBottom: 14 }}>
        ← 숏츠로
      </Link>

      {video.file_url ? (
        <video
          ref={videoRef}
          src={video.file_url}
          controls
          playsInline
          onLoadedMetadata={onLoaded}
          style={{ width: "100%", borderRadius: "var(--radius)", background: "#000",
            aspectRatio: "16 / 9" }}
        />
      ) : (
        <div className="empty"><p>영상 파일이 없습니다.</p></div>
      )}

      <h1 style={{ fontSize: 22, margin: "16px 0 4px" }}>{video.title}</h1>
      <p style={{ color: "var(--steel)", fontSize: 13.5, marginTop: 0 }}>
        조회 {(video.view_count || 0).toLocaleString()}회
        {video.duration_sec ? ` · ${fmt(video.duration_sec)}` : ""}
      </p>
      {startAt > 0 && (
        <div className="notice notice-info" style={{ marginTop: 6 }}>
          숏츠에 나온 <b>{fmt(startAt)}</b> 지점부터 재생합니다.
        </div>
      )}
      {video.description && (
        <p className="prose" style={{ marginTop: 12 }}>{video.description}</p>
      )}

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
