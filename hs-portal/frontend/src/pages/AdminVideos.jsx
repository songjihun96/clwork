import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useSeo } from "../seo";
import { errMsg, okMsg } from "../toast";

/** 영상 관리 — 롱폼과 숏츠.
 *
 * 화면을 유튜브 스튜디오처럼 잡았다. 이유가 있다.
 *   1) **파일부터 던진다.** 예전에는 제목을 먼저 묻고(prompt), 빈 껍데기를
 *      만든 다음, 그 안에서 파일을 골랐다. 세 단계였고 중간에 그만두면
 *      제목만 있는 빈 영상이 남았다. 지금은 끌어다 놓으면 파일 이름이
 *      제목이 되고 바로 올라간다. 제목은 나중에 고치면 된다.
 *   2) **목록이 곧 전부다.** 썸네일·공개상태·길이·조회수가 한 줄에 있고,
 *      줄을 누르면 그 자리에서 펼쳐 고친다. 다른 화면으로 안 넘어간다.
 *   3) **롱폼이 중심이다.** 숏츠는 롱폼에서 잘라 낸 조각이니, 롱폼을 열고
 *      그 안에서 올린다. 올리는 순간 그 롱폼에 붙으므로 "어디에 연결할지"를
 *      따로 고를 일이 없다 — 고르는 단계가 있으면 빼먹게 되고, 그러면 어디에도
 *      안 붙은 숏츠가 생긴다.
 *
 *      단, 롱폼을 지우면 거기 붙어 있던 숏츠는 갈 곳을 잃는다. 그런 숏츠만
 *      목록 맨 아래 **연결 안 된 숏츠**로 모아 둔다 — 평소엔 아예 안 보이고,
 *      생겼을 때만 나타난다. 예전에 이걸 안 두었다가, 영상은 남아 있는데
 *      화면 어디에서도 못 찾아 지울 수조차 없는 상태를 만든 적이 있다.
 */

const STATUS_LABEL = {
  pending: "분석 전", processing: "분석 중", completed: "찾음",
  needs_review: "확인 필요", failed: "실패", confirmed: "확정",
};
const STATUS_CLASS = {
  completed: "badge-cat", confirmed: "badge-cat",
  needs_review: "badge-dorm", failed: "badge-dorm", processing: "badge-dorm",
};

export function fmtTime(sec) {
  if (sec === null || sec === undefined) return "—";
  const s = Math.max(Number(sec), 0);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const rest = (s % 60).toFixed(2).padStart(5, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${rest}` : `${m}:${rest}`;
}

function fmtLen(sec) {
  if (!sec) return "—";
  const s = Math.floor(sec);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = String(s % 60).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${r}` : `${m}:${r}`;
}

function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, "0")}.${String(d.getDate()).padStart(2, "0")}`;
}

function parseTime(text) {
  // "3:24.12" / "1:03:24.12" / "204.12" 를 모두 초로 받는다.
  const t = (text || "").trim();
  if (!t) return null;
  const parts = t.split(":").map((x) => Number(x));
  if (parts.some((n) => Number.isNaN(n))) return null;
  return parts.reduce((acc, n) => acc * 60 + n, 0);
}

function baseName(name) {
  return (name || "").replace(/\.[^.]+$/, "").trim() || "제목 없음";
}

const pct = (x) => (x === null || x === undefined ? "—" : `${Math.round(x * 100)}%`);

/* ------------------------------------------------------------------ 본체 */

export default function AdminVideos() {
  useSeo({ title: "영상 관리", path: "/admin/videos" });
  const [longforms, setLongforms] = useState([]);
  const [shorts, setShorts] = useState([]);
  const [openId, setOpenId] = useState(null);
  const [detail, setDetail] = useState(null);      // 펼친 영상의 상세
  const [stt, setStt] = useState(null);
  const [publicOn, setPublicOn] = useState(null);
  const [confirmAt, setConfirmAt] = useState(null);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    const [lf, sh] = await Promise.all([
      api.adminVideos("longform"), api.adminVideos("shorts"),
    ]);
    setLongforms(lf);
    setShorts(sh);
    setLoaded(true);
  }, []);

  useEffect(() => {
    load().catch((e) => setMsg(errMsg(e.message)));
    api.sttStatus().then(setStt).catch(() => setStt(null));
    api.videosVisibility().then((r) => setPublicOn(!!r.public)).catch(() => setPublicOn(null));
    api.matchThresholds().then((t) => setConfirmAt(t.confirm)).catch(() => setConfirmAt(null));
  }, [load]);

  const loadDetail = useCallback(async (id) => {
    if (!id) return setDetail(null);
    try {
      setDetail(await api.adminVideo(id));
    } catch (e) {
      setMsg(errMsg(e.message));
      setDetail(null);
    }
  }, []);

  useEffect(() => { loadDetail(openId); }, [openId, loadDetail]);

  const refresh = useCallback(async () => {
    await load();
    if (openId) await loadDetail(openId);
  }, [load, loadDetail, openId]);

  const toggle = (id) => setOpenId((cur) => (cur === id ? null : id));

  const remove = async (v) => {
    // 되돌릴 수 없으니, 무엇이 함께 사라지는지 먼저 정확히 알린다.
    let withShorts = false;
    if (v.kind === "longform") {
      const linked = shorts.filter((s) => s.link?.longform_id === v.id);
      if (linked.length) {
        const also = window.confirm(
          `'${v.title}' 에 숏츠 ${linked.length}개가 붙어 있습니다.\n\n` +
          "[확인] 숏츠까지 모두 삭제\n[취소] 롱폼만 삭제하고 숏츠는 남기기\n" +
          "(남긴 숏츠는 숏츠 탭에 '연결 안 됨'으로 보입니다)");
        withShorts = also;
      }
    }
    if (!window.confirm(`'${v.title}' 을(를) 삭제할까요?${withShorts ? " 붙어 있는 숏츠까지 함께 지웁니다." : ""}\n\n되돌릴 수 없습니다.`)) return;
    try {
      const r = await api.deleteVideo(v.id, withShorts);
      if (openId === v.id) setOpenId(null);
      await load();
      setMsg(okMsg(`${r.deleted > 1 ? `${r.deleted}개를 ` : ""}삭제했습니다.`));
    } catch (e) {
      setMsg(errMsg(e.message));
    }
  };

  const runAll = async (longformId) => {
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.matchAll(longformId);
      await refresh();
      setMsg(okMsg(`숏츠 ${r.queued}개를 분석했습니다.`));
    } catch (e) {
      setMsg(errMsg(e.message));
    } finally {
      setBusy(false);
    }
  };

  const orphans = shorts.filter((s) => !s.link || !s.link.longform_id);

  return (
    <div className="wrap" style={{ padding: "34px 0 60px" }}>
      <span className="label">관리자</span>
      <h1 style={{ fontSize: 26, margin: "8px 0 4px" }}>영상 관리</h1>
      <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 0 }}>
        롱폼을 올리고 숏츠를 연결하면, 숏츠가 롱폼의 어느 구간에서 나왔는지 자동으로 찾습니다.
      </p>

      <SettingsBar
        stt={stt} publicOn={publicOn} setPublicOn={setPublicOn}
        confirmAt={confirmAt} setConfirmAt={setConfirmAt} setMsg={setMsg} />

      {msg && <div className={`notice notice-${msg.type}`} style={{ marginTop: 12 }}>{msg.text}</div>}

      <h3 style={{ marginTop: 22 }}>롱폼 ({longforms.length})</h3>
      <Dropzone kind="longform" onDone={refresh} setMsg={setMsg} stt={stt} />

      {!loaded ? (
        <p style={{ fontSize: 13.5, color: "var(--steel)", marginTop: 18 }}>불러오는 중…</p>
      ) : longforms.length === 0 ? (
        <div className="empty" style={{ marginTop: 18 }}>
          <p>등록된 롱폼이 없습니다.</p>
          <p style={{ fontSize: 13, color: "var(--steel)" }}>
            위 상자에 영상 파일을 끌어다 놓으면 바로 올라갑니다.
            숏츠는 롱폼을 연 다음 그 안에서 올립니다.
          </p>
        </div>
      ) : (
        <div style={{ display: "grid", gap: 10, marginTop: 14 }}>
          {longforms.map((v) => (
            <VideoRow key={v.id}
              video={v} open={openId === v.id} onToggle={() => toggle(v.id)}
              onRemove={() => remove(v)}
              longforms={longforms}
              shortsCount={shorts.filter((s) => s.link?.longform_id === v.id).length}
              detail={openId === v.id ? detail : null}
              onChanged={refresh} setMsg={setMsg} stt={stt} publicOn={publicOn}
              busy={busy} onRunAll={() => runAll(v.id)} onRemoveVideo={remove} />
          ))}
        </div>
      )}

      {orphans.length > 0 && (
        <OrphanShorts list={orphans} longforms={longforms}
          onChanged={refresh} setMsg={setMsg} onRemove={remove} />
      )}
    </div>
  );
}

/** 갈 곳을 잃은 숏츠.
 *
 * 롱폼을 지우면 거기 붙어 있던 숏츠는 연결만 끊긴 채 남는다(영상 자체는
 * 따로 올린 파일이라 같이 지우지 않는 게 기본이다). 그런 숏츠가 화면
 * 어디에도 안 나오면 지울 방법조차 없어지므로, 여기 모아 둔다.
 * 하나도 없으면 이 구역 자체가 안 나온다 — 평소엔 볼 일이 없어야 한다.
 */
function OrphanShorts({ list, longforms, onChanged, setMsg, onRemove }) {
  return (
    <div className="panel" style={{ marginTop: 22, borderColor: "var(--color-attention)" }}>
      <h3 style={{ border: "none", padding: 0, margin: "0 0 4px" }}>
        연결 안 된 숏츠 ({list.length})
      </h3>
      <p style={{ fontSize: 12.5, color: "var(--steel)", margin: "0 0 12px" }}>
        붙어 있던 롱폼이 삭제된 숏츠입니다. 다른 롱폼에 다시 붙이거나 지우세요.
      </p>
      <div style={{ display: "grid", gap: 8 }}>
        {list.map((v) => (
          <div key={v.id} style={{ display: "flex", gap: 10, alignItems: "center",
            flexWrap: "wrap", padding: "10px 12px",
            border: "1px solid var(--line)", borderRadius: "var(--radius-sm)" }}>
            <Thumb video={v} small />
            <div style={{ flex: "1 1 160px", minWidth: 0 }}>
              <strong style={{ fontSize: 14 }}>{v.title}</strong>
              <div style={{ fontSize: 12, color: "var(--steel)", marginTop: 2 }}>
                {fmtLen(v.duration_sec)} · {fmtDate(v.created_at)}
              </div>
            </div>
            <select className="select" style={{ width: "auto", maxWidth: 220 }}
              value="" onChange={async (e) => {
                if (!e.target.value) return;
                try {
                  await api.updateVideo(v.id, { longform_id: Number(e.target.value) });
                  setMsg(okMsg("롱폼에 다시 붙였습니다."));
                  onChanged();
                } catch (err) { setMsg(errMsg(err.message)); }
              }}>
              <option value="">롱폼에 붙이기…</option>
              {longforms.map((lf) => <option key={lf.id} value={lf.id}>{lf.title}</option>)}
            </select>
            <button className="btn btn-ghost btn-sm" onClick={() => onRemove(v)}>삭제</button>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ 설정 */

/** 자주 안 건드리는 설정은 접어 둔다.
 *
 * 예전에는 이 셋(전사 엔진 상태·학생 공개·자동확정 기준)이 화면 맨 위를
 * 통째로 차지해, 정작 매일 하는 일인 영상 목록이 스크롤 아래로 밀렸다.
 * 지금 상태만 한 줄로 보이고, 고칠 때만 편다.
 */
function SettingsBar({ stt, publicOn, setPublicOn, confirmAt, setConfirmAt, setMsg }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="panel" style={{ marginTop: 14, padding: "12px 14px" }}>
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <span className={`badge ${publicOn ? "badge-cat" : "badge-dorm"}`}>
          {publicOn ? "학생에게 공개 중" : "관리자만 보임"}
        </span>
        {stt && (
          <span className={`badge ${stt.fingerprint ? "badge-cat" : "badge-dorm"}`}>
            소리 지문 {stt.fingerprint ? "켜짐" : "꺼짐"}
          </span>
        )}
        {confirmAt !== null && (
          <span style={{ fontSize: 12.5, color: "var(--steel)" }}>
            · 자동 확정 {Math.round(confirmAt * 100)}%
          </span>
        )}
        <span style={{ flex: 1 }} />
        <button className="btn btn-ghost btn-sm" onClick={() => setOpen(!open)}>
          {open ? "설정 접기" : "설정"}
        </button>
      </div>

      {open && (
        <div style={{ display: "grid", gap: 14, marginTop: 14,
          paddingTop: 14, borderTop: "1px solid var(--line)" }}>
          {stt && (
            <div style={{ fontSize: 13, lineHeight: 1.6 }}>
              <b>소리 지문:</b>{" "}
              {stt.fingerprint
                ? "켜짐 — 숏츠의 소리를 롱폼의 소리와 맞춰 구간을 찾습니다."
                : stt.fingerprint_note}
              {!stt.ffmpeg && <div style={{ marginTop: 4 }}>{stt.ffmpeg_note}</div>}
              {!stt.fingerprint && (
                <div style={{ marginTop: 4, color: "var(--color-attention)" }}>
                  지문이 꺼져 있으면 구간을 찾을 방법이 없습니다.
                </div>
              )}
            </div>
          )}

          {publicOn !== null && (
            <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
              <b style={{ fontSize: 13.5 }}>학생 공개</b>
              <span style={{ fontSize: 12.5, color: "var(--steel)", flex: "1 1 260px" }}>
                {publicOn
                  ? "메뉴에 '숏츠'가 나오고, 공개로 설정한 영상을 누구나 볼 수 있습니다."
                  : "학생 메뉴에 '숏츠'가 없고, 주소를 직접 쳐도 열리지 않습니다."}
              </span>
              <button className="btn btn-sm" onClick={async () => {
                const next = !publicOn;
                if (next && !window.confirm("지금부터 학생에게 숏츠가 보입니다. 계속할까요?")) return;
                try {
                  await api.setVideosVisibility(next);
                  setPublicOn(next);
                  setMsg(okMsg(next ? "학생에게 공개했습니다." : "다시 감췄습니다."));
                } catch (e) { setMsg(errMsg(e.message)); }
              }}>
                {publicOn ? "다시 감추기" : "학생에게 공개"}
              </button>
            </div>
          )}

          {confirmAt !== null && (
            <div>
              <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
                <b style={{ fontSize: 13.5 }}>자동 확정 기준</b>
                <input type="range" min="50" max="100" step="1"
                  value={Math.round(confirmAt * 100)}
                  onChange={(e) => setConfirmAt(Number(e.target.value) / 100)}
                  style={{ flex: "1 1 200px", maxWidth: 320 }} />
                <b style={{ minWidth: 46 }}>{Math.round(confirmAt * 100)}%</b>
                <button className="btn btn-sm" onClick={async () => {
                  try {
                    await api.setMatchThresholds(confirmAt);
                    setMsg(okMsg(`${Math.round(confirmAt * 100)}% 이상이면 자동 확정합니다.`));
                  } catch (e) { setMsg(errMsg(e.message)); }
                }}>기준 저장</button>
              </div>
              <p style={{ fontSize: 12.5, color: "var(--steel)", margin: "8px 0 0", lineHeight: 1.6 }}>
                이 값 이상이면 <b>찾음</b>으로, 그 아래면 <b>확인 필요</b>로 둡니다.
                숏츠에 배경음악·자막이 많이 들어가면 점수가 전반적으로 내려가니,
                실제 영상 몇 개를 돌려 보고 대부분 맞는데 확인 필요로 뜬다면 낮추세요.
                낮추면 손이 덜 가는 대신 틀린 구간이 그냥 확정될 위험이 커집니다.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- 올리기 */

/** 끌어다 놓기로 올린다.
 *
 * 제목을 먼저 묻지 않는다 — 파일 이름이 곧 제목이고, 마음에 안 들면
 * 목록에서 바로 고치면 된다. 한 번에 여러 개를 떨어뜨려도 되지만
 * **한 개씩 차례로** 올린다. 동시에 보내면 서로 대역폭을 나눠 가져
 * 전부 느려지고, 어느 것이 어디까지 갔는지도 알기 어렵다.
 */
function Dropzone({ kind, onDone, setMsg, stt, longformId = null, compact = false }) {
  const [over, setOver] = useState(false);
  const [queue, setQueue] = useState([]);   // [{name, percent, total, loaded, state, error}]
  const running = useRef(false);
  const maxBytes = stt?.max_video_mb ? stt.max_video_mb * 1024 * 1024 : 0;
  const limitLabel = stt?.max_video_label || "";

  const accept = async (picked) => {
    // picked 는 이미 배열이어야 한다. 파일 고르기 창에서 온 FileList 를
    // 그대로 들고 오면 안 된다 — input.value 를 비우는 순간 그 목록도
    // 함께 비어, 고른 파일이 사라진다(끌어다 놓기만 되고 고르기는 실패).
    const list = picked.filter((f) => f.type.startsWith("video/") || /\.(mp4|mov|m4v|webm)$/i.test(f.name));
    if (!list.length) {
      // 고르기 창을 그냥 닫은 경우까지 오류로 떠들지 않는다.
      if (picked.length) {
        setMsg(errMsg("MP4·MOV·M4V·WEBM 영상 파일만 올릴 수 있습니다."));
      }
      return;
    }
    const tooBig = maxBytes && list.find((f) => f.size > maxBytes);
    if (tooBig) {
      // 몇 기가를 다 보낸 뒤에 거절하지 않는다. 보내기 전에 막는다.
      setMsg(errMsg(`'${tooBig.name}' 은(는) ${mb(tooBig.size)} 라 한도(${limitLabel})를 넘습니다.`));
      return;
    }
    if (running.current) {
      setMsg({ type: "info", text: "먼저 올리던 영상이 끝난 뒤에 다시 놓아주세요." });
      return;
    }
    running.current = true;
    setQueue(list.map((f) => ({ name: f.name, state: "wait", percent: 0 })));
    setMsg(null);

    for (let i = 0; i < list.length; i += 1) {
      const file = list[i];
      const at = (patch) => setQueue((q) => q.map((row, j) => (j === i ? { ...row, ...patch } : row)));
      try {
        at({ state: "up", percent: 0, total: file.size });
        const body = { kind, title: baseName(file.name) };
        // 숏츠는 열어 둔 롱폼 안에서만 올리므로 연결이 자동으로 붙는다.
        if (kind === "shorts" && longformId) body.longform_id = longformId;
        const v = await api.createVideo(body);
        await api.uploadVideoFile(v.id, file, (p) => at({
          percent: p.percent, loaded: p.loaded, total: p.total,
          state: p.processing || p.percent === 100 ? "save" : "up",
        }));
        at({ state: "done", percent: 100 });
      } catch (e) {
        at({ state: "error", error: e.message });
      }
    }
    running.current = false;
    await onDone();
    setTimeout(() => setQueue((q) => (q.every((r) => r.state === "done") ? [] : q)), 2500);
  };

  return (
    <div style={{ marginTop: 16 }}>
      <label
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); accept([...e.dataTransfer.files]); }}
        style={{
          display: "block", cursor: "pointer", textAlign: "center",
          padding: compact ? "16px 14px" : "28px 20px", borderRadius: "var(--radius)",
          border: `2px dashed ${over ? "var(--color-accent)" : "var(--line)"}`,
          background: over ? "var(--color-accent-soft)" : "var(--raised)",
          transition: "background .15s ease, border-color .15s ease",
        }}>
        <div style={{ fontSize: compact ? 20 : 30, lineHeight: 1 }}>⬆</div>
        <div style={{ fontWeight: 700, fontSize: compact ? 13.5 : 15, marginTop: compact ? 5 : 8 }}>
          {kind === "longform"
            ? "롱폼 영상을 여기로 끌어다 놓으세요"
            : "이 롱폼에서 잘라 낸 숏츠를 여기로 끌어다 놓으세요"}
        </div>
        <div style={{ fontSize: 12, color: "var(--steel)", marginTop: 4 }}>
          또는 눌러서 파일 고르기 · MP4·MOV·M4V·WEBM
          {limitLabel && <> · {limitLabel} 이하</>} · 파일 이름이 제목이 됩니다
          {stt?.disk_free_mb !== null && stt?.disk_free_mb !== undefined && (
            <> · 서버 여유 {(stt.disk_free_mb / 1024).toFixed(1)}GB</>
          )}
        </div>
        <input type="file" multiple accept="video/mp4,video/quicktime,video/webm"
          onChange={(e) => { const f = [...e.target.files]; e.target.value = ""; accept(f); }}
          style={{ display: "none" }} />
      </label>

      {queue.length > 0 && (
        <div style={{ display: "grid", gap: 8, marginTop: 10 }}>
          {queue.map((row, i) => (
            <div key={i} className="panel" style={{ padding: "10px 12px" }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>
                <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis",
                  whiteSpace: "nowrap" }}>{row.name}</span>
                <span style={{ color: row.state === "error" ? "var(--color-attention)" : "var(--steel)",
                  fontSize: 12.5 }}>
                  {row.state === "wait" ? "대기"
                    : row.state === "up" ? `${(row.percent || 0).toFixed(1)}%  ·  ${mb(row.loaded)} / ${mb(row.total)}`
                      : row.state === "save" ? "서버가 저장하는 중…"
                        : row.state === "done" ? "완료" : row.error}
                </span>
              </div>
              {row.state !== "error" && (
                <div style={{ height: 6, background: "var(--raised)", borderRadius: 999,
                  overflow: "hidden", marginTop: 6 }}>
                  <div style={{
                    width: `${row.state === "done" ? 100 : row.percent || 0}%`,
                    height: "100%", background: "var(--color-accent)",
                    transition: "width .2s ease",
                  }} />
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- 목록 줄 */

/** 목록 한 줄 — 썸네일·제목·상태가 한눈에, 누르면 그 자리에서 펼쳐 고친다. */
function VideoRow({ video, open, onToggle, onRemove, longforms, shortsCount,
                    detail, onChanged, setMsg, stt, busy, onRunAll, publicOn,
                    onRemoveVideo }) {

  return (
    <div className="panel" style={{
      padding: 0, overflow: "hidden",
      border: open ? "1px solid var(--color-accent)" : undefined,
    }}>
      <div style={{ display: "flex", gap: 14, padding: 12, alignItems: "flex-start" }}>
        <Thumb video={video} />

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
            <strong style={{ fontSize: 15 }}>{video.title}</strong>
            {video.is_public
              ? <span className="badge badge-cat">공개</span>
              : <span className="badge badge-dorm">비공개</span>}
            {!video.file_url && <span className="badge badge-dorm">영상 없음</span>}
          </div>

          {video.description && (
            <p style={{ fontSize: 12.5, color: "var(--steel)", margin: "4px 0 0",
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {video.description}
            </p>
          )}

          <div style={{ fontSize: 12, color: "var(--steel)", marginTop: 6 }}>
            {fmtLen(video.duration_sec)} · 조회 {video.view_count || 0}
            {video.created_at && <> · {fmtDate(video.created_at)}</>}
            <> · 숏츠 {shortsCount}개</>
          </div>
        </div>

        <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
          <button className="btn btn-ghost btn-sm" onClick={onToggle}>
            {open ? "닫기" : "열기"}
          </button>
          <button className="btn btn-ghost btn-sm" onClick={onRemove}>삭제</button>
        </div>
      </div>

      {open && (
        <div style={{ padding: "0 12px 14px", borderTop: "1px solid var(--line)" }}>
          {!detail ? (
            <p style={{ fontSize: 13, color: "var(--steel)", padding: "12px 0 0" }}>불러오는 중…</p>
          ) : (
            <div style={{ display: "grid", gap: 14, paddingTop: 14 }}>
              <VideoEditor video={detail} onChanged={onChanged} setMsg={setMsg} stt={stt} />
              <ShortsManager longform={detail} longforms={longforms} publicOn={publicOn}
                onChanged={onChanged} setMsg={setMsg} stt={stt}
                busy={busy} onRunAll={onRunAll} onRemove={onRemoveVideo} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** 썸네일 자리. 첫 프레임을 그대로 쓴다(따로 만들지 않는다). */
function Thumb({ video, small = false }) {
  const box = {
    width: small ? 74 : 132, height: small ? 46 : 76,
    flexShrink: 0, borderRadius: 8,
    background: "#000", objectFit: "contain",
  };
  if (video.thumbnail) return <img src={video.thumbnail} alt="" style={box} />;
  if (video.file_url) {
    return <video src={video.file_url} preload="metadata" muted style={box} />;
  }
  return (
    <div style={{ ...box, display: "grid", placeItems: "center",
      background: "var(--raised)", color: "var(--steel)", fontSize: small ? 10.5 : 11.5 }}>
      영상 없음
    </div>
  );
}

/** 롱폼 상세 안의 숏츠 관리 — 올리기·확인·구간 맞추기가 전부 여기 있다.
 *
 * 숏츠를 이 자리에서 올리는 게 요점이다. 올리는 순간 이 롱폼에 붙으므로
 * "어느 롱폼에서 나온 조각인지"를 사람이 고를 일이 없다. 고르는 단계를
 * 두면 반드시 빼먹는 사람이 생기고, 그렇게 생긴 미아 숏츠는 나중에
 * 하나씩 찾아 붙여야 한다.
 */
function ShortsManager({ longform, longforms, publicOn, onChanged, setMsg, stt,
                         busy, onRunAll, onRemove }) {
  const [openId, setOpenId] = useState(null);
  const list = longform.shorts || [];

  return (
    <div className="field">
      <label className="label">이 롱폼의 숏츠 ({list.length})</label>

      <Dropzone kind="shorts" longformId={longform.id} compact
        onDone={onChanged} setMsg={setMsg} stt={stt} />

      {list.length === 0 ? (
        <p style={{ fontSize: 12.5, color: "var(--steel)", margin: "10px 0 0" }}>
          아직 없습니다. 위 상자에 숏츠를 올리면 이 롱폼에 바로 붙습니다.
        </p>
      ) : (
        <>
          <div style={{ display: "grid", gap: 8, margin: "12px 0 10px" }}>
            {list.map((sv) => (
              <ShortsItem key={sv.id} shorts={sv} longform={longform} longforms={longforms}
                open={openId === sv.id}
                onToggle={() => setOpenId((cur) => (cur === sv.id ? null : sv.id))}
                publicOn={publicOn} onChanged={onChanged} setMsg={setMsg} stt={stt}
                onRemove={onRemove} />
            ))}
          </div>
          <button className="btn btn-sm" onClick={onRunAll} disabled={busy}>
            {busy ? "분석 중…" : `숏츠 ${list.length}개 한 번에 분석`}
          </button>
        </>
      )}
    </div>
  );
}

/** 숏츠 한 줄. 펼치면 그 숏츠의 상세를 그때 받아 온다.
 *
 * 목록에 실려 오는 숏츠에는 지문 정보가 없다(롱폼 상세를 받을 때마다
 * 숏츠 개수만큼 더 캐물으면 느려진다). 펼친 것만 따로 받는다.
 */
function ShortsItem({ shorts, longform, longforms, open, onToggle,
                      publicOn, onChanged, setMsg, stt, onRemove }) {
  const [detail, setDetail] = useState(null);
  const m = shorts.match;

  useEffect(() => {
    if (!open) return setDetail(null);
    let alive = true;
    api.adminVideo(shorts.id)
      .then((d) => { if (alive) setDetail(d); })
      .catch((e) => setMsg(errMsg(e.message)));
    return () => { alive = false; };
  }, [open, shorts.id, shorts.title, shorts.is_public]);

  return (
    <div style={{ border: "1px solid var(--line)", borderRadius: "var(--radius-sm)" }}>
      <div style={{ display: "flex", gap: 10, alignItems: "center",
        flexWrap: "wrap", padding: 10 }}>
        <Thumb video={shorts} small />
        <div style={{ flex: "1 1 160px", minWidth: 0 }}>
          <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
            <strong style={{ fontSize: 14 }}>{shorts.title}</strong>
            {!shorts.is_public && <span className="badge badge-dorm">비공개</span>}
            <span className={`badge ${STATUS_CLASS[m?.status] || "badge-dorm"}`}>
              {STATUS_LABEL[m?.status] || "분석 전"}
            </span>
          </div>
          <div style={{ fontSize: 12, color: "var(--steel)", marginTop: 3 }}>
            {m?.source_start_time !== null && m?.source_start_time !== undefined
              ? <>구간 {fmtTime(m.source_start_time)} ~ {fmtTime(m.source_end_time)} · 신뢰도 {pct(m.confidence)}</>
              : <>구간 미확인</>}
          </div>
        </div>
        <button className="btn btn-ghost btn-sm" onClick={onToggle}>
          {open ? "닫기" : "열기"}
        </button>
        <button className="btn btn-ghost btn-sm" onClick={() => onRemove(shorts)}>삭제</button>
      </div>

      {open && (
        <div style={{ padding: "0 10px 12px", borderTop: "1px solid var(--line)" }}>
          {!detail ? (
            <p style={{ fontSize: 12.5, color: "var(--steel)", padding: "10px 0 0" }}>불러오는 중…</p>
          ) : (
            <div style={{ display: "grid", gap: 12, paddingTop: 12 }}>
              <VideoEditor video={detail} onChanged={onChanged} setMsg={setMsg} stt={stt} />
              <MatchPanel shorts={detail} longforms={longforms} publicOn={publicOn}
                onChanged={onChanged} setMsg={setMsg} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------ 영상 편집기 */

/** 영상 하나의 기본 정보 + 파일 + 소리 지문 상태 */
function VideoEditor({ video, onChanged, setMsg, stt }) {
  const [form, setForm] = useState({
    title: video.title, description: video.description || "",
    is_public: video.is_public,
  });
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(null);   // {percent, loaded, total, processing}
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setForm({ title: video.title, description: video.description || "", is_public: video.is_public });
  }, [video.id, video.title, video.description, video.is_public]);

  const save = async () => {
    setBusy(true);
    try {
      await api.updateVideo(video.id, form);
      setMsg(okMsg("저장했습니다."));
      onChanged();
    } catch (e) {
      setMsg(errMsg(e.message));
    } finally {
      setBusy(false);
    }
  };

  const pickFile = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setUploading(true);
    setProgress({ percent: 0, loaded: 0, total: file.size });
    setMsg(null);
    try {
      const r = await api.uploadVideoFile(video.id, file, setProgress);
      setMsg(okMsg(`올렸습니다. ${r.note || ""}`));
      onChanged();
    } catch (err) {
      setMsg(errMsg(err.message));
    } finally {
      setUploading(false);
      setProgress(null);
    }
  };

  return (
    <div style={{ display: "grid", gap: 12 }}>
      <div className="field">
        <label className="label">제목</label>
        <input className="input" value={form.title}
          onChange={(e) => setForm({ ...form, title: e.target.value })} />
      </div>
      <div className="field">
        <label className="label">설명</label>
        <textarea className="textarea" rows={2} value={form.description}
          onChange={(e) => setForm({ ...form, description: e.target.value })} />
      </div>
      <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13.5 }}>
          <input type="checkbox" checked={form.is_public}
            onChange={(e) => setForm({ ...form, is_public: e.target.checked })} />
          공개 (학생에게 보임)
        </label>
        <button className="btn btn-sm" onClick={save} disabled={busy}>정보 저장</button>
      </div>

      <div className="field">
        <label className="label">영상 파일</label>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          {video.file_url ? (
            <>
              <video src={video.file_url} controls preload="metadata"
                style={{ width: 240, borderRadius: 8, background: "#000" }} />
              <span className="label" style={{ color: "var(--steel-light)" }}>
                길이 {video.duration_sec ? fmtTime(video.duration_sec) : "미확인"}
              </span>
            </>
          ) : (
            <span className="label" style={{ color: "var(--steel-light)" }}>아직 없음</span>
          )}
          <label className="btn btn-ghost btn-sm"
            style={{ cursor: uploading ? "default" : "pointer", opacity: uploading ? .6 : 1 }}>
            {uploading ? "올리는 중…" : video.file_url ? "다른 파일로 바꾸기" : "영상 올리기"}
            <input type="file" accept="video/mp4,video/quicktime,video/webm"
              onChange={pickFile} disabled={uploading} style={{ display: "none" }} />
          </label>
          {video.file_url && (
            <button className="btn btn-ghost btn-sm" onClick={async () => {
              if (!window.confirm("원본 파일만 지웁니다. 소리 지문과 찾아 둔 구간은 남습니다. 계속할까요?")) return;
              await api.deleteVideoFile(video.id);
              onChanged();
            }}>원본 삭제(용량 회수)</button>
          )}
        </div>
        {uploading && <UploadBar progress={progress} />}
      </div>

      <div className="field">
        <label className="label">
          소리 지문{" "}
          <span style={{ fontWeight: "normal", color: "var(--steel)" }}>
            — {video.fingerprint?.status === "completed"
              ? `${video.fingerprint.hashes.toLocaleString()}개`
              : video.fingerprint?.status === "failed"
                ? `실패: ${video.fingerprint.error}`
                : video.fingerprint?.status === "processing"
                  ? "만드는 중…"
                  : "아직 없음"}
          </span>
        </label>
        <p style={{ fontSize: 12, color: "var(--steel)", margin: "2px 0 0" }}>
          영상을 올리면 자동으로 만들어집니다. 롱폼과 숏츠 양쪽에 있어야 구간을 찾을 수 있습니다.
        </p>
      </div>
    </div>
  );
}

function mb(bytes) {
  if (bytes === null || bytes === undefined) return "";
  const m = bytes / (1024 * 1024);
  return m >= 1024 ? `${(m / 1024).toFixed(2)}GB` : `${m.toFixed(1)}MB`;
}

/** 업로드 진행률.
 *
 * 영상은 수백 MB~기가라 다 올라가기까지 한참 걸린다. 버튼 글자만 바뀌면
 * 멈춘 건지 되는 건지 알 수 없어 사용자가 새로고침해 버린다(그러면 처음부터).
 * 다 보낸 뒤 서버가 저장·길이 측정을 하는 동안도 따로 알려 준다 — 그 구간이
 * 100% 에서 멈춘 것처럼 보이기 때문이다.
 */
function UploadBar({ progress }) {
  const pctv = progress?.percent;
  const done = progress?.processing || pctv === 100;
  return (
    <div style={{ marginTop: 10, maxWidth: 420 }}>
      <div style={{ height: 8, background: "var(--raised)", borderRadius: 999, overflow: "hidden" }}>
        <div style={{
          width: pctv === null || pctv === undefined ? "100%" : `${pctv}%`,
          height: "100%", background: "var(--color-accent)",
          transition: "width .2s ease",
          // 길이를 모를 때는 진행률 대신 흐린 줄로 "도는 중"만 알린다.
          opacity: pctv === null ? .5 : 1,
        }} />
      </div>
      <div style={{ fontSize: 12, color: "var(--steel)", marginTop: 5 }}>
        {done
          ? "전송 완료 — 서버가 저장하는 중입니다. 잠시만요."
          : pctv === null || pctv === undefined
            ? "올리는 중…"
            : `${pctv.toFixed(1)}%  ·  ${mb(progress.loaded)} / ${mb(progress.total)}`}
      </div>
    </div>
  );
}

/** 학생에게 지금 이 숏츠가 어떻게 보이는지.
 *
 * 이게 없어서 한 번 크게 헤맸다. 특강을 연결하고 구간까지 확정했는데도
 * 학생 화면에는 아무것도 안 떴다. 원인은 **영상이 비공개**였던 것 — 눌러도
 * 열 수 없는 영상으로 보낼 수는 없으니 서버가 막은 건데, 관리자 화면은
 * 그 이유를 한 마디도 안 했다.
 *
 * 그래서 조건을 숨기지 않고 전부 늘어놓는다. 막힌 것이 있으면 무엇을
 * 누르면 풀리는지까지 같이 준다.
 */
function StudentView({ shorts, match, longform, publicOn, onChanged, setMsg }) {
  const blockers = [];
  if (publicOn === false) {
    blockers.push({ text: "영상 기능이 아직 학생에게 공개되지 않았습니다 (위 설정에서 공개)." });
  }
  if (!shorts.is_public) {
    blockers.push({ text: "이 숏츠가 비공개입니다.", fix: "숏츠 공개하기", id: shorts.id });
  }
  if (!match?.longform_id) {
    blockers.push({ text: "연결된 특강 챕터가 없습니다." });
  } else {
    if (!["confirmed", "completed"].includes(match.status)) {
      blockers.push({
        text: match.status === "needs_review"
          ? "구간 신뢰도가 낮아 확인 대기 중입니다 — 확인 후 [확정]을 누르세요."
          : "원본 구간을 아직 못 찾았습니다 — [원본 구간 찾기]를 누르세요.",
      });
    } else if (match.source_start_time === null || match.source_start_time === undefined) {
      blockers.push({ text: "구간 시각이 비어 있습니다." });
    }
    if (longform && !longform.is_public) {
      // 실제로 우리를 물 먹인 조건. 가장 알아채기 어려운 자리라 버튼까지 붙인다.
      blockers.push({
        text: "연결된 챕터 영상이 비공개라 넘어갈 수 없습니다.",
        fix: "영상 공개하기", id: longform.id,
      });
    }
  }

  const ok = blockers.length === 0;
  return (
    <div style={{
      padding: "10px 12px", borderRadius: "var(--radius-sm)",
      background: "var(--raised)", fontSize: 12.5, lineHeight: 1.7,
    }}>
      <b style={{ color: ok ? "var(--color-success)" : "var(--color-attention)" }}>
        {ok ? "학생 화면: 특강에서 이어 보기가 나옵니다"
            : "학생 화면: 특강에서 이어 보기가 안 나옵니다"}
      </b>
      {!ok && (
        <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
          {blockers.map((b, i) => (
            <li key={i}>
              {b.text}
              {b.fix && (
                <button className="btn btn-ghost btn-sm" style={{ marginLeft: 8 }}
                  onClick={async () => {
                    try {
                      await api.updateVideo(b.id, { is_public: true });
                      setMsg(okMsg("공개로 바꿨습니다."));
                      onChanged();
                    } catch (e) { setMsg(errMsg(e.message)); }
                  }}>{b.fix}</button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/* -------------------------------------------------------------- 구간 맞추기 */

/** 숏츠가 롱폼의 어디서 나왔는지 — 연결·분석·확인·수정을 한자리에서.
 *
 * 결과를 **바로 재생해 눈으로 확인**할 수 있게 두었다. 숫자만 보고
 * 확정하라고 하면 아무도 확인하지 않는다.
 */
function MatchPanel({ shorts, longforms, publicOn, onChanged, setMsg }) {
  const m = shorts.match;
  const [busy, setBusy] = useState(false);
  const [edit, setEdit] = useState({ start: "", end: "" });
  const [chapters, setChapters] = useState([]);
  const videoRef = useRef(null);
  const longform = longforms.find((v) => v.id === m?.longform_id) || null;

  useEffect(() => {
    api.adminBriefing().then((c) => setChapters(c.chapters || [])).catch(() => setChapters([]));
  }, []);

  // 영상이 붙은 챕터만 고를 수 있다. 영상 없는 챕터에 붙이면 넘어가도 틀 게 없다.
  const chapterOptions = chapters
    .filter((c) => c.video_id)
    .map((c, i) => ({
      video_id: c.video_id,
      label: `CHAPTER ${i + 1} · ${c.title}`,
    }));

  useEffect(() => {
    if (m) setEdit({ start: fmtTime(m.source_start_time), end: fmtTime(m.source_end_time) });
  }, [m?.source_start_time, m?.source_end_time]);

  const relink = async (value) => {
    try {
      await api.updateVideo(shorts.id, { longform_id: value ? Number(value) : null });
      setMsg(okMsg(value ? "롱폼을 연결했습니다. 이제 구간을 찾아보세요." : "연결을 끊었습니다."));
      onChanged();
    } catch (e) {
      setMsg(errMsg(e.message));
    }
  };

  const analyze = async () => {
    setBusy(true);
    try {
      await api.matchShorts(shorts.id);
      onChanged();
    } catch (e) {
      setMsg(errMsg(e.message));
    } finally {
      setBusy(false);
    }
  };

  const preview = () => {
    const el = videoRef.current;
    if (!el || m?.source_start_time === null) return;
    el.currentTime = m.source_start_time;
    el.play().catch(() => {});
  };

  const saveEdit = async () => {
    const s = parseTime(edit.start);
    const e = parseTime(edit.end);
    if (s === null || e === null) return setMsg(errMsg("시각 형식을 확인해주세요 (예: 3:24.12)"));
    setBusy(true);
    try {
      await api.editMatch(m.id, { source_start_time: s, source_end_time: e, note: "관리자 수정" });
      setMsg(okMsg("구간을 저장했습니다. 다시 분석해도 이 값은 유지됩니다."));
      onChanged();
    } catch (err) {
      setMsg(errMsg(err.message));
    } finally {
      setBusy(false);
    }
  };

  const total = longform?.duration_sec || 0;
  const left = total && m?.source_start_time ? (m.source_start_time / total) * 100 : null;

  return (
    <div style={{ display: "grid", gap: 12, borderTop: "1px solid var(--line)", paddingTop: 14 }}>
      {/* 숏츠는 **특강의 챕터**에 붙인다.
        * 학생이 [특강에서 이어 보기]를 누르면 그 특강 페이지로 가서 이 챕터가
        * 잘린 그 초부터 재생된다. 영상 목록에서 아무 롱폼이나 고르게 두면,
        * 특강에 안 들어 있는 영상에 붙어 버려 넘어갈 곳이 없어진다. */}
      <div className="field">
        <label className="label">연결할 특강 챕터</label>
        <select className="select" style={{ maxWidth: 400 }}
          value={m?.longform_id || ""} onChange={(e) => relink(e.target.value)}>
          <option value="">연결 안 함</option>
          {chapterOptions.map((c) => (
            <option key={c.video_id} value={c.video_id}>
              {c.label}
            </option>
          ))}
        </select>
        {chapterOptions.length === 0 && (
          <p style={{ fontSize: 12.5, color: "var(--color-attention)", margin: "6px 0 0" }}>
            영상이 붙은 특강 챕터가 없습니다. 먼저 <b>설명회 관리 → 강의 구성</b>에서
            챕터마다 영상을 골라주세요.
          </p>
        )}
        {chapterOptions.length > 0 && !m?.longform_id && (
          <p style={{ fontSize: 12.5, color: "var(--color-attention)", margin: "6px 0 0" }}>
            연결된 특강이 없습니다. 학생 화면에서 &lsquo;특강에서 이어 보기&rsquo;가 안 나옵니다.
          </p>
        )}
      </div>

      <StudentView shorts={shorts} match={m} longform={longform}
        publicOn={publicOn} onChanged={onChanged} setMsg={setMsg} />

      {m?.longform_id && (
        <>
          <div style={{ fontSize: 13 }}>
            <div>
              원본 구간 <b>{fmtTime(m.source_start_time)} ~ {fmtTime(m.source_end_time)}</b>
              {"  ·  신뢰도 "}
              <b style={{ color: (m.confidence || 0) >= 0.95 ? "var(--color-success)" : "var(--color-attention)" }}>
                {pct(m.confidence)}
              </b>
              {m.manually_modified && <span className="badge badge-cat" style={{ marginLeft: 6 }}>관리자 수정</span>}
            </div>
            <div style={{ color: "var(--steel)", marginTop: 2 }}>
              소리 지문으로 찾음
              {m.audio_score !== null && m.audio_score !== undefined && <> · 일치도 {pct(m.audio_score)}</>}
            </div>
            {m.note && <div style={{ color: "var(--color-attention)", marginTop: 2 }}>{m.note}</div>}
            {left !== null && (
              <div style={{ position: "relative", height: 6, background: "var(--raised)",
                borderRadius: 999, marginTop: 8 }}>
                <div style={{ position: "absolute", left: `${left}%`,
                  width: `${Math.max(((m.source_end_time - m.source_start_time) / total) * 100, 1)}%`,
                  top: 0, bottom: 0, background: "var(--color-accent)", borderRadius: 999 }} />
              </div>
            )}
          </div>

          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button className="btn btn-sm" onClick={analyze} disabled={busy}>
              {busy ? "분석 중…"
                : m.status === "failed" || m.status === "needs_review" ? "다시 분석" : "원본 구간 찾기"}
            </button>
            {m.source_start_time !== null && m.source_start_time !== undefined && (
              <>
                <button className="btn btn-ghost btn-sm" onClick={preview}>▶ 구간 미리보기</button>
                {m.status !== "confirmed" && (
                  <button className="btn btn-ghost btn-sm" disabled={busy} onClick={async () => {
                    await api.confirmMatch(m.id);
                    setMsg(okMsg("확정했습니다. 이제 학생 화면에 나옵니다."));
                    onChanged();
                  }}>확정</button>
                )}
              </>
            )}
          </div>

          {longform?.file_url && (
            <div>
              <span className="label">롱폼 미리보기</span>
              <video ref={videoRef} src={longform.file_url} controls preload="metadata"
                style={{ width: "100%", maxWidth: 520, borderRadius: 8, background: "#000" }} />
            </div>
          )}

          <div className="field">
            <label className="label">구간 직접 수정</label>
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <input className="input" style={{ width: 130 }} value={edit.start}
                placeholder="3:24.12"
                onChange={(e) => setEdit({ ...edit, start: e.target.value })} />
              <span>~</span>
              <input className="input" style={{ width: 130 }} value={edit.end}
                placeholder="3:51.47"
                onChange={(e) => setEdit({ ...edit, end: e.target.value })} />
              <button className="btn btn-sm" onClick={saveEdit} disabled={busy}>구간 저장</button>
            </div>
            <p style={{ fontSize: 12, color: "var(--steel)", margin: "6px 0 0" }}>
              직접 고친 구간은 다시 분석해도 덮어쓰지 않습니다.
            </p>
          </div>
        </>
      )}
    </div>
  );
}
