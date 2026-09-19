import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useCallCenter } from "../callcenter";
import { Empty, Masked, Modal, Note, Pager, fmtDateTime, useList } from "../components/ui";

/** 상담 고객. 포털 회원과는 다른 명부다.
 *
 *  목록에서는 번호를 가린다. 명부를 훑는 일과 한 사람의 이력을 보는 일은
 *  다르고, 앞의 일에는 전체 번호가 필요 없기 때문이다.
 */

const TYPE_LABEL = {
  STUDENT: "학생·학부모",
  TEACHER: "교사",
  SCHOOL: "학교",
  OTHER: "기타",
};

export default function Customers() {
  const [q, setQ] = useState("");
  const [term, setTerm] = useState("");
  const [type, setType] = useState("");
  const [open, setOpen] = useState(null);
  const [creating, setCreating] = useState(false);

  const list = useList(
    ({ limit, offset }) => api.customers({ q: term, customer_type: type, limit, offset }),
    [term, type]
  );

  return (
    <>
      <div className="page-head">
        <h1>고객</h1>
        <p>전화가 오면 이 명부에서 발신번호로 찾습니다.</p>
      </div>

      <div className="toolbar">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setTerm(q.trim());
          }}
        >
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="이름·전화번호·학교"
            aria-label="고객 검색"
          />
        </form>
        <select value={type} onChange={(e) => setType(e.target.value)} aria-label="고객 유형">
          <option value="">모든 유형</option>
          {Object.entries(TYPE_LABEL).map(([v, l]) => (
            <option key={v} value={v}>{l}</option>
          ))}
        </select>
        <span style={{ flex: 1 }} />
        <button className="btn go" onClick={() => setCreating(true)}>고객 추가</button>
      </div>

      <div className="card">
        <Note kind="bad">{list.error}</Note>
        {list.loading ? (
          <Empty>불러오는 중…</Empty>
        ) : list.items.length === 0 ? (
          <Empty>{term ? "찾는 고객이 없습니다." : "등록된 고객이 없습니다."}</Empty>
        ) : (
          <>
            <table>
              <thead>
                <tr>
                  <th>이름</th>
                  <th>전화번호</th>
                  <th>유형</th>
                  <th>학교</th>
                  <th>최근 수정</th>
                </tr>
              </thead>
              <tbody>
                {list.items.map((c) => (
                  <tr key={c.id} className="row-click" onClick={() => setOpen(c.id)}>
                    <td>{c.name || <span className="muted tiny">이름 없음</span>}</td>
                    <td><Masked value={c.phone_number} /></td>
                    <td><span className="badge flat">{TYPE_LABEL[c.customer_type]}</span></td>
                    <td>{c.school_name || <span className="muted tiny">—</span>}</td>
                    <td className="tiny muted">{fmtDateTime(c.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pager {...list} onMove={list.move} />
          </>
        )}
      </div>

      {open && <CustomerDetail id={open} onClose={() => setOpen(null)} onSaved={list.reload} />}
      {creating && (
        <CustomerForm
          onClose={() => setCreating(false)}
          onSaved={() => {
            setCreating(false);
            list.reload();
          }}
        />
      )}
    </>
  );
}

function CustomerDetail({ id, onClose, onSaved }) {
  const cc = useCallCenter();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState("consultations");
  const [rows, setRows] = useState([]);
  const [editing, setEditing] = useState(false);
  const [calling, setCalling] = useState(false);

  // 발신을 지원하지 않는 사업자에서 버튼만 띄우면, 눌러도 아무 일이
  // 없거나 오류가 난다. 할 수 있을 때만 보여준다.
  const canCall = !!cc?.settings?.provider_capabilities?.outbound;

  const placeCall = async () => {
    setCalling(true);
    setError("");
    try {
      await api.outboundCall(data.phone_number, data.id);
      await cc.refresh();
      // 통화 화면으로 옮겨준다. 여기 머물면 방금 건 전화가 어디 있는지 모른다.
      // 주소를 통째로 다시 여는 게 아니라 화면만 바꾼다. 새로고침을 하면
      // 실시간 연결이 끊겼다 붙으면서 방금 건 전화를 놓칠 수 있다.
      onClose();
      navigate("/calls");
    } catch (e) {
      setError(e.message);
      setCalling(false);
    }
  };

  useEffect(() => {
    // 상세는 전화번호 원문이 필요하다. 열람 사실은 서버가 감사로그에 남긴다.
    api.customer(id, true).then(setData).catch((e) => setError(e.message));
  }, [id]);

  useEffect(() => {
    const fetcher = tab === "consultations" ? api.customerConsultations : api.customerCalls;
    fetcher(id, { limit: 20, offset: 0 })
      .then((r) => setRows(r.items || []))
      .catch(() => setRows([]));
  }, [id, tab]);

  if (editing && data) {
    return (
      <CustomerForm
        initial={data}
        onClose={() => setEditing(false)}
        onSaved={() => {
          setEditing(false);
          api.customer(id, true).then(setData).catch(() => {});
          onSaved?.();
        }}
      />
    );
  }

  return (
    <Modal
      title={data?.name || "고객"}
      sub={data ? `${data.phone_number} · ${TYPE_LABEL[data.customer_type]}` : ""}
      onClose={onClose}
      foot={
        <>
          <button className="btn" onClick={onClose}>닫기</button>
          <button className="btn primary" onClick={() => setEditing(true)} disabled={!data}>
            정보 수정
          </button>
          {canCall && (
            <button className="btn go" onClick={placeCall} disabled={!data || calling}>
              {calling ? "거는 중…" : "전화 걸기"}
            </button>
          )}
        </>
      }
    >
      <Note kind="bad">{error}</Note>
      {!data ? (
        <Empty>불러오는 중…</Empty>
      ) : (
        <>
          <dl className="kv">
            <dt>학교</dt><dd>{data.school_name || "—"}</dd>
            <dt>이메일</dt><dd>{data.email || "—"}</dd>
            <dt>총 상담</dt><dd>{data.consultation_count ?? 0}회</dd>
            <dt>미처리</dt>
            <dd>
              {data.open_consultation_count
                ? <span className="badge wait">{data.open_consultation_count}건</span>
                : "없음"}
            </dd>
            <dt>최근 상담</dt><dd>{fmtDateTime(data.last_consulted_at)}</dd>
            <dt>통화</dt><dd>{data.call_count ?? 0}회</dd>
          </dl>
          {data.memo && <div className="note info">{data.memo}</div>}
          {canCall && (
            <p className="tiny muted" style={{ margin: "8px 0 0" }}>
              [전화 걸기] 를 누르면 이 번호로 겁니다. 고객에게 보이는 발신번호는
              전화 사업자에 등록된 번호를 따르며, CS 에서 바꿀 수 없습니다.
            </p>
          )}

          <div className="toolbar" style={{ marginTop: 14, marginBottom: 8 }}>
            <button className={`btn sm ${tab === "consultations" ? "primary" : ""}`}
                    onClick={() => setTab("consultations")}>상담 이력</button>
            <button className={`btn sm ${tab === "calls" ? "primary" : ""}`}
                    onClick={() => setTab("calls")}>통화 이력</button>
          </div>

          {rows.length === 0 ? (
            <Empty>기록이 없습니다.</Empty>
          ) : tab === "consultations" ? (
            <ul className="minilist">
              {rows.map((x) => (
                <li key={x.id}>
                  <span className="tiny muted">{fmtDateTime(x.created_at)}</span>
                  <span>{x.subject || "제목 없음"}</span>
                  <span className="tiny muted">
                    {x.counselor_name || "—"} · {x.inquiry_type_name || "미분류"}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <ul className="minilist">
              {rows.map((x) => (
                <li key={x.id}>
                  <span className="tiny muted">{fmtDateTime(x.started_at)}</span>
                  <span>{x.direction === "INBOUND" ? "수신" : "발신"} · {x.status}</span>
                  <span className="tiny muted">
                    {x.counselor_name || "—"} · {x.duration_seconds || 0}초
                  </span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </Modal>
  );
}

function CustomerForm({ initial, onClose, onSaved }) {
  const [form, setForm] = useState({
    name: initial?.name || "",
    phone_number: initial?.phone_number || "",
    email: initial?.email || "",
    customer_type: initial?.customer_type || "STUDENT",
    school_name: initial?.school_name || "",
    memo: initial?.memo || "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      const body = { ...form, school_id: initial?.school_id ?? null };
      if (initial) await api.updateCustomer(initial.id, body);
      else await api.createCustomer(body);
      onSaved();
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  };

  return (
    <Modal
      title={initial ? "고객 정보 수정" : "고객 추가"}
      onClose={onClose}
      foot={
        <>
          <button className="btn" onClick={onClose}>취소</button>
          <button className="btn go" onClick={save} disabled={busy}>
            {busy ? "저장 중…" : "저장"}
          </button>
        </>
      }
    >
      <Note kind="bad">{error}</Note>
      <div className="grid2">
        <div className="field">
          <label htmlFor="cu-name">이름</label>
          <input id="cu-name" value={form.name}
                 onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="cu-phone">전화번호</label>
          <input id="cu-phone" value={form.phone_number}
                 onChange={(e) => setForm({ ...form, phone_number: e.target.value })}
                 placeholder="010-1234-5678" />
        </div>
      </div>
      <div className="grid2">
        <div className="field">
          <label htmlFor="cu-type">고객 유형</label>
          <select id="cu-type" value={form.customer_type}
                  onChange={(e) => setForm({ ...form, customer_type: e.target.value })}>
            {Object.entries(TYPE_LABEL).map(([v, l]) => (
              <option key={v} value={v}>{l}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="cu-school">학교</label>
          <input id="cu-school" value={form.school_name}
                 onChange={(e) => setForm({ ...form, school_name: e.target.value })} />
        </div>
      </div>
      <div className="field">
        <label htmlFor="cu-email">이메일</label>
        <input id="cu-email" value={form.email}
               onChange={(e) => setForm({ ...form, email: e.target.value })} />
      </div>
      <div className="field">
        <label htmlFor="cu-memo">메모</label>
        <textarea id="cu-memo" value={form.memo}
                  onChange={(e) => setForm({ ...form, memo: e.target.value })}
                  placeholder="통화할 때 알고 있어야 할 것" />
      </div>
    </Modal>
  );
}
