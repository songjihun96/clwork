import { useEffect, useState } from "react";
import { api } from "../api";
import { errMsg, okMsg } from "../toast";

/** 강의 구성 편집 — 챕터마다 영상을 붙인다.
 *
 * 예전에는 여러 줄 텍스트 하나로 받았다. 붙여넣기는 편했지만 **챕터마다
 * 영상을 고르는 일은 글자로 못 한다**(영상 번호를 외워 적게 할 수는 없다).
 * 그래서 줄마다 칸을 세운 편집기로 바꾸되, 처음 한 번에 여러 줄을 넣는
 * 길(붙여넣기)은 남겨 둔다 — 챕터 일곱 개를 [추가] 일곱 번으로 만들게 하면
 * 아무도 안 쓴다.
 *
 * **설명회와 합격생 영상이 이 편집기를 같이 쓴다.** 짜는 일이 똑같아서
 * 화면을 두 벌로 두면 한쪽만 고쳐 놓고 잊는다. 다른 것은 두 가지뿐이라
 * `feed` 로 받는다 — 어느 API 에 저장하는지, 그리고 **영상이 공개여야
 * 하는지**. 설명회는 공개라야 재생되고, 파는 영상은 반대로 공개면 안 된다
 * (공개로 두면 특강 목록에 그냥 뜬다).
 */

/** 설명회용 기본값. 안 주면 예전과 똑같이 동작한다. */
export const BRIEFING_FEED = {
  heading: "강의 구성",
  load: () => api.adminBriefing(),
  save: (body) => api.saveBriefing(body),
  uploadCover: (file) => api.uploadBriefingCover(file),
  wantPublic: true,
};

export function fmtTime(sec) {
  const s = Math.max(Math.floor(Number(sec) || 0), 0);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = String(s % 60).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${r}` : `${m}:${r}`;
}

export function parseTime(text) {
  const t = (text || "").trim();
  if (!t) return 0;
  const parts = t.split(":").map((x) => Number(x));
  if (parts.some((n) => Number.isNaN(n))) return null;
  return parts.reduce((acc, n) => acc * 60 + n, 0);
}

export default function ChapterEditor({ setMsg, feed = BRIEFING_FEED }) {
  const [cfg, setCfg] = useState(null);
  const [videos, setVideos] = useState([]);
  const [busy, setBusy] = useState(false);
  const [pasting, setPasting] = useState(false);
  const [pasteText, setPasteText] = useState("");
  const [uploading, setUploading] = useState(false);

  useEffect(() => {
    feed.load().then(setCfg)
      .catch((e) => setMsg(errMsg(e.message)));
    api.adminVideos("longform").then(setVideos).catch(() => setVideos([]));
  }, [setMsg, feed]);

  if (!cfg) return null;
  const chapters = cfg.chapters || [];

  const setChapters = (next) => setCfg({ ...cfg, chapters: next });
  const patchCh = (i, patch) =>
    setChapters(chapters.map((c, j) => (j === i ? { ...c, ...patch } : c)));

  const move = (i, delta) => {
    const j = i + delta;
    if (j < 0 || j >= chapters.length) return;
    const next = [...chapters];
    [next[i], next[j]] = [next[j], next[i]];
    setChapters(next);
  };

  const addChapter = () =>
    setChapters([...chapters, { title: "", video_id: null, start_sec: 0, items: [] }]);

  const removeChapter = (i) => {
    if (!window.confirm(`'${chapters[i].title || "제목 없음"}' 챕터를 지울까요?`)) return;
    setChapters(chapters.filter((_, j) => j !== i));
  };

  const addItem = (i) =>
    patchCh(i, { items: [...(chapters[i].items || []),
      { title: "", video_id: null, start_sec: null }] });

  const patchItem = (i, j, patch) =>
    patchCh(i, {
      items: (chapters[i].items || []).map((it, k) => (k === j ? { ...it, ...patch } : it)),
    });

  const removeItem = (i, j) =>
    patchCh(i, { items: (chapters[i].items || []).filter((_, k) => k !== j) });

  const applyPaste = () => {
    // 한 줄에 하나. 앞에 공백이나 "-" 가 있으면 그 위 챕터의 강의로 본다.
    const added = [];
    for (const raw of pasteText.split("\n")) {
      if (!raw.trim()) continue;
      const sub = /^\s+/.test(raw) || /^\s*-/.test(raw);
      const line = raw.replace(/^\s*-?\s*/, "").trim();
      if (!line) continue;
      if (sub && added.length) {
        added[added.length - 1].items.push({ title: line, video_id: null, start_sec: null });
      } else {
        added.push({ title: line, video_id: null, start_sec: 0, items: [] });
      }
    }
    if (!added.length) return;
    setChapters([...chapters, ...added]);
    setPasteText("");
    setPasting(false);
    setMsg({ type: "info", text: `챕터 ${added.length}개를 넣었습니다. 영상은 각 줄에서 고르세요.` });
  };

  // 제목이 비었는데 내용은 들어 있는 줄. 그냥 저장하면 말없이 사라진다.
  const missingTitle = chapters.findIndex(
    (c) => !(c.title || "").trim()
      && (c.video_id || (c.items || []).some((it) => (it.title || "").trim() || it.video_id)));
  const missingItem = (() => {
    for (let i = 0; i < chapters.length; i += 1) {
      const j = (chapters[i].items || []).findIndex(
        (it) => !(it.title || "").trim() && it.video_id);
      if (j >= 0) return { i, j };
    }
    return null;
  })();

  const save = async () => {
    // 빈 제목 줄을 조용히 버리지 않는다. 예전에는 제목만 안 적어도 영상까지
    // 붙여 둔 챕터가 저장과 동시에 사라졌다 — 지웠다는 말도 없이.
    if (missingTitle >= 0) {
      setMsg(errMsg(`${missingTitle + 1}번째 챕터에 제목이 없습니다. 제목을 적어야 저장됩니다.`));
      return;
    }
    if (missingItem) {
      setMsg(errMsg(`${missingItem.i + 1}번째 챕터의 ${missingItem.j + 1}번째 강의에 제목이 없습니다.`));
      return;
    }
    setBusy(true);
    try {
      const saved = await feed.save({
        // 기본 영상은 더 쓰지 않는다 — 챕터마다 영상을 붙이는 쪽으로 정리했다.
        video_id: null,
        headline: cfg.headline || "",
        intro: cfg.intro || "",
        cover: cfg.cover || "",
        chapters: chapters
          .filter((c) => (c.title || "").trim())
          .map((c) => ({
            title: c.title.trim(),
            video_id: c.video_id ? Number(c.video_id) : null,
            start_sec: c.start_sec || 0,
            items: (c.items || []).filter((it) => (it.title || "").trim())
              .map((it) => ({
                title: it.title.trim(),
                video_id: it.video_id ? Number(it.video_id) : null,
                start_sec: it.start_sec,
              })),
          })),
      });
      setCfg(saved);
      setMsg(okMsg(`${feed.heading}을 저장했습니다.`));
    } catch (e) {
      setMsg(errMsg(e.message));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel" style={{ marginTop: 16 }}>
      <h3>{feed.heading}</h3>

      <div style={{ display: "grid", gap: 12 }}>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <div className="field" style={{ flex: "1 1 220px" }}>
            <label className="label">큰 제목</label>
            <input className="input" value={cfg.headline || ""} placeholder="직업계고설명회"
              onChange={(e) => setCfg({ ...cfg, headline: e.target.value })} />
          </div>
          <div className="field" style={{ flex: "2 1 300px" }}>
            <label className="label">소개 문구</label>
            <input className="input" value={cfg.intro || ""}
              placeholder="직업계고가 무엇인지 차근차근 짚어 드립니다."
              onChange={(e) => setCfg({ ...cfg, intro: e.target.value })} />
          </div>
        </div>

        <div className="field">
          <label className="label">대표 이미지 <span style={{ fontWeight: "normal", color: "var(--steel)" }}>(선택)</span></label>
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            {cfg.cover && (
              <img src={cfg.cover} alt="" style={{
                width: 160, height: 90, objectFit: "cover", borderRadius: 8,
                border: "1px solid var(--line)",
              }} />
            )}
            <label className="btn btn-ghost btn-sm"
              style={{ cursor: uploading ? "default" : "pointer", opacity: uploading ? .6 : 1 }}>
              {uploading ? "올리는 중…" : cfg.cover ? "다른 이미지로" : "이미지 올리기"}
              <input type="file" accept="image/png,image/jpeg,image/webp"
                disabled={uploading} style={{ display: "none" }}
                onChange={async (e) => {
                  const file = e.target.files?.[0];
                  e.target.value = "";
                  if (!file) return;
                  setUploading(true);
                  try {
                    const r = await feed.uploadCover(file);
                    setCfg({ ...cfg, cover: r.url });
                    setMsg({ type: "info",
                      text: `올렸습니다. 아래 [${feed.heading} 저장]까지 눌러야 반영됩니다.` });
                  } catch (err) { setMsg(errMsg(err.message)); }
                  finally { setUploading(false); }
                }} />
            </label>
            {cfg.cover && (
              <button className="btn btn-ghost btn-sm"
                onClick={() => setCfg({ ...cfg, cover: "" })}>이미지 지우기</button>
            )}
          </div>
          <p style={{ fontSize: 12, color: "var(--steel)", margin: "6px 0 0", lineHeight: 1.7 }}>
            맨 위 큰 화면의 배경입니다. 가로로 넓은 이미지(16:9)가 잘 맞습니다.
            {feed.wantPublic
              ? "안 올리면 첫 챕터 영상의 첫 장면을 씁니다."
              /* 파는 영상은 첫 장면조차 못 보여 준다 — 그러려면 안 산
                 사람에게도 영상 주소를 내줘야 한다. */
              : "안 올리면 배경 없이 제목만 보입니다."}
          </p>
        </div>

        <div className="field">
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <label className="label" style={{ margin: 0 }}>
              챕터 ({chapters.length})
              <span style={{ fontWeight: "normal", color: "var(--steel)", marginLeft: 6 }}>
                — 챕터마다 영상을 하나씩 고릅니다
              </span>
            </label>
            <span style={{ flex: 1 }} />
            <button className="btn btn-ghost btn-sm" onClick={() => setPasting(!pasting)}>
              여러 줄 붙여넣기
            </button>
            <button className="btn btn-ghost btn-sm" onClick={addChapter}>+ 챕터 추가</button>
          </div>

          {pasting && (
            <div style={{ marginTop: 10 }}>
              <textarea className="textarea" rows={8} value={pasteText}
                onChange={(e) => setPasteText(e.target.value)}
                placeholder={"직업계고의 정체성\n고졸취업의 진실 혹은 거짓\n  고졸취업은 무시당하지 않아요\n  고졸취업은 승진이 어렵지 않아요"} />
              <p style={{ fontSize: 12, color: "var(--steel)", margin: "6px 0 8px" }}>
                한 줄에 하나. 강의(하위 항목)는 앞에 공백이나 &ldquo;-&rdquo;를 붙이세요.
                넣은 뒤 각 줄에서 영상을 고르면 됩니다.
              </p>
              <button className="btn btn-sm" onClick={applyPaste}>목록에 넣기</button>
            </div>
          )}

          <div style={{ display: "grid", gap: 10, marginTop: 12 }}>
            {chapters.length === 0 && (
              <p style={{ fontSize: 13, color: "var(--steel)", margin: 0 }}>
                아직 챕터가 없습니다. <b>+ 챕터 추가</b> 또는 <b>여러 줄 붙여넣기</b>로 시작하세요.
              </p>
            )}
            {chapters.map((ch, i) => (
              <div key={i} style={{
                border: "1px solid var(--line)", borderRadius: "var(--radius-sm)",
                padding: 12,
              }}>
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <span style={{
                    fontSize: 12, color: "var(--steel)", minWidth: 74,
                  }}>{`CHAPTER ${i + 1}`}</span>
                  <input className="input"
                    style={{ flex: "2 1 200px",
                      borderColor: missingTitle === i ? "var(--color-attention)" : undefined }}
                    value={ch.title} placeholder="챕터 제목"
                    onChange={(e) => patchCh(i, { title: e.target.value })} />
                  <VideoSelect videos={videos} value={ch.video_id}
                    onChange={(v) => patchCh(i, { video_id: v })}
                    empty="영상 고르기" style={{ flex: "1 1 180px" }} />
                  <button className="btn btn-ghost btn-sm" onClick={() => move(i, -1)}
                    disabled={i === 0} title="위로">▲</button>
                  <button className="btn btn-ghost btn-sm" onClick={() => move(i, 1)}
                    disabled={i === chapters.length - 1} title="아래로">▼</button>
                  <button className="btn btn-ghost btn-sm" onClick={() => removeChapter(i)}>삭제</button>
                </div>

                <ChapterStatus ch={ch} videos={videos} setMsg={setMsg}
                  wantPublic={feed.wantPublic}
                  onFixed={() => api.adminVideos("longform").then(setVideos)} />

                <div style={{ display: "grid", gap: 6, margin: "10px 0 0", paddingLeft: 16 }}>
                  {(ch.items || []).map((it, j) => (
                    <div key={j} style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                      <span style={{ fontSize: 12, color: "var(--steel-light)" }}>▶</span>
                      <input className="input"
                        style={{ flex: "2 1 180px",
                          borderColor: missingItem && missingItem.i === i && missingItem.j === j
                            ? "var(--color-attention)" : undefined }}
                        value={it.title} placeholder="강의 제목"
                        onChange={(e) => patchItem(i, j, { title: e.target.value })} />
                      <VideoSelect videos={videos} value={it.video_id}
                        onChange={(v) => patchItem(i, j, { video_id: v })}
                        empty="챕터 영상 사용" style={{ flex: "1 1 170px" }} />
                      <TimeInput value={it.start_sec} placeholder="시작(선택)"
                        onChange={(v) => patchItem(i, j, { start_sec: v })} allowEmpty />
                      <button className="btn btn-ghost btn-sm"
                        onClick={() => removeItem(i, j)}>×</button>
                    </div>
                  ))}
                  <div>
                    <button className="btn btn-ghost btn-sm" onClick={() => addItem(i)}>
                      + 강의 추가
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div>
          <button className="btn btn-signal" onClick={save}
            disabled={busy || missingTitle >= 0 || !!missingItem}>
            {busy ? "저장 중…" : `${feed.heading} 저장`}
          </button>
          {(missingTitle >= 0 || missingItem) && (
            <span style={{ fontSize: 12.5, color: "var(--color-attention)", marginLeft: 10 }}>
              제목이 빈 줄이 있습니다. 채우거나 그 줄을 지워주세요.
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function VideoSelect({ videos, value, onChange, empty, style }) {
  return (
    <select className="select" style={{ width: "auto", maxWidth: 260, ...style }}
      value={value || ""} onChange={(e) => onChange(e.target.value || null)}>
      <option value="">{empty}</option>
      {videos.map((v) => (
        <option key={v.id} value={v.id}>
          {v.title}{v.is_public ? "" : " (비공개)"}
        </option>
      ))}
    </select>
  );
}

/** 시각 칸. 화면에는 3:24 로 보이고 밖으로는 초로 나간다. */
function TimeInput({ value, onChange, placeholder, allowEmpty = false }) {
  const [text, setText] = useState(
    value === null || value === undefined ? "" : fmtTime(value));
  const [bad, setBad] = useState(false);

  const commit = (t) => {
    if (!t.trim()) {
      setBad(false);
      onChange(allowEmpty ? null : 0);
      return;
    }
    const sec = parseTime(t);
    setBad(sec === null);
    if (sec !== null) onChange(sec);
  };

  return (
    <input className="input" style={{
      width: 110, borderColor: bad ? "var(--color-attention)" : undefined,
    }}
      value={text} placeholder={placeholder}
      onChange={(e) => { setText(e.target.value); commit(e.target.value); }} />
  );
}


/** 이 챕터가 학생 화면에서 실제로 재생되는지.
 *
 * "영상을 골랐는데 왜 안 나오지"를 관리자가 혼자 풀게 두지 않는다. 서버가
 * 재생을 막는 조건을 그대로 짚어 주고, 고칠 수 있는 것은 여기서 바로 고친다.
 *
 * 공개 여부는 어디에 쓰이느냐에 따라 정반대다. 설명회는 공개라야 재생되고,
 * 파는 영상은 **공개면 안 된다** — 공개로 두면 돈 안 낸 사람도 특강 목록에서
 * 그냥 본다. wantPublic 이 그 갈림길이다.
 */
function ChapterStatus({ ch, videos, setMsg, onFixed, wantPublic = true }) {
  if (!ch.video_id) {
    return (
      <p style={{ fontSize: 12.5, color: "var(--color-attention)", margin: "8px 0 0" }}>
        영상을 고르지 않으면 학생 화면에서 이 챕터가 재생되지 않습니다.
      </p>
    );
  }
  const v = videos.find((x) => String(x.id) === String(ch.video_id));
  if (!v) {
    return (
      <p style={{ fontSize: 12.5, color: "var(--color-attention)", margin: "8px 0 0" }}>
        고른 영상을 찾을 수 없습니다(삭제된 듯합니다). 다시 골라주세요.
      </p>
    );
  }
  if (!v.file_url) {
    return (
      <p style={{ fontSize: 12.5, color: "var(--color-attention)", margin: "8px 0 0" }}>
        &lsquo;{v.title}&rsquo; 에 영상 파일이 없습니다. 영상 관리에서 파일을 올려주세요.
      </p>
    );
  }
  const flip = async (next, done) => {
    try {
      await api.updateVideo(v.id, { is_public: next });
      setMsg(okMsg(done));
      onFixed();
    } catch (e) { setMsg(errMsg(e.message)); }
  };

  if (wantPublic && !v.is_public) {
    return (
      <p style={{ fontSize: 12.5, color: "var(--color-attention)", margin: "8px 0 0" }}>
        &lsquo;{v.title}&rsquo; 이 비공개라 학생 화면에서 재생되지 않습니다.
        <button className="btn btn-ghost btn-sm" style={{ marginLeft: 8 }}
          onClick={() => flip(true, "영상을 공개로 바꿨습니다.")}>영상 공개하기</button>
      </p>
    );
  }
  if (!wantPublic && v.is_public) {
    return (
      <p style={{ fontSize: 12.5, color: "var(--color-danger)", margin: "8px 0 0" }}>
        &lsquo;{v.title}&rsquo; 이 <b>공개</b>라 돈을 안 낸 사람도 특강에서 볼 수 있습니다.
        <button className="btn btn-ghost btn-sm" style={{ marginLeft: 8 }}
          onClick={() => flip(false, "영상을 비공개로 바꿨습니다.")}>비공개로 바꾸기</button>
      </p>
    );
  }
  return (
    <p style={{ fontSize: 12.5, color: "var(--color-success)", margin: "8px 0 0" }}>
      {wantPublic ? "학생 화면에서 재생됩니다."
                  : "결제한 계정에서만 재생됩니다."}
    </p>
  );
}
