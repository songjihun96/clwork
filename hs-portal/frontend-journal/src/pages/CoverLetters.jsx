import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import SeatCodeBox from "../components/SeatCodeBox";

export default function CoverLetters() {
  const navigate = useNavigate();
  const [items, setItems] = useState(null);
  const [locked, setLocked] = useState(false);
  // 요금은 관리자가 바꿀 수 있다. 화면에 박아두면 바꿔도 예전 값이 남는다.
  const [price, setPrice] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.coverLetters()
      .then(setItems)
      .catch((e) => {
        // 402 는 구독이 필요하다는 뜻
        if (e.status === 402) {
          setLocked(true);
          api.subscription().then((s) => setPrice(s.price_per_month)).catch(() => {});
        }
        else setError(e.message);
        setItems([]);
      });
  }, []);

  if (locked) {
    return (
      <div className="wrap page" style={{ maxWidth: 620 }}>
        <span className="label">자기소개서</span>
        <h1>내 기록으로 자기소개서를 씁니다</h1>
        <p style={{ color: "var(--steel)", lineHeight: 1.8 }}>
          그동안 남긴 일지와 일기를 자기소개서 항목에 맞게 정리할 수 있습니다.
          <b> 일지 작성과 선생님께 제출은 계속 무료</b>이고, 자기소개서만 이용권이 필요합니다.
        </p>

        <div className="panel" style={{ marginTop: 18 }}>
          <SeatCodeBox featureLabel="자기소개서" onDone={() => window.location.reload()} />
        </div>
      </div>
    );
  }

  if (error) {
    return <div className="wrap page"><div className="notice notice-error">{error}</div></div>;
  }
  if (!items) return <div className="wrap page"><p>불러오는 중…</p></div>;

  return (
    <div className="wrap page">
      <div className="row">
        <div>
          <span className="label">자기소개서</span>
          <h1 style={{ marginTop: 4 }}>내 자기소개서</h1>
        </div>
        <div className="spacer" />
        <Link to="/cover-letters/new" className="btn btn-primary">새로 쓰기</Link>
      </div>
      <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 10, lineHeight: 1.8 }}>
        글을 쓸 때 그 항목에 맞는 <b>내 일지</b>가 옆에 함께 나옵니다.
        막막하면 거기서 골라 넣고 내 말로 다듬으면 됩니다.
      </p>

      <div style={{ marginTop: 20 }}>
        {items.length === 0 ? (
          <div className="empty">
            <h3>아직 작성한 자기소개서가 없습니다</h3>
            <p>일지에 남긴 경험을 항목별로 정리해보세요.</p>
          </div>
        ) : (
          items.map((it) => (
            <Link key={it.id} to={`/cover-letters/${it.id}`} className="entry">
              <h4>{it.title || "제목 없음"}</h4>
              <div className="meta">
                마지막 수정 {String(it.updated_at).slice(0, 10)}
              </div>
            </Link>
          ))
        )}
      </div>

    </div>
  );
}
