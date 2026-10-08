import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { useSeo } from "../seo";

/** 숏츠 보기 — 세로 전체화면, 위아래로 넘긴다.
 *
 * 숏츠의 값어치는 "짧게 보고 궁금하면 원본으로 간다"에 있다. 그래서
 * [전체 영상 보기] 버튼이 화면에서 가장 눈에 띄어야 하고, 눌렀을 때
 * 롱폼 처음이 아니라 **이 숏츠가 잘려 나온 그 초**부터 시작해야 한다.
 * 그 초는 관리자가 확정한 것만 내려온다(추정값으로 엉뚱한 데서 시작하면
 * 연결이 없느니만 못하다).
 */
export default function Shorts() {
  useSeo({
    title: "숏츠",
    description: "직업계고 진로·취업 이야기를 짧게. 궁금한 대목은 전체 영상에서 이어 보세요.",
    path: "/shorts",
  });
  const { id } = useParams();
  const navigate = useNavigate();

  const [items, setItems] = useState([]);
  const [index, setIndex] = useState(0);
  const [detail, setDetail] = useState(null);
  // 소리를 켠 채로 시작한다. 다만 브라우저가 거절할 수 있어(아래 참고)
  // 실제로 소리가 나는지는 재생을 시도해 봐야 안다.
  const [muted, setMuted] = useState(false);
  const [blocked, setBlocked] = useState(false);   // 브라우저가 소리를 막았나
  const [playing, setPlaying] = useState(true);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");
  const [dragY, setDragY] = useState(0);      // 손가락을 따라 살짝 움직이는 양
  const videoRef = useRef(null);
  const drag = useRef(null);                   // {startY, moved}

  useEffect(() => {
    api.videos("shorts")
      .then((list) => {
        setItems(list);
        if (id) {
          const at = list.findIndex((v) => String(v.id) === String(id));
          if (at >= 0) setIndex(at);
        }
      })
      .catch((e) => setError(e.message));
  }, []);

  const current = items[index];

  // 원본 구간은 상세에만 들어 있다. 화면에 보이는 영상이 바뀔 때만 받는다.
  useEffect(() => {
    if (!current) return;
    setDetail(null);
    setProgress(0);
    api.video(current.id).then(setDetail).catch(() => setDetail(null));
    api.countVideoView(current.id).catch(() => {});
    // 주소를 함께 바꿔 둔다 — 이 숏츠를 그대로 공유할 수 있어야 한다.
    window.history.replaceState(null, "", `/shorts/${current.id}`);
  }, [current?.id]);

  /** 소리를 켠 채로 재생을 시도한다.
   *
   * 브라우저는 사용자가 페이지를 건드리기 전에는 **소리 나는 자동재생을
   * 거절한다**(크롬·사파리 공통). 그래서 그냥 muted={false} 로 두면 소리가
   * 켜지는 게 아니라 **영상이 아예 안 돌아간다** — 검은 화면만 남는다.
   *
   * 그래서 순서를 둔다. 소리를 켜고 시도해 보고, 거절당하면 그때만 음소거로
   * 되돌려 재생한다. 학생은 최소한 영상을 보게 되고, 화면에 "소리 켜기"를
   * 띄워 한 번만 누르면 그 뒤로는 계속 소리가 난다.
   */
  const tryPlayWithSound = useCallback(async () => {
    const el = videoRef.current;
    if (!el) return;
    el.muted = false;
    try {
      await el.play();
      setMuted(false);
      setBlocked(false);
    } catch {
      // 정책에 막혔다. 소리를 끄고라도 보여 준다.
      el.muted = true;
      setMuted(true);
      setBlocked(true);
      el.play().catch(() => {});
    }
  }, []);

  const move = useCallback((delta) => {
    setDragY(0);
    setIndex((i) => Math.min(Math.max(i + delta, 0), Math.max(items.length - 1, 0)));
  }, [items.length]);

  // ---- 넘기기 동작 ----
  // 손가락(모바일)과 마우스 드래그만 받는다.
  //
  // 휠은 일부러 뺐다. 페이지를 훑어 내리려고 굴린 것까지 "다음 영상"으로
  // 먹어서, 보려던 영상이 멋대로 넘어간다. 넘기려는 뜻이 분명한 동작
  // (끌기)만 받는 편이 낫다.
  const SWIPE_MIN = 50;        // 이만큼 끌어야 넘어간다. 탭과 구분하는 선.

  const onDragStart = (y) => { drag.current = { startY: y, moved: 0 }; };

  const onDragMove = (y) => {
    if (!drag.current) return;
    const dy = y - drag.current.startY;
    drag.current.moved = dy;
    // 끌리는 만큼 화면도 따라 움직여야 "넘어가는 중"이라는 게 느껴진다.
    // 끝에서는 덜 움직여 더 갈 곳이 없음을 알린다.
    const atEdge = (dy > 0 && index === 0) || (dy < 0 && index >= items.length - 1);
    setDragY(atEdge ? dy * 0.25 : dy);
  };

  const onDragEnd = () => {
    const dy = drag.current?.moved || 0;
    drag.current = null;
    if (Math.abs(dy) > SWIPE_MIN) move(dy < 0 ? 1 : -1);
    else setDragY(0);
  };

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "ArrowDown") move(1);
      else if (e.key === "ArrowUp") move(-1);
      else if (e.key === " ") { e.preventDefault(); togglePlay(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [move]);

  const togglePlay = () => {
    const el = videoRef.current;
    if (!el) return;
    if (el.paused) { el.play().catch(() => {}); setPlaying(true); }
    else { el.pause(); setPlaying(false); }
  };

  const goLongform = () => {
    const src = detail?.source;
    if (!src) return;
    // 특강 페이지로 보낸다. 원본 영상만 덩그러니 띄우면 "이게 무슨 강의의
    // 어디쯤인지"를 알 수 없다 — 커리큘럼 안에서 그 챕터가 재생돼야
    // 앞뒤로 무엇이 더 있는지까지 같이 보인다.
    // 어느 영상의 몇 초인지는 주소에 담아, 새로고침해도 그대로 이어진다.
    navigate(`/briefing?v=${src.longform_id}&t=${src.start}`);
  };

  if (error) return <div className="wrap" style={{ padding: 40 }}><div className="notice notice-error">{error}</div></div>;
  if (!items.length) {
    return (
      <div className="wrap" style={{ padding: 40 }}>
        <div className="empty"><p>아직 등록된 숏츠가 없습니다.</p></div>
      </div>
    );
  }

  return (
    <div
      style={{
        position: "relative", width: "100%", maxWidth: 460, margin: "0 auto",
        height: "calc(100vh - 120px)", background: "#000",
        borderRadius: "var(--radius)", overflow: "hidden",
        // 이게 없으면 브라우저가 세로 드래그를 페이지 스크롤로 먹어서
        // 스와이프가 아예 안 걸린다. 숏츠에서는 우리가 세로를 쓴다.
        touchAction: "none",
        userSelect: "none",
        cursor: drag.current ? "grabbing" : "grab",
      }}
      onTouchStart={(e) => onDragStart(e.touches[0].clientY)}
      onTouchMove={(e) => onDragMove(e.touches[0].clientY)}
      onTouchEnd={onDragEnd}
      onTouchCancel={onDragEnd}
      onMouseDown={(e) => onDragStart(e.clientY)}
      onMouseMove={(e) => drag.current && onDragMove(e.clientY)}
      onMouseUp={onDragEnd}
      onMouseLeave={() => drag.current && onDragEnd()}
    >
      <div style={{
        position: "absolute", inset: 0,
        transform: `translateY(${dragY}px)`,
        transition: drag.current ? "none" : "transform .18s ease",
      }}>
      {current?.file_url ? (
        <video
          ref={videoRef}
          key={current.id}
          src={current.file_url}
          autoPlay
          controlsList="nodownload"
          onContextMenu={(e) => e.preventDefault()}
          muted={muted}
          playsInline
          loop
          onClick={togglePlay}
          onLoadedData={() => { if (!blocked) tryPlayWithSound(); }}
          onTimeUpdate={(e) => {
            const el = e.currentTarget;
            if (el.duration) setProgress((el.currentTime / el.duration) * 100);
          }}
          style={{ width: "100%", height: "100%", objectFit: "contain", background: "#000" }}
        />
      ) : (
        <div style={{ display: "grid", placeItems: "center", height: "100%", color: "#fff" }}>
          영상 파일이 없습니다.
        </div>
      )}

      </div>

      {/* 진행률 */}
      <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: 3, background: "rgba(255,255,255,.2)" }}>
        <div style={{ width: `${progress}%`, height: "100%", background: "#fff" }} />
      </div>

      {/* 조작 버튼 — 왼쪽 위에 가로로
        *
        * 예전에는 오른쪽 한가운데에 세로로 세워 두었는데, 거기가 하필
        * 영상에서 가장 볼 것이 많은 자리라 버튼이 그림에 파묻혀 안 보였다.
        * 특히 음소거는 소리가 꺼진 채로 보고 있다는 걸 알려야 하는 버튼이라
        * 안 보이면 안 된다(숏츠는 처음에 늘 음소거로 시작한다).
        *
        * 왼쪽 위는 영상에서 대체로 여백이고, 손가락으로 넘길 때 지나는 길도
        * 아니다. 배경을 더 진하게 깔고 흐림까지 줘서, 밝은 화면 위에서도
        * 테두리가 살아 있게 했다.
        */}
      <div style={{
        position: "absolute", left: 12, top: 14,
        display: "flex", flexDirection: "row", gap: 6,
      }}>
        {[
          { key: "up", label: "▲", title: "이전 숏츠",
            onClick: () => move(-1), disabled: index === 0 },
          { key: "down", label: "▼", title: "다음 숏츠",
            onClick: () => move(1), disabled: index >= items.length - 1 },
          { key: "mute", label: muted ? "🔇" : "🔊", title: muted ? "소리 켜기" : "소리 끄기",
            onClick: () => {
              // 사용자가 직접 누른 것이므로 브라우저도 소리를 허락한다.
              if (muted) { setBlocked(false); tryPlayWithSound(); } else { setMuted(true); }
            },
            on: !muted },
          { key: "play", label: playing ? "❚❚" : "▶", title: playing ? "멈춤" : "재생",
            onClick: togglePlay },
        ].map((b) => (
          <button key={b.key} onClick={b.onClick} disabled={b.disabled} title={b.title}
            aria-label={b.title}
            style={{
              width: 38, height: 38, borderRadius: 999, border: "none",
              display: "grid", placeItems: "center", fontSize: 14,
              // 밝은 장면 위에서도 버튼이 보여야 한다. 반투명 검정만으로는
              // 흰 배경 영상에서 사라져서, 흐림과 옅은 테두리를 함께 준다.
              background: b.on ? "rgba(255,255,255,.92)" : "rgba(0,0,0,.62)",
              color: b.on ? "#111" : "#fff",
              boxShadow: "0 1px 6px rgba(0,0,0,.45), inset 0 0 0 1px rgba(255,255,255,.22)",
              backdropFilter: "blur(6px)",
              opacity: b.disabled ? .35 : 1,
              cursor: b.disabled ? "default" : "pointer",
            }}>
            {b.label}
          </button>
        ))}
      </div>

      {/* 소리가 막혔을 때만 나오는 안내.
        *
        * 버튼이 왼쪽 위에 있긴 하지만, 소리가 안 나는 이유까지는 알 수 없다.
        * "왜 무음이지?" 를 학생이 혼자 풀게 두지 않는다. */}
      {blocked && (
        <button
          onClick={() => { setBlocked(false); tryPlayWithSound(); }}
          style={{
            position: "absolute", left: "50%", top: 66, transform: "translateX(-50%)",
            border: "none", borderRadius: 999, padding: "9px 16px",
            background: "rgba(255,255,255,.94)", color: "#111",
            fontSize: 13.5, fontWeight: 700, cursor: "pointer",
            boxShadow: "0 2px 10px rgba(0,0,0,.4)",
          }}>
          🔊 소리 켜기
        </button>
      )}

      {/* 아래 정보 + 전체 영상 보기 */}
      <div style={{
        position: "absolute", left: 0, right: 0, bottom: 0, padding: "18px 16px 16px",
        background: "linear-gradient(transparent, rgba(0,0,0,.8))", color: "#fff",
      }}>
        <div style={{ fontSize: 12, opacity: .75 }}>{index + 1} / {items.length}</div>
        <div style={{ fontWeight: 700, fontSize: 17, margin: "4px 0 2px" }}>{current?.title}</div>
        {current?.description && (
          <p style={{ fontSize: 13, opacity: .85, margin: "0 0 10px", lineHeight: 1.5 }}>
            {current.description}
          </p>
        )}
        {detail?.source ? (
          <button className="btn btn-signal" onClick={goLongform} style={{ marginTop: 6 }}>
            특강에서 이어 보기 → {detail.source.longform_title}
          </button>
        ) : (
          <div style={{ fontSize: 12, opacity: .7, marginTop: 6 }}>
            연결된 특강이 없습니다.
          </div>
        )}
      </div>
    </div>
  );
}
