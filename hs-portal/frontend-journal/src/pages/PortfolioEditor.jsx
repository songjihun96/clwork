import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api";

/** 포트폴리오 편집 화면.
 *  Canva 같은 전문 편집기를 만들지 않는다 — 컴퓨터를 잘 모르는 학생도 쓸 수
 *  있게, 페이지는 화살표로, 블록도 화살표로 순서를 바꾼다. 전문 용어
 *  (Flex/Grid/Section 등)는 화면 어디에도 쓰지 않는다.
 *
 *  처음에는 화면이 전부 펼쳐져 있어 한눈에 너무 많은 버튼·칸이 보인다는
 *  의견이 있었다. 그래서 "지금 만지는 것만 보이게" 바꿨다 — 블록은 평소엔
 *  내용만 보이고, 눌러야 고치는 칸과 버튼이 나온다. 페이지 관리(순서·복제·
 *  삭제)도 평소엔 숨어 있다가 "⋯"를 눌러야 나온다. 한 번에 한 가지씩만
 *  다루게 하려는 것이다. */

const BLOCK_TYPES = [
  ["heading", "제목", "Aa", "이 페이지의 소제목"],
  ["text", "글", "≡", "자세한 설명이나 이야기"],
  ["image", "사진", "▨", "사진이나 결과물 이미지"],
  ["quote", "인용구", "❝", "기억에 남는 말이나 소감"],
  ["tag", "태그", "#", "키워드 몇 개"],
  ["divider", "구분선", "—", "내용 사이 구분선"],
];

export default function PortfolioEditor() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [p, setP] = useState(null);
  const [error, setError] = useState("");
  const [pageId, setPageId] = useState(null);

  const load = () => api.portfolio(id).then((d) => {
    setP(d);
    setPageId((cur) => cur && d.pages.some((pg) => pg.id === cur) ? cur : d.pages[0]?.id);
  }).catch((e) => setError(e.message));
  useEffect(() => { load(); }, [id]);

  if (error) return <div className="wrap page"><div className="notice notice-error">{error}</div></div>;
  if (!p) return <div className="wrap page"><p>불러오는 중…</p></div>;

  const page = p.pages.find((pg) => pg.id === pageId);

  return (
    <div className="wrap page" style={{ maxWidth: 720 }}>
      <button className="btn btn-sm btn-ghost" onClick={() => navigate("/portfolio")}>← 내 포트폴리오</button>

      <PortfolioHeader p={p} onSaved={(next) => setP((cur) => ({ ...cur, ...next }))} />

      <PageTabs pages={p.pages} pageId={pageId} onPick={setPageId}
        onChanged={load} portfolioId={p.id} />

      <GettingStarted portfolioId={p.id}
        totalBlocks={p.pages.reduce((sum, pg) => sum + pg.blocks.length, 0)} />

      {page && <PageEditor key={page.id} page={page} onChanged={load} portfolioId={p.id} />}
    </div>
  );
}

/** 클릭해야 고칠 수 있게 하는 공통 부품. 평소엔 값만 보여주고,
 *  누르면 입력칸이 나온다 — 블록·페이지 제목·포트폴리오 제목이 전부 이걸 쓴다. */
function ClickToEdit({ value, placeholder, onSave, as = "div", inputStyle, displayStyle, multiline }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value || "");

  useEffect(() => { setDraft(value || ""); }, [value]);

  const commit = () => {
    setEditing(false);
    if (draft !== (value || "")) onSave(draft);
  };

  if (editing) {
    const props = {
      autoFocus: true, className: "input", value: draft,
      onChange: (e) => setDraft(e.target.value),
      onBlur: commit,
      onKeyDown: (e) => {
        if (e.key === "Enter" && !multiline) { e.preventDefault(); commit(); }
        if (e.key === "Escape") { setDraft(value || ""); setEditing(false); }
      },
      style: { width: "100%", fontFamily: "inherit", ...inputStyle },
    };
    return multiline ? <textarea rows={3} {...props} /> : <input {...props} />;
  }

  const Tag = as;
  const empty = !(value || "").trim();
  return (
    <Tag onClick={() => setEditing(true)} className="click-to-edit"
      style={{ cursor: "text", color: empty ? "var(--steel-light)" : "inherit",
               whiteSpace: multiline ? "pre-wrap" : "nowrap", ...displayStyle }}>
      {empty ? placeholder : value}
    </Tag>
  );
}

function PortfolioHeader({ p, onSaved }) {
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const flash = () => { setSaved(true); setTimeout(() => setSaved(false), 1500); };

  const save = async (patch) => {
    try {
      const next = await api.updatePortfolio(p.id, patch);
      onSaved(next);
      flash();
    } catch (e) {
      setErr(e.message);
    }
  };

  const toggleShare = async () => {
    setBusy(true); setErr("");
    try {
      if (p.visibility === "shared") {
        await api.unsharePortfolio(p.id);
        onSaved({ visibility: "private" });
      } else {
        const r = await api.sharePortfolio(p.id);
        onSaved({ visibility: "shared", share_token: r.share_token });
      }
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  const shareUrl = p.share_token ? `${window.location.origin}/portfolio-share/${p.share_token}` : "";
  const copyLink = () => navigator.clipboard?.writeText(shareUrl);

  return (
    <div style={{ marginTop: 14, marginBottom: 4 }}>
      <div className="row" style={{ alignItems: "flex-start", gap: 10 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <ClickToEdit value={p.title} placeholder="제목 없는 포트폴리오"
            onSave={(v) => save({ title: v })}
            as="h1" displayStyle={{ margin: 0, fontSize: 22, overflowWrap: "anywhere" }} />
          <ClickToEdit value={p.description} placeholder="소개를 눌러 적어보세요" multiline
            onSave={(v) => save({ description: v })}
            as="p" displayStyle={{ margin: "6px 0 0", fontSize: 13.5, color: "var(--steel)", lineHeight: 1.6 }} />
        </div>
        <div style={{ textAlign: "right", flexShrink: 0 }}>
          <button className="btn btn-sm btn-ghost" disabled={busy} onClick={toggleShare}>
            {p.visibility === "shared" ? "공유 끄기" : "공유하기"}
          </button>
          {saved && <div className="meta" style={{ marginTop: 4 }}>저장됨</div>}
        </div>
      </div>

      {p.visibility === "shared" && shareUrl && (
        <div className="panel" style={{ marginTop: 10, padding: "8px 12px", display: "flex",
                                         alignItems: "center", gap: 8 }}>
          <span className="meta" style={{ flex: 1, wordBreak: "break-all" }}>{shareUrl}</span>
          <button className="btn btn-sm btn-ghost" onClick={copyLink}>링크 복사</button>
        </div>
      )}
      {err && <div className="notice notice-error" style={{ marginTop: 8 }}>{err}</div>}
    </div>
  );
}

/** "블록만 눌러서 고치면 된다"는 게 처음 보면 잘 안 보인다는 의견이 있어
 *  추가한 안내 상자. 내용이 어느 정도 채워지면(블록 5개 이상) 더는 필요
 *  없다고 보고 자동으로 숨긴다. 닫기를 누르면 이 포트폴리오에서는 다시
 *  뜨지 않는다(브라우저에 기억). */
function GettingStarted({ portfolioId, totalBlocks }) {
  const storageKey = `portfolio-guide-dismissed-${portfolioId}`;
  const [dismissed, setDismissed] = useState(() => {
    try { return localStorage.getItem(storageKey) === "1"; } catch { return false; }
  });

  if (dismissed || totalBlocks >= 5) return null;

  const hide = () => {
    setDismissed(true);
    try { localStorage.setItem(storageKey, "1"); } catch { /* ignore */ }
  };

  return (
    <div className="panel" style={{ margin: "10px 0 4px", padding: "10px 14px", background: "var(--paper)" }}>
      <div className="row" style={{ alignItems: "center", justifyContent: "space-between" }}>
        <strong style={{ fontSize: 13.5 }}>처음이신가요? 이 순서로 해보세요</strong>
        <button className="btn btn-sm btn-ghost" onClick={hide}>닫기</button>
      </div>
      <ol style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: 13, color: "var(--steel)", lineHeight: 1.9 }}>
        <li>위에서 채울 페이지를 고르세요.</li>
        <li>아래 글이나 사진을 <b>눌러서</b> 내용을 채우세요 — 이미 써 있는 것도 눌러서 고칠 수 있어요.</li>
        <li>더 넣고 싶은 게 있으면 맨 아래 <b>+ 내용 추가</b>로 더하세요.</li>
        <li>다 됐으면 위쪽 <b>공유하기</b>를 눌러 링크를 만드세요.</li>
      </ol>
    </div>
  );
}

function PageTabs({ pages, pageId, onPick, onChanged, portfolioId }) {
  const [busy, setBusy] = useState(false);

  const addPage = async () => {
    setBusy(true);
    try {
      const pg = await api.createPage(portfolioId, "새 페이지");
      await onChanged();
      onPick(pg.id);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="row" style={{ gap: 6, margin: "18px 0 4px", flexWrap: "wrap", alignItems: "center" }}>
      {pages.map((pg, i) => (
        <button key={pg.id} className={`btn btn-sm ${pg.id === pageId ? "" : "btn-ghost"}`}
          onClick={() => onPick(pg.id)}>
          {i + 1}. {pg.title || "제목 없음"}
        </button>
      ))}
      <button className="btn btn-sm btn-ghost" onClick={addPage} disabled={busy}>+ 페이지 추가</button>
    </div>
  );
}

function PageEditor({ page, onChanged, portfolioId }) {
  const [showManage, setShowManage] = useState(false);
  const [busy, setBusy] = useState(false);
  const [pickingType, setPickingType] = useState(false);
  const [justAddedId, setJustAddedId] = useState(null);

  const saveTitle = async (v) => { await api.updatePage(page.id, v || "제목 없음"); onChanged(); };
  const movePage = async (direction) => { await api.movePage(page.id, direction); onChanged(); };
  const dupPage = async () => { await api.duplicatePage(page.id); onChanged(); };
  const delPage = async () => {
    if (!window.confirm("이 페이지를 지울까요? 안의 내용도 함께 지워집니다.")) return;
    await api.deletePage(page.id);
    onChanged();
  };

  const addBlock = async (type) => {
    setBusy(true); setPickingType(false);
    try {
      const b = await api.createBlock(page.id, type, {});
      setJustAddedId(b.id);
      onChanged();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <div className="row" style={{ alignItems: "center", gap: 8, margin: "10px 0 14px" }}>
        <ClickToEdit value={page.title} placeholder="페이지 제목"
          onSave={saveTitle} as="h3"
          displayStyle={{ margin: 0, fontSize: 16 }} inputStyle={{ maxWidth: 280, fontWeight: 700 }} />
        <button className="btn btn-sm btn-ghost" onClick={() => setShowManage((v) => !v)}>⋯</button>
      </div>

      {showManage && (
        <div className="row" style={{ gap: 6, marginBottom: 14, flexWrap: "wrap" }}>
          <button className="btn btn-sm btn-ghost" onClick={() => movePage("up")}>페이지 위로</button>
          <button className="btn btn-sm btn-ghost" onClick={() => movePage("down")}>페이지 아래로</button>
          <button className="btn btn-sm btn-ghost" onClick={dupPage}>페이지 복제</button>
          <button className="btn btn-sm btn-ghost" onClick={delPage}>페이지 삭제</button>
        </div>
      )}

      <div style={{ display: "grid", gap: 4 }}>
        {page.blocks.length === 0 && (
          <p className="meta" style={{ marginBottom: 8 }}>
            아직 내용이 없습니다. 아래 '+ 내용 추가'를 눌러 시작해보세요.
          </p>
        )}
        {page.blocks.map((b, i) => (
          <BlockEditor key={b.id} block={b} onChanged={onChanged} portfolioId={portfolioId}
            startEditing={b.id === justAddedId}
            isFirst={i === 0} isLast={i === page.blocks.length - 1} />
        ))}
      </div>

      <div style={{ marginTop: 10 }}>
        {!pickingType ? (
          <button className="btn btn-sm" onClick={() => setPickingType(true)} disabled={busy}>
            + 내용 추가
          </button>
        ) : (
          <div className="panel" style={{ display: "inline-block", padding: 8 }}>
            <div className="row" style={{ gap: 6, flexWrap: "wrap", alignItems: "stretch" }}>
              {BLOCK_TYPES.map(([type, label, icon, desc]) => (
                <button key={type} className="btn btn-sm btn-ghost" disabled={busy}
                  onClick={() => addBlock(type)}
                  style={{ display: "flex", flexDirection: "column", alignItems: "flex-start",
                           gap: 2, height: "auto", padding: "6px 10px", minWidth: 96 }}>
                  <span>{icon} {label}</span>
                  <span style={{ fontSize: 11, fontWeight: 400, color: "var(--steel-light)" }}>{desc}</span>
                </button>
              ))}
              <button className="btn btn-sm btn-ghost" onClick={() => setPickingType(false)}>취소</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/** 블록 하나. 평소엔 내용만 보인다 — 누르면 고치는 칸과 버튼이 나오고,
 *  칸 밖을 누르면(blur) 다시 조용해진다. 방금 추가한 블록은 바로
 *  고칠 수 있게 처음부터 열려 있다. */
function BlockEditor({ block, onChanged, portfolioId, startEditing, isFirst, isLast }) {
  const [editing, setEditing] = useState(!!startEditing);
  const [text, setText] = useState(block.content.text || "");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [toolsOpen, setToolsOpen] = useState(false);

  useEffect(() => { setText(block.content.text || ""); }, [block.content.text]);

  const save = async (newText = text) => {
    setBusy(true);
    try {
      await api.updateBlock(block.id, block.block_type, { ...block.content, text: newText });
      onChanged();
    } catch (e) {
      setMsg(e.message);
    } finally {
      setBusy(false);
    }
  };

  const closeEdit = () => {
    setEditing(false);
    setToolsOpen(false);
    if (text !== (block.content.text || "")) save();
  };

  const move = async (direction) => { await api.moveBlock(block.id, direction); onChanged(); };
  const dup = async () => { await api.duplicateBlock(block.id); onChanged(); };
  const del = async () => {
    if (!window.confirm("이 내용을 지울까요?")) return;
    await api.deleteBlock(block.id);
    onChanged();
  };

  const proofread = async (action) => {
    setBusy(true); setMsg("");
    try {
      const job = await api.requestProofread(text, action);
      const result = await api.waitAiJob(job.job_id);
      setText(result.result);
      await save(result.result);
    } catch (e) {
      setMsg(e.message);
    } finally {
      setBusy(false);
    }
  };

  const manageRow = (
    <div className="row" style={{ gap: 4, marginTop: 8 }}>
      <button className="btn btn-sm btn-ghost" onClick={() => move("up")} disabled={isFirst}>↑ 위로</button>
      <button className="btn btn-sm btn-ghost" onClick={() => move("down")} disabled={isLast}>↓ 아래로</button>
      <button className="btn btn-sm btn-ghost" onClick={dup}>복제</button>
      <button className="btn btn-sm btn-ghost" onClick={del}>삭제</button>
      <div className="spacer" />
      <button className="btn btn-sm btn-primary" onClick={closeEdit}>완료</button>
    </div>
  );

  if (block.block_type === "divider") {
    return editing ? (
      <div className="panel" style={{ padding: 10 }}>
        <hr style={{ border: "none", borderTop: "1px solid var(--line)", margin: 0 }} />
        {manageRow}
      </div>
    ) : (
      <div onClick={() => setEditing(true)} style={{ padding: "10px 4px", cursor: "pointer" }}>
        <hr style={{ border: "none", borderTop: "1px solid var(--line)", margin: 0 }} />
      </div>
    );
  }

  if (block.block_type === "image") {
    return (
      <ImageBlock block={block} onChanged={onChanged} portfolioId={portfolioId}
        editing={editing} setEditing={setEditing} manageRow={manageRow} />
    );
  }

  const isHeading = block.block_type === "heading";
  const isQuote = block.block_type === "quote";
  const isTag = block.block_type === "tag";
  const canProofread = !isHeading && !isTag;

  if (!editing) {
    const empty = !text.trim();
    return (
      <div onClick={() => setEditing(true)} className="block-preview"
        style={{ padding: "6px 4px", cursor: "text", borderRadius: 6 }}>
        {isHeading ? (
          <h3 style={{ margin: 0, color: empty ? "var(--steel-light)" : "inherit" }}>
            {empty ? "제목을 눌러 입력하세요" : text}
          </h3>
        ) : isQuote ? (
          <blockquote style={{ borderLeft: "3px solid var(--signal)", margin: 0, paddingLeft: 12,
                               color: empty ? "var(--steel-light)" : "var(--steel)", fontStyle: "italic" }}>
            {empty ? "인용구를 눌러 입력하세요" : text}
          </blockquote>
        ) : isTag ? (
          <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
            {empty ? (
              <span className="meta">태그를 눌러 입력하세요 (쉼표로 구분)</span>
            ) : (
              text.split(",").map((t, i) => t.trim() && <span key={i} className="badge">{t.trim()}</span>)
            )}
          </div>
        ) : (
          <p style={{ margin: 0, whiteSpace: "pre-wrap", lineHeight: 1.75,
                     color: empty ? "var(--steel-light)" : "inherit" }}>
            {empty ? "내용을 눌러 입력하세요" : text}
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="panel">
      {isHeading ? (
        <input autoFocus className="input" value={text} style={{ fontWeight: 700, fontSize: 17 }}
          onChange={(e) => setText(e.target.value)} />
      ) : (
        <textarea autoFocus className="input" rows={isTag ? 1 : 4} value={text}
          placeholder={isTag ? "예: 협업, 문제 해결, 3D 프린팅" : undefined}
          onChange={(e) => setText(e.target.value)}
          style={{ resize: "vertical", fontFamily: "inherit", width: "100%" }} />
      )}

      {canProofread && (
        <div style={{ marginTop: 8 }}>
          {!toolsOpen ? (
            <button className="btn btn-sm btn-ghost" onClick={() => setToolsOpen(true)}>AI로 다듬기</button>
          ) : (
            <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
              <button className="btn btn-sm btn-ghost" disabled={busy} onClick={() => proofread("TEXT_PROOFREAD")}>
                맞춤법 고치기
              </button>
              <button className="btn btn-sm btn-ghost" disabled={busy} onClick={() => proofread("TEXT_EDIT")}>
                문장 다듬기
              </button>
              <button className="btn btn-sm btn-ghost" disabled={busy} onClick={() => proofread("TEXT_SHORTEN")}>
                짧게 줄이기
              </button>
              <button className="btn btn-sm btn-ghost" disabled={busy} onClick={() => proofread("TEXT_EXPAND")}>
                조금 더 자세히
              </button>
            </div>
          )}
        </div>
      )}
      {msg && <p className="meta" style={{ marginTop: 6 }}>{msg}</p>}
      {manageRow}
    </div>
  );
}

function ImageBlock({ block, onChanged, portfolioId, editing, setEditing, manageRow }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [blobUrl, setBlobUrl] = useState(null);
  const imageId = block.content.image_id;
  const url = block.content.url;

  // <img src>는 로그인 토큰을 못 붙이므로, 직접 받아 온 뒤 blob 주소로 보여준다.
  useEffect(() => {
    if (!url) { setBlobUrl(null); return; }
    let revoke = null;
    api.loadPortfolioImageUrl(url).then((b) => { revoke = b; setBlobUrl(b); }).catch(() => {});
    return () => { if (revoke) URL.revokeObjectURL(revoke); };
  }, [url]);

  const onFile = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true); setMsg("");
    try {
      const img = await api.uploadPortfolioImage(portfolioId, file, { pageId: block.page_id });
      await api.updateBlock(block.id, "image", { image_id: img.id, url: img.url });
      onChanged();
    } catch (err) {
      setMsg(err.message);
    } finally {
      setBusy(false);
    }
  };

  const genCaption = async () => {
    if (!imageId) return;
    setBusy(true); setMsg("");
    try {
      const job = await api.requestImageCaption(imageId);
      const result = await api.waitAiJob(job.job_id);
      await api.updatePortfolioImage(imageId, { caption: result.caption });
      setMsg("사진 설명을 만들었습니다: " + result.caption);
    } catch (err) {
      setMsg(err.message);
    } finally {
      setBusy(false);
    }
  };

  const preview = url ? (
    blobUrl
      ? <img src={blobUrl} alt="" style={{ maxWidth: "100%", borderRadius: 8, display: "block" }} />
      : <p className="meta">사진 불러오는 중…</p>
  ) : (
    <p className="meta">아직 사진이 없습니다. 눌러서 올려보세요.</p>
  );

  if (!editing) {
    return (
      <div onClick={() => setEditing(true)} style={{ padding: "6px 4px", cursor: "pointer" }}>
        {preview}
      </div>
    );
  }

  return (
    <div className="panel">
      {preview}
      <div className="row" style={{ gap: 8, marginTop: 8, alignItems: "center" }}>
        <input type="file" accept="image/*" onChange={onFile} disabled={busy} />
        {url && (
          <button className="btn btn-sm btn-ghost" disabled={busy} onClick={genCaption}>
            사진 설명 생성
          </button>
        )}
      </div>
      {msg && <p className="meta" style={{ marginTop: 6 }}>{msg}</p>}
      {manageRow}
    </div>
  );
}
