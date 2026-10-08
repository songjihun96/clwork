import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { DormBadge, PlanBadge } from "./SchoolCard";
import { ddayClass, ddayText } from "../dday";
import { errMsg } from "../toast";

function eventTimeLine(e) {
  const parts = [e.start_date + (e.end_date ? ` ~ ${e.end_date}` : "")];
  if (e.start_time) parts.push(`${e.start_time}${e.end_time ? `~${e.end_time}` : ""}`);
  if (e.location) parts.push(e.location);
  return parts.join(" · ");
}

/** 같은 이름의 일정(같은 설명회를 여러 날짜에 걸쳐 등록한 경우)을 한 그룹으로 묶는다. */
function groupEvents(list) {
  const groups = [];
  const byTitle = new Map();
  for (const e of list) {
    if (!byTitle.has(e.title)) {
      const g = { title: e.title, items: [] };
      byTitle.set(e.title, g);
      groups.push(g);
    }
    byTitle.get(e.title).items.push(e);
  }
  return groups;
}

function EventDetailModal({ event, onClose }) {
  return createPortal(
    <div className="notice-modal-backdrop" onClick={onClose}>
      <div className="notice-modal" onClick={(e) => e.stopPropagation()}>
        <div className="notice-modal-body">
          <span className={ddayClass(event.d_day)}>{ddayText(event.d_day)}</span>
          <h2 style={{ fontSize: 19, margin: "8px 0 4px" }}>{event.title}</h2>
          <p style={{ fontSize: 13, color: "var(--steel)", margin: "0 0 12px" }}>
            {eventTimeLine(event)}
          </p>
          {event.description && <p className="prose">{event.description}</p>}
        </div>
        <div className="notice-modal-foot">
          {event.registration_url ? (
            <a className="btn btn-signal btn-sm" href={event.registration_url}
              target="_blank" rel="noopener noreferrer">
              참가 신청하기
            </a>
          ) : <span />}
          <button className="btn btn-ghost btn-sm" onClick={onClose}>닫기</button>
        </div>
      </div>
    </div>,
    document.body
  );
}

/** 학교가 등록한 소개 영상. 처음엔 썸네일만 두고, 재생을 누른 뒤에야
 *  유튜브를 불러온다. 영상 3개를 한꺼번에 띄우면 상세 페이지가 무거워진다. */
function YoutubeCard({ video }) {
  const [playing, setPlaying] = useState(false);
  return (
    <div style={{ position: "relative", width: "100%", aspectRatio: "16 / 9",
      borderRadius: "var(--radius-sm)", overflow: "hidden", background: "#000" }}>
      {playing ? (
        <iframe
          src={`${video.embed_url}?autoplay=1&rel=0`}
          title="학교 소개 영상"
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
          allowFullScreen
          style={{ width: "100%", height: "100%", border: "none", display: "block" }}
        />
      ) : (
        <button
          onClick={() => setPlaying(true)}
          aria-label="영상 재생"
          style={{
            width: "100%", height: "100%", padding: 0, border: "none", cursor: "pointer",
            display: "grid", placeItems: "center",
            background: `#000 url(${video.thumbnail}) center/cover no-repeat`,
          }}
        >
          <span style={{
            width: 62, height: 44, borderRadius: 11, background: "rgba(0,0,0,0.72)",
            display: "grid", placeItems: "center", color: "#fff", fontSize: 17, lineHeight: 1,
          }}>▶</span>
        </button>
      )}
    </div>
  );
}

function InquiryForm({ schoolId, schoolName, canQuick }) {
  const [form, setForm] = useState({ asker_name: "", contact_email: "", contact_phone: "", question: "" });
  const [consent, setConsent] = useState(false);
  const [notice, setNotice] = useState(null);
  const [showNotice, setShowNotice] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  // 접수 완료 문구. okMsg() 는 토스트만 띄우고 null 을 돌려주므로 msg 에 담으면
  // 완료 화면의 상자가 비어 보인다 — 따로 들고 있는다.
  const [done, setDone] = useState("");

  useEffect(() => {
    api.inquiryPrivacy().then(setNotice).catch(() => {});
  }, []);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const submit = async () => {
    setMsg(null);
    if (!form.contact_email.trim()) return setMsg(errMsg("답변받을 이메일을 입력해주세요."));
    // 메일이 안 닿을 때 학교가 연락할 길이 있어야 한다.
    if (form.contact_phone.replace(/\D/g, "").length < 9)
      return setMsg(errMsg("연락처를 정확히 입력해주세요."));
    if (form.question.trim().length < 5) return setMsg(errMsg("문의 내용을 5자 이상 적어주세요."));
    if (!consent) return setMsg(errMsg("개인정보 수집·이용에 동의해야 문의를 남길 수 있습니다."));
    setBusy(true);
    try {
      const res = await api.createInquiry(schoolId, {
        asker_name: form.asker_name.trim(),
        contact_email: form.contact_email.trim(),
        contact_phone: form.contact_phone.trim(),
        question: form.question.trim(),
        privacy_consent: consent,
      });
      setDone(res.message || "문의가 접수되었습니다. 학교가 답변하면 입력하신 이메일로 보내드립니다.");
    } catch (e) {
      setMsg(errMsg(e.message));
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <div className="panel" id="inquiry">
        <h3>학교에 문의하기</h3>
        <div className="notice notice-ok">{done}</div>
        <button className="btn btn-ghost btn-sm" style={{ marginTop: 12 }}
          onClick={() => { setDone(""); setForm({ asker_name: "", contact_email: "", contact_phone: "", question: "" }); setConsent(false); setMsg(null); }}>
          다른 문의 남기기
        </button>
      </div>
    );
  }

  return (
    <div className="panel" id="inquiry">
      <h3>학교에 문의하기</h3>
      <p style={{ fontSize: 13, color: "var(--steel)", marginTop: -4 }}>
        {schoolName}에 궁금한 점을 남기면, 학교가 확인 후 입력하신 이메일로 답변을 보내드립니다.
      </p>
      {canQuick ? (
        <div className="notice notice-ok" style={{ marginBottom: 12 }}>
          ⚡ 이 학교는 <b>빠른 문의 가능</b> 학교입니다. 학교가 답변을 등록하면 입력하신 이메일로 발송됩니다.
        </div>
      ) : (
        <div className="notice notice-info" style={{ marginBottom: 12 }}>
          이 학교는 아직 포털에 계정을 개설하지 않아, 답변이 늦거나 어려울 수 있습니다.
        </div>
      )}
      <div style={{ display: "grid", gap: 12 }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <div className="field">
            <label className="label">이름 (선택)</label>
            <input className="input" value={form.asker_name} onChange={set("asker_name")} maxLength={60} />
          </div>
          <div className="field">
            <label className="label">연락처 (필수)</label>
            <input className="input" value={form.contact_phone} onChange={set("contact_phone")}
              placeholder="전화번호" maxLength={30} />
          </div>
        </div>
        <div className="field">
          <label className="label">이메일 (필수) · 답변을 받을 주소</label>
          <input className="input" type="email" value={form.contact_email} onChange={set("contact_email")}
            placeholder="example@email.com" maxLength={120} />
        </div>
        <div className="field">
          <label className="label">문의 내용 (필수)</label>
          <textarea className="textarea" value={form.question} onChange={set("question")}
            placeholder="예: 반도체장비과 실습실은 몇 개인가요? 기숙사 신청은 어떻게 하나요?" maxLength={2000} />
        </div>

        <div style={{ border: "1px solid var(--line)", borderRadius: 6, padding: 12 }}>
          <label style={{ display: "flex", alignItems: "flex-start", gap: 8, fontSize: 13, cursor: "pointer" }}>
            <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)}
              style={{ marginTop: 2 }} />
            <span>
              <strong>[필수]</strong> 개인정보 수집·이용에 동의합니다.
              <button type="button" onClick={() => setShowNotice((v) => !v)}
                style={{ marginLeft: 6, background: "none", border: "none", color: "var(--signal-deep)", cursor: "pointer", padding: 0, fontSize: 12.5, textDecoration: "underline" }}>
                {showNotice ? "접기" : "자세히 보기"}
              </button>
            </span>
          </label>
          {showNotice && notice && (
            <div style={{ marginTop: 10, fontSize: 12.5, color: "var(--steel)", lineHeight: 1.7 }}>
              <div><b>수집 항목</b> : {notice.collected.join(", ")}</div>
              <div><b>수집·이용 목적</b> : {notice.purpose}</div>
              <div><b>보유·이용 기간</b> : {notice.retention}</div>
              <div><b>열람 범위</b> : {notice.recipient}</div>
              <div style={{ color: "var(--alert)" }}>{notice.right_to_refuse}</div>
              <div style={{ marginTop: 6 }}>
                <a href="/privacy" target="_blank" rel="noreferrer" style={{ color: "var(--signal-deep)" }}>
                  전체 개인정보처리방침 보기 →
                </a>
              </div>
            </div>
          )}
        </div>

        {msg && <div className={`notice notice-${msg.type}`}>{msg.text}</div>}
        <div>
          <button className="btn btn-signal" onClick={submit} disabled={busy}>
            {busy ? "접수 중…" : "문의 남기기"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function SchoolDetailView({ schoolId, embedded, onLoaded }) {
  const { user } = useAuth();
  const [school, setSchool] = useState(null);
  const [error, setError] = useState("");
  const [articles, setArticles] = useState([]);
  const [interviews, setInterviews] = useState([]);
  const [selectedEvent, setSelectedEvent] = useState(null);

  const load = () =>
    api
      .school(schoolId)
      .then((data) => {
        setSchool(data);
        if (onLoaded) onLoaded(data);
      })
      .catch((e) => setError(e.message));

  useEffect(() => {
    load();
    api.schoolArticles(schoolId).then(setArticles).catch(() => setArticles([]));
    api.interviews(schoolId).then((d) => setInterviews(d.items || [])).catch(() => setInterviews([]));
    // 조회수는 화면을 열 때 한 번만 센다. load() 안에 두면 즐겨찾기 등으로
    // 다시 불릴 때마다 중복 집계된다.
    api.countSchoolView(schoolId).catch(() => {});
  }, [schoolId]);

  // 학교 일정 목록에서 일정을 누르면 ?event=12 를 달고 들어온다.
  // 누른 그 일정의 상세를 바로 띄우고, 뒤에는 그 일정이 있는 칸을 펼쳐둔다
  // (상세를 닫았을 때 목록 맨 위가 아니라 그 자리에 있게).
  // 학교 정보를 받아 화면이 그려진 뒤라야 그 칸이 있으므로 여기서 처리한다.
  useEffect(() => {
    if (!school || embedded) return;
    const wanted = Number(new URLSearchParams(window.location.search).get("event"));
    const target = wanted ? (school.events || []).find((e) => e.id === wanted) : null;
    const anchor = target
      ? `school-${target.kind || "briefing"}`
      : window.location.hash.slice(1);
    const el = anchor ? document.getElementById(anchor) : null;
    if (!el) return;
    if (target) {
      // 상세를 띄울 때는 단숨에 옮긴다. 부드럽게 굴리면 그 사이에 상세가
      // 덮여 버려서, 닫았을 때 엉뚱한 데 가 있게 된다. 기사·이미지가 늦게
      // 들어오며 위치가 밀리는 것도 있어 한 번 더 맞춘다(상세에 가려 안 보임).
      el.scrollIntoView({ block: "start" });
      const again = setTimeout(() => el.scrollIntoView({ block: "start" }), 400);
      setSelectedEvent(target);
      return () => clearTimeout(again);
    }
    el.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [school, embedded]);

  if (error) return <div className="notice notice-error">{error}</div>;
  if (!school) return <div className="empty"><p>불러오는 중…</p></div>;

  const isStudent = user?.role === "student";

  const toggleFav = async () => {
    if (school.is_favorite) await api.removeFavorite(school.id);
    else await api.addFavorite(school.id);
    load();
  };

  const heroActions = (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
      {school.website && (
        <a className="btn btn-ghost btn-sm" href={school.website} target="_blank" rel="noreferrer">
          학교 홈페이지
        </a>
      )}
      {embedded && (
        <a className="btn btn-ghost btn-sm" href={`/schools/${school.id}`} target="_blank" rel="noreferrer">
          새 탭에서 열기
        </a>
      )}
    </div>
  );

  // 학과별 사진은 없는 데이터라, 통계 카드는 실제로 있는 값만 보여준다
  // (없는 지표를 지어내지 않는다).
  const stats = [
    school.employment_rate != null && { icon: "work", value: `${school.employment_rate}%`, label: "졸업생 취업률", tone: "accent" },
    school.student_count != null && { icon: "groups", value: `${school.student_count.toLocaleString()}명`, label: "재학생 수", tone: "neutral" },
  ].filter(Boolean);

  return (
    <>
      {school.hero_image ? (
        <div className="detail-hero-photo" style={{ backgroundImage: `url(${school.hero_image})` }}>
          <div className="detail-hero-photo-body">
            <div style={{ color: "#fff", minWidth: 0 }}>
              <div style={{ display: "flex", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
                <span className="hero-chip"><span className="msi" style={{ fontSize: 14 }}>location_on</span>{school.region}</span>
                <span className="hero-chip on-accent">{school.category}</span>
                <PlanBadge plan={school.plan} visible={user?.role === "admin" || user?.role === "school"} />
              </div>
              <h2>{school.name}</h2>
              <p>{school.slogan || school.address}</p>
              <div style={{ marginTop: 16 }}>
                {isStudent && (
                  <button className={school.is_favorite ? "btn btn-ghost btn-sm" : "btn btn-signal btn-sm"} onClick={toggleFav}>
                    {school.is_favorite ? "★ 즐겨찾기 해제" : "☆ 즐겨찾기"}
                  </button>
                )}
              </div>
            </div>
            {isStudent ? (
              <button className="hero-fav-btn" onClick={toggleFav} aria-label="즐겨찾기">
                <span className="msi" style={{ fontVariationSettings: school.is_favorite ? "'FILL' 1" : "'FILL' 0" }}>favorite</span>
              </button>
            ) : <span />}
          </div>
        </div>
      ) : (
        <div className="detail-hero">
          <div style={{ display: "flex", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
            <span className="badge badge-cat">{school.category}</span>
            <PlanBadge plan={school.plan} visible={user?.role === "admin" || user?.role === "school"} />
            <span className="badge">{school.region}</span>
          </div>
          <h2>{school.name}</h2>
          <p>{school.slogan || school.address}</p>
          <div style={{ marginTop: 16 }}>
            {isStudent && (
              <button className={school.is_favorite ? "btn btn-ghost btn-sm" : "btn btn-signal btn-sm"} onClick={toggleFav}>
                {school.is_favorite ? "★ 즐겨찾기 해제" : "☆ 즐겨찾기"}
              </button>
            )}
          </div>
        </div>
      )}

      <div className="detail-body" style={embedded ? undefined : { padding: "0 28px 28px" }}>
        {!embedded && <div style={{ margin: "20px 0" }}>{heroActions}</div>}

        <div className={embedded ? undefined : "detail-grid"}>
          <div className={embedded ? undefined : "detail-main"}>
        {stats.length > 0 && (
          <div className="stat-icon-grid">
            {stats.map((s) => (
              <div className="stat-icon-card" key={s.label}>
                <div className={`stat-icon-circle tone-${s.tone}`}><span className="msi">{s.icon}</span></div>
                <div className="stat-icon-value">{s.value}</div>
                <div className="stat-icon-label">{s.label}</div>
              </div>
            ))}
          </div>
        )}

        {/* 검색 목록에도 나오는 기초 정보 */}
        <div className="panel">
          <h3>기본 정보</h3>
          <div className="kv-grid">
            {embedded && (
              <>
                <div>
                  <span className="label">주소</span>
                  <dd>{school.address}</dd>
                </div>
                <div>
                  <span className="label">전화번호</span>
                  <dd>{school.phone || "—"}</dd>
                </div>
              </>
            )}
            <div>
              <span className="label">남녀공학</span>
              <dd>{school.coed}</dd>
            </div>
            {school.dormitory === true && (
              <div>
                <span className="label">기숙사</span>
                <dd><DormBadge value={school.dormitory} /></dd>
              </div>
            )}
            <div>
              <span className="label">설립</span>
              <dd>
                {school.foundation || "—"}
                {school.established_year ? ` · ${school.established_year}년` : ""}
              </dd>
            </div>
          </div>
        </div>

        {school.departments.length > 0 && (
          <div className="panel">
            <h3>개설 학과</h3>
            <div className="dept-list">
              {school.departments.map((d) => (
                <span className="dept" key={d}>{d}</span>
              ))}
            </div>
          </div>
        )}

        {school.intro && (
          <div className="panel">
            <h3>학교 소개</h3>
            <p className="prose">{school.intro}</p>
          </div>
        )}

        {school.facilities && (
          <div className="panel">
            <h3>실습 시설</h3>
            <p className="prose">{school.facilities}</p>
          </div>
        )}

        {/* 진학정보(플래티넘). 서버가 이 사람이 열 수 있을 때만 true 를 준다. */}
        {school.has_admission_info && (
          <div className="panel adm-link-panel">
            <div>
              <h3 style={{ marginBottom: 4 }}>취업/진학 정보</h3>
              <p style={{ margin: 0, fontSize: 13.5, color: "var(--steel)" }}>
                졸업생 진로·주요 진학 대학·취업 분야·주요 취업처 (학교 직접 입력 자료)
              </p>
            </div>
            {/* 모달(embedded)은 새 탭으로, 상세 페이지는 앱 안에서 넘어간다.
                from 을 넘겨야 진학정보의 '← 학교 정보' 가 새 기록을 쌓지 않고
                뒤로 돌아온다 — 안 그러면 '뒤로'가 두 화면을 무한히 오간다. */}
            {embedded ? (
              <a className="btn btn-signal btn-sm" href={`/schools/${school.id}/admission`}
                target="_blank" rel="noreferrer">취업/진학 정보 보기</a>
            ) : (
              <Link className="btn btn-signal btn-sm" to={`/schools/${school.id}/admission`}
                state={{ from: "school" }}>취업/진학 정보 보기</Link>
            )}
          </div>
        )}

        {school.admission_info && (
          <div className="panel">
            <h3>학교 상세 안내</h3>
            <p className="prose">{school.admission_info}</p>
          </div>
        )}

        {["briefing", "admission"].map((kind) => {
          const list = school.events.filter(
            (e) => (e.kind || "briefing") === kind
          );
          if (list.length === 0) return null;
          const heading = kind === "briefing" ? "학교 설명회" : "참가 행사";
          const groups = groupEvents(list);
          return (
            <div className="panel" key={kind} id={`school-${kind}`}>
              <h3>{heading}</h3>
              {groups.map((g) => (
                <div key={g.title}>
                  {g.items.length > 1 && (
                    <div style={{ fontWeight: 600, fontSize: 14, margin: "10px 0 2px" }}>
                      {g.title}
                    </div>
                  )}
                  {g.items.map((e) => (
                    <button key={e.id} className="event-row"
                      style={{ width: "100%", textAlign: "left", border: "none",
                        background: "none", cursor: "pointer", padding: "11px 0" }}
                      onClick={() => setSelectedEvent(e)}>
                      <span className={ddayClass(e.d_day)}>{ddayText(e.d_day)}</span>
                      <div style={{ flex: 1 }}>
                        {g.items.length === 1 && (
                          <div style={{ fontWeight: 600, fontSize: 14 }}>{e.title}</div>
                        )}
                        <div style={{ fontSize: 12.5, color: "var(--steel)" }}>
                          {eventTimeLine(e)}
                        </div>
                      </div>
                    </button>
                  ))}
                </div>
              ))}
            </div>
          );
        })}

        {(school.youtube_videos || []).length > 0 && (
          <div className="panel" id="school-videos">
            <h3>학교 소개 영상</h3>
            {/* 격자로 깔면 3개·5개처럼 딱 안 떨어질 때 마지막 한 칸이
                왼쪽에 혼자 남아 비뚤어 보인다. 줄바꿈 후 가운데로 모은다. */}
            <div style={{ display: "flex", flexWrap: "wrap", gap: 12,
              justifyContent: "center" }}>
              {school.youtube_videos.map((v) => (
                <div key={v.video_id} style={{ flex: "1 1 300px", maxWidth: 420 }}>
                  <YoutubeCard video={v} />
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 포털이 학교에 찾아가 찍은 인터뷰. 재생은 회원만(인터뷰 화면에서 막는다). */}
        {interviews.length > 0 && (
          <div className="panel" id="school-interviews">
            <h3>학교 홍보 인터뷰</h3>
            <div style={{ display: "grid", gap: 8 }}>
              {interviews.map((it) => {
                const inner = (
                  <>
                    <span aria-hidden="true">🎤</span>
                    <span style={{ flex: 1, minWidth: 0 }}>
                      <b style={{ display: "block", fontSize: 14 }}>{it.title}</b>
                      {it.speakers && <small style={{ color: "var(--steel)" }}>{it.speakers}</small>}
                    </span>
                    <span className="label" style={{ color: "var(--signal-deep)" }}>
                      {user ? "보기 →" : "회원 전용 →"}
                    </span>
                  </>
                );
                return embedded ? (
                  <a key={it.id} className="iv-row" href={`/interviews/${it.id}`}
                    target="_blank" rel="noreferrer">{inner}</a>
                ) : (
                  <Link key={it.id} className="iv-row" to={`/interviews/${it.id}`}>{inner}</Link>
                );
              })}
            </div>
          </div>
        )}

        {selectedEvent && (
          <EventDetailModal event={selectedEvent} onClose={() => setSelectedEvent(null)} />
        )}

        {articles.length > 0 && (
          <div className="panel">
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
              <h3 style={{ border: "none", padding: 0, margin: 0 }}>특성화고신문 기사</h3>
              <span className="label" style={{ color: "var(--steel-light)" }}>특성화고신문 제공</span>
            </div>
            <div style={{ display: "grid", gap: 12 }}>
              {articles.map((a) => (
                <a
                  key={a.id}
                  href={a.url}
                  target="_blank"
                  rel="noreferrer"
                  style={{
                    display: "flex", gap: 12, textDecoration: "none", color: "inherit",
                    border: "1px solid var(--line)", borderRadius: "var(--radius-sm)",
                    padding: 10, alignItems: "flex-start",
                  }}
                >
                  {a.thumbnail ? (
                    <div style={{ width: 92, height: 68, borderRadius: 8, flexShrink: 0, background: `#f0e6de url(${a.thumbnail}) center/cover no-repeat` }} />
                  ) : (
                    <div style={{ width: 92, height: 68, borderRadius: 8, flexShrink: 0, background: "var(--signal-soft)", display: "grid", placeItems: "center", fontSize: 24 }}>📰</div>
                  )}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 600, fontSize: 14, lineHeight: 1.4, marginBottom: 3 }}>{a.title}</div>
                    {a.summary && (
                      <p style={{ fontSize: 12.5, color: "var(--steel)", margin: 0, lineHeight: 1.5, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
                        {a.summary}
                      </p>
                    )}
                    <div style={{ display: "flex", gap: 8, marginTop: 5, alignItems: "center" }}>
                      {a.published_at && <span style={{ fontSize: 11.5, color: "var(--steel-light)" }}>{a.published_at}</span>}
                      <span style={{ fontSize: 11.5, color: "var(--signal-deep)" }}>원문 보기 →</span>
                    </div>
                  </div>
                </a>
              ))}
            </div>
          </div>
        )}

        <InquiryForm schoolId={school.id} schoolName={school.name} canQuick={school.can_quick_inquiry} />

          </div>

          {!embedded && (
            <div className="detail-sidebar">
              <div className="panel">
                <h3>위치 및 연락처</h3>
                <div className="contact-list">
                  <div className="contact-row">
                    <span className="msi icon">location_on</span>
                    <div>
                      <span className="label">주소</span>
                      <div style={{ fontSize: 14, marginTop: 2 }}>{school.address}</div>
                    </div>
                  </div>
                  <div className="contact-row">
                    <span className="msi icon">call</span>
                    <div>
                      <span className="label">전화번호</span>
                      <div style={{ fontSize: 14, marginTop: 2 }}>{school.phone || "—"}</div>
                    </div>
                  </div>
                  {school.website && (
                    <div className="contact-row">
                      <span className="msi icon">language</span>
                      <div>
                        <span className="label">홈페이지</span>
                        <a href={school.website} target="_blank" rel="noreferrer"
                          style={{ display: "block", fontSize: 14, marginTop: 2 }}>
                          {school.website.replace(/^https?:\/\//, "")}
                        </a>
                      </div>
                    </div>
                  )}
                </div>
                <a className="btn btn-signal" href="#inquiry"
                  style={{ width: "100%", justifyContent: "center", display: "flex", alignItems: "center", gap: 8 }}>
                  <span className="msi" style={{ fontSize: 18 }}>forum</span> 입학 상담 신청
                </a>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
