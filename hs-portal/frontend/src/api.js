const TOKEN_KEY = "hsportal_token";

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (t) => localStorage.setItem(TOKEN_KEY, t);
export const clearToken = () => localStorage.removeItem(TOKEN_KEY);

// 배포 방식에 따라 API 주소를 정한다.
// - nginx 리버스 프록시로 /api 를 백엔드에 넘기는 경우(권장): 설정 불필요.
//   같은 도메인이므로 window.location.origin 을 그대로 쓴다.
// - 프론트와 API가 다른 도메인인 경우: 빌드 때 VITE_API_URL 을 주면 그리로 보낸다.
//   예) VITE_API_URL=https://api.udt.example.com
const API_BASE = import.meta.env.VITE_API_URL || window.location.origin;

async function request(path, { method = "GET", body, formData, params, keepTokenOn401 = false } = {}) {
  const url = new URL(path, API_BASE);
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== "" && v !== null && v !== undefined) url.searchParams.set(k, v);
    });
  }

  const headers = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  // FormData는 브라우저가 Content-Type(경계 포함)을 자동 설정하므로 직접 지정하지 않는다.
  if (body && !formData) headers["Content-Type"] = "application/json";

  const res = await fetch(url, {
    method,
    headers,
    body: formData ? formData : body ? JSON.stringify(body) : undefined,
  });

  // 401은 보통 토큰 만료를 뜻하지만, 비밀번호 검증이 목적인 요청(탈퇴 등)의
  // 401은 '비밀번호 틀림'이라 로그아웃시키면 안 된다.
  if (res.status === 401 && !keepTokenOn401) clearToken();

  const text = await res.text();
  const data = text ? JSON.parse(text) : null;

  if (!res.ok) {
    const detail = data?.detail;
    // FastAPI 검증 오류는 배열로 온다.
    const message = Array.isArray(detail)
      ? detail.map((d) => d.msg).join(", ")
      : detail || "요청을 처리하지 못했습니다.";
    throw new Error(message);
  }
  return data;
}

/** 진행률을 알려주는 파일 업로드.
 *
 * fetch 로는 못 한다 — 요청 본문이 얼마나 나갔는지 알려주는 자리가 없다.
 * XHR 의 upload.onprogress 만 그걸 준다. 응답 처리(오류 문구·401)는 위
 * request() 와 같은 규칙을 따른다.
 */
function uploadWithProgress(path, file, onProgress) {
  return new Promise((resolve, reject) => {
    const fd = new FormData();
    fd.append("file", file);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", new URL(path, API_BASE));
    const token = getToken();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);

    xhr.upload.onprogress = (e) => {
      if (!onProgress) return;
      // 서버가 길이를 못 셀 때가 있다. 그때는 퍼센트 대신 보낸 양만 준다.
      onProgress({
        loaded: e.loaded,
        total: e.lengthComputable ? e.total : null,
        percent: e.lengthComputable ? (e.loaded / e.total) * 100 : null,
      });
    };
    // 다 보낸 뒤 서버가 파일을 저장하고 길이를 재는 동안이 있다.
    // 100% 에서 잠깐 멈춘 것처럼 보이므로 화면에 따로 알려 준다.
    xhr.upload.onload = () => onProgress && onProgress({ percent: 100, processing: true });

    xhr.onload = () => {
      if (xhr.status === 401) clearToken();
      let data = null;
      try { data = xhr.responseText ? JSON.parse(xhr.responseText) : null; } catch { /* 본문 없음 */ }
      if (xhr.status >= 200 && xhr.status < 300) return resolve(data);
      const detail = data?.detail;
      const message = Array.isArray(detail)
        ? detail.map((d) => d.msg).join(", ")
        : detail || "업로드하지 못했습니다.";
      reject(new Error(message));
    };
    xhr.onerror = () => reject(new Error("네트워크 오류로 업로드하지 못했습니다."));
    xhr.onabort = () => reject(new Error("업로드를 취소했습니다."));
    xhr.send(fd);
  });
}

export const api = {
  meta: () => request("/api/meta"),

  // 학급 이관
  classOptions: () => request("/api/teacher/class-options"),
  moveStudents: (user_ids, class_name) =>
    request("/api/teacher/students/move", {
      method: "POST", body: { user_ids, class_name },
    }),

  quizQuestions: () => request("/api/quiz/questions"),
  quizResult: (answers, lat, lng, location_label, commute_time, seed) =>
    request("/api/quiz/result", {
      method: "POST",
      // seed 는 이번 회차에 어떤 문항이 나왔는지를 가리킨다.
      // 문항이 매번 달라지므로, 채점도 그 문항으로 해야 맞는다.
      body: { answers, lat, lng, location_label, commute_time, seed },
    }),
  geoConfig: () => request("/api/geo-config"),
  geocode: (address) => request("/api/geocode", { params: { address } }),

  login: (email, password) =>
    request("/api/auth/login", { method: "POST", body: { email, password } }),
  signup: (body) => request("/api/auth/signup", { method: "POST", body }),
  // 휴대폰 본인확인
  verifyConfig: () => request("/api/verify-config"),
  sendPhoneCode: (body) => request("/api/phone/send-code", { method: "POST", body }),
  verifyPhoneCode: (body) => request("/api/phone/verify-code", { method: "POST", body }),
  resetPasswordByPhone: (body) =>
    request("/api/auth/reset-password-by-phone", { method: "POST", body }),
  // 만 14세 미만 법정대리인 동의
  guardianConsentInfo: (token) => request(`/api/guardian-consent/${token}`),
  guardianConsentSubmit: (token) =>
    request(`/api/guardian-consent/${token}`, { method: "POST" }),
  auditLogs: (params) => request("/api/admin/audit-logs", { params }),
  me: () => request("/api/auth/me"),

  findId: (body) => request("/api/auth/find-id", { method: "POST", body }),
  forgotPassword: (email) =>
    request("/api/auth/forgot-password", { method: "POST", body: { email } }),
  resetPassword: (email, code, new_password) =>
    request("/api/auth/reset-password", { method: "POST", body: { email, code, new_password } }),
  changePassword: (current_password, new_password, phone_verification_token) =>
    request("/api/auth/change-password", {
      method: "POST",
      body: { current_password, new_password, phone_verification_token },
    }),
  adminResetPassword: (id, new_password) =>
    request(`/api/admin/users/${id}/reset-password`, { method: "POST", body: { new_password } }),

  schools: (params) => request("/api/schools", { params }),
  schoolsForMap: (params) => request("/api/schools/map", { params }),
  school: (id) => request(`/api/schools/${id}`),
  countSchoolView: (id) => request(`/api/schools/${id}/view`, { method: "POST" }),
  compare: (ids) => request("/api/schools/compare/list", { params: { ids: ids.join(",") } }),

  favorites: () => request("/api/favorites"),
  addFavorite: (school_id, memo = "") =>
    request("/api/favorites", { method: "POST", body: { school_id, memo } }),
  updateFavoriteMemo: (school_id, memo) =>
    request(`/api/favorites/${school_id}`, { method: "PATCH", body: { school_id, memo } }),
  removeFavorite: (school_id) => request(`/api/favorites/${school_id}`, { method: "DELETE" }),
  favoriteCalendar: () => request("/api/favorites/calendar"),


  inquiryPrivacy: () => request("/api/privacy/inquiry"),
  createInquiry: (school_id, body) =>
    request(`/api/schools/${school_id}/inquiries`, { method: "POST", body }),
  myInquiries: (status) => request("/api/school-admin/inquiries", { params: { status } }),
  answerInquiry: (id, answer, files = []) => {
    const fd = new FormData();
    fd.append("answer", answer);
    for (const f of files) fd.append("files", f);
    return request(`/api/school-admin/inquiries/${id}/answer`, { method: "POST", formData: fd });
  },
  deleteInquiry: (id) =>
    request(`/api/school-admin/inquiries/${id}`, { method: "DELETE" }),

  myProfile: () => request("/api/school-admin/profile"),
  saveProfile: (body) => request("/api/school-admin/profile", { method: "PUT", body }),
  myStats: () => request("/api/school-admin/stats"),
  myEvents: () => request("/api/school-admin/events"),
  addEvent: (body) => request("/api/school-admin/events", { method: "POST", body }),
  updateEvent: (id, body) => request(`/api/school-admin/events/${id}`, { method: "PUT", body }),
  deleteEvent: (id) => request(`/api/school-admin/events/${id}`, { method: "DELETE" }),
  // 재학생 인증 (선생님이 처리)
  teacherVerifications: () => request("/api/teacher/verifications"),
  approveVerification: (id, class_name = "") =>
    request(`/api/teacher/verifications/${id}/approve`, { method: "POST", body: { class_name } }),
  rejectVerification: (id) =>
    request(`/api/teacher/verifications/${id}/reject`, { method: "POST" }),
  myOrders: () => request("/api/school-admin/orders"),
  requestPlan: (plan, months, note = "", tax = {}) =>
    request("/api/school-admin/orders", {
      method: "POST",
      body: { plan, months, note, tax_email: tax.email || "", tax_manager: tax.manager || "" },
    }),

  adminStats: () => request("/api/admin/stats"),
  // 현황 CSV 내려받기 (Authorization 헤더가 필요해 blob으로 처리)
  downloadAdminStats: async () => {
    const res = await fetch(new URL("/api/admin/stats/export", API_BASE), {
      headers: { Authorization: `Bearer ${getToken()}` },
    });
    if (!res.ok) throw new Error("내려받기에 실패했습니다.");
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `udj-sales-report-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },
  adminOrders: (status) => request("/api/admin/orders", { params: { status } }),
  approveOrder: (id) => request(`/api/admin/orders/${id}/approve`, { method: "POST" }),
  rejectOrder: (id, reason) =>
    request(`/api/admin/orders/${id}/reject`, { method: "POST", params: { reason } }),
  adminUsers: (params) => request("/api/admin/users", { params }),
  toggleUser: (id, active) =>
    request(`/api/admin/users/${id}/active`, { method: "PATCH", params: { active } }),
  createSchoolAccount: (body) =>
    request("/api/admin/school-accounts", { method: "POST", body }),
  updateSchool: (id, body) => request(`/api/admin/schools/${id}`, { method: "PATCH", body }),
  createSchool: (body) => request("/api/admin/schools", { method: "POST", body }),
  deleteSchool: (id) => request(`/api/admin/schools/${id}`, { method: "DELETE" }),
  resetSchoolProfile: (id) =>
    request(`/api/admin/schools/${id}/reset-profile`, { method: "POST" }),
  resetSchoolPlan: (id) =>
    request(`/api/admin/schools/${id}/reset-plan`, { method: "POST" }),

  articles: (limit = 8) => request("/api/articles", { params: { limit } }),
  allEvents: (params) => request("/api/events", { params }),

  // 선생님 워크스페이스
  teacherMe: () => request("/api/teacher/me"),
  teacherChangePassword: (body) => request("/api/teacher/change-password", { method: "POST", body }),
  teacherSearchStudents: (q) => request("/api/teacher/students/search", { params: { q } }),
  teacherStudents: (scope = "mine") => request("/api/teacher/students", { params: { scope } }),
  teacherRegisterStudent: (user_id, class_name = "") =>
    request("/api/teacher/students", { method: "POST", body: { user_id, class_name } }),
  teacherUnregisterStudent: (id) => request(`/api/teacher/students/${id}`, { method: "DELETE" }),

  schoolArticles: (schoolId, limit = 6) =>
    request(`/api/schools/${schoolId}/articles`, { params: { limit } }),
  searchArticles: (q) => request("/api/articles/search", { params: { q } }),
  crawlArticles: () => request("/api/admin/articles/crawl", { method: "POST" }),
  rematchArticles: () => request("/api/admin/articles/rematch", { method: "POST" }),
  dedupeArticles: () => request("/api/admin/articles/dedupe", { method: "POST" }),
  addManualArticle: (body) =>
    request("/api/admin/articles/manual", { method: "POST", body }),
  deleteArticle: (id) =>
    request(`/api/admin/articles/${id}`, { method: "DELETE" }),

  homeRanking: (period = "month", limit = 10) =>
    request("/api/home/ranking", { params: { period, limit } }),
  homeCategories: () => request("/api/home/categories"),
  sigungu: (region) => request("/api/sigungu", { params: { region } }),

  adminPlanPrices: () => request("/api/admin/plan-prices"),
  // 입금 계좌 설정
  adminBankInfo: () => request("/api/admin/bank-info"),
  saveBankInfo: (body) => request("/api/admin/bank-info", { method: "PUT", body }),
  schoolBankInfo: () => request("/api/school-admin/bank-info"),
  // 주문 상태
  markOrderPaid: (id) => request(`/api/admin/orders/${id}/paid`, { method: "POST" }),
  expireOrder: (id) => request(`/api/admin/orders/${id}/expire`, { method: "POST" }),
  // 견적서 / 거래명세서 (새 탭으로 열기)
  openOrderDoc: async (id, kind = "quote", asAdmin = false) => {
    const base = asAdmin ? "/api/admin/orders" : "/api/school-admin/orders";
    const url = new URL(`${base}/${id}/quote?kind=${kind}`, API_BASE);
    const res = await fetch(url, { headers: { Authorization: `Bearer ${getToken()}` } });
    if (!res.ok) throw new Error("문서를 불러오지 못했습니다.");
    const html = await res.text();
    const win = window.open("", "_blank");
    if (!win) throw new Error("팝업이 차단되었습니다. 팝업 허용 후 다시 시도해주세요.");
    win.document.write(html);
    win.document.close();
  },
  perkCatalog: () => request("/api/admin/perk-catalog"),
  setPlanPerks: (plan, keys) =>
    request(`/api/admin/plan-perks/${plan}`, { method: "PATCH", body: { keys } }),
  resetPlanPerks: (plan) =>
    request(`/api/admin/plan-perks/${plan}`, { method: "PATCH", body: { reset: true } }),
  // per: "month"(월 결제) 또는 "year"(1년치를 한 번에)
  setPlanPrice: (plan, price, per = "month") =>
    request(`/api/admin/plan-prices/${plan}`, { method: "PATCH", params: { price, per } }),
  toggleSchoolVisibility: (id, visible) =>
    request(`/api/admin/schools/${id}/visibility`, { method: "PATCH", params: { visible } }),
  toggleCategoryVisibility: (category, visible) =>
    request("/api/admin/schools-visibility-by-category", { method: "PATCH", params: { category, visible } }),
  deptFieldFilter: () => request("/api/admin/dept-field-filter"),
  setDeptFieldFilter: (enabled) =>
    request("/api/admin/dept-field-filter", { method: "PATCH", params: { enabled } }),
  rebuildDeptFields: () =>
    request("/api/admin/dept-field-filter/rebuild", { method: "POST" }),
  // 개인 구독(자기소개서 이용권) 결제 관리
  // 무상 플랜 지급
  schoolPlanStatus: (schoolId) => request(`/api/admin/schools/${schoolId}/plan-status`),
  grantPlan: (schoolId, params) =>
    request(`/api/admin/schools/${schoolId}/grant-plan`, { method: "POST", params }),
  revokePlan: (schoolId, reason) =>
    request(`/api/admin/schools/${schoolId}/revoke-plan`, { method: "POST", params: { reason } }),
  planGrants: () => request("/api/admin/plan-grants"),
  // 유료 플랜이 걸린 학교를 만료가 가까운 순서로. days=30 이면 30일 안쪽만.
  planExpiry: (days = 0) => request("/api/admin/plan-expiry", { params: { days } }),

  categoryVisibility: () => request("/api/admin/category-visibility"),
  pausePlan: (id, paused) =>
    request(`/api/admin/schools/${id}/plan-pause`, { method: "PATCH", params: { paused } }),
  // 공지 · 알림
  notices: () => request("/api/notices"),
  floatingButton: () => request("/api/floating-button"),
  adminFloatingButton: () => request("/api/admin/floating-button"),
  saveFloatingButton: (body) => request("/api/admin/floating-button", { method: "PUT", body }),
  readNotice: (id) => request(`/api/notices/${id}/read`, { method: "POST" }),
  adminNotices: () => request("/api/admin/notices"),
  uploadNoticeImage: async (file) => {
    const fd = new FormData();
    fd.append("file", file);
    return request("/api/admin/notices/image", { method: "POST", formData: fd });
  },
  // ---------- 온라인 직업계고설명회 ----------
  briefing: () => request("/api/briefing"),
  adminBriefing: () => request("/api/admin/briefing"),
  saveBriefing: (body) => request("/api/admin/briefing", { method: "PUT", body }),
  uploadBriefingCover: (file) => {
    const fd = new FormData();
    fd.append("file", file);
    return request("/api/admin/briefing/cover", { method: "POST", formData: fd });
  },
  lecturer: () => request("/api/lecturer"),
  saveLecturer: (body) => request("/api/admin/lecturer", { method: "PUT", body }),
  uploadLecturerPhoto: (file) => {
    const fd = new FormData();
    fd.append("file", file);
    return request("/api/admin/lecturer/photo", { method: "POST", formData: fd });
  },

  // ---------- 유료 서비스 신청 ----------
  applicationRegions: () => request("/api/applications/regions"),
  applicationInfo: (kind) => request("/api/applications/info", { params: { kind } }),
  submitApplication: (body) => request("/api/applications", { method: "POST", body }),
  adminApplications: (params) => request("/api/admin/applications", { params }),
  // 신청 목록 CSV. 그냥 <a href> 로 걸면 브라우저가 Authorization 헤더를
  // 안 붙여서 401 이 난다(그렇게 되어 있어 안 열렸다). 현황 리포트와 같은
  // 방식으로 받아서 파일로 떨군다.
  downloadApplicationsCsv: async (kind) => {
    const path = `/api/admin/applications.csv${kind ? `?kind=${encodeURIComponent(kind)}` : ""}`;
    const res = await fetch(new URL(path, API_BASE), {
      headers: { Authorization: `Bearer ${getToken()}` },
    });
    if (!res.ok) throw new Error("내려받기에 실패했습니다.");
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `applications-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },
  updateApplication: (id, body) =>
    request(`/api/admin/applications/${id}`, { method: "PATCH", body }),
  deleteApplication: (id) =>
    request(`/api/admin/applications/${id}`, { method: "DELETE" }),
  // ---------- 진로 챗봇 (진로 테스트 추천 학과) ----------
  careerGuide: (group) => request("/api/career-guide", { params: { group } }),
  careerChat: (group, messages) =>
    request("/api/career-chat", { method: "POST", body: { group, messages } }),
  adminCareerGuide: () => request("/api/admin/career-guide"),
  saveCareerGuide: (group, jobs) =>
    request("/api/admin/career-guide", { method: "PUT", body: { group, jobs } }),

  // ---------- 합격생 영상 (산 사람만 시청) ----------
  graduateVideo: () => request("/api/graduate-video"),
  adminGraduateVideo: () => request("/api/admin/graduate-video"),
  saveGraduateVideo: (body) =>
    request("/api/admin/graduate-video", { method: "PUT", body }),
  uploadGraduateVideoCover: (file) => {
    const fd = new FormData();
    fd.append("file", file);
    return request("/api/admin/graduate-video/cover", { method: "POST", formData: fd });
  },

  applicationSettings: () => request("/api/admin/application-settings"),
  saveApplicationSettings: (body) =>
    request("/api/admin/application-settings", { method: "PUT", body }),

  // ---------- 롱폼·숏츠 영상 ----------
  videosVisibility: () => request("/api/videos/visibility"),
  navVisibility: () => request("/api/nav-visibility"),
  adminNavVisibility: () => request("/api/admin/nav-visibility"),
  saveNavVisibility: (body) =>
    request("/api/admin/nav-visibility", { method: "PUT", body }),
  matchThresholds: () => request("/api/admin/videos-thresholds"),
  setMatchThresholds: (confirm) =>
    request("/api/admin/videos-thresholds", { method: "PUT", body: { confirm } }),
  setVideosVisibility: (pub) =>
    request("/api/admin/videos-visibility", { method: "PUT", body: { public: pub } }),
  videos: (kind) => request("/api/videos", { params: { kind } }),
  video: (id) => request(`/api/videos/${id}`),
  countVideoView: (id) => request(`/api/videos/${id}/view`, { method: "POST" }),

  adminVideos: (kind) => request("/api/admin/videos", { params: { kind } }),
  adminVideo: (id) => request(`/api/admin/videos/${id}`),
  createVideo: (body) => request("/api/admin/videos", { method: "POST", body }),
  updateVideo: (id, body) => request(`/api/admin/videos/${id}`, { method: "PATCH", body }),
  deleteVideo: (id, withShorts = false) =>
    request(`/api/admin/videos/${id}`,
      { method: "DELETE", params: withShorts ? { with_shorts: true } : {} }),
  deleteVideoFile: (id) => request(`/api/admin/videos/${id}/file`, { method: "DELETE" }),
  // 영상은 수백 MB~기가라 "올리는 중…" 만 띄우면 멈춘 것과 구별이 안 된다.
  // fetch 는 업로드 진행률을 알려주지 않아서 이 요청만 XHR 을 쓴다.
  uploadVideoFile: (id, file, onProgress) => uploadWithProgress(
    `/api/admin/videos/${id}/file`, file, onProgress),
  sttStatus: () => request("/api/admin/stt-status"),
  matchShorts: (id) => request(`/api/admin/videos/${id}/match`, { method: "POST" }),
  matchAll: (id) => request(`/api/admin/videos/${id}/match-all`, { method: "POST" }),
  matchProgress: (id) => request(`/api/admin/videos/${id}/match-progress`),
  editMatch: (id, body) => request(`/api/admin/matches/${id}`, { method: "PUT", body }),
  confirmMatch: (id) => request(`/api/admin/matches/${id}/confirm`, { method: "POST" }),

  uploadHeroImage: async (file) => {
    const fd = new FormData();
    fd.append("file", file);
    return request("/api/school-admin/hero-image", { method: "POST", formData: fd });
  },
  createAdminNotice: (body) => request("/api/admin/notices", { method: "POST", body }),
  deleteAdminNotice: (id) => request(`/api/admin/notices/${id}`, { method: "DELETE" }),

  terms: () => request("/api/terms"),
  refundPolicy: () => request("/api/refund-policy"),
  myAccount: () => request("/api/me"),
  updateMyAccount: (body) => request("/api/me", { method: "PUT", body }),
  changePhone: (current_password, new_phone, phone_verification_token) =>
    request("/api/me/change-phone", {
      method: "POST",
      body: { current_password, new_phone, phone_verification_token },
    }),
  deleteMyAccount: (password) =>
    request("/api/auth/me", { method: "DELETE", body: { password }, keepTokenOn401: true }),
};

export const PLAN_LABEL = {
  free: "무료",
  basic: "베이직",
  premium: "프리미엄",
  platinum: "플래티넘",
};

export const ROLE_LABEL = {
  student: "학생",
  teacher: "선생님",
  school: "학교",
  admin: "관리자",
};
