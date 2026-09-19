import { forwardRef, useCallback, useEffect, useRef, useState } from "react";

/** 산 사람만 보는 영상 재생기.
 *
 * **워터마크가 이 컴포넌트의 핵심이다.** 녹화와 캡처는 웹에서 못 막는다 —
 * 브라우저에 그런 수단이 없고, 폰으로 모니터를 찍는 건 어차피 못 막는다.
 * 그래서 "못 찍게" 대신 "찍으면 누가 찍었는지 드러나게" 한다. 보는 사람의
 * 이름과 연락처 끝자리가 화면 위를 계속 옮겨 다니고, 어느 프레임을 잘라도
 * 함께 찍힌다.
 *
 * **전체화면이 이 방식의 급소였다.** 브라우저의 전체화면 버튼은 <video>
 * 하나만 전체화면으로 만든다. 그러면 형제로 얹어 둔 워터마크는 화면 밖으로
 * 밀려나고, 전체화면으로 보는 동안만 표시가 사라진다 — 녹화하려는 사람에게
 * 가장 쉬운 길을 열어 두는 셈이다. 그래서 여기서는
 *
 *   · 브라우저 기본 전체화면 버튼을 감추고,
 *   · 우리 버튼으로 **바깥 상자째** 전체화면으로 만들고(워터마크가 함께 간다),
 *   · 그래도 <video> 만 전체화면이 되면(사파리 등) 그 자리에서 되돌린다.
 *
 * 자리를 옮기는 이유는 두 가지다. 한자리에 고정하면 (1) 그 부분만 잘라내
 * 지우기 쉽고, (2) 오래 보는 사람의 눈에 계속 거슬린다. 12초마다 조용히
 * 옮기면 둘 다 덜하다.
 *
 * 우클릭 막기 같은 건 하지 않는다. 받아 갈 사람은 그걸로 안 막히고, 정작
 * 산 사람만 불편해진다.
 *
 * ref 는 부르는 쪽으로 그대로 넘긴다 — 커리큘럼에서 강의를 고르면 그 초로
 * 옮겨 틀어야 해서, 바깥에서 <video> 를 직접 만질 수 있어야 한다.
 */
const PaidPlayer = forwardRef(function PaidPlayer({ src, mark, poster, onError, onEnded }, ref) {
  const wrapRef = useRef(null);
  const videoRef = useRef(null);
  const [spot, setSpot] = useState({ top: "12%", left: "8%" });
  const [full, setFull] = useState(false);

  // 부르는 쪽에 넘겨주면서 우리도 <video> 를 쥐고 있어야 한다.
  // ref 는 함수일 수도 객체일 수도 있어 둘 다 받아 준다.
  const setVideo = useCallback((el) => {
    videoRef.current = el;
    if (typeof ref === "function") ref(el);
    else if (ref) ref.current = el;
  }, [ref]);

  useEffect(() => {
    if (!mark) return undefined;
    const move = () => {
      // 가장자리는 피한다 — 재생 막대와 겹치면 읽히지도 않고 가리기만 한다.
      setSpot({
        top: `${8 + Math.random() * 66}%`,
        left: `${5 + Math.random() * 55}%`,
      });
    };
    const id = setInterval(move, 12000);
    return () => clearInterval(id);
  }, [mark]);

  const exitFull = useCallback(() => {
    try {
      if (document.exitFullscreen) return document.exitFullscreen();
      if (document.webkitExitFullscreen) return document.webkitExitFullscreen();
    } catch { /* 브라우저가 거절해도 아래에서 상태는 맞춘다 */ }
    return undefined;
  }, []);

  // 전체화면 상태를 따라간다. **<video> 만 전체화면이 된 경우는 되돌린다** —
  // 그 화면에는 워터마크를 얹을 자리가 없다.
  useEffect(() => {
    const onChange = () => {
      const el = document.fullscreenElement || document.webkitFullscreenElement || null;
      if (el && videoRef.current && el === videoRef.current) {
        exitFull();
        setFull(false);
        return;
      }
      setFull(!!el && el === wrapRef.current);
    };
    document.addEventListener("fullscreenchange", onChange);
    document.addEventListener("webkitfullscreenchange", onChange);
    return () => {
      document.removeEventListener("fullscreenchange", onChange);
      document.removeEventListener("webkitfullscreenchange", onChange);
    };
  }, [exitFull]);

  // 아이폰 사파리는 <video> 를 제 전체화면 재생기로 띄운다. 그 화면에는
  // 아무것도 못 얹으므로 들어가는 즉시 빠져나온다.
  useEffect(() => {
    const el = videoRef.current;
    if (!el) return undefined;
    const onNative = () => {
      if (el.webkitExitFullscreen) el.webkitExitFullscreen();
    };
    el.addEventListener("webkitbeginfullscreen", onNative);
    return () => el.removeEventListener("webkitbeginfullscreen", onNative);
  }, [src]);

  const toggleFull = () => {
    const box = wrapRef.current;
    if (!box) return;
    if (document.fullscreenElement || document.webkitFullscreenElement) {
      exitFull();
      return;
    }
    const go = box.requestFullscreen || box.webkitRequestFullscreen;
    if (go) {
      try { go.call(box); } catch { /* 막혀 있으면 그냥 창 안에서 본다 */ }
    }
  };

  return (
    <div ref={wrapRef} className={`paid-player${full ? " is-full" : ""}`}>
      <video
        ref={setVideo}
        src={src}
        poster={poster || undefined}
        controls
        playsInline
        preload="metadata"
        // 내려받기·화면 속 화면·기본 전체화면을 뺀다. 전체화면은 아래 우리
        // 버튼으로 대신한다 — 워터마크가 함께 가야 하기 때문이다.
        controlsList="nodownload noplaybackrate nofullscreen noremoteplayback"
        disablePictureInPicture
        onContextMenu={(e) => e.preventDefault()}
        // 주소가 죽으면(티켓 만료·서버 재시작) 부르는 쪽이 새로 받아 온다.
        onError={onError}
        onEnded={onEnded}
      />

      {mark && (
        <div aria-hidden="true" className="paid-mark"
          style={{ top: spot.top, left: spot.left }}>
          {mark}
        </div>
      )}

      <button type="button" className="paid-full" onClick={toggleFull}
        title={full ? "전체화면 나가기" : "전체화면"}>
        {full ? "⤡ 나가기" : "⤢ 전체화면"}
      </button>
    </div>
  );
});

export default PaidPlayer;
