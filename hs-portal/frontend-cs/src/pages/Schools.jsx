import { useEffect, useState } from "react";
import { api } from "../api";
import {
  Empty,
  Masked,
  Modal,
  Note,
  PLAN_LABEL,
  Pager,
  fmtDate,
  useList,
} from "../components/ui";

export default function Schools() {
  const [term, setTerm] = useState("");
  const [q, setQ] = useState("");
  const [plan, setPlan] = useState("");
  const [openId, setOpenId] = useState(null);

  const list = useList(({ limit, offset }) => api.schools({ q, plan, limit, offset }), [q, plan]);

  return (
    <>
      <div className="page-head">
        <h1>학교</h1>
        <p>연락처와 소개 같은 공개 정보를 고칠 수 있습니다.</p>
      </div>

      <div className="toolbar">
        <input
          placeholder="학교 이름"
          value={term}
          onChange={(e) => setTerm(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && setQ(term)}
        />
        <select value={plan} onChange={(e) => setPlan(e.target.value)}>
          <option value="">전체 플랜</option>
          <option value="free">무료</option>
          <option value="basic">베이직</option>
          <option value="premium">프리미엄</option>
          <option value="platinum">플래티넘</option>
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
          <Empty>찾는 학교가 없습니다.</Empty>
        ) : (
          <>
            <table>
              <thead>
                <tr>
                  <th>학교</th>
                  <th>지역</th>
                  <th>대표번호</th>
                  <th>플랜</th>
                  <th>만료</th>
                  <th className="num">조회수</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {list.items.map((s) => (
                  <tr key={s.id} className="row-click" onClick={() => setOpenId(s.id)}>
                    <td>
                      <strong>{s.name}</strong>
                      <div className="tiny muted">{s.category}</div>
                    </td>
                    <td>{s.region}</td>
                    <td>{s.phone || <span className="muted tiny">—</span>}</td>
                    <td>
                      <span className={`badge ${s.plan === "free" ? "flat" : "done"}`}>
                        {PLAN_LABEL[s.plan] || s.plan}
                      </span>
                      {s.plan_paused && (
                        <span className="badge hold" style={{ marginLeft: 4 }}>
                          정지
                        </span>
                      )}
                    </td>
                    <td className="tiny muted">
                      {s.plan_expires_at ? fmtDate(s.plan_expires_at) : "—"}
                    </td>
                    <td className="num">{(s.view_count || 0).toLocaleString()}</td>
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

      {openId && <SchoolDetail id={openId} onClose={() => setOpenId(null)} onSaved={list.reload} />}
    </>
  );
}

const FIELDS = [
  ["phone", "대표번호", "text"],
  ["website", "홈페이지", "text"],
  ["slogan", "한 줄 소개", "text"],
  // 정식 명칭 말고 실제로 통용되는 이름. 학교 계정은 못 고치고 운영자만 넣는다.
  ["search_aliases", "검색 별칭 (쉼표로 구분)", "text"],
  ["student_count", "학생 수", "number"],
  ["established_year", "설립 연도", "number"],
  ["employment_rate", "취업률 (%)", "number"],
  ["intro", "학교 소개", "area"],
  ["departments", "학과 (줄바꿈으로 구분)", "area"],
  ["facilities", "시설", "area"],
  ["admission_info", "학교 상세 안내", "area"],
];

function SchoolDetail({ id, onClose, onSaved }) {
  const [data, setData] = useState(null);
  const [form, setForm] = useState({});
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .school(id)
      .then((d) => {
        setData(d);
        setForm(
          Object.fromEntries(
            Object.entries(d.editable).map(([k, v]) => [k, v === null ? "" : v])
          )
        );
      })
      .catch((e) => setError(e.message));
  }, [id]);

  const save = async () => {
    setBusy(true);
    setError("");
    setMsg("");
    try {
      // 숫자 칸은 비워두면 '지우기'가 아니라 '안 건드림'으로 본다.
      const patch = {};
      for (const [k, label, type] of FIELDS) {
        const v = form[k];
        if (v === "" || v === null || v === undefined) continue;
        patch[k] = type === "number" ? Number(v) : v;
      }
      const r = await api.updateSchool(id, patch);
      setMsg(
        r.changed.length
          ? `${r.changed.length}개 항목을 저장했습니다.`
          : "바뀐 내용이 없습니다."
      );
      if (r.changed.length) onSaved();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title={data ? data.name : "학교"}
      sub={data ? `${data.region} · ${data.category}` : ""}
      onClose={onClose}
      foot={
        <>
          <button className="btn" onClick={onClose}>
            닫기
          </button>
          <button className="btn go" onClick={save} disabled={busy || !data}>
            {busy ? "저장 중…" : "저장"}
          </button>
        </>
      }
    >
      <Note kind="bad">{error}</Note>
      <Note kind="good">{msg}</Note>

      {!data ? (
        <Empty>불러오는 중…</Empty>
      ) : (
        <>
          <Note kind="info">
            플랜·노출 여부·메일 계정은 이 화면에서 바꿀 수 없습니다. 필요하면 관리자에게
            요청하세요.
          </Note>

          <div className="grid2">
            {FIELDS.filter(([, , t]) => t !== "area").map(([k, label, type]) => (
              <div className="field" key={k}>
                <label htmlFor={k}>{label}</label>
                <input
                  id={k}
                  type={type}
                  value={form[k] ?? ""}
                  onChange={(e) => setForm({ ...form, [k]: e.target.value })}
                />
              </div>
            ))}
          </div>

          {FIELDS.filter(([, , t]) => t === "area").map(([k, label]) => (
            <div className="field" key={k}>
              <label htmlFor={k}>{label}</label>
              <textarea
                id={k}
                value={form[k] ?? ""}
                onChange={(e) => setForm({ ...form, [k]: e.target.value })}
              />
            </div>
          ))}

          <h2 style={{ fontSize: 13, marginTop: 18, marginBottom: 8 }}>학교 계정</h2>
          {data.accounts.length === 0 ? (
            <p className="tiny muted">연결된 계정이 없습니다.</p>
          ) : (
            <table>
              <tbody>
                {data.accounts.map((a) => (
                  <tr key={a.id}>
                    <td>{a.name}</td>
                    <td>
                      <Masked value={a.email} />
                    </td>
                    <td>
                      <span className={`badge ${a.is_active ? "flat" : "stop"}`}>
                        {a.is_active ? a.role : "중지"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {data.orders.length > 0 && (
            <>
              <h2 style={{ fontSize: 13, marginTop: 18, marginBottom: 8 }}>최근 주문</h2>
              <table>
                <tbody>
                  {data.orders.map((o) => (
                    <tr key={o.id}>
                      <td>{PLAN_LABEL[o.plan] || o.plan}</td>
                      <td className="num">{o.amount.toLocaleString()}원</td>
                      <td>
                        <span className="badge flat">{o.status_label}</span>
                      </td>
                      <td className="tiny muted">{fmtDate(o.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </>
      )}
    </Modal>
  );
}
