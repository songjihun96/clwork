import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api";
import "../../research-theme.css";

// AI 호출은 스트리밍이 아니라 다 만들어질 때까지 기다렸다가 한 번에
// 받아오므로, 다른 연구 화면과 같은 방식으로 체감 진행률만 보여준다.
function estimateAiProgress(seconds, expectedSeconds) {
  const pct = 90 * (1 - Math.exp(-seconds / expectedSeconds));
  return Math.min(90, Math.round(pct));
}

function AiGauge({ percent }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6, maxWidth: 220 }}>
      <div style={{ flex: 1, height: 6, borderRadius: 999, background: "var(--color-border)", overflow: "hidden" }}>
        <div style={{ width: `${percent}%`, height: "100%", background: "var(--color-primary)",
          transition: "width .3s ease" }} />
      </div>
      <span style={{ fontSize: 11.5, color: "var(--color-text-muted)", minWidth: 32, textAlign: "right" }}>
        {percent}%
      </span>
    </div>
  );
}

const SUGGESTION_LABEL = {
  keep: "유지해도 좋아요", revise: "다듬으면 좋겠어요", duplicate: "다른 글과 겹쳐요",
  weak: "근거가 더 필요해요", exclude: "이 연구와 관련이 적어요",
};

const DECISION_LABEL = { pending: "검토 전", approved: "승인됨", rejected: "반려됨", revised: "수정됨" };

export default function TeamBoard() {
  const { id } = useParams();
  const [research, setResearch] = useState(null);
  const [team, setTeam] = useState(null);
  const [posts, setPosts] = useState(null);
  const [activity, setActivity] = useState([]);
  const [error, setError] = useState("");
  const [me, setMe] = useState(null);

  const load = () => {
    api.getResearch(id).then((r) => { setResearch(r); setTeam(r.team); }).catch((e) => setError(e.message));
    api.listBoardPosts(id).then((r) => setPosts(r.items)).catch(() => setPosts([]));
    api.listResearchActivity(id).then((r) => setActivity(r.items)).catch(() => {});
    api.me().then(setMe).catch(() => {});
  };
  useEffect(load, [id]);

  if (error) {
    return <div className="research-theme wrap page"><div className="notice notice-error">{error}</div></div>;
  }
  if (!research || !team || posts === null) {
    return <div className="research-theme wrap page"><p>불러오는 중…</p></div>;
  }

  const myMembership = team.members.find((m) => me && m.user_id === me.id);
  const isLeader = !!myMembership?.is_leader;

  return (
    <div className="research-theme wrap page" style={{ maxWidth: 760 }}>
      <Link to={`/research/${id}`} className="label">← {research.title || research.interest_keyword}</Link>
      <h1 style={{ marginTop: 8 }}>팀 게시판</h1>

      <MembersSection researchId={id} team={team} isLeader={isLeader} myUserId={me?.id}
        onChanged={load} />

      <BoardSection researchId={id} posts={posts} onChanged={load} />

      <ActivitySection activity={activity} />
    </div>
  );
}

function MembersSection({ researchId, team, isLeader, myUserId, onChanged }) {
  const [q, setQ] = useState("");
  const [candidates, setCandidates] = useState([]);
  const [myRole, setMyRole] = useState(team.members.find((m) => m.user_id === myUserId)?.research_role || "");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [roleSuggestions, setRoleSuggestions] = useState(null);
  const [roleBusy, setRoleBusy] = useState(false);
  const [roleProgress, setRoleProgress] = useState(0);
  const [leaveBusy, setLeaveBusy] = useState(false);
  const [leaveMsg, setLeaveMsg] = useState("");

  useEffect(() => {
    const term = q.trim();
    if (!term) { setCandidates([]); return; }
    const t = setTimeout(() => {
      api.searchTeamCandidates(researchId, term).then((r) => setCandidates(r.items || [])).catch(() => {});
    }, 250);
    return () => clearTimeout(t);
  }, [q, researchId]);

  const invite = async (userId) => {
    setBusy(true); setMsg("");
    try {
      await api.inviteTeamMember(researchId, userId);
      setCandidates((prev) => prev.map((c) => (c.user_id === userId ? { ...c, already_invited: true } : c)));
      setMsg("초대를 보냈어요.");
    } catch (e) {
      setMsg(e.message);
    } finally {
      setBusy(false);
    }
  };

  const saveRole = async () => {
    setBusy(true); setMsg("");
    try {
      await api.updateTeamMemberRole(researchId, myUserId, myRole);
      setMsg("내 역할을 저장했어요.");
      onChanged();
    } catch (e) {
      setMsg(e.message);
    } finally {
      setBusy(false);
    }
  };

  const askRoleSuggestions = async () => {
    setRoleBusy(true); setRoleProgress(0); setMsg("");
    try {
      const { job_id } = await api.requestTeamRoleSuggestions(researchId);
      const result = await api.waitAiJob(job_id, { onTick: (s) => setRoleProgress(estimateAiProgress(s, 4)) });
      setRoleProgress(100);
      setRoleSuggestions(result.roles || []);
    } catch (e) {
      setMsg(e.message);
    } finally {
      setRoleBusy(false);
    }
  };

  const leave = async () => {
    if (!confirm("탈퇴를 신청할까요? 담당 선생님이 승인해야 실제로 나가집니다.")) return;
    setLeaveBusy(true); setLeaveMsg("");
    try {
      const r = await api.requestLeaveTeam(researchId);
      setLeaveMsg(r.status === "approved" ? "바로 처리됐어요." : "신청했어요. 담당 선생님 승인을 기다려주세요.");
      onChanged();
    } catch (e) {
      setLeaveMsg(e.message);
    } finally {
      setLeaveBusy(false);
    }
  };

  return (
    <div className="panel" style={{ marginTop: 16 }}>
      <h3 style={{ marginTop: 0 }}>팀원 ({team.members.length}명)</h3>
      <div style={{ display: "grid", gap: 6 }}>
        {team.members.map((m) => (
          <div key={m.user_id} className="row" style={{ gap: 8, alignItems: "center" }}>
            <span>{m.name}</span>
            {m.is_leader && <span className="badge">팀장</span>}
            {m.research_role && <span className="meta">{m.research_role}</span>}
          </div>
        ))}
      </div>

      {myUserId && (
        <div className="field" style={{ marginTop: 12 }}>
          <label className="label">내 역할 (직접 적어요 — 팀원들과 상의해서 정해요)</label>
          <div className="row" style={{ gap: 8 }}>
            <input className="input" value={myRole} onChange={(e) => setMyRole(e.target.value)}
              placeholder="예: 자료 조사" maxLength={60} />
            <button className="btn btn-sm" onClick={saveRole} disabled={busy}>저장</button>
          </div>
        </div>
      )}

      <div style={{ marginTop: 10 }}>
        <button className="btn btn-sm btn-ghost" onClick={askRoleSuggestions} disabled={roleBusy}>
          {roleBusy ? "역할 후보 만드는 중…" : "AI에게 역할 후보 물어보기"}
        </button>
        {roleBusy && <AiGauge percent={roleProgress} />}
        {roleSuggestions && (
          <ul style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: 13.5 }}>
            {roleSuggestions.map((r, i) => (
              <li key={i}><b>{r.name}</b> — {r.description}</li>
            ))}
          </ul>
        )}
      </div>

      {isLeader && (
        <div style={{ marginTop: 14, paddingTop: 14, borderTop: "1px solid var(--color-border)" }}>
          <div className="label">친구 초대 (팀장만 보낼 수 있어요)</div>
          <input className="input" value={q} onChange={(e) => setQ(e.target.value)}
            placeholder="같은 학교 친구 이름으로 검색" style={{ marginTop: 6, maxWidth: 320 }} />
          {candidates.length > 0 && (
            <div style={{ display: "grid", gap: 6, marginTop: 8 }}>
              {candidates.map((cnd) => (
                <div key={cnd.user_id} className="row" style={{ gap: 8, alignItems: "center" }}>
                  <span>{cnd.name}</span>
                  <span className="meta">{cnd.class_name || (cnd.grade ? `${cnd.grade}학년` : "")}</span>
                  <div className="spacer" />
                  {cnd.already_member ? (
                    <span className="badge badge-done">팀원</span>
                  ) : cnd.already_invited ? (
                    <span className="meta">초대함</span>
                  ) : (
                    <button className="btn btn-sm" disabled={busy} onClick={() => invite(cnd.user_id)}>초대</button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {msg && <div className="notice" style={{ marginTop: 10 }}>{msg}</div>}

      {myUserId && (
        <div style={{ marginTop: 14, paddingTop: 14, borderTop: "1px solid var(--color-border)" }}>
          <button className="btn btn-sm btn-ghost" onClick={leave} disabled={leaveBusy}>
            {leaveBusy ? "신청 중…" : "팀 탈퇴 신청"}
          </button>
          <p className="meta" style={{ marginTop: 6 }}>
            바로 나가지는 것이 아니라 담당 선생님의 승인을 거쳐요.
          </p>
          {leaveMsg && <div className="notice" style={{ marginTop: 6 }}>{leaveMsg}</div>}
        </div>
      )}
    </div>
  );
}

function BoardSection({ researchId, posts, onChanged }) {
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [synthBusy, setSynthBusy] = useState(false);
  const [synthProgress, setSynthProgress] = useState(0);

  const create = async () => {
    if (!content.trim()) return setError("내용을 입력해주세요.");
    setBusy(true); setError("");
    try {
      await api.createBoardPost(researchId, title, content);
      setTitle(""); setContent("");
      onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const synthesize = async () => {
    setSynthBusy(true); setSynthProgress(0); setError("");
    try {
      const { job_id } = await api.synthesizeBoard(researchId);
      await api.waitAiJob(job_id, { onTick: (s) => setSynthProgress(estimateAiProgress(s, 6)) });
      setSynthProgress(100);
      onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setSynthBusy(false);
    }
  };

  const decide = async (postId, decision) => {
    try {
      await api.decideBoardPost(researchId, postId, decision);
      onChanged();
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <div className="panel" style={{ marginTop: 16 }}>
      <h3 style={{ marginTop: 0 }}>게시판</h3>
      <p style={{ fontSize: 13.5, color: "var(--color-text-secondary)" }}>
        각자 조사하거나 모은 내용을 올려주세요. AI가 훑어보고 의견을 주지만,
        반영할지는 팀에서 직접 정해요.
      </p>

      <div className="field">
        <input className="input" value={title} onChange={(e) => setTitle(e.target.value)}
          placeholder="제목(선택)" />
        <textarea className="textarea" value={content} onChange={(e) => setContent(e.target.value)}
          placeholder="조사·수집한 내용을 적어주세요" style={{ minHeight: 80, marginTop: 6 }} />
      </div>
      {error && <div className="notice notice-error">{error}</div>}
      <div className="row" style={{ gap: 8 }}>
        <button className="btn btn-sm btn-primary" onClick={create} disabled={busy}>
          {busy ? "올리는 중…" : "올리기"}
        </button>
        <button className="btn btn-sm btn-ghost" onClick={synthesize} disabled={synthBusy || posts.length === 0}>
          {synthBusy ? "검토하는 중…" : "AI에게 전체 검토 요청"}
        </button>
      </div>
      {synthBusy && <AiGauge percent={synthProgress} />}

      <div style={{ display: "grid", gap: 10, marginTop: 14 }}>
        {posts.length === 0 && <p className="meta">아직 게시글이 없습니다.</p>}
        {posts.map((p) => (
          <div key={p.id} className="entry" style={{ cursor: "default" }}>
            <div className="row" style={{ gap: 8, alignItems: "center" }}>
              <b>{p.title || "(제목 없음)"}</b>
              <span className="meta">{p.author_name}</span>
              <div className="spacer" />
              <span className="badge">{DECISION_LABEL[p.decision] || p.decision}</span>
            </div>
            <p style={{ margin: "6px 0", fontSize: 13.5, whiteSpace: "pre-wrap" }}>{p.content}</p>
            {p.ai_suggestion && (
              <p style={{ fontSize: 12.5, color: "var(--color-primary)", margin: "4px 0" }}>
                AI 의견: {SUGGESTION_LABEL[p.ai_suggestion] || p.ai_suggestion}
                {p.ai_note ? ` — ${p.ai_note}` : ""}
              </p>
            )}
            <div className="row" style={{ gap: 6, marginTop: 4 }}>
              <button className="btn btn-sm btn-ghost" onClick={() => decide(p.id, "approved")}>승인</button>
              <button className="btn btn-sm btn-ghost" onClick={() => decide(p.id, "rejected")}>반려</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ActivitySection({ activity }) {
  if (!activity.length) return null;
  return (
    <div className="panel" style={{ marginTop: 16 }}>
      <h3 style={{ marginTop: 0 }}>최근 활동</h3>
      <div style={{ display: "grid", gap: 6, fontSize: 13.5 }}>
        {activity.map((e, i) => (
          <div key={i} className="row" style={{ gap: 8 }}>
            <span className="meta" style={{ minWidth: 90 }}>
              {String(e.at).slice(5, 16).replace("T", " ")}
            </span>
            <span>{e.text}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
