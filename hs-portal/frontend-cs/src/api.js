// 상담 사이트는 본 사이트와 같은 백엔드를 쓰지만 /api/cs 아래만 부른다.
// 도메인이 다르므로 로그인 토큰도 따로 보관한다.
const TOKEN_KEY = "udj_cs_token";
const DEVICE_KEY = "udj_cs_device";

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (t) => localStorage.setItem(TOKEN_KEY, t);
export const clearToken = () => localStorage.removeItem(TOKEN_KEY);

// 기기 토큰은 서버가 발급한다. 승인을 받으면 이 기기에서 계속 쓸 수 있다.
// 로그아웃해도 지우지 않는다. 지우면 승인을 다시 받아야 한다.
export const getDevice = () => localStorage.getItem(DEVICE_KEY);
export const setDevice = (t) => localStorage.setItem(DEVICE_KEY, t);

async function request(path, { method = "GET", body, params } = {}) {
  const url = new URL(path, window.location.origin);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, v);
    }
  }

  const headers = {};
  const token = getToken();
  const device = getDevice();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (device) headers["X-CS-Device"] = device;
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
    const err = new Error(detailOf(data) || `요청에 실패했습니다 (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return data;
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
  login: (email, password, device_label = "") =>
    request("/api/cs/login", { method: "POST", body: { email, password, device_label } }),
  me: () => request("/api/cs/me"),
  summary: () => request("/api/cs/summary"),

  // 회원
  users: (params) => request("/api/cs/users", { params }),
  user: (id, reveal = false) =>
    request(`/api/cs/users/${id}`, { params: reveal ? { reveal: "true" } : null }),
  sendPasswordReset: (id, reason) =>
    request(`/api/cs/users/${id}/password-reset`, { method: "POST", body: { reason } }),

  // 학교
  schools: (params) => request("/api/cs/schools", { params }),
  school: (id) => request(`/api/cs/schools/${id}`),
  updateSchool: (id, patch) =>
    request(`/api/cs/schools/${id}`, { method: "PATCH", body: patch }),

  // 문의
  inquiries: (params) => request("/api/cs/inquiries", { params }),
  answerInquiry: (id, answer) =>
    request(`/api/cs/inquiries/${id}/answer`, { method: "POST", body: { answer } }),


  // 재학생 인증
  verifications: (params) => request("/api/cs/verifications", { params }),
  decideVerification: (id, decision, note = "") =>
    request(`/api/cs/verifications/${id}/decide`, {
      method: "POST",
      body: { decision, note },
    }),

  // 결제·구독
  orders: (params) => request("/api/cs/orders", { params }),
  confirmPaid: (id, note = "") =>
    request(`/api/cs/orders/${id}/confirm-paid`, { method: "POST", body: { note } }),
  subscriptions: (params) => request("/api/cs/subscriptions", { params }),

  // 관리자 전용
  devices: (status = "") => request("/api/cs/admin/devices", { params: { status } }),
  decideDevice: (id, decision, label = "") =>
    request(`/api/cs/admin/devices/${id}/decide`, {
      method: "POST",
      body: { decision, label },
    }),
  deleteDevice: (id) => request(`/api/cs/admin/devices/${id}`, { method: "DELETE" }),
  agents: () => request("/api/cs/admin/agents"),
  createAgent: (body) => request("/api/cs/admin/agents", { method: "POST", body }),
  updateAgent: (id, body) =>
    request(`/api/cs/admin/agents/${id}`, { method: "PATCH", body }),
  officeIps: () => request("/api/cs/admin/office-ips"),
  setOfficeIps: (ips) =>
    request("/api/cs/admin/office-ips", { method: "PUT", body: { ips } }),
  audit: (params) => request("/api/cs/admin/audit", { params }),

  // ── 전화 상담 ─────────────────────────────────────────────
  // 접두사가 /api/cs 그대로인 것은 일부러다. 사무실 IP·기기승인 관문을
  // 전화 화면에도 똑같이 걸기 위해서다.

  // 고객
  customers: (params) => request("/api/cs/customers", { params }),
  customer: (id, reveal = false) =>
    request(`/api/cs/customers/${id}`, { params: reveal ? { reveal: "true" } : null }),
  createCustomer: (body) => request("/api/cs/customers", { method: "POST", body }),
  updateCustomer: (id, body) =>
    request(`/api/cs/customers/${id}`, { method: "PUT", body }),
  lookupCustomer: (phone) => request("/api/cs/customers/lookup", { params: { phone } }),
  customerConsultations: (id, params) =>
    request(`/api/cs/customers/${id}/consultations`, { params }),
  customerCalls: (id, params) => request(`/api/cs/customers/${id}/call-logs`, { params }),

  // 상담
  consultations: (params) => request("/api/cs/consultations", { params }),
  consultation: (id) => request(`/api/cs/consultations/${id}`),
  createConsultation: (body) => request("/api/cs/consultations", { method: "POST", body }),
  updateConsultation: (id, body) =>
    request(`/api/cs/consultations/${id}`, { method: "PUT", body }),
  assignConsultation: (id, counselor_id) =>
    request(`/api/cs/consultations/${id}/assign`, { method: "POST", body: { counselor_id } }),

  // 상담원
  counselors: () => request("/api/cs/counselors"),
  myCounselor: () => request("/api/cs/counselors/me"),
  setMyStatus: (status) =>
    request("/api/cs/counselors/me/status", { method: "PUT", body: { status } }),
  updateCounselor: (id, body) =>
    request(`/api/cs/counselors/${id}`, { method: "PUT", body }),
  setCounselorOrder: (counselor_ids) =>
    request("/api/cs/counselors/order", { method: "PUT", body: { counselor_ids } }),

  // 통화
  activeCalls: () => request("/api/cs/calls/active"),
  callLogs: (params) => request("/api/cs/call-logs", { params }),
  answerCall: (id) => request(`/api/cs/calls/${id}/answer`, { method: "POST" }),
  rejectCall: (id) => request(`/api/cs/calls/${id}/reject`, { method: "POST" }),
  hangupCall: (id) => request(`/api/cs/calls/${id}/hangup`, { method: "POST" }),
  transferCall: (id, body) =>
    request(`/api/cs/calls/${id}/transfer`, { method: "POST", body }),
  outboundCall: (phone_number, customer_id = null) =>
    request("/api/cs/calls/outbound", { method: "POST", body: { phone_number, customer_id } }),
  linkCallCustomer: (id, customer_id) =>
    request(`/api/cs/calls/${id}/customer`, { method: "POST", body: { customer_id } }),
  // 개발용. 서버가 Mock Provider 일 때만 열린다.
  mockIncoming: (phone_number) =>
    request("/api/cs/calls/mock/incoming", { method: "POST", body: { phone_number } }),
  // 발신 통화에서 상대가 받았다고 가정한다(Mock 전용).
  mockAnswered: (id) => request(`/api/cs/calls/${id}/mock/answered`, { method: "POST" }),

  // 설정·통계
  phoneSettings: () => request("/api/cs/phone/settings"),
  savePhoneSettings: (body) => request("/api/cs/phone/settings", { method: "PUT", body }),
  phoneSummary: () => request("/api/cs/phone/summary"),
  // 브라우저 전화기 등록용 단기 자격증명. 사업자 API 키는 서버 밖으로 안 나온다.
  webrtcToken: () => request("/api/cs/phone/webrtc-token", { method: "POST" }),
  dropWebrtcToken: () => request("/api/cs/phone/webrtc-token", { method: "DELETE" }),
  statistics: () => request("/api/cs/statistics"),
  // 전화 소리(수신 벨·발신음·고객 대기음)
  phoneSounds: () => request("/api/cs/phone/sounds"),
  deletePhoneSound: (kind) =>
    request(`/api/cs/phone/sounds/${kind}`, { method: "DELETE" }),
  uploadPhoneSound: async (kind, blob, filename) => {
    const body = new FormData();
    body.append("file", blob, filename);
    const headers = {};
    const token = getToken();
    const device = getDevice();
    if (token) headers.Authorization = `Bearer ${token}`;
    if (device) headers["X-CS-Device"] = device;
    const res = await fetch(`/api/cs/phone/sounds/${kind}`, {
      method: "PUT", headers, body,
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error(detailOf(data) || `올리지 못했습니다 (${res.status})`);
    return data;
  },

  consultationOptions: () => request("/api/cs/consultation-options"),
  saveConsultationOptions: (body) =>
    request("/api/cs/consultation-options", { method: "PUT", body }),
  inquiryTypes: () => request("/api/cs/inquiry-types"),
  createInquiryType: (body) => request("/api/cs/inquiry-types", { method: "POST", body }),
  updateInquiryType: (id, body) =>
    request(`/api/cs/inquiry-types/${id}`, { method: "PUT", body }),
};

/** 실시간 통화 알림 주소.
 *  브라우저 WebSocket 은 헤더를 못 붙이므로 토큰을 쿼리로 넘긴다.
 *  서버는 HTTP 와 똑같이 권한·기기승인을 다시 확인한다. */
export function callsSocketUrl() {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const url = new URL(`${proto}//${window.location.host}/api/cs/ws/calls`);
  const token = getToken();
  const device = getDevice();
  if (token) url.searchParams.set("token", token);
  if (device) url.searchParams.set("device", device);
  return url.toString();
}
