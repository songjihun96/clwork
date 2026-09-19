import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import SchoolCard from "../components/SchoolCard";
import SchoolDetailView from "../components/SchoolDetailView";
import { ddayClass, ddayText } from "../dday";
import { toast } from "../toast";

export default function Favorites() {
  const [items, setItems] = useState([]);
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [openId, setOpenId] = useState(null);
  const [editing, setEditing] = useState(null);
  const [memo, setMemo] = useState("");
  const [tab, setTab] = useState("list");

  const load = () => {
    setLoading(true);
    Promise.all([api.favorites(), api.favoriteCalendar()])
      .then(([f, e]) => {
        setItems(f);
        setEvents(e);
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  // 지우거나 저장하고 나면 목록만 다시 그려져서, 눌린 게 맞는지 알 길이
  // 없었다. 실패해도 조용히 지나가던 것도 함께 잡는다.
  const remove = async (school) => {
    try {
      await api.removeFavorite(school.id);
      toast.ok(`${school.name}을(를) 관심 학교에서 뺐습니다.`);
      load();
    } catch (e) { toast.error(e.message); }
  };

  const saveMemo = async (schoolId) => {
    try {
      await api.updateFavoriteMemo(schoolId, memo);
      setEditing(null);
      toast.ok("메모를 저장했습니다.");
      load();
    } catch (e) { toast.error(e.message); }
  };

  if (loading) return <div className="wrap" style={{ padding: 60 }}><div className="empty"><p>불러오는 중…</p></div></div>;

  const upcoming = events.filter((e) => e.d_day >= 0);

  return (
    <div className="wrap" style={{ padding: "34px 0 60px" }}>
      <span className="label">내 즐겨찾기</span>
      <h1 style={{ fontSize: 26, margin: "8px 0 6px" }}>관심 있는 학교 {items.length}곳</h1>
      <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 0 }}>
        학교마다 메모를 붙여두면 나중에 왜 담았는지 기억하기 쉽습니다.
      </p>

      <div className="tabs" style={{ marginTop: 20 }}>
        <button className={`tab ${tab === "list" ? "active" : ""}`} onClick={() => setTab("list")}>
          학교 목록
        </button>
        <button className={`tab ${tab === "cal" ? "active" : ""}`} onClick={() => setTab("cal")}>
          학교 일정 {upcoming.length > 0 && `(${upcoming.length})`}
        </button>
      </div>

      {tab === "list" ? (
        items.length === 0 ? (
          <div className="empty">
            <h3>아직 담은 학교가 없습니다</h3>
            <p>
              검색 결과에서 별 버튼을 누르면 여기 모입니다.{" "}
              <Link to="/" style={{ fontWeight: 600 }}>학교 검색하러 가기</Link>
            </p>
          </div>
        ) : (
          <div className="card-list">
            {items.map((f) => (
              <div key={f.school.id}>
                <SchoolCard school={f.school} onOpen={setOpenId} onToggleFavorite={remove} showFavorite />
                <div
                  style={{
                    background: "var(--surface)",
                    border: "1px solid var(--line)", borderTop: "none",
                    borderRadius: "0 0 var(--radius) var(--radius)",
                    padding: "9px 17px", display: "flex", alignItems: "center", gap: 10,
                  }}
                >
                  <span className="label">메모</span>
                  {editing === f.school.id ? (
                    <>
                      <input
                        className="input"
                        style={{ flex: 1, padding: "5px 9px", fontSize: 13 }}
                        value={memo}
                        autoFocus
                        onChange={(e) => setMemo(e.target.value)}
                        onKeyDown={(e) => e.key === "Enter" && saveMemo(f.school.id)}
                      />
                      <button className="btn btn-sm" onClick={() => saveMemo(f.school.id)}>저장</button>
                      <button className="btn btn-ghost btn-sm" onClick={() => setEditing(null)}>취소</button>
                    </>
                  ) : (
                    <>
                      <span style={{ flex: 1, fontSize: 13, color: f.memo ? "var(--ink)" : "var(--steel-light)" }}>
                        {f.memo || "메모 없음"}
                      </span>
                      <button
                        className="btn btn-ghost btn-sm"
                        onClick={() => {
                          setEditing(f.school.id);
                          setMemo(f.memo);
                        }}
                      >
                        {f.memo ? "수정" : "메모 쓰기"}
                      </button>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        )
      ) : events.length === 0 ? (
        <div className="empty">
          <h3>다가오는 일정이 없습니다</h3>
          <p>즐겨찾기한 학교가 학교 일정을 등록하면 여기에 D-day로 모입니다.</p>
        </div>
      ) : (
        <div className="panel">
          {events.map((e) => (
            <div className="event-row" key={e.id}>
              <span className={ddayClass(e.d_day)}>
                {ddayText(e.d_day)}
              </span>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600, fontSize: 14 }}>{e.title}</div>
                <div style={{ fontSize: 12.5, color: "var(--steel)" }}>
                  {e.school_name} · {e.start_date}
                  {e.end_date ? ` ~ ${e.end_date}` : ""}
                  {e.start_time ? ` · ${e.start_time}${e.end_time ? `~${e.end_time}` : ""}` : ""}
                </div>
              </div>
              <button className="btn btn-ghost btn-sm" onClick={() => setOpenId(e.school_id)}>
                학교 보기
              </button>
            </div>
          ))}
        </div>
      )}

      {openId && (
        <div className="modal-backdrop" onClick={() => setOpenId(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <SchoolDetailView schoolId={openId} embedded />
            <div style={{ padding: "0 28px 24px" }}>
              <button className="btn btn-ghost" onClick={() => { setOpenId(null); load(); }}>닫기</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
