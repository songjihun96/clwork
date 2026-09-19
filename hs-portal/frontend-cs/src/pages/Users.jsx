import { useEffect, useState } from "react";
import { api } from "../api";
import {
  Empty,
  Masked,
  Modal,
  Note,
  Pager,
  ROLE_LABEL,
  fmtDate,
  fmtDateTime,
  useList,
} from "../components/ui";

export default function Users() {
  const [term, setTerm] = useState("");
  const [q, setQ] = useState("");
  const [role, setRole] = useState("");
  const [openId, setOpenId] = useState(null);

  const list = useList(({ limit, offset }) => api.users({ q, role, limit, offset }), [q, role]);

  return (
    <>
      <div className="page-head">
        <h1>회원</h1>
        <p>이름·이메일·연락처 뒷자리로 찾을 수 있습니다.</p>
      </div>

      <div className="toolbar">
        <input
          placeholder="이름, 이메일 또는 연락처"
          value={term}
          onChange={(e) => setTerm(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && setQ(term)}
        />
        <select value={role} onChange={(e) => setRole(e.target.value)}>
          <option value="">전체 권한</option>
          <option value="student">학생·학부모</option>
          <option value="teacher">교사</option>
          <option value="school">학교</option>
        </select>
        <button className="btn primary" onClick={() => setQ(term)}>
          찾기
        </button>
      </div>

      <div className="card">
        <Note kind="bad">{list.error}</Note>
        {list.loading ? (
          <Empty>불러오는 중…</Empty>
        ) : list.items.length === 0 ? (
          <Empty>{q ? "찾는 회원이 없습니다." : "검색어를 입력해주세요."}</Empty>
        ) : (
          <>
            <table>
              <thead>
                <tr>
                  <th>이름</th>
                  <th>권한</th>
                  <th>이메일</th>
                  <th>연락처</th>
                  <th>소속 학교</th>
                  <th>가입일</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {list.items.map((u) => (
                  <tr key={u.id} className="row-click" onClick={() => setOpenId(u.id)}>
                    <td>
                      <strong>{u.name}</strong>
                      {!u.is_active && (
                        <span className="badge stop" style={{ marginLeft: 6 }}>
                          중지
                        </span>
                      )}
                    </td>
                    <td>{ROLE_LABEL[u.role] || u.role}</td>
                    <td>
                      <Masked value={u.email} />
                    </td>
                    <td>
                      <Masked value={u.phone} />
                    </td>
                    <td>{u.school_name || <span className="muted tiny">—</span>}</td>
                    <td className="tiny muted">{fmtDate(u.created_at)}</td>
                    <td>
                      <button className="btn sm">열기</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pager {...list} onMove={list.move} />
          </>
        )}
      </div>

      {openId && <UserDetail id={openId} onClose={() => setOpenId(null)} />}
    </>
  );
}

function UserDetail({ id, onClose }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [askReset, setAskReset] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const load = (reveal) => {
    setError("");
    api
      .user(id, reveal)
      .then(setData)
      .catch((e) => setError(e.message));
  };

  // 열자마자 가려진 상태로 먼저 보여준다. 원본은 눌러야 나온다.
  useEffect(() => {
    load(false);
  }, [id]);

  const sendReset = async () => {
    setBusy(true);
    setError("");
    try {
      const r = await api.sendPasswordReset(id, reason);
      setMsg(r.message);
      setAskReset(false);
      setReason("");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title={data ? data.name : "회원 정보"}
      sub={data ? ROLE_LABEL[data.role] || data.role : ""}
      onClose={onClose}
      foot={
        <button className="btn" onClick={onClose}>
          닫기
        </button>
      }
    >
      <Note kind="bad">{error}</Note>
      <Note kind="good">{msg}</Note>

      {!data ? (
        <Empty>불러오는 중…</Empty>
      ) : (
        <>
          {data.masked && (
            <div className="note info" style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <span style={{ flex: 1 }}>
                연락처가 가려져 있습니다. 본인 확인이 필요할 때만 원본을 보세요. 누가 언제
                열었는지 기록됩니다.
              </span>
              <button className="btn sm" onClick={() => load(true)}>
                원본 보기
              </button>
            </div>
          )}

          <table>
            <tbody>
              <Row label="이메일" value={data.email} mono={data.masked} />
              <Row label="연락처" value={data.phone || "—"} mono={data.masked} />
              <Row label="소속 학교" value={data.school_name || "—"} />
              <Row
                label="학년·학과"
                value={[data.grade ? `${data.grade}학년` : "", data.department]
                  .filter(Boolean)
                  .join(" ") || "—"}
              />
              <Row label="담당 학급" value={data.class_name || "—"} />
              <Row label="가입일" value={fmtDateTime(data.created_at)} />
              <Row
                label="계정 상태"
                value={data.is_active ? "정상" : "사용 중지"}
              />
              {data.guardian_consent_at && (
                <Row
                  label="보호자 동의"
                  value={`${fmtDate(data.guardian_consent_at)} · ${data.guardian_email}`}
                />
              )}
              <Row
                label="기록해 구독"
                value={
                  !data.subscription
                    ? "없음"
                    : `${data.subscription.active ? "이용 중" : "만료"} · ${fmtDate(
                        data.subscription.expires_at
                      )}까지`
                }
              />
            </tbody>
          </table>

          {data.verifications.length > 0 && (
            <>
              <h2 style={{ fontSize: 13, marginTop: 18, marginBottom: 8 }}>재학생 인증 이력</h2>
              <table>
                <tbody>
                  {data.verifications.map((v) => (
                    <tr key={v.id}>
                      <td>{v.school_name}</td>
                      <td>{v.class_name || "—"}</td>
                      <td>
                        <span
                          className={`badge ${
                            v.status === "approved" ? "done" : v.status === "pending" ? "wait" : "flat"
                          }`}
                        >
                          {v.status === "approved"
                            ? "승인"
                            : v.status === "pending"
                            ? "대기"
                            : "거절"}
                        </span>
                      </td>
                      <td className="tiny muted">{fmtDate(v.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          <div style={{ marginTop: 18 }}>
            {!askReset ? (
              <button className="btn" onClick={() => setAskReset(true)}>
                비밀번호 재설정 코드 보내기
              </button>
            ) : (
              <div className="card" style={{ background: "var(--raised)" }}>
                <p className="tiny muted" style={{ marginTop: 0 }}>
                  회원 이메일로 6자리 코드가 갑니다. 상담원이 새 비밀번호를 정해주지는
                  않습니다. 본인 확인을 마친 뒤에만 보내세요.
                </p>
                <div className="field">
                  <label>사유 (기록에 남습니다)</label>
                  <input
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    placeholder="예: 전화로 본인 확인 완료"
                  />
                </div>
                <div className="btn-row">
                  <button className="btn go" onClick={sendReset} disabled={busy}>
                    {busy ? "보내는 중…" : "보내기"}
                  </button>
                  <button className="btn" onClick={() => setAskReset(false)}>
                    그만두기
                  </button>
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </Modal>
  );
}

function Row({ label, value, mono }) {
  return (
    <tr>
      <td style={{ width: 110, color: "var(--muted)", fontSize: 12.5 }}>{label}</td>
      <td className={mono ? "masked" : ""}>{value}</td>
    </tr>
  );
}
