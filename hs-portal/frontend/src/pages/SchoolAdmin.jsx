import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import {
  Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api, PLAN_LABEL } from "../api";
import { ddayClass, ddayText } from "../dday";
import { errMsg, okMsg } from "../toast";

const STATUS_LABEL = { pending: "승인 대기", approved: "승인됨", rejected: "반려됨" };

const DELIVERY_LABEL = {
  pending: "미발송",
  sent: "메일 발송 완료",
  failed: "메일 발송 실패",
  not_configured: "메일 서버 미설정",
};


/** 저장이 끝났다는 걸 확실히 알리는 팝업. 화면 아래쪽 안내 문구만으로는
 *  긴 입력 폼에서 스크롤 밖에 있어 저장됐는지 모르고 지나치기 쉽다. */
function SavedModal({ text, onClose }) {
  return createPortal(
    <div className="notice-modal-backdrop" onClick={onClose}>
      <div className="notice-modal" onClick={(e) => e.stopPropagation()}>
        <div className="notice-modal-body">
          <h2 style={{ fontSize: 18, margin: "4px 0 6px" }}>저장이 완료되었습니다</h2>
          <p style={{ fontSize: 13.5, color: "var(--steel)", margin: 0 }}>{text}</p>
        </div>
        <div className="notice-modal-foot">
          <span />
          <button className="btn btn-signal btn-sm" onClick={onClose}>확인</button>
        </div>
      </div>
    </div>,
    document.body
  );
}

function AttachmentPicker({ id, attachments, setAttachments }) {
  const files = attachments[id] || [];
  const onPick = (e) => {
    const picked = Array.from(e.target.files || []);
    const merged = [...files, ...picked].slice(0, 5);
    setAttachments({ ...attachments, [id]: merged });
    e.target.value = ""; // 같은 파일 다시 선택 가능하게
  };
  const removeAt = (i) => {
    const next = files.filter((_, idx) => idx !== i);
    setAttachments({ ...attachments, [id]: next });
  };
  const totalMB = (files.reduce((n, f) => n + f.size, 0) / (1024 * 1024)).toFixed(1);

  return (
    <div>
      <label className="btn btn-ghost btn-sm" style={{ cursor: "pointer", display: "inline-block" }}>
        📎 파일 첨부
        <input type="file" multiple onChange={onPick} style={{ display: "none" }} />
      </label>
      {files.length > 0 && (
        <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 4 }}>
          {files.map((f, i) => (
            <div key={i} style={{ fontSize: 12.5, color: "var(--steel)", display: "flex", gap: 8, alignItems: "center" }}>
              <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {f.name} ({(f.size / 1024).toFixed(0)}KB)
              </span>
              <button className="btn btn-ghost btn-sm" style={{ padding: "1px 7px", fontSize: 11 }} onClick={() => removeAt(i)}>×</button>
            </div>
          ))}
          <span className="label" style={{ color: totalMB > 10 ? "var(--alert)" : "var(--steel-light)" }}>
            총 {totalMB}MB · 최대 5개, 합계 10MB
          </span>
        </div>
      )}
    </div>
  );
}

function InquiriesTab({ inquiries, profile, reload }) {
  const [drafts, setDrafts] = useState({});
  // 알림 주소는 문의를 다루는 이 화면에서 바로 손보게 둔다. 학교 정보 탭에
  // 두면 '검색 결과에 보이는 정보'처럼 공개되는 값으로 오해하기 쉽다.
  const [notifyEmail, setNotifyEmail] = useState(profile.inquiry_notify_email || "");
  const [notifyBusy, setNotifyBusy] = useState(false);
  const [notifySaved, setNotifySaved] = useState(false);
  const [attachments, setAttachments] = useState({});
  const [busyId, setBusyId] = useState(null);
  const [msg, setMsg] = useState(null);

  const send = async (id) => {
    const answer = (drafts[id] || "").trim();
    if (!answer) return setMsg(errMsg("답변 내용을 입력해주세요."));
    setBusyId(id);
    setMsg(null);
    try {
      const res = await api.answerInquiry(id, answer, attachments[id] || []);
      if (res.delivery_status === "sent") {
        setMsg(okMsg("답변을 저장하고 문의자 이메일로 발송했습니다."));
      } else {
        setMsg({
          type: "info",
          text: `답변은 저장됐지만 이메일이 발송되지 않았습니다 (${DELIVERY_LABEL[res.delivery_status] || res.delivery_status}). ${res.delivery_error || ""}`,
        });
      }
      setAttachments({ ...attachments, [id]: [] });
      reload();
    } catch (e) {
      setMsg(errMsg(e.message));
    } finally {
      setBusyId(null);
    }
  };

  const saveNotify = async () => {
    setNotifyBusy(true);
    setMsg(null);
    try {
      await api.saveProfile({ inquiry_notify_email: notifyEmail.trim() });
      setNotifySaved(true);
      reload();
    } catch (e) {
      setMsg(errMsg(e.message));
    } finally {
      setNotifyBusy(false);
    }
  };

  const remove = async (id) => {
    if (!window.confirm("이 문의를 삭제할까요? 개인정보(이메일 등)가 함께 파기됩니다.")) return;
    await api.deleteInquiry(id);
    reload();
  };

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div className="notice notice-info">
        방문자가 남긴 문의입니다. 답변을 저장하면 문의자가 입력한 이메일로 답변이 자동 발송됩니다.
        개인정보 보호를 위해 처리가 끝난 문의는 삭제해 주세요. (접수 후 1년이 지난 문의는 자동 파기됩니다.)
      </div>

      <div className="panel">
        <h3>새 문의 알림 받기</h3>
        <div className="field">
          <label className="label">알림 받을 이메일 (선택)</label>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <input className="input" type="email" value={notifyEmail}
              style={{ flex: 1, minWidth: 220 }}
              placeholder="예: admission@school.kr"
              onChange={(e) => setNotifyEmail(e.target.value)} />
            <button className="btn btn-signal" onClick={saveNotify} disabled={notifyBusy}
              style={{ flexShrink: 0 }}>
              {notifyBusy ? "저장 중…" : "저장"}
            </button>
          </div>
          <p style={{ fontSize: 12.5, color: "var(--steel)", margin: "8px 0 0", lineHeight: 1.6 }}>
            학생이 문의를 남기면 이 주소로 알림 메일이 갑니다.
            <b> 로그인 계정 메일과 달라도 됩니다</b> — 대표 계정으로 로그인하고
            알림은 담당 선생님이 받아도 됩니다.<br />
            이 주소는 학교 페이지에 공개되지 않습니다. 비워두고 저장하면 알림을 보내지 않습니다.<br />
            알림 메일에는 문의 내용만 담기고 문의자의 연락처는 담기지 않습니다. 답변은 아래에서 해주세요.
          </p>
        </div>
      </div>

      {msg && <div className={`notice notice-${msg.type}`}>{msg.text}</div>}
      {notifySaved && (
        <SavedModal
          text={notifyEmail.trim()
            ? `새 문의가 들어오면 ${notifyEmail.trim()} 으로 알려드립니다.`
            : "알림을 받지 않도록 설정했습니다."}
          onClose={() => setNotifySaved(false)}
        />
      )}

      {inquiries.length === 0 ? (
        <div className="panel"><p style={{ margin: 0, color: "var(--steel)", fontSize: 13.5 }}>아직 들어온 문의가 없습니다.</p></div>
      ) : (
        inquiries.map((q) => (
          <div className="panel" key={q.id}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
              <span className={`badge ${q.status === "answered" ? "badge-dorm" : ""}`}>
                {q.status === "answered" ? "답변 완료" : "미답변"}
              </span>
              {q.status === "answered" && (
                <span className="label" style={{ color: q.delivery_status === "sent" ? "var(--verify)" : "var(--alert)" }}>
                  {DELIVERY_LABEL[q.delivery_status] || q.delivery_status}
                </span>
              )}
              <span className="label" style={{ marginLeft: "auto" }}>{q.created_at.slice(0, 16).replace("T", " ")}</span>
              <button className="btn btn-ghost btn-sm" style={{ padding: "3px 8px", fontSize: 11 }} onClick={() => remove(q.id)}>
                삭제
              </button>
            </div>

            <div style={{ fontSize: 13, color: "var(--steel)", marginBottom: 6 }}>
              {q.asker_name || "이름 미기재"} · {q.contact_email}
              {q.contact_phone ? ` · ${q.contact_phone}` : ""}
            </div>
            <p className="prose" style={{ fontSize: 14, margin: "0 0 12px" }}>{q.question}</p>

            {q.status === "answered" ? (
              <div style={{ borderTop: "1px solid var(--line)", paddingTop: 10 }}>
                <span className="label">보낸 답변</span>
                <p className="prose" style={{ fontSize: 13.5, marginTop: 4 }}>{q.answer}</p>
                {q.delivery_status !== "sent" && (
                  <div style={{ display: "grid", gap: 8, marginTop: 8 }}>
                    <textarea className="textarea" placeholder="답변을 수정해 다시 발송할 수 있습니다."
                      value={drafts[q.id] ?? q.answer} onChange={(e) => setDrafts({ ...drafts, [q.id]: e.target.value })} />
                    <AttachmentPicker id={q.id} attachments={attachments} setAttachments={setAttachments} />
                    <div>
                      <button className="btn btn-sm" onClick={() => send(q.id)} disabled={busyId === q.id}>
                        {busyId === q.id ? "발송 중…" : "다시 발송"}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div style={{ display: "grid", gap: 8, borderTop: "1px solid var(--line)", paddingTop: 10 }}>
                <textarea className="textarea" placeholder="답변 내용을 입력하세요. 저장하면 문의자 이메일로 발송됩니다."
                  value={drafts[q.id] || ""} onChange={(e) => setDrafts({ ...drafts, [q.id]: e.target.value })} />
                <AttachmentPicker id={q.id} attachments={attachments} setAttachments={setAttachments} />
                <div>
                  <button className="btn btn-signal btn-sm" onClick={() => send(q.id)} disabled={busyId === q.id}>
                    {busyId === q.id ? "발송 중…" : "답변 저장 및 발송"}
                  </button>
                </div>
              </div>
            )}
          </div>
        ))
      )}
    </div>
  );
}

function ProfileTab({ profile, reload }) {
  const [form, setForm] = useState(profile);
  const [msg, setMsg] = useState(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  // 서버에는 줄바꿈으로 이어 붙인 한 칸으로 저장되지만, 화면에서는
  // 칸 3개로 나눠 받는다. 어느 자리를 지우고 넣는지 눈에 보여야 해서다.
  const [videos, setVideos] = useState(() => {
    const lines = (profile.youtube_urls || "").split("\n").map((x) => x.trim());
    return [0, 1, 2, 3].map((i) => lines[i] || "");
  });

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const setVideo = (i) => (e) =>
    setVideos(videos.map((v, idx) => (idx === i ? e.target.value : v)));

  const pickHeroImage = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // 같은 파일 다시 선택 가능하게
    if (!file) return;
    setUploading(true);
    setMsg(null);
    try {
      const { url } = await api.uploadHeroImage(file);
      setForm({ ...form, hero_image: url });
    } catch (err) {
      setMsg(errMsg(err.message));
    } finally {
      setUploading(false);
    }
  };

  const save = async () => {
    setBusy(true);
    setMsg(null);
    try {
      await api.saveProfile({
        slogan: form.slogan,
        intro: form.intro,
        departments: form.departments,
        facilities: form.facilities,
        admission_info: form.admission_info,
        youtube_urls: videos.map((v) => v.trim()).filter(Boolean).join("\n"),
        employment_rate: form.employment_rate === "" ? null : Number(form.employment_rate),
        student_count: form.student_count === "" ? null : Number(form.student_count),
        established_year: form.established_year === "" ? null : Number(form.established_year),
        hero_image: form.hero_image,
        phone: form.phone,
        website: form.website,
        dormitory: form.dormitory === "" ? null : form.dormitory === "true",
      });
      setMsg(null);
      setSaved(true);
      reload();
    } catch (e) {
      setMsg(errMsg(e.message));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div className="notice notice-info">
        학교 이름·주소·계열은 나이스에서 받아온 값이라 이곳에서 바꿀 수 없습니다.
        틀린 부분이 있으면 포털 관리자에게 알려주세요.
      </div>

      <div className="panel">
        <h3>검색 결과에 보이는 정보</h3>
        <div style={{ display: "grid", gap: 14 }}>
          <div className="field">
            <label className="label">한 줄 소개</label>
            <input className="input" value={form.slogan || ""} onChange={set("slogan")}
              placeholder="예: 반도체 장비 인재를 키우는 학교" maxLength={120} />
          </div>
          <div className="field">
            <label className="label">대표 이미지</label>
            <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
              {form.hero_image && (
                <div style={{
                  width: 96, height: 96, borderRadius: "var(--radius)", backgroundColor: "var(--raised)",
                  backgroundImage: `url(${form.hero_image})`, backgroundSize: "cover", backgroundPosition: "center",
                  border: "1px solid var(--line)", flexShrink: 0,
                }} />
              )}
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <label className="btn btn-ghost btn-sm" style={{ cursor: "pointer", display: "inline-block" }}>
                  {uploading ? "올리는 중…" : form.hero_image ? "이미지 바꾸기" : "이미지 올리기"}
                  <input type="file" accept="image/png,image/jpeg,image/gif,image/webp" onChange={pickHeroImage}
                    disabled={uploading} style={{ display: "none" }} />
                </label>
                {form.hero_image && (
                  <button className="btn btn-ghost btn-sm" onClick={() => setForm({ ...form, hero_image: "" })}>
                    삭제
                  </button>
                )}
              </div>
            </div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
            <div className="field">
              <label className="label">기숙사 운영</label>
              <select className="select" value={form.dormitory === null ? "" : String(form.dormitory)}
                onChange={(e) => setForm({ ...form, dormitory: e.target.value })}>
                <option value="">미확인</option>
                <option value="true">운영함</option>
                <option value="false">운영하지 않음</option>
              </select>
            </div>
            <div className="field">
              <label className="label">전화번호</label>
              <input className="input" value={form.phone || ""} onChange={set("phone")} />
            </div>
            <div className="field">
              <label className="label">홈페이지</label>
              <input className="input" value={form.website || ""} onChange={set("website")} />
            </div>
          </div>
        </div>
      </div>

      <div className="panel">
        <h3>상세 페이지에만 보이는 정보</h3>
        <div style={{ display: "grid", gap: 14 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
            <div className="field">
              <label className="label">학생 수</label>
              <input className="input" type="number" value={form.student_count ?? ""} onChange={set("student_count")} />
            </div>
            <div className="field">
              <label className="label">취업률 (%)</label>
              <input className="input" type="number" step="0.1" value={form.employment_rate ?? ""} onChange={set("employment_rate")} />
            </div>
            <div className="field">
              <label className="label">개교 연도</label>
              <input className="input" type="number" value={form.established_year ?? ""} onChange={set("established_year")} />
            </div>
          </div>
          <div className="field">
            <label className="label">개설 학과 (한 줄에 하나씩)</label>
            <textarea className="textarea" value={form.departments || ""} onChange={set("departments")}
              placeholder={"스마트전기과\n반도체장비과"} />
          </div>
          <div className="field">
            <label className="label">학교 소개</label>
            <textarea className="textarea" value={form.intro || ""} onChange={set("intro")} />
          </div>
          <div className="field">
            <label className="label">실습 시설</label>
            <textarea className="textarea" value={form.facilities || ""} onChange={set("facilities")} />
          </div>
          <div className="field">
            <label className="label">학교 상세 안내</label>
            <textarea className="textarea" value={form.admission_info || ""} onChange={set("admission_info")} />
          </div>
          <div className="field">
            <label className="label">학교 소개 영상 (유튜브, 최대 4개)</label>
            <p style={{ fontSize: 12, color: "var(--steel)", margin: "0 0 8px" }}>
              상세 페이지의 학교 설명회 아래에 붙습니다. 학생이 재생을 누르면 그 자리에서 바로 재생됩니다.
            </p>
            <div style={{ display: "grid", gap: 8 }}>
              {videos.map((v, i) => (
                <input key={i} className="input" type="url" value={v} onChange={setVideo(i)}
                  placeholder={i === 0 ? "https://www.youtube.com/watch?v=..." : "비워두어도 됩니다"} />
              ))}
            </div>
          </div>
        </div>
      </div>

      {msg && <div className={`notice notice-${msg.type}`}>{msg.text}</div>}
      {saved && (
        <SavedModal
          text="검색 결과와 학교 상세 페이지에 바로 반영됩니다."
          onClose={() => setSaved(false)}
        />
      )}
      <div>
        <button className="btn btn-signal" onClick={save} disabled={busy}>
          {busy ? "저장 중…" : "변경사항 저장"}
        </button>
      </div>
    </div>
  );
}

function StatsTab({ stats }) {
  const data = stats.daily_views.map((d) => ({ day: d.day.slice(5), 조회수: d.count }));
  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div className="stat-grid">
        <div className="stat">
          <span className="label">누적 조회수</span>
          <div className="stat-value">{stats.view_count.toLocaleString()}</div>
        </div>
        <div className="stat">
          <span className="label">즐겨찾기</span>
          <div className="stat-value">{stats.favorite_count.toLocaleString()}<small> 명</small></div>
        </div>
        <div className="stat">
          <span className="label">같은 지역·계열 내 노출 순서</span>
          <div className="stat-value">{stats.search_rank_hint}<small> 번째</small></div>
        </div>
      </div>

      <div className="panel">
        <h3>최근 14일 조회수</h3>
        <div style={{ height: 240 }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 5, right: 5, bottom: 5, left: -20 }}>
              <CartesianGrid strokeDasharray="2 4" stroke="#dbe1e6" vertical={false} />
              <XAxis dataKey="day" tick={{ fontSize: 11, fill: "#8a99a6" }} tickLine={false} axisLine={{ stroke: "#dbe1e6" }} />
              <YAxis tick={{ fontSize: 11, fill: "#8a99a6" }} tickLine={false} axisLine={false} allowDecimals={false} />
              <Tooltip
                contentStyle={{ border: "1px solid #dbe1e6", borderRadius: 4, fontSize: 13 }}
                cursor={{ fill: "rgba(255,197,61,0.12)" }}
              />
              <Bar dataKey="조회수" fill="#ff7a59" radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}

const EVENT_KIND_LABEL = { briefing: "학교 설명회", admission: "참가 행사" };

// 한 번에 일정 하나씩만 등록한다. 예전에는 날짜를 여러 개 얹어 한꺼번에
// 만들 수 있었는데, 화면만 복잡해지고 회차마다 장소·시간이 달라 결국
// 하나씩 손보게 되는 경우가 많아 걷어냈다.
const EMPTY_FORM = {
  kind: "briefing", title: "",
  start_date: "", end_date: "", start_time: "", end_time: "",
  location: "", registration_url: "", description: "",
};

function EventsTab({ plan, events, reload }) {
  const [form, setForm] = useState(EMPTY_FORM);
  const [editingId, setEditingId] = useState(null);
  const [error, setError] = useState("");

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const startEdit = (e) => {
    setEditingId(e.id);
    setError("");
    setForm({
      kind: e.kind || "briefing", title: e.title,
      start_date: e.start_date, end_date: e.end_date || "",
      start_time: e.start_time || "", end_time: e.end_time || "",
      location: e.location || "", registration_url: e.registration_url || "",
      description: e.description || "",
    });
  };

  const cancelEdit = () => {
    setEditingId(null);
    setForm(EMPTY_FORM);
    setError("");
  };

  const canSubmit = form.title.trim() && form.start_date;

  const submit = async () => {
    setError("");
    const body = {
      kind: form.kind, title: form.title.trim(),
      start_date: form.start_date, end_date: form.end_date || null,
      start_time: form.start_time || null, end_time: form.end_time || null,
      location: form.location, registration_url: form.registration_url,
      description: form.description,
    };
    try {
      if (editingId) await api.updateEvent(editingId, body);
      else await api.addEvent(body);
      cancelEdit();
      reload();
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <div style={{ display: "grid", gap: 16 }}>
      {plan === "free" && (
        <div className="notice notice-info">
          학교 설명회·참가 행사 등록은 베이직 플랜부터 쓸 수 있습니다. 등록하면 학생의 즐겨찾기 화면에 D-day로 뜹니다.
        </div>
      )}

      <div className="panel">
        <h3>{editingId ? "일정 수정" : "일정 추가"}</h3>
        <div style={{ display: "grid", gap: 12 }}>
          <div className="field">
            <label className="label">일정 종류</label>
            <select className="input" value={form.kind} onChange={set("kind")}>
              <option value="briefing">학교 설명회</option>
              <option value="admission">참가 행사</option>
            </select>
          </div>
          <div className="field">
            <label className="label">일정 이름</label>
            <input className="input" value={form.title}
              placeholder={form.kind === "briefing" ? "예: 2학기 입학 설명회" : "예: 중학생 진로체험의 날"}
              onChange={set("title")} />
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <div className="field">
              <label className="label">시작일</label>
              <input className="input" type="date" value={form.start_date} onChange={set("start_date")} />
            </div>
            <div className="field">
              <label className="label">종료일 (선택)</label>
              <input className="input" type="date" value={form.end_date} onChange={set("end_date")} />
            </div>
            <div className="field">
              <label className="label">시작 시각 (선택)</label>
              <input className="input" type="time" value={form.start_time} onChange={set("start_time")} />
            </div>
            <div className="field">
              <label className="label">종료 시각 (선택)</label>
              <input className="input" type="time" value={form.end_time} onChange={set("end_time")} />
            </div>
          </div>

          <div className="field">
            <label className="label">장소 (선택)</label>
            <input className="input" value={form.location}
              placeholder="예: 본관 3층 강당" onChange={set("location")} />
          </div>
          <div className="field">
            <label className="label">참가 신청 링크 (선택)</label>
            <input className="input" type="url" value={form.registration_url}
              placeholder="https://..." onChange={set("registration_url")} />
          </div>
          <div className="field">
            <label className="label">설명 (선택)</label>
            <textarea className="textarea" rows={5} value={form.description}
              placeholder={"진행 순서나 준비물 등을 자유롭게 적어주세요.\n줄바꿈도 그대로 보여집니다."}
              onChange={set("description")} />
          </div>
          {error && <div className="notice notice-error">{error}</div>}
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn" onClick={submit} disabled={!canSubmit}>
              {editingId ? "수정 저장" : "일정 추가"}
            </button>
            {editingId && (
              <button className="btn btn-ghost" onClick={cancelEdit}>취소</button>
            )}
          </div>
        </div>
      </div>

      <div className="panel">
        <h3>등록된 일정 ({events.length})</h3>
        {events.length === 0 ? (
          <p style={{ fontSize: 13.5, color: "var(--steel)", margin: 0 }}>등록된 일정이 없습니다.</p>
        ) : (
          ["briefing", "admission"].map((kind) => {
            const list = events.filter((e) => (e.kind || "briefing") === kind);
            if (list.length === 0) return null;
            return (
              <div key={kind} style={{ marginBottom: 14 }}>
                <div className="label" style={{ fontWeight: 700, color: "var(--ink)", margin: "6px 0" }}>
                  {EVENT_KIND_LABEL[kind]} ({list.length})
                </div>
                {list.map((e) => (
                  <div className="event-row" key={e.id}>
                    <span className={ddayClass(e.d_day)}>{ddayText(e.d_day)}</span>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontWeight: 600, fontSize: 14 }}>{e.title}</div>
                      <div style={{ fontSize: 12.5, color: "var(--steel)" }}>
                        {e.start_date}{e.end_date ? ` ~ ${e.end_date}` : ""}
                        {e.start_time ? ` · ${e.start_time}${e.end_time ? `~${e.end_time}` : ""}` : ""}
                        {e.location ? ` · ${e.location}` : ""}
                      </div>
                    </div>
                    <button className="btn btn-ghost btn-sm" onClick={() => startEdit(e)}>
                      수정
                    </button>
                    <button className="btn btn-ghost btn-sm" onClick={async () => { await api.deleteEvent(e.id); reload(); }}>
                      삭제
                    </button>
                  </div>
                ))}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

function PlanTab({ profile, plans, orders, reload }) {
  const myPerks = profile.my_perks || [];
  const baseFeatures = profile.base_features || [];
  const [selected, setSelected] = useState("premium");
  const [months, setMonths] = useState(3);
  const [msg, setMsg] = useState(null);
  const [tax, setTax] = useState({ email: "", manager: "" });
  const [agreed, setAgreed] = useState(false);
  const [bank, setBank] = useState(null);

  useEffect(() => { api.schoolBankInfo().then(setBank).catch(() => {}); }, []);

  const openDoc = async (id, kind) => {
    try { await api.openOrderDoc(id, kind, false); }
    catch (e) { setMsg(errMsg(e.message)); }
  };

  // 아직 입금 전인 신청 (안내를 크게 보여준다)
  const waiting = (orders || []).find((o) => o.status === "pending" || o.status === "paid");

  const request = async () => {
    setMsg(null);
    if (!agreed) {
      return setMsg(errMsg("환불 규정을 확인하고 동의해 주세요."));
    }
    try {
      await api.requestPlan(selected, Number(months), "", tax);
      setMsg(okMsg("신청했습니다. 아래 입금 안내를 확인해 주세요."));
      reload();
    } catch (e) {
      setMsg(errMsg(e.message));
    }
  };

  const picked = plans.find((p) => p.plan === selected);
  const price = picked?.price_per_month || 0;
  const priceYear = picked?.price_per_year || price * 12;

  // 결제 예정 금액. **서버의 계산과 같은 규칙이어야 한다** — 12개월이 찰
  // 때마다 연 가격, 남는 달은 월 가격(서버 plan_amount 와 한 쌍이다).
  // 화면에 보인 값과 입금 요청액이 다르면 그건 그냥 사고다.
  const m = Math.max(Number(months || 0), 0);
  const amount = priceYear * Math.floor(m / 12) + price * (m % 12);
  const saved = price * m - amount;

  return (
    <div style={{ display: "grid", gap: 16 }}>

      <div className="panel" style={{ marginBottom: 16 }}>
        <h3>현재 사용 중인 기능</h3>
        <div style={{ marginTop: 8 }}>
          <span className="label">기본 제공 (모든 플랜)</span>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 4 }}>
            {baseFeatures.map((t) => (
              <span key={t} className="badge">{t}</span>
            ))}
          </div>
        </div>
        <div style={{ marginTop: 12 }}>
          <span className="label">플랜 혜택</span>
          {myPerks.length === 0 ? (
            <p style={{ fontSize: 13.5, color: "var(--steel)", margin: "4px 0 0" }}>
              현재 플랜에는 추가 혜택이 없습니다. 아래에서 플랜을 신청하면 더 많은 기능을 쓸 수 있습니다.
            </p>
          ) : (
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 4 }}>
              {myPerks.map((t) => (
                <span key={t} className="badge badge-dorm">{t}</span>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="stat" style={{ borderLeft: "4px solid var(--signal)" }}>
        <span className="label">현재 플랜</span>
        <div className="stat-value">
          {PLAN_LABEL[profile.plan]}
          {profile.plan_expires_at && <small> · {profile.plan_expires_at}까지</small>}
          {profile.plan_is_free_trial && (
            <span className="badge" style={{ marginLeft: 8, verticalAlign: "middle" }}>
              무료 체험
            </span>
          )}
        </div>
        {/* 갑자기 기능이 사라지면 곤란하므로 미리 알린다. */}
        {profile.plan_is_free_trial && (
          <p style={{ fontSize: 12.5, color: "var(--steel)", margin: "6px 0 0", lineHeight: 1.7 }}>
            무료로 제공된 플랜입니다. {profile.plan_expires_at}까지 이용하실 수 있고,
            그 뒤에는 무료 플랜으로 돌아갑니다. 계속 쓰시려면 기간이 끝나기 전에
            플랜을 신청해주세요.
          </p>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px,1fr))", gap: 10 }}>
        {plans.map((p) => (
          <button
            key={p.plan}
            onClick={() => p.plan !== "free" && setSelected(p.plan)}
            disabled={p.plan === "free"}
            className="panel"
            style={{
              textAlign: "left", cursor: p.plan === "free" ? "default" : "pointer",
              borderColor: selected === p.plan ? "var(--signal)" : "var(--line)",
              borderWidth: selected === p.plan ? 2 : 1,
              opacity: p.plan === "free" ? 0.6 : 1,
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
              <h3 style={{ border: "none", padding: 0, margin: 0, fontSize: 15 }}>{p.label}</h3>
              {profile.plan === p.plan && <span className="badge badge-dorm">이용 중</span>}
            </div>
            <div style={{ fontFamily: "var(--font-display)", fontSize: 20, marginBottom: 10 }}>
              {p.price_per_month === 0 ? "무료" : `${p.price_per_month.toLocaleString()}원`}
              <span style={{ fontSize: 12, color: "var(--steel)" }}>{p.price_per_month > 0 && " / 월"}</span>
            </div>
            <ul style={{ margin: 0, paddingLeft: 16, fontSize: 12.5, color: "var(--steel)", lineHeight: 1.8 }}>
              {p.perks.map((perk) => <li key={perk}>{perk}</li>)}
            </ul>
          </button>
        ))}
      </div>

      <div className="panel">
        <h3>플랜 신청</h3>
        <div style={{ display: "flex", gap: 12, alignItems: "end", flexWrap: "wrap" }}>
          <div className="field" style={{ minWidth: 130 }}>
            <label className="label">플랜</label>
            <select className="select" value={selected} onChange={(e) => setSelected(e.target.value)}>
              {plans.filter((p) => p.plan !== "free").map((p) => (
                <option key={p.plan} value={p.plan}>{p.label}</option>
              ))}
            </select>
          </div>
          <div className="field" style={{ minWidth: 100 }}>
            <label className="label">기간 (개월)</label>
            <input className="input" type="number" min="1" max="36" value={months}
              onChange={(e) => setMonths(e.target.value)} />
          </div>
          <div className="field">
            <span className="label">결제 예정 금액</span>
            <div style={{ fontFamily: "var(--font-display)", fontSize: 20 }}>
              {amount.toLocaleString()}원
            </div>
            {saved > 0 && (
              <span className="label" style={{ color: "var(--color-success)" }}>
                연간 결제로 {saved.toLocaleString()}원 저렴
              </span>
            )}
          </div>
          <button className="btn btn-signal" onClick={request}>신청하기</button>
        </div>

        <div style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--line)" }}>
          <label style={{ display: "flex", gap: 8, alignItems: "flex-start", cursor: "pointer" }}>
            <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)}
              style={{ marginTop: 3 }} />
            <span style={{ fontSize: 13.5, lineHeight: 1.6 }}>
              <b>환불 규정</b>을 확인했으며 이에 동의합니다.
              <span style={{ color: "var(--steel)" }}>
                {" "}시작 전 취소는 전액 환불, 시작 후 중도 해지는 남은 일수만큼 일할 계산해 환불됩니다.
              </span>{" "}
              <Link to="/refund" target="_blank" style={{ color: "var(--signal-deep)", fontWeight: 600 }}>
                전문 보기
              </Link>
            </span>
          </label>
        </div>

        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 12,
                      paddingTop: 12, borderTop: "1px solid var(--line)" }}>
          <div className="field" style={{ minWidth: 200 }}>
            <label className="label">세금계산서 담당자 (선택)</label>
            <input className="input" value={tax.manager} placeholder="예: 김행정"
              onChange={(e) => setTax({ ...tax, manager: e.target.value })} />
          </div>
          <div className="field" style={{ minWidth: 240 }}>
            <label className="label">세금계산서 받을 이메일 (선택)</label>
            <input className="input" type="email" value={tax.email} placeholder="office@school.kr"
              onChange={(e) => setTax({ ...tax, email: e.target.value })} />
          </div>
          <p className="label" style={{ color: "var(--steel-light)", alignSelf: "flex-end" }}>
            입력하시면 견적서에 표기되고, 입금 확인 후 이 주소로 세금계산서를 발행해 드립니다.
          </p>
        </div>
        {msg && <div className={`notice notice-${msg.type}`} style={{ marginTop: 12 }}>{msg.text}</div>}
        <p style={{ fontSize: 12.5, color: "var(--steel)", marginTop: 12, marginBottom: 0 }}>
          신청하면 관리자가 입금을 확인한 뒤 승인합니다. 승인 시점부터 기간이 시작되고,
          남은 기간이 있으면 이어붙습니다.
        </p>
      </div>

      {waiting && (
        <div className="panel" style={{ borderColor: "var(--signal)" }}>
          <h3>입금 안내</h3>
          <p style={{ fontSize: 13, color: "var(--steel)", marginTop: -4 }}>
            아래 계좌로 입금해 주세요. 입금이 확인되면 관리자가 플랜을 적용합니다.
          </p>
          <div style={{ display: "grid", gap: 8, marginTop: 8 }}>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <span className="label" style={{ width: 90 }}>입금 계좌</span>
              <b>{bank?.bank_name || "-"} {bank?.bank_account || "(관리자 미설정)"}</b>
              <span style={{ color: "var(--steel)" }}>예금주 {bank?.bank_holder || "-"}</span>
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span className="label" style={{ width: 90 }}>입금 금액</span>
              <b style={{ fontSize: 16 }}>{waiting.amount.toLocaleString()}원</b>
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span className="label" style={{ width: 90 }}>입금자명</span>
              <code style={{ fontSize: 17, fontWeight: 700, background: "var(--surface)",
                             padding: "4px 10px", borderRadius: 6, letterSpacing: 1 }}>
                {waiting.deposit_code}
              </code>
              <span style={{ fontSize: 12.5, color: "var(--alert)" }}>
                ← 이 코드를 입금자명에 꼭 포함해 주세요
              </span>
            </div>
            {waiting.due_at && (
              <div style={{ display: "flex", gap: 8 }}>
                <span className="label" style={{ width: 90 }}>입금 기한</span>
                <span>{waiting.due_at.slice(0, 10)}</span>
              </div>
            )}
          </div>
          {bank?.payment_note && (
            <p className="label" style={{ marginTop: 10, color: "var(--steel-light)" }}>{bank.payment_note}</p>
          )}
          <div style={{ display: "flex", gap: 6, marginTop: 12 }}>
            <button className="btn btn-primary btn-sm" onClick={() => openDoc(waiting.id, "quote")}>
              견적서 발행
            </button>
            <button className="btn btn-ghost btn-sm" onClick={() => openDoc(waiting.id, "contract")}>
              계약서
            </button>
            <button className="btn btn-ghost btn-sm" onClick={() => openDoc(waiting.id, "statement")}>
              거래명세서
            </button>
          </div>
        </div>
      )}

      <div className="panel">
        <h3>신청 내역</h3>
        {orders.length === 0 ? (
          <p style={{ fontSize: 13.5, color: "var(--steel)", margin: 0 }}>신청 내역이 없습니다.</p>
        ) : (
          <table className="table">
            <thead>
              <tr><th>신청일</th><th>플랜</th><th>입금 코드</th><th>금액</th><th>상태</th><th>문서</th></tr>
            </thead>
            <tbody>
              {orders.map((o) => (
                <tr key={o.id}>
                  <td>{o.created_at.slice(0, 10)}</td>
                  <td>{PLAN_LABEL[o.plan]} · {o.months}개월</td>
                  <td style={{ fontFamily: "var(--font-mono)", fontWeight: 700 }}>{o.deposit_code || "-"}</td>
                  <td>{o.amount.toLocaleString()}원</td>
                  <td>
                    <span className={`badge ${o.status === "approved" ? "badge-dorm" : ""}`}>
                      {o.status_label || STATUS_LABEL[o.status]}
                    </span>
                    {o.status === "rejected" && o.note && (
                      <div style={{ fontSize: 11, color: "var(--alert)", marginTop: 3 }}>{o.note}</div>
                    )}
                  </td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    <button className="btn btn-ghost btn-sm" onClick={() => openDoc(o.id, "quote")}>견적서</button>{" "}
                    <button className="btn btn-ghost btn-sm" onClick={() => openDoc(o.id, "contract")}>계약서</button>{" "}
                    <button className="btn btn-ghost btn-sm" onClick={() => openDoc(o.id, "statement")}>명세서</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

export default function SchoolAdmin() {
  const [tab, setTab] = useState("stats");
  const [profile, setProfile] = useState(null);
  const [stats, setStats] = useState(null);
  const [events, setEvents] = useState([]);
  const [orders, setOrders] = useState([]);
  const [plans, setPlans] = useState([]);
  const [inquiries, setInquiries] = useState([]);

  const load = () => {
    api.myProfile().then(setProfile);
    api.myStats().then(setStats);
    api.myEvents().then(setEvents);
    api.myOrders().then(setOrders);
    api.meta().then((m) => setPlans(m.plans));
    api.myInquiries().then(setInquiries).catch(() => {});
  };

  useEffect(() => { load(); }, []);

  if (!profile || !stats) return <div className="wrap" style={{ padding: 60 }}><div className="empty"><p>불러오는 중…</p></div></div>;

  const unanswered = inquiries.filter((q) => q.status === "pending").length;

  return (
    <div className="wrap" style={{ padding: "34px 0 60px" }}>
      <span className="label">학교 관리</span>
      <h1 style={{ fontSize: 26, margin: "8px 0 4px" }}>{profile.name}</h1>
      <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 0 }}>
        {profile.region} · {profile.category} · {profile.coed}
      </p>

      <div className="tabs" style={{ marginTop: 20 }}>
        <button className={`tab ${tab === "stats" ? "active" : ""}`} onClick={() => setTab("stats")}>통계</button>
        <button className={`tab ${tab === "profile" ? "active" : ""}`} onClick={() => setTab("profile")}>학교 정보</button>
        <button className={`tab ${tab === "inquiries" ? "active" : ""}`} onClick={() => setTab("inquiries")}>
          문의 관리{unanswered > 0 ? ` (${unanswered})` : ""}
        </button>
        <button className={`tab ${tab === "events" ? "active" : ""}`} onClick={() => setTab("events")}>학교일정등록</button>
        <button className={`tab ${tab === "plan" ? "active" : ""}`} onClick={() => setTab("plan")}>노출 플랜</button>
      </div>

      {tab === "stats" && <StatsTab stats={stats} />}
      {tab === "profile" && <ProfileTab profile={profile} reload={load} />}
      {tab === "inquiries" && <InquiriesTab inquiries={inquiries} profile={profile} reload={load} />}
      {tab === "events" && <EventsTab plan={profile.plan} events={events} reload={load} />}
      {tab === "plan" && <PlanTab profile={profile} plans={plans} orders={orders} reload={load} />}
    </div>
  );
}
