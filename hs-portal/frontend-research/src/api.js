// 기록해 자체 백엔드(diary-backend)를 쓴다 — UDJ(본 사이트)와는 서버·DB가
// 분리된 별도 서비스다. 계정만 UDJ 것을 그대로 쓰므로(로그인 시 diary-backend가
// UDJ에 확인 후 자기 토큰을 발급), 도메인이 달라 localStorage가 공유되지 않는
// 이 앱에서 따로 로그인한다.
const TOKEN_KEY = "udj_journal_token";

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (t) => localStorage.setItem(TOKEN_KEY, t);
export const clearToken = () => localStorage.removeItem(TOKEN_KEY);

// UDJ 주소. 휴대폰 인증처럼 계정 관련 기능은 UDJ 것을 그대로 쓴다.
export const UDJ = "https://udjschool.ggm.kr";

async function request(path, { method = "GET", body, params, base, noAuth } = {}) {
  const url = new URL(path, base || window.location.origin);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, v);
    }
  }

  const headers = {};
  // 공유 링크 화면은 로그인하지 않은 사람도 연다. 토큰을 붙이면
  // 만료된 토큰 때문에 오히려 401 이 날 수 있어 아예 보내지 않는다.
  const token = noAuth ? null : getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body) headers["Content-Type"] = "application/json";

  const res = await fetch(url, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (res.status === 204) return null;

  let data = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }

  if (!res.ok) {
    // 402 는 구독이 필요하다는 뜻. 화면에서 결제 안내로 보낸다.
    const err = new Error(detailOf(data) || `요청에 실패했습니다 (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return data;
}

// 파일로 내려받기. 서버가 정해준 파일 이름을 그대로 쓴다.
async function downloadPdf(path, fallbackName) {
  const res = await fetch(path, { headers: { Authorization: `Bearer ${getToken()}` } });
  if (!res.ok) {
    const d = await res.json().catch(() => null);
    throw new Error(d?.detail || "파일을 받지 못했습니다.");
  }
  const disp = res.headers.get("content-disposition") || "";
  const m = disp.match(/filename\*=UTF-8''([^;]+)/);
  const name = m ? decodeURIComponent(m[1]) : fallbackName;
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

function detailOf(data) {
  if (!data) return "";
  const d = data.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d) && d.length) return d[0].msg || "";
  return "";
}

export const api = {
  // 인증
  // 계정 — 원본은 UDJ 에 있고, 이 화면은 창구 역할만 한다
  login: (email, password) =>
    request("/api/auth/login", { method: "POST", body: { email, password } }),
  signup: (body) => request("/api/auth/signup", { method: "POST", body }),
  me: () => request("/api/auth/me"),
  // 담당 학급은 기록해에만 둔다. UDJ 로 보내지 않는다.
  updateMyClass: (body) => request("/api/me/class", { method: "PATCH", body }),
  updateMe: (body) => request("/api/me", { method: "PATCH", body }),
  changePassword: (current_password, new_password) =>
    request("/api/me/change-password", { method: "POST",
      body: { current_password, new_password } }),
  deleteMe: (password) => request("/api/me", { method: "DELETE", body: { password } }),

  // UDJ 의 휴대폰 인증을 그대로 쓴다 (가입 화면에서 사용)
  udjVerifyConfig: () => request("/api/verify-config", { base: UDJ }),
  udjSendCode: (body) => request("/api/phone/send-code", { method: "POST", body, base: UDJ }),
  udjVerifyCode: (body) => request("/api/phone/verify-code", { method: "POST", body, base: UDJ }),

  // 일지 · 일기
  journalMeta: () => request("/api/journal-meta"),
  journals: () => request("/api/journals"),
  journal: (id) => request(`/api/journals/${id}`),
  createJournal: (body) => request("/api/journals", { method: "POST", body }),
  updateJournal: (id, body) => request(`/api/journals/${id}`, { method: "PUT", body }),
  deleteJournal: (id) => request(`/api/journals/${id}`, { method: "DELETE" }),
  submitJournal: (id) => request(`/api/journals/${id}/submit`, { method: "POST" }),
  journalSubjects: () => request("/api/journal-subjects"),

  // 내 정보 화면은 /api/auth/me 를 쓴다(소속이 최신으로 갱신된다)
  schoolProfile: () => request("/api/auth/me"),
  setSchoolProfile: (params) => request("/api/me", { method: "PATCH", body: params }),

  // ── AI 기능 ──────────────────────────────────────────
  // 무거운 일은 서버가 뒤에서 처리한다. 맡긴 뒤 결과를 물어본다.
  aiStatus: () => request("/api/ai/status"),
  setAiConsent: (agreed) =>
    request("/api/ai/consent", { method: "POST", body: { agreed } }),
  analyzeJournal: (journalId) =>
    request(`/api/journals/${journalId}/analyze`, { method: "POST" }),
  aiJob: (jobId) => request(`/api/ai/jobs/${jobId}`),
  generateEssay: (question, journal_ids, character_limit, research_ids = []) =>
    request("/api/cover-letters/generate", {
      method: "POST", body: { question, journal_ids, character_limit, research_ids },
    }),
  verifyEssay: (draft, journal_ids, research_ids = []) =>
    request("/api/cover-letters/verify", {
      method: "POST", body: { draft, journal_ids, research_ids },
    }),

  // 맡긴 일이 끝날 때까지 기다린다. 화면이 얼어붙지 않도록
  // 잠깐씩 쉬며 물어본다.
  //
  // onTick(elapsedSec, job) 의 job.queue_position 은 대기 중일 때만 있고,
  // 몇 명이 이 요청보다 앞에서 기다리는지 알려준다(처리가 시작되면 사라짐)
  // — 사람이 몰리는 시간대에 "멈춘 것 아닌가" 하는 불안을 줄이는 용도.
  waitAiJob: async (jobId, { onTick, timeoutMs = 180000 } = {}) => {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      const r = await request(`/api/ai/jobs/${jobId}`);
      if (r.status === "done") return r.result;
      if (r.status === "failed") throw new Error(r.error || "처리하지 못했습니다.");
      onTick?.(Math.round((Date.now() - started) / 1000), r);
      await new Promise((s) => setTimeout(s, 2000));
    }
    throw new Error("시간이 오래 걸려 멈췄습니다. 잠시 뒤에 다시 시도해주세요.");
  },

  polishCoverLetter: (text) =>
    request("/api/cover-letters/polish", { method: "POST", body: { text } }),
  spellcheck: (fields) => request("/api/spellcheck", { method: "POST", body: { fields } }),

  // ── 연구 플랫폼 (M1: 관심 키워드 → AI 대화 → 주제 5개 → 선택/수정) ──
  startResearch: (interest_keyword, duration_weeks, difficulty_level, mode = "solo") =>
    request("/api/research", { method: "POST",
      body: { interest_keyword, duration_weeks, difficulty_level, mode } }),
  listResearch: () => request("/api/research"),
  getResearch: (id) => request(`/api/research/${id}`),
  deleteResearch: (id) => request(`/api/research/${id}`, { method: "DELETE" }),
  // 팀 연구는 팀부터 꾸리고 주제를 나중에 정한다 — 그때 이걸로 채운다.
  setResearchKeyword: (id, body) =>
    request(`/api/research/${id}/keyword`, { method: "POST", body }),
  sendResearchDialogue: (id, message) =>
    request(`/api/research/${id}/dialogue`, { method: "POST", body: { message } }),
  listResearchDialogue: (id) => request(`/api/research/${id}/dialogue`),
  requestResearchTopics: (id) => request(`/api/research/${id}/topics`, { method: "POST" }),
  listResearchTopics: (id) => request(`/api/research/${id}/topics`),
  editResearchTopic: (id, topicId, body) =>
    request(`/api/research/${id}/topics/${topicId}`, { method: "PUT", body }),
  reviewResearchTopic: (id, topicId) =>
    request(`/api/research/${id}/topics/${topicId}/review`, { method: "POST" }),
  selectResearchTopic: (id, topicId) =>
    request(`/api/research/${id}/topics/${topicId}/select`, { method: "POST" }),
  updateResearch: (id, body) => request(`/api/research/${id}`, { method: "PUT", body }),
  requestResearchPlan: (id) => request(`/api/research/${id}/plan`, { method: "POST" }),
  confirmResearchPlan: (id) => request(`/api/research/${id}/confirm-plan`, { method: "POST" }),
  requestResearchRoadmap: (id) => request(`/api/research/${id}/roadmap`, { method: "POST" }),
  getResearchRoadmap: (id) => request(`/api/research/${id}/roadmap`),
  updateResearchTask: (id, taskId, status) =>
    request(`/api/research/${id}/tasks/${taskId}`, { method: "PATCH", body: { status } }),
  advanceResearchWeek: (id) => request(`/api/research/${id}/advance-week`, { method: "POST" }),
  requestTaskGuide: (id, taskId) => request(`/api/research/${id}/tasks/${taskId}/guide`, { method: "POST" }),

  // 공동 연구(팀)
  getResearchTeam: (id) => request(`/api/research/${id}/team`),
  searchTeamCandidates: (id, q) => request(`/api/research/${id}/team/candidates`, { params: { q } }),
  inviteTeamMember: (id, invited_user_id) =>
    request(`/api/research/${id}/team/invites`, { method: "POST", body: { invited_user_id } }),
  listMyTeamInvites: () => request("/api/team-invites"),
  acceptTeamInvite: (inviteId) => request(`/api/team-invites/${inviteId}/accept`, { method: "POST" }),
  declineTeamInvite: (inviteId) => request(`/api/team-invites/${inviteId}/decline`, { method: "POST" }),
  updateTeamMemberRole: (id, userId, research_role) =>
    request(`/api/research/${id}/team/members/${userId}/role`, { method: "PUT", body: { research_role } }),
  listTeamRoleHistory: (id) => request(`/api/research/${id}/team/role-history`),
  requestTeamRoleSuggestions: (id) =>
    request(`/api/research/${id}/team/role-suggestions`, { method: "POST" }),
  requestLeaveTeam: (id) => request(`/api/research/${id}/team/leave-request`, { method: "POST" }),
  listTeamLeaveRequests: () => request("/api/teacher/team-leave-requests"),
  approveTeamLeave: (requestId) => request(`/api/team-leave-requests/${requestId}/approve`, { method: "POST" }),
  rejectTeamLeave: (requestId, note = "") =>
    request(`/api/team-leave-requests/${requestId}/reject`, { method: "POST", body: { note } }),
  createBoardPost: (id, title, content) =>
    request(`/api/research/${id}/board`, { method: "POST", body: { title, content } }),
  listBoardPosts: (id) => request(`/api/research/${id}/board`),
  synthesizeBoard: (id) => request(`/api/research/${id}/board/synthesize`, { method: "POST" }),
  decideBoardPost: (id, postId, decision, content) =>
    request(`/api/research/${id}/board/${postId}/decide`, { method: "POST",
      body: content ? { decision, content } : { decision } }),
  listResearchActivity: (id, beforeId) =>
    request(`/api/research/${id}/activity`, { params: beforeId ? { before_id: beforeId } : undefined }),

  // 외부 교사 질문
  createExternalQuestion: (id, title, body) =>
    request(`/api/research/${id}/questions`, { method: "POST", body: { title, body } }),
  listExternalQuestions: (id) => request(`/api/research/${id}/questions`),
  listExternalAnswers: (questionId) => request(`/api/external-questions/${questionId}/answers`),
  toggleAnswerHelpful: (answerId) =>
    request(`/api/external-answers/${answerId}/helpful`, { method: "POST" }),
  reflectAnswer: (answerId) => request(`/api/external-answers/${answerId}/reflect`, { method: "POST" }),
  listAnswerNotes: (id) => request(`/api/research/${id}/answer-notes`),
  approveAnswerNote: (noteId) =>
    request(`/api/external-answer-notes/${noteId}/approve`, { method: "POST" }),
  discardAnswerNote: (noteId) => request(`/api/external-answer-notes/${noteId}`, { method: "DELETE" }),

  // 외부 교사 질문 — 교사 쪽
  myFieldTags: () => request("/api/teacher/field-tags"),
  addFieldTag: (tag) => request("/api/teacher/field-tags", { method: "POST", body: { tag } }),
  removeFieldTag: (tagId) => request(`/api/teacher/field-tags/${tagId}`, { method: "DELETE" }),
  matchedExternalQuestions: () => request("/api/teacher/external-questions"),
  answerExternalQuestion: (questionId, body) =>
    request(`/api/external-questions/${questionId}/answers`, { method: "POST", body: { body } }),
  schoolResearchContribution: () => request("/api/schools/research-contribution"),
  notificationsSummary: () => request("/api/notifications/summary"),
  markExternalAnswersSeen: (research_id) =>
    request("/api/notifications/mark-external-answers-seen", { method: "POST", body: { research_id } }),

  // 참고 자료
  addResearchLiterature: (id, body) => request(`/api/research/${id}/literature`, { method: "POST", body }),
  listResearchLiterature: (id) => request(`/api/research/${id}/literature`),
  updateResearchLiterature: (id, litId, body) =>
    request(`/api/research/${id}/literature/${litId}`, { method: "PUT", body }),
  verifyResearchLiterature: (id, litId) =>
    request(`/api/research/${id}/literature/${litId}/verify`, { method: "POST" }),
  deleteResearchLiterature: (id, litId) =>
    request(`/api/research/${id}/literature/${litId}`, { method: "DELETE" }),
  suggestResearchLiterature: (id) => request(`/api/research/${id}/literature/suggest`, { method: "POST" }),
  attachResearchLiteratureFile: async (id, litId, file) => {
    const fd = new FormData();
    fd.append("file", file);
    const token = getToken();
    const res = await fetch(new URL(`/api/research/${id}/literature/${litId}/attachment`, window.location.origin), {
      method: "POST", headers: token ? { Authorization: `Bearer ${token}` } : {}, body: fd,
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error(detailOf(data) || "첨부에 실패했습니다.");
    return data;
  },
  removeResearchLiteratureFile: (id, litId) =>
    request(`/api/research/${id}/literature/${litId}/attachment`, { method: "DELETE" }),

  // 연구 데이터·분석
  requestResearchDataDirection: (id) => request(`/api/research/${id}/data/direction`, { method: "POST" }),
  addResearchData: (id, body) => request(`/api/research/${id}/data`, { method: "POST", body }),
  uploadResearchDataImage: async (id, file, title) => {
    const fd = new FormData();
    fd.append("file", file);
    if (title) fd.append("title", title);
    const token = getToken();
    const res = await fetch(new URL(`/api/research/${id}/data/image`, window.location.origin), {
      method: "POST", headers: token ? { Authorization: `Bearer ${token}` } : {}, body: fd,
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error(detailOf(data) || "업로드에 실패했습니다.");
    return data;
  },
  listResearchData: (id) => request(`/api/research/${id}/data`),
  deleteResearchData: (id, dataId) => request(`/api/research/${id}/data/${dataId}`, { method: "DELETE" }),
  requestResearchAnalysis: (id) => request(`/api/research/${id}/analysis`, { method: "POST" }),
  listResearchAnalysis: (id) => request(`/api/research/${id}/analysis`),

  // 연구심사·후속 연구
  requestResearchReview: (id) => request(`/api/research/${id}/review`, { method: "POST" }),
  listResearchReview: (id) => request(`/api/research/${id}/review`),
  requestResearchFollowup: (id) => request(`/api/research/${id}/followup`, { method: "POST" }),

  // 중간 리포트
  requestResearchReport: (id, report_type, blockers) =>
    request(`/api/research/${id}/reports`, { method: "POST", body: { report_type, blockers } }),
  listResearchReports: (id) => request(`/api/research/${id}/reports`),
  listResearchFeedback: (id) => request(`/api/research/${id}/feedback`),

  // 최종 논문
  draftResearchPaper: (id) => request(`/api/research/${id}/paper/draft`, { method: "POST" }),
  getResearchPaper: (id) => request(`/api/research/${id}/paper`),
  updateResearchPaper: (id, body) => request(`/api/research/${id}/paper`, { method: "PUT", body }),
  downloadResearchPaperPdf: (id) => downloadPdf(`/api/research/${id}/paper/pdf`, "연구논문.pdf"),

  // 연구 포트폴리오
  draftResearchPortfolio: (id) => request(`/api/research/${id}/portfolio/draft`, { method: "POST" }),
  getResearchPortfolio: (id) => request(`/api/research/${id}/portfolio`),
  updateResearchPortfolio: (id, body) => request(`/api/research/${id}/portfolio`, { method: "PUT", body }),
  downloadResearchPortfolioPdf: (id) => downloadPdf(`/api/research/${id}/portfolio/pdf`, "연구포트폴리오.pdf"),
  shareResearchPortfolio: (id) => request(`/api/research/${id}/portfolio/share`, { method: "POST" }),
  unshareResearchPortfolio: (id) => request(`/api/research/${id}/portfolio/share`, { method: "DELETE" }),
  sharedResearchPortfolio: (token) =>
    request(`/api/research-portfolio-share/${token}`, { noAuth: true }),

  // 교사: 담당 학급 연구 현황
  listTeacherResearch: () => request("/api/teacher/research"),
  getTeacherResearchDetail: (studentId) => request(`/api/teacher/research/${studentId}`),
  addTeacherResearchFeedback: (researchId, content) =>
    request(`/api/teacher/research/${researchId}/feedback`, { method: "POST", body: { content } }),
  listTeacherResearchFeedback: (researchId) => request(`/api/teacher/research/${researchId}/feedback`),

  // 구독
  subscription: () => request("/api/subscription/me"),

  // 학교 좌석 (결제 주체가 학교로 바뀌었다). product: "essay"(자기소개서, 기본값) | "research"
  schoolDashboard: () => request("/api/school/dashboard"),
  schoolSeats: (product = "essay") => request("/api/school/seats", { params: { product } }),
  schoolStudents: (params) => request("/api/school/students", { params }),
  seatQuote: (seats) => request("/api/school/seat-quote", { params: { seats } }),
  assignSeats: (user_ids, product = "essay") =>
    request("/api/school/seats/assign", { method: "POST", body: { user_ids, product } }),
  revokeSeats: (user_ids, product = "essay") =>
    request("/api/school/seats/revoke", { method: "POST", body: { user_ids, product } }),
  resetSubscriptions: (confirm) =>
    request("/api/admin/reset-subscriptions", { method: "POST", body: { confirm } }),
  seatCodes: (product = "essay") => request("/api/school/seat-codes", { params: { product } }),
  // 학급 정보를 함께 담는다. 학생이 이 코드를 넣으면 그대로 배정된다.
  createSeatCode: (max_uses, label, extra = {}) =>
    request("/api/school/seat-codes", {
      method: "POST", body: { max_uses, label, ...extra },
    }),
  toggleSeatCode: (id) =>
    request(`/api/school/seat-codes/${id}/toggle`, { method: "POST" }),
  redeemSeatCode: (code, student_no) =>
    request("/api/seat-codes/redeem", {
      method: "POST",
      body: student_no ? { code, student_no } : { code },
    }),
  seatOrders: () => request("/api/school/seat-orders"),
  createSeatOrder: (body) =>
    request("/api/school/seat-orders", { method: "POST", body }),
  cancelSeatOrder: (id) =>
    request(`/api/school/seat-orders/${id}/cancel`, { method: "POST" }),
  adminSeatOrders: (status = "") =>
    request("/api/admin/seat-orders", { params: { status } }),
  approveSeatOrder: (id, seats, note = "") =>
    request(`/api/admin/seat-orders/${id}/approve`, { method: "POST", body: { seats, note } }),
  confirmSeatDeposit: (id) =>
    request(`/api/admin/seat-orders/${id}/confirm-deposit`, { method: "POST" }),
  rejectSeatOrder: (id, note = "") =>
    request(`/api/admin/seat-orders/${id}/reject`, { method: "POST", body: { note } }),
  // 로그인 전에도 볼 수 있어야 하는 규정이다.
  refundPolicy: () => request("/api/refund-policy", { noAuth: true }),

  // 자기소개서 (구독 필요)
  coverLetterMaterials: (topic) =>
    request("/api/cover-letters/materials", { params: { topic } }),
  reviewCoverLetter: (fields, limit) =>
    request("/api/cover-letters/review", { method: "POST", body: { fields, limit } }),
  coverLetters: () => request("/api/cover-letters"),
  // 파일로 내려받기. 브라우저가 저장하도록 blob 으로 받는다.
  downloadCoverLetter: async (id, fmt) => {
    const res = await fetch(`/api/cover-letters/${id}/download?fmt=${fmt}`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    });
    if (!res.ok) {
      const d = await res.json().catch(() => null);
      throw new Error(d?.detail || "파일을 받지 못했습니다.");
    }
    // 서버가 정해준 파일 이름을 그대로 쓴다.
    const disp = res.headers.get("content-disposition") || "";
    const m = disp.match(/filename\*=UTF-8''([^;]+)/);
    const name = m ? decodeURIComponent(m[1]) : `자기소개서.${fmt}`;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
  },
  coverLetter: (id) => request(`/api/cover-letters/${id}`),
  createCoverLetter: (body) => request("/api/cover-letters", { method: "POST", body }),
  updateCoverLetter: (id, body) =>
    request(`/api/cover-letters/${id}`, { method: "PUT", body }),
  deleteCoverLetter: (id) => request(`/api/cover-letters/${id}`, { method: "DELETE" }),

  // 교사
  // 관리자
  adminStats: () => request("/api/admin/stats"),
  adminSettings: () => request("/api/admin/settings"),
  saveAdminSettings: (body) => request("/api/admin/settings", { method: "PUT", body }),
  matchDeposits: (body) =>
    request("/api/admin/match-deposits", { method: "POST", body }),
  // 파일 업로드는 JSON 이 아니라 FormData 로 보낸다.
  parseStatement: async (file, password = "") => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("password", password);
    const res = await fetch("/api/admin/parse-statement", {
      method: "POST",
      headers: { Authorization: `Bearer ${getToken()}` },
      body: fd,
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error(data?.detail || "파일을 읽지 못했습니다.");
    return data;
  },
  unmatchedDeposits: (status = "open") =>
    request("/api/admin/unmatched", { params: { status } }),
  rematchUnmatched: (autoApprove = false) =>
    request("/api/admin/unmatched/rematch", {
      method: "POST", params: { auto_approve: autoApprove },
    }),
  resolveUnmatched: (id, body) =>
    request(`/api/admin/unmatched/${id}/resolve`, { method: "POST", body }),
  auditLogs: (params) => request("/api/admin/audit-logs", { params }),

  // 공유 링크
  createShare: (id) => request(`/api/journals/${id}/share`, { method: "POST" }),
  revokeShare: (id) => request(`/api/journals/${id}/share`, { method: "DELETE" }),
  // 로그인 없이 여는 화면이라 토큰을 붙이지 않는다.
  sharedJournal: (token) => request(`/api/share/${token}`, { noAuth: true }),

  // 선생님 피드백
  writeFeedback: (id, text, schoolId) =>
    request(`/api/teacher/journals/${id}/feedback`, {
      method: "POST",
      body: { text },
      params: schoolId ? { school_id: schoolId } : undefined,
    }),

  teacherJournals: (params) => request("/api/teacher/journals", { params }),
  teacherJournal: (id, schoolId) =>
    request(`/api/teacher/journals/${id}`, { params: { school_id: schoolId } }),
  teacherStudents: (params) => request("/api/teacher/students", { params }),

  // 담당 과목 (담당 학급은 여전히 class_name 하나뿐, 여기서 다루지 않는다)
  schoolTeachers: () => request("/api/school/teachers"),
  mySubjects: () => request("/api/teacher/my-subjects"),
  teacherSubjects: (teacherId) => request(`/api/school/teachers/${teacherId}/subjects`),
  addTeacherSubject: (teacherId, subject_id) =>
    request(`/api/school/teachers/${teacherId}/subjects`, {
      method: "POST", body: { subject_id },
    }),
  removeTeacherSubject: (teacherId, assignmentId) =>
    request(`/api/school/teachers/${teacherId}/subjects/${assignmentId}`, { method: "DELETE" }),

  // 선생님 계정(검색·권한부여·해제) — 계정 원본은 UDJ 뿐이라 매 요청을 그대로 전달만 한다
  teacherAccounts: () => request("/api/school/teacher-accounts"),
  searchTeacherAccounts: (q) => request("/api/school/teacher-accounts/search", { params: { q } }),
  grantTeacherAccount: (user_id, class_name = "") =>
    request("/api/school/teacher-accounts/grant", { method: "POST", body: { user_id, class_name } }),
  updateTeacherAccount: (id, body) =>
    request(`/api/school/teacher-accounts/${id}`, { method: "PUT", body }),
  revokeTeacherAccount: (id) =>
    request(`/api/school/teacher-accounts/${id}`, { method: "DELETE" }),

  // AI 생기부(세특·행동특성) 초안 — 화면 진입점은 없앴지만 API는 그대로 둔다
  // (예전에 만든 초안 데이터를 지우지 않았기 때문). 새 기능은 안 쓴다.
  aiRecords: (studentId, type) =>
    request(`/api/students/${studentId}/ai-records`, { params: { type } }),
  requestSubjectNote: (studentId, subjectId) =>
    request(`/api/students/${studentId}/subjects/${subjectId}/ai-special-note`,
           { method: "POST" }),
  requestObservationNote: (studentId, subjectId) =>
    request(`/api/students/${studentId}/subjects/${subjectId}/ai-observation-note`,
           { method: "POST" }),
  requestBehaviorNote: (studentId) =>
    request(`/api/students/${studentId}/ai-behavioral-characteristics`, { method: "POST" }),
  updateAiRecord: (id, content) =>
    request(`/api/ai-records/${id}`, { method: "PUT", body: { content } }),
  confirmAiRecord: (id) =>
    request(`/api/ai-records/${id}/confirm`, { method: "POST" }),

  // 교사 관찰 기록 — 작성한 교사 본인만 볼 수 있다. NEIS 누가기록을
  // 대신하는 기능이 아니라, 이 서비스만의 독립된 개인 기록이다.
  observationsSummary: (scope = "mine") =>
    request("/api/teacher/observations/summary", { params: { scope } }),
  teacherObservations: (studentId, { order, q, subjectId } = {}) =>
    request("/api/teacher/observations",
           { params: { student_id: studentId, order, q, subject_id: subjectId } }),
  teacherObservation: (id) => request(`/api/teacher/observations/${id}`),
  createObservation: (body) => request("/api/teacher/observations", { method: "POST", body }),
  updateObservation: (id, body) =>
    request(`/api/teacher/observations/${id}`, { method: "PUT", body }),
  deleteObservation: (id) => request(`/api/teacher/observations/${id}`, { method: "DELETE" }),

  observationTemplates: () => request("/api/teacher/observation-templates"),
  createObservationTemplate: (title, content) =>
    request("/api/teacher/observation-templates", { method: "POST", body: { title, content } }),
  deleteObservationTemplate: (id) =>
    request(`/api/teacher/observation-templates/${id}`, { method: "DELETE" }),

  // 학과 계열
  deptFields: () => request("/api/dept-fields"),

  // 포트폴리오
  portfolios: () => request("/api/portfolios"),
  portfolio: (id) => request(`/api/portfolios/${id}`),
  createPortfolio: (body) => request("/api/portfolios", { method: "POST", body }),
  updatePortfolio: (id, body) => request(`/api/portfolios/${id}`, { method: "PUT", body }),
  deletePortfolio: (id) => request(`/api/portfolios/${id}`, { method: "DELETE" }),
  duplicatePortfolio: (id) => request(`/api/portfolios/${id}/duplicate`, { method: "POST" }),
  sharePortfolio: (id) => request(`/api/portfolios/${id}/share`, { method: "POST" }),
  unsharePortfolio: (id) => request(`/api/portfolios/${id}/share`, { method: "DELETE" }),
  sharedPortfolio: (token) => request(`/api/portfolio-share/${token}`, { noAuth: true }),

  createPage: (portfolioId, title) =>
    request(`/api/portfolios/${portfolioId}/pages`, { method: "POST", body: { title } }),
  updatePage: (id, title) => request(`/api/portfolio-pages/${id}`, { method: "PUT", body: { title } }),
  deletePage: (id) => request(`/api/portfolio-pages/${id}`, { method: "DELETE" }),
  duplicatePage: (id) => request(`/api/portfolio-pages/${id}/duplicate`, { method: "POST" }),
  movePage: (id, direction) =>
    request(`/api/portfolio-pages/${id}/move`, { method: "POST", body: { direction } }),

  createBlock: (pageId, block_type, content = {}, style = {}) =>
    request(`/api/portfolio-pages/${pageId}/blocks`, {
      method: "POST", body: { block_type, content, style },
    }),
  updateBlock: (id, block_type, content = {}, style = {}) =>
    request(`/api/portfolio-blocks/${id}`, {
      method: "PUT", body: { block_type, content, style },
    }),
  deleteBlock: (id) => request(`/api/portfolio-blocks/${id}`, { method: "DELETE" }),
  duplicateBlock: (id) => request(`/api/portfolio-blocks/${id}/duplicate`, { method: "POST" }),
  moveBlock: (id, direction) =>
    request(`/api/portfolio-blocks/${id}/move`, { method: "POST", body: { direction } }),

  // 사진 — 파일 업로드라 FormData로 보낸다
  uploadPortfolioImage: async (portfolioId, file, { pageId, title } = {}) => {
    const fd = new FormData();
    fd.append("portfolio_id", portfolioId);
    if (pageId) fd.append("page_id", pageId);
    fd.append("title", title || "");
    fd.append("file", file);
    const res = await fetch("/api/portfolio-images", {
      method: "POST",
      headers: { Authorization: `Bearer ${getToken()}` },
      body: fd,
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error(data?.detail || "사진을 올리지 못했습니다.");
    return data;
  },
  updatePortfolioImage: (id, body) =>
    request(`/api/portfolio-images/${id}`, { method: "PUT", body }),
  // <img src> 태그는 Authorization 헤더를 못 붙인다. 그래서 화면에 보여줄
  // 때는 직접 fetch로 받아 blob 주소를 만들어 쓴다(공유 화면은 로그인이
  // 아예 없어도 서버가 허용하므로 이 함수를 쓸 필요가 없다).
  loadPortfolioImageUrl: async (url) => {
    const res = await fetch(url, { headers: { Authorization: `Bearer ${getToken()}` } });
    if (!res.ok) throw new Error("사진을 불러오지 못했습니다.");
    const blob = await res.blob();
    return URL.createObjectURL(blob);
  },
  deletePortfolioImage: (id) => request(`/api/portfolio-images/${id}`, { method: "DELETE" }),
  requestImageCaption: (id) =>
    request(`/api/portfolio-images/${id}/caption`, { method: "POST" }),

  // 테마 추천 · 포트폴리오 생성 · 경험 · 첨삭 (전부 AI 큐를 거치므로 waitAiJob과 함께 쓴다)
  requestThemeRecommend: () =>
    request("/api/portfolio-theme-recommendations", { method: "POST" }),
  cachedThemeRecommendations: () => request("/api/portfolio-theme-recommendations"),
  requestPortfolioGenerate: (theme_type, purpose, journal_ids = []) =>
    request("/api/portfolios/generate", { method: "POST",
      body: { theme_type, purpose, journal_ids } }),
  requestProofread: (text, action) =>
    request("/api/portfolio-text/proofread", { method: "POST", body: { text, action } }),

  experiences: () => request("/api/experiences"),
  experienceSources: (id) => request(`/api/experiences/${id}/sources`),
  createExperience: (body) => request("/api/experiences", { method: "POST", body }),
  updateExperience: (id, body) => request(`/api/experiences/${id}`, { method: "PUT", body }),
  deleteExperience: (id) => request(`/api/experiences/${id}`, { method: "DELETE" }),
  requestExperienceExtract: (journal_id) =>
    request("/api/experiences/extract", { method: "POST", body: { journal_id } }),
};
