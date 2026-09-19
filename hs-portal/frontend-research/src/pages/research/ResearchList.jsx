import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import "../../research-theme.css";

const STAGE_LABEL = {
  interest: "관심 탐색 중", topic: "주제 고르는 중", question: "연구 질문 확정",
  plan: "연구 계획", literature: "문헌 조사", method: "연구 설계", execution: "실행",
  data: "데이터 수집", analysis: "분석", discussion: "논의", paper: "논문 작성",
  portfolio: "포트폴리오", completed: "완료",
};

export default function ResearchList() {
  const { user } = useAuth();
  const [items, setItems] = useState(null);
  const [locked, setLocked] = useState(false);
  const [error, setError] = useState("");
  const [invites, setInvites] = useState([]);
  const [deletingId, setDeletingId] = useState(null);

  const loadInvites = () => {
    api.listMyTeamInvites().then((r) => setInvites(r.items || [])).catch(() => {});
  };

  useEffect(() => {
    api.listResearch().then((r) => setItems(r.items)).catch((e) => {
      if (e.status === 402) setLocked(true);
      else setError(e.message);
      setItems([]);
    });
    loadInvites();
  }, []);

  const respond = async (inviteId, accept) => {
    try {
      const r = accept ? await api.acceptTeamInvite(inviteId) : await api.declineTeamInvite(inviteId);
      setInvites((prev) => prev.filter((i) => i.id !== inviteId));
      if (accept && r?.research_id) {
        api.listResearch().then((r2) => setItems(r2.items)).catch(() => {});
      }
    } catch (e) {
      setError(e.message);
    }
  };

  const remove = async (r) => {
    const msg = r.team
      ? `"${r.title || r.interest_keyword}" 연구를 지울까요? 팀원 전체의 자료가 함께 사라지고 되돌릴 수 없습니다.`
      : `"${r.title || r.interest_keyword}" 연구를 지울까요? 되돌릴 수 없습니다.`;
    if (!window.confirm(msg)) return;
    setDeletingId(r.id);
    try {
      await api.deleteResearch(r.id);
      setItems((prev) => prev.filter((x) => x.id !== r.id));
    } catch (e) {
      alert(e.message);
    } finally {
      setDeletingId(null);
    }
  };

  if (locked) {
    return (
      <div className="research-theme wrap page" style={{ maxWidth: 620 }}>
        <span className="label">연구</span>
        <h1>내 기록으로 연구를 시작합니다</h1>
        <p style={{ color: "var(--color-text-secondary)", lineHeight: 1.8 }}>
          궁금한 것 하나로 시작해서 AI 연구 코치와 함께 논문까지 완성할 수 있습니다.
          
        </p>
        <div className="panel" style={{ marginTop: 18 }}>
          {/* 이용권은 이 서비스에 아직 없다(서버도 402 를 안 준다). 이 갈래를
              지우지 않고 남겨 둔 것은, 나중에 이용권을 붙일 때 들어올 자리가
              여기여서다. */}
          <p style={{ margin: 0, color: "var(--color-text-secondary)" }}>
            준비 중입니다. 잠시 후 다시 시도해 주세요.
          </p>
        </div>
      </div>
    );
  }

  if (error) {
    return <div className="research-theme wrap page"><div className="notice notice-error">{error}</div></div>;
  }
  if (!items) {
    return <div className="research-theme wrap page"><p>불러오는 중…</p></div>;
  }

  return (
    <div className="research-theme wrap page">
      <div className="row" style={{ marginBottom: 6 }}>
        <div>
          <span className="label">MY RESEARCH</span>
          <h1 style={{ marginTop: 4 }}>내 연구</h1>
        </div>
        <div className="spacer" />
        <Link to="/research/new" className="btn btn-primary">새 연구 시작</Link>
      </div>

      {invites.length > 0 && (
        <div style={{ display: "grid", gap: 8, margin: "12px 0" }}>
          {invites.map((inv) => (
            <div key={inv.id} className="panel row" style={{ gap: 10, alignItems: "center" }}>
              <span>
                <b>{inv.invited_by_name}</b>님이 <b>{inv.research_title || "연구"}</b> 팀에 초대했어요
              </span>
              <div className="spacer" />
              <button className="btn btn-sm btn-primary" onClick={() => respond(inv.id, true)}>수락</button>
              <button className="btn btn-sm btn-ghost" onClick={() => respond(inv.id, false)}>거절</button>
            </div>
          ))}
        </div>
      )}

      {items.length === 0 ? (
        <div className="empty">
          <h3>아직 시작한 연구가 없습니다</h3>
          <p>관심 있는 주제를 키워드 하나로 입력하는 것부터 시작해보세요.</p>
          <Link to="/research/new" className="btn btn-primary" style={{ marginTop: 12 }}>
            첫 연구 시작하기
          </Link>
        </div>
      ) : (
        <div style={{ display: "grid", gap: 12 }}>
          {items.map((r) => {
            // 팀 연구는 팀장만 지울 수 있다(서버도 같은 규칙) — 팀원 전체의
            // 자료를 한 명이 마음대로 없앨 수 없어야 한다. 리더가 아니면
            // 버튼 자체를 안 보여준다.
            const canDelete = !r.team || r.team.members.some((m) => m.is_leader && m.user_id === user?.id);
            return (
              <div key={r.id} className="entry" style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <Link to={r.title ? `/research/${r.id}` : `/research/new?id=${r.id}`}
                  style={{ flex: 1, minWidth: 0 }}>
                  <div className="row" style={{ gap: 6, marginBottom: 4 }}>
                    <span className="research-stage-pill">{STAGE_LABEL[r.current_stage] || r.current_stage}</span>
                    {r.status === "completed" && <span className="badge badge-done">완료</span>}
                    {r.team && <span className="badge">팀 연구 · {r.team.members.length}명</span>}
                  </div>
                  <h4>{r.title || r.interest_keyword}</h4>
                  <div className="meta">{r.duration_weeks}주 연구</div>
                </Link>
                {canDelete && (
                  <button className="btn btn-sm btn-ghost" disabled={deletingId === r.id}
                    onClick={() => remove(r)}>
                    {deletingId === r.id ? "지우는 중…" : "삭제"}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
