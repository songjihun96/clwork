/* 우리업무 — 화면 동작.
 *
 * 빌드 도구를 안 쓴다. 이 폴더를 nginx 가 그대로 내보내고 브라우저가 바로 읽는다.
 * 배포가 zip 수동 적용이라, `npm run build` 가 끼면 배포 한 단계가 늘고 그만큼
 * 틀어질 자리가 생긴다. 화면이 복잡해지면 그때 옮기면 된다.
 *
 * **권한은 서버가 정한다.** 여기서 메뉴를 숨기는 건 보기 편하라고 하는 것일 뿐,
 * 막는 건 서버다(work.py). 화면 코드는 사용자가 얼마든지 고칠 수 있다.
 */

'use strict';

const $ = (id) => document.getElementById(id);
const API = '/api/work';

const state = { token: localStorage.getItem('work_token') || '', me: null, page: '' };

const PRIORITY = ['보통', '중요', '급함'];
const TASK_LABEL = { todo: '할 일', doing: '진행 중', done: '완료', hold: '보류' };
const REQ_LABEL = { new: '미확인', reading: '확인함', answered: '답변함', closed: '종료' };

const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// ───────────────────────────────────────────────────────────────────────────
// 서버와 주고받기
// ───────────────────────────────────────────────────────────────────────────

async function api(path, opts = {}) {
  const r = await fetch(API + path, {
    ...opts,
    headers: {
      'Content-Type': 'application/json',
      ...(state.token ? { Authorization: 'Bearer ' + state.token } : {}),
      ...(opts.headers || {}),
    },
  });
  let data = null;
  try { data = await r.json(); } catch (_) { data = null; }
  if (r.status === 401) { logout(); throw new Error('로그인이 필요합니다.'); }
  if (!r.ok) throw new Error(errorText(data, r.status));
  return data;
}

// 입력 검사에 걸리면 서버가 **목록**으로 답한다(어느 칸이 왜 틀렸는지).
// 그걸 그대로 Error 에 넣으면 화면에 "[object Object]" 가 뜬다 — 실제로 그랬다.
const FIELD_KO = {
  login_id: '아이디', name: '이름', title: '제목', body: '내용',
  new_password: '새 비밀번호', password: '비밀번호',
  assignee_id: '담당자', org_id: '소속 기업', priority: '중요도',
  due_at: '기한', phone: '연락처', memo: '메모', contact: '담당자',
};

function ruleKo(e) {
  const m = String(e.msg || '');
  const n = (e.ctx && (e.ctx.min_length ?? e.ctx.max_length));
  if (/at least/.test(m)) return `${n}자 이상이어야 합니다`;
  if (/at most/.test(m)) return `${n}자 이하여야 합니다`;
  if (/[Ff]ield required/.test(m)) return '반드시 넣어야 합니다';
  if (/valid integer|valid number/.test(m)) return '숫자여야 합니다';
  if (/valid email/.test(m)) return '메일 주소 형식이 아닙니다';
  return m;
}

function errorText(data, status) {
  const d = data && data.detail;
  if (typeof d === 'string') return d;
  if (Array.isArray(d) && d.length) {
    return d.map((e) => {
      const key = (e.loc || []).filter((x) => x !== 'body').join('.');
      return `${FIELD_KO[key] || key} — ${ruleKo(e)}`;
    }).join('\n');
  }
  return `오류가 발생했습니다 (${status})`;
}

function logout() {
  state.token = '';
  state.me = null;
  localStorage.removeItem('work_token');
  $('appView').hidden = true;
  $('loginView').hidden = false;
}

// ───────────────────────────────────────────────────────────────────────────
// 뼈대
// ───────────────────────────────────────────────────────────────────────────

const MENU = {
  admin: [
    ['home', '한눈에'], ['tasks', '업무'], ['requests', '요청사항'],
    ['attendance', '출근'], ['payroll', '급여'], ['visits', '방문 통계'], ['sales', '매출 통계'], ['settlement', '정산'], ['users', '계정'],
  ],
  staff: [['home', '한눈에'], ['tasks', '내 할 일'], ['myatt', '내 출근'], ['payroll', '급여명세서']],
  partner: [['home', '한눈에'], ['visits', '방문 통계'], ['sales', '매출 통계'], ['settlement', '정산'], ['requests', '요청사항']],
};

function drawNav() {
  // 협력사 중 정산을 받는 곳이 아니면 정산 메뉴를 숨긴다(서버도 막는다).
  const items = (MENU[state.me.role] || []).filter(([k]) =>
    !(k === 'settlement' && state.me.role === 'partner' && !state.canSettle)
    && !(k === 'sales' && state.me.role === 'partner' && !state.canSales));
  $('nav').innerHTML = items.map(([k, label]) =>
    `<button data-page="${k}" class="${state.page === k ? 'on' : ''}">${label}</button>`).join('');
  $('nav').querySelectorAll('button').forEach((b) => {
    b.onclick = () => go(b.dataset.page);
  });
  const roleName = { admin: '관리자', staff: '직원', partner: state.me.org_name || '협업기업' };
  $('who').textContent = `${state.me.name} · ${roleName[state.me.role]}`;
}

async function go(page) {
  state.page = page;
  drawNav();
  $('page').innerHTML = '<div class="card"><div class="empty">불러오는 중…</div></div>';
  try {
    const render = {
      home: pageHome, tasks: pageTasks, requests: pageRequests,
      attendance: pageAttendance, users: pageUsers, myatt: pageMyAttendance,
      visits: pageVisits, settlement: pageSettlement, payroll: pagePayroll, sales: pageSales,
    }[page];
    await render();
  } catch (e) {
    $('page').innerHTML = `<div class="card"><div class="empty">${esc(e.message)}</div></div>`;
  }
}

// ───────────────────────────────────────────────────────────────────────────
// 한눈에
// ───────────────────────────────────────────────────────────────────────────

async function pageHome() {
  const s = await api('/summary');
  let html = '';

  if (s.role === 'admin') {
    const a = s.attendance, r = s.requests, t = s.tasks_all;
    html += workCard(s.my_today);
    html += `<div class="grid g4">
      ${stat(a.working, `근무 중 · 출근 ${a.present}/${a.staff_total}명`,
        a.present >= a.staff_total ? 'good' : 'warn')}
      ${stat(r.new, '미확인 요청', r.new ? 'crit' : 'good')}
      ${stat(t.doing, '진행 중인 업무', 'brand')}
      ${stat(t.todo, '아직 시작 안 함')}
    </div>`;
    const [att, reqs, tasks] = await Promise.all([
      api('/attendance'), api('/requests?status_filter=new,reading'), api('/tasks'),
    ]);
    html += `<div class="grid g2">
      <div class="card">
        <div class="card-head"><h2>오늘 출근</h2>
          <span class="muted">${esc(att.date)} · 기준 ${esc(att.start_time)}</span></div>
        <div class="att">${att.rows.map(attRow).join('') || '<div class="empty">직원이 없습니다</div>'}</div>
        <p class="muted small" style="margin:10px 0 0">${esc(att.note)}</p>
      </div>
      <div class="card">
        <div class="card-head"><h2>확인할 요청</h2>
          <button class="mini" onclick="go('requests')">전체 보기</button></div>
        <div class="list">${reqs.slice(0, 6).map((r) => reqItem(r, true)).join('')
          || '<div class="empty">확인할 요청이 없습니다</div>'}</div>
      </div>
    </div>`;
    html += `<div class="card">
      <div class="card-head"><h2>진행 중인 업무</h2>
        <button class="mini" onclick="go('tasks')">전체 보기</button></div>
      <div class="list">${tasks.filter((t) => t.status !== 'done').slice(0, 8)
        .map((t) => taskItem(t, true)).join('') || '<div class="empty">배분한 업무가 없습니다</div>'}</div>
    </div>`;
    html += '<div id="settleCard"></div><div id="visitCard"></div><div id="serverCard"></div>';
  }

  if (s.role === 'staff') {
    const m = s.my_tasks;
    html += workCard(s.my_today);
    html += '<div id="incentiveCard"></div>';
    html += `<div class="grid g3">
      ${stat(m.todo, '할 일', m.todo ? 'brand' : 'good')}
      ${stat(m.doing, '진행 중')}
      ${stat(m.overdue, '기한 지남', m.overdue ? 'crit' : 'good')}
    </div>`;
    const tasks = await api('/tasks');
    html += `<div class="card">
      <div class="card-head"><h2>내 할 일</h2><span class="muted">체크하면 완료됩니다</span></div>
      <div class="list">${tasks.filter((t) => t.status !== 'done').map((t) => taskItem(t)).join('')
        || '<div class="empty">받은 업무가 없습니다</div>'}</div>
    </div>`;
  }

  if (s.role === 'partner') {
    const r = s.requests;
    html += `<div class="grid g3">
      ${stat(r.open, '처리 중', r.open ? 'warn' : 'good')}
      ${stat(r.answered, '답변 받음', 'good')}
      ${stat(r.total, '전체 요청')}
    </div>`;
    html += '<div id="visitCard"></div>';
    const reqs = await api('/requests');
    html += `<div class="card">
      <div class="card-head"><h2>우리 요청</h2>
        <button class="primary" onclick="openReq()">요청 등록</button></div>
      <div class="list">${reqs.slice(0, 8).map((x) => reqItem(x)).join('')
        || '<div class="empty">등록한 요청이 없습니다</div>'}</div>
    </div>`;
  }
  $('page').innerHTML = html;
  // 방문·서버 카드는 따로 채운다. 로그를 읽느라 늦어도 업무 화면은 먼저 뜬다.
  if (s.role === 'admin' || s.role === 'partner') loadVisitCard();
  if (s.role === 'admin') loadSettleCard();
  if (s.role === 'staff') loadIncentiveCard();
  if (s.role === 'admin') loadServerCard();
}

/** 서버 상태 카드. 실패해도 조용히 비워 둔다 — 업무를 보러 온 사람에게
 *  감시 설정 오류를 들이밀 이유는 없다(안내 한 줄이면 충분하다). */
async function loadServerCard() {
  const box = $('serverCard');
  if (!box) return;
  let d;
  try { d = await api('/admin/server'); } catch (_) { return; }
  if (!d.available) {
    box.innerHTML = `<div class="card"><div class="card-head"><h2>서버</h2></div>
      <div class="empty">${esc(d.reason || '서버 상태를 가져오지 못했습니다')}</div></div>`;
    return;
  }
  try {
    renderServerCard(box, d);
  } catch (e) {
    box.innerHTML = `<div class="card"><div class="card-head"><h2>서버</h2></div>`
      + `<div class="empty">서버 상태를 그리지 못했습니다 (${esc(e.message)})</div></div>`;
  }
}

function renderServerCard(box, d) {
  const tone = d.status === 'critical' ? 'crit' : d.status === 'warn' ? 'warn' : 'good';
  const label = { ok: '정상', warn: '주의', critical: '위험' }[d.status] || d.status;
  const sites = Object.entries(d.visitors || {})
    .map(([k, v]) => `${esc(k)} ${v}명`).join(' · ') || '집계 없음';

  box.innerHTML = `<div class="card">
    <div class="card-head">
      <h2>서버 <span class="tag ${tone === 'good' ? 'done' : tone === 'warn' ? 'p1' : 'new'}">${label}</span></h2>
      <span class="muted">${esc(d.collected_at)} 기준 · 지금 접속 ${esc(sites)}</span>
    </div>
    ${d.alerts.length ? `<div class="list" style="margin-bottom:12px">${d.alerts.map((a) =>
      `<div class="item"><div class="body"><div class="title">${esc(a.message)}</div></div>
       <div class="side"><span class="tag ${a.level === 'critical' ? 'new' : 'p1'}">${
         a.level === 'critical' ? '위험' : '주의'}</span></div></div>`).join('')}
      ${d.alert_count > d.alerts.length
        ? `<div class="muted small">그 밖에 ${d.alert_count - d.alerts.length}건</div>` : ''}
    </div>` : ''}
    <div class="grid g4">
      ${mini('CPU', d.cpu + '%', d.cpu >= 88 ? 'crit' : d.cpu >= 70 ? 'warn' : '')}
      ${mini('메모리', d.mem + '%', d.mem >= 92 ? 'crit' : d.mem >= 80 ? 'warn' : '')}
      ${mini('디스크', d.disk + '%', d.disk >= 88 ? 'crit' : d.disk >= 75 ? 'warn' : '',
        d.disk_days_left != null ? `${d.disk_days_left}일 뒤 가득 참` : '')}
      ${mini('서비스', d.down.length ? `${d.down.length}개 내려감` : '모두 정상',
        d.down.length ? 'crit' : 'good', d.down.join(', '))}
    </div>
    <div class="kv-card" style="margin-top:12px">
      ${kv('최근 60분 서버 오류', `${d.errors_5xx}건`, d.errors_5xx ? 'warn' : '')}
      ${kv('인증서', d.ssl_days_left == null ? '-' : `${d.ssl_days_left}일 남음`,
        d.ssl_days_left != null && d.ssl_days_left <= 14 ? 'warn' : '')}
      ${kv('마지막 백업', d.backup_age_hours == null ? '못 찾음'
        : `${d.backup_age_hours}시간 전`, d.backup_age_hours == null ? 'warn' : '')}
      ${kv('30일 가동률', d.uptime_percent == null ? '표본 모으는 중' : `${d.uptime_percent}%`)}
    </div>
  </div>`;
}

/** 오늘 내 근무. 출근은 자동으로 찍혀 있고, 퇴근만 누른다. */
function workCard(t) {
  if (!t || !t.tracked) {
    return `<div class="card"><div class="card-head"><h2>오늘 근무</h2></div>
      <div class="empty">출근 기록을 만드는 중입니다</div></div>`;
  }
  if (t.left_at) {
    return `<div class="card">
      <div class="card-head"><h2>오늘 근무</h2>
        <button class="mini" onclick="clockOut(false)">퇴근 취소</button></div>
      <div class="work-row">
        <div><div class="muted small">출근</div><b>${esc(t.first_seen)}</b>
          ${t.late ? '<span class="tag late">지각</span>' : ''}</div>
        <div><div class="muted small">퇴근</div><b>${esc(t.left_at)}</b>
          ${t.auto_closed ? '<span class="tag hold">자동</span>' : ''}</div>
        <div><div class="muted small">근무</div><b>${t.worked_hours}시간</b></div>
      </div>
      <p class="muted small" style="margin:10px 0 0">오늘 퇴근을 찍었습니다. 수고하셨습니다.</p>
    </div>`;
  }
  return `<div class="card">
    <div class="card-head"><h2>오늘 근무</h2>
      <span class="muted">출근 ${esc(t.first_seen)}${t.late ? ' · 지각' : ''}</span></div>
    <button class="primary wide" onclick="clockOut(true)">퇴근하기</button>
    <p class="muted small" style="margin:9px 0 0">
      출근은 접속할 때 자동으로 남습니다. 퇴근만 눌러 주세요.</p>
  </div>`;
}

async function clockOut(on) {
  if (on && !confirm('오늘 퇴근으로 기록할까요?')) return;
  try {
    await api('/attendance/leave' + (on ? '' : '/cancel'), { method: 'POST' });
    go(state.page);
  } catch (e) { alert(e.message); }
}

const kv = (label, value, tone) =>
  `<div class="kv"><span>${esc(label)}</span><b class="${tone || ''}">${esc(value)}</b></div>`;

const mini = (label, value, tone, note) =>
  `<div><div class="muted small">${esc(label)}</div>
   <div style="font-size:20px;font-weight:700" class="${tone === 'crit' ? 'crit' : ''}">${esc(value)}</div>
   ${note ? `<div class="muted small">${esc(note)}</div>` : ''}</div>`;

const stat = (n, t, tone) =>
  `<div class="card stat"><span class="n ${tone || ''}">${n}</span><span class="t">${esc(t)}</span></div>`;

/** "0분 전 활동"은 사람이 쓰는 말이 아니다. 방금 움직였으면 그렇게 적는다. */
function sinceText(min) {
  if (min <= 2) return '지금 활동 중';
  if (min < 60) return `${min}분 전 활동`;
  const h = Math.floor(min / 60);
  return h < 24 ? `${h}시간 전 활동` : `${Math.floor(h / 24)}일 전 활동`;
}

const ATT_TAIL = {
  absent: () => '미접속',
  left: (r) => `${r.first_seen} ~ ${r.left_at} · ${r.worked_hours}시간`,
  in: (r) => `${r.first_seen} 출근 · ${sinceText(r.minutes_ago)}`,
  away: (r) => `${r.first_seen} 출근 · ${sinceText(r.minutes_ago)}`,
};

const attRow = (r) => `<div class="att-row ${r.state === 'absent' ? 'absent' : ''}">
  <span class="dot ${r.state}"></span>
  <span class="nm">${esc(r.name)}</span>
  ${r.late ? '<span class="tag late">지각</span>' : ''}
  ${r.state === 'left' ? '<span class="tag closed">퇴근</span>' : ''}
  ${r.auto_closed ? '<span class="tag hold" title="퇴근을 안 눌러 마지막 활동 시각으로 닫음">자동</span>' : ''}
  ${r.edited ? '<span class="tag hold" title="관리자가 고친 기록">수정</span>' : ''}
  ${r.role === 'admin' ? '<span class="tag">관리자</span>' : ''}
  <span class="tm">${esc((ATT_TAIL[r.state] || ATT_TAIL.in)(r))}</span>
  ${state.me && state.me.role === 'admin'
    ? `<button class="mini" onclick="editAtt(${r.user_id}, '${esc(r.name)}', '${r.first_seen || ''}', '${r.left_at || ''}')">고치기</button>`
    : ''}
</div>`;

/** 출근·퇴근 시각 고치기. 깜빡한 날, 외근한 날은 자동 기록이 실제와 다르다. */
async function editAtt(userId, name, first, left) {
  const day = window.__attDate || new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 10);
  const f = prompt(`${name} — ${day} 출근 시각 (09:30 형식, 비우면 그대로)`, first);
  if (f === null) return;
  const l = prompt(`${name} — 퇴근 시각 (비우면 퇴근 기록을 지웁니다)`, left);
  if (l === null) return;
  try {
    await api(`/attendance/${userId}?on=${day}`, {
      method: 'PATCH',
      body: JSON.stringify({ first_seen: f, left_at: l }),
    });
    go(state.page);
  } catch (e) { alert(e.message); }
}

// ───────────────────────────────────────────────────────────────────────────
// 업무
// ───────────────────────────────────────────────────────────────────────────

function taskItem(t, showAssignee) {
  const done = t.status === 'done';
  const canCheck = state.me.role === 'staff' || state.me.role === 'admin';
  return `<div class="item ${done ? 'done' : ''}">
    ${canCheck ? `<button class="check ${done ? 'on' : ''}" title="완료 표시"
        onclick="toggleTask(${t.id}, '${done ? 'todo' : 'done'}')"></button>` : ''}
    <div class="body">
      <div class="title ${done ? 'strike' : ''}">${esc(t.title)}</div>
      <div class="meta">
        ${showAssignee ? esc(t.assignee) + ' · ' : ''}${esc(t.created_at)}
        ${t.due_at ? ` · 기한 ${esc(t.due_at)}` : ''}
        ${t.progress_note ? ` · ${esc(t.progress_note)}` : ''}
      </div>
      ${t.body ? `<div class="desc">${esc(t.body)}</div>` : ''}
    </div>
    <div class="side">
      ${t.priority ? `<span class="tag p${t.priority}">${PRIORITY[t.priority]}</span>` : ''}
      <span class="tag ${t.status}">${TASK_LABEL[t.status]}</span>
      ${t.overdue ? '<span class="tag overdue">기한 지남</span>' : ''}
      ${state.me.role === 'staff' && !done
        ? `<button class="mini" onclick="noteTask(${t.id})">메모</button>` : ''}
      ${state.me.role === 'admin'
        ? `<div class="btnrow"><button class="mini" onclick="openTask(${t.id})">고치기</button>
           <button class="mini" onclick="delTask(${t.id})">삭제</button></div>` : ''}
    </div>
  </div>`;
}

async function pageTasks() {
  const admin = state.me.role === 'admin';
  const [tasks, users] = await Promise.all([
    api('/tasks'), admin ? api('/admin/users') : Promise.resolve([]),
  ]);
  window.__users = users.filter((u) => u.role !== 'partner' && u.is_active);
  const open = tasks.filter((t) => t.status !== 'done');
  const done = tasks.filter((t) => t.status === 'done');

  $('page').innerHTML = `
    <div class="card">
      <div class="card-head">
        <h2>${admin ? '전체 업무' : '내 할 일'} <span class="muted">${open.length}건</span></h2>
        ${admin ? '<button class="primary" onclick="openTask()">업무 배분</button>' : ''}
      </div>
      <div class="list">${open.map((t) => taskItem(t, admin)).join('')
        || '<div class="empty">진행 중인 업무가 없습니다</div>'}</div>
    </div>
    ${done.length ? `<div class="card">
      <div class="card-head"><h2>완료 <span class="muted">${done.length}건</span></h2></div>
      <div class="list">${done.slice(0, 20).map((t) => taskItem(t, admin)).join('')}</div>
    </div>` : ''}`;
}

async function toggleTask(id, status) {
  try {
    await api('/tasks/' + id, { method: 'PATCH', body: JSON.stringify({ status }) });
    go(state.page);
  } catch (e) { alert(e.message); }
}

async function noteTask(id) {
  const note = prompt('진행 상황을 짧게 남겨 주세요');
  if (note === null) return;
  try {
    await api('/tasks/' + id, {
      method: 'PATCH',
      body: JSON.stringify({ progress_note: note, status: 'doing' }),
    });
    go(state.page);
  } catch (e) { alert(e.message); }
}

async function delTask(id) {
  if (!confirm('이 업무를 지울까요? 되돌릴 수 없습니다.')) return;
  try { await api('/tasks/' + id, { method: 'DELETE' }); go(state.page); }
  catch (e) { alert(e.message); }
}

function openTask(id) {
  const f = $('taskForm');
  f.reset();
  const users = window.__users || [];
  f.assignee_id.innerHTML = users.map((u) =>
    `<option value="${u.id}">${esc(u.name)}${u.memo ? ' · ' + esc(u.memo) : ''}</option>`).join('');
  $('taskDlgTitle').textContent = id ? '업무 고치기' : '업무 배분';
  f.id.value = id || '';
  $('taskMsg').hidden = true;
  $('taskDlg').showModal();
}

// ───────────────────────────────────────────────────────────────────────────
// 요청사항
// ───────────────────────────────────────────────────────────────────────────

function reqItem(r, compact) {
  const admin = state.me.role === 'admin';
  return `<div class="item">
    <div class="body">
      <div class="title">${esc(r.title)}</div>
      <div class="meta">${esc(r.org_name)}${r.author ? ' · ' + esc(r.author) : ''} · ${esc(r.created_at)}</div>
      ${!compact && r.body ? `<div class="desc">${esc(r.body)}</div>` : ''}
      ${r.admin_note ? `<div class="desc"><b>답변</b> ${esc(r.admin_note)}${
        r.handled_at ? ` <span class="muted">(${esc(r.handled_at)})</span>` : ''}</div>` : ''}
    </div>
    <div class="side">
      ${r.priority ? `<span class="tag p${r.priority}">${PRIORITY[r.priority]}</span>` : ''}
      <span class="tag ${r.status}">${REQ_LABEL[r.status]}</span>
      ${admin ? `<div class="btnrow">
        <button class="mini" onclick="answerReq(${r.id})">답변</button>
        <button class="mini" onclick="reqToTask(${r.id}, ${JSON.stringify(r.title).replace(/"/g, '&quot;')})">업무로</button>
      </div>` : ''}
    </div>
  </div>`;
}

async function pageRequests() {
  const admin = state.me.role === 'admin';
  const reqs = await api('/requests');
  const open = reqs.filter((r) => r.status === 'new' || r.status === 'reading');
  const rest = reqs.filter((r) => r.status !== 'new' && r.status !== 'reading');
  $('page').innerHTML = `
    <div class="card">
      <div class="card-head">
        <h2>${admin ? '받은 요청' : '우리 요청'} <span class="muted">처리 중 ${open.length}건</span></h2>
        ${admin ? '' : '<button class="primary" onclick="openReq()">요청 등록</button>'}
      </div>
      <div class="list">${open.map((r) => reqItem(r)).join('')
        || '<div class="empty">처리할 요청이 없습니다</div>'}</div>
    </div>
    ${rest.length ? `<div class="card">
      <div class="card-head"><h2>지난 요청 <span class="muted">${rest.length}건</span></h2></div>
      <div class="list">${rest.slice(0, 30).map((r) => reqItem(r)).join('')}</div>
    </div>` : ''}`;
}

function openReq() { $('reqForm').reset(); $('reqMsg').hidden = true; $('reqDlg').showModal(); }

async function answerReq(id) {
  const note = prompt('답변을 적어 주세요');
  if (note === null) return;
  try {
    await api('/requests/' + id, {
      method: 'PATCH', body: JSON.stringify({ admin_note: note, status: 'answered' }),
    });
    go(state.page);
  } catch (e) { alert(e.message); }
}

async function reqToTask(id, title) {
  if (!(window.__users || []).length) {
    window.__users = (await api('/admin/users')).filter((u) => u.role !== 'partner' && u.is_active);
  }
  openTask();
  const f = $('taskForm');
  f.title.value = title;
  f.id.value = '';
  f.dataset.requestId = id;
  try {
    await api('/requests/' + id, { method: 'PATCH', body: JSON.stringify({ status: 'reading' }) });
  } catch (_) { /* 표시만 못 바꾼 것이니 넘어간다 */ }
}

// ───────────────────────────────────────────────────────────────────────────
// 출근
// ───────────────────────────────────────────────────────────────────────────

async function pageAttendance() {
  const on = new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 10);
  const att = await api('/attendance?on=' + (window.__attDate || on));
  $('page').innerHTML = `<div class="card">
    <div class="card-head">
      <h2>출근 현황 <span class="muted">${att.present} / ${att.total}명</span></h2>
      <input type="date" value="${esc(att.date)}" style="width:auto;margin:0"
             onchange="window.__attDate=this.value; go('attendance')">
    </div>
    <div class="att">${att.rows.map(attRow).join('') || '<div class="empty">직원이 없습니다</div>'}</div>
    <p class="muted small" style="margin:12px 0 0">${esc(att.note)}
      출근 기준 시각은 ${esc(att.start_time)} 이며 서버 설정(WORK_START_TIME)으로 바꿉니다.</p>
  </div>`;
}

async function pageMyAttendance() {
  const rows = await api('/attendance/me?days=30');
  $('page').innerHTML = `<div class="card">
    <div class="card-head"><h2>내 출근 기록 <span class="muted">최근 30일</span></h2></div>
    <div class="tablewrap"><table>
      <tr><th>날짜</th><th>출근</th><th>퇴근</th><th>근무</th><th></th></tr>
      ${rows.map((r) => `<tr><td>${esc(r.date)}</td><td>${esc(r.first_seen)}</td>
        <td>${esc(r.left_at || '–')}</td>
        <td>${r.worked_hours != null ? r.worked_hours + '시간' : '–'}</td>
        <td>${r.late ? '<span class="tag late">지각</span>' : ''}
            ${r.auto_closed ? '<span class="tag hold">자동</span>' : ''}
            ${r.edited ? '<span class="tag hold">수정</span>' : ''}</td></tr>`).join('')
        || '<tr><td colspan="5" class="empty">기록이 없습니다</td></tr>'}
    </table></div>
    <p class="muted small" style="margin:12px 0 0">
      출근은 그날 처음 접속한 시각으로 자동 기록되고, 퇴근은 버튼을 누른 시각입니다.
      퇴근을 안 누른 날은 비어 있습니다.</p>
  </div>`;
}

// ───────────────────────────────────────────────────────────────────────────
// 계정·기업
// ───────────────────────────────────────────────────────────────────────────

const ROLE_LABEL = { admin: '관리자', staff: '직원', partner: '협업기업' };

async function pageUsers() {
  const [users, orgs] = await Promise.all([api('/admin/users'), api('/admin/orgs')]);
  window.__orgs = orgs;
  $('page').innerHTML = `
    <div class="card">
      <div class="card-head"><h2>계정 <span class="muted">${users.length}개</span></h2>
        <button class="primary" onclick="openUser()">계정 만들기</button></div>
      <div class="tablewrap"><table>
        <tr><th>이름</th><th>아이디</th><th>권한</th><th>소속</th><th>마지막 로그인</th><th></th></tr>
        ${users.map((u) => `<tr${u.is_active ? '' : ' style="opacity:.5"'}>
          <td><b>${esc(u.name)}</b>${u.memo ? ` <span class="muted">${esc(u.memo)}</span>` : ''}</td>
          <td>${esc(u.login_id)}</td>
          <td><span class="tag">${ROLE_LABEL[u.role] || u.role}</span>
              ${u.must_change_password ? '<span class="tag p1">비번 미변경</span>' : ''}</td>
          <td>${esc(u.org_name || '-')}</td>
          <td class="muted">${esc(u.last_login_at || '없음')}</td>
          <td><div class="btnrow">
            <button class="mini" onclick="resetPw(${u.id})">비번 초기화</button>
            <button class="mini" onclick="toggleUser(${u.id}, ${!u.is_active})">${u.is_active ? '중지' : '재개'}</button>
            ${u.id !== state.me.id ? `<button class="mini danger" onclick="deleteUser(${u.id})">삭제</button>` : ''}
          </div></td>
        </tr>`).join('')}
      </table></div>
    </div>
    <div class="card">
      <div class="card-head"><h2>협업기업 <span class="muted">${orgs.length}곳</span></h2>
        <button class="primary" onclick="newOrg()">+ 기업 추가</button></div>
      ${orgs.length ? '' : `<p class="muted small" style="margin:0 0 10px">
        협업기업 계정을 만들려면 기업을 먼저 등록해야 합니다.</p>`}
      <div class="tablewrap"><table>
        <tr><th>이름</th><th>담당</th><th>계정 수</th><th>등록일</th><th></th></tr>
        ${orgs.map((o, i) => `<tr><td><b>${esc(o.name)}</b></td><td>${esc(o.contact || '-')}</td>
          <td>${o.user_count}</td><td class="muted">${esc(o.created_at)}</td>
          <td><button class="mini" onclick="editOrgVisits(${o.id}, window.__orgs[${i}].name)">방문 통계 공개</button></td></tr>`).join('')
          || '<tr><td colspan="5" class="empty">등록된 기업이 없습니다</td></tr>'}
      </table></div>
    </div>`;
}

function openUser() {
  const f = $('userForm');
  f.reset();
  f.org_id.innerHTML = (window.__orgs || []).map((o) =>
    `<option value="${o.id}">${esc(o.name)}</option>`).join('');
  $('orgWrap').hidden = true;
  $('userMsg').hidden = true;
  $('userDlg').showModal();
}

async function newOrg() {
  const name = prompt('협업기업 이름');
  if (!name) return;
  const contact = prompt('담당자·연락처 (선택)') || '';
  try {
    const o = await api('/admin/orgs', { method: 'POST', body: JSON.stringify({ name, contact }) });
    window.__orgs = (window.__orgs || []).concat(o);
    go('users');
  } catch (e) { alert(e.message); }
}

async function resetPw(id) {
  if (!confirm('임시 비밀번호를 새로 만들까요? 기존 비밀번호는 못 쓰게 됩니다.')) return;
  try {
    const r = await api(`/admin/users/${id}/reset-password`, { method: 'POST' });
    showTemp(r.temp_password);
    go('users');
  } catch (e) { alert(e.message); }
}

async function toggleUser(id, active) {
  try {
    await api('/admin/users/' + id, {
      method: 'PATCH', body: JSON.stringify({ is_active: active }),
    });
    go('users');
  } catch (e) { alert(e.message); }
}

/** 계정 삭제. 지우기 전에 무엇이 같이 사라지는지 보여 주고 한 번 더 묻는다. */
async function deleteUser(id) {
  let p;
  try { p = await api(`/admin/users/${id}?preview=true`, { method: 'DELETE' }); }
  catch (e) { alert(e.message); return; }
  const lines = [`'${p.name}' 계정을 삭제합니다. 되돌릴 수 없습니다.`, ''];
  if (p.role !== 'partner') {
    lines.push(`· 받은 업무 ${p.tasks}건 삭제${p.open_tasks ? ` (그중 끝나지 않은 업무 ${p.open_tasks}건)` : ''}`);
    lines.push(`· 출근 기록 ${p.attendance_days}일치 삭제`);
  }
  if (p.requests) lines.push(`· 올린 요청 ${p.requests}건은 남깁니다 (작성자만 비움)`);
  if (p.role !== 'partner' && p.attendance_days) {
    lines.push('', '출근 기록을 남겨야 한다면 삭제 대신 \'중지\'를 쓰세요.');
  }
  if (!confirm(lines.join('\n'))) return;
  try {
    await api(`/admin/users/${id}`, { method: 'DELETE' });
    go('users');
  } catch (e) { alert(e.message); }
}

function showTemp(pw) {
  $('tempBox').textContent = pw;
  $('tempDlg').showModal();
}

// ───────────────────────────────────────────────────────────────────────────
// 대화상자 연결
// ───────────────────────────────────────────────────────────────────────────

function onSubmit(formId, msgId, handler) {
  $(formId).onsubmit = async (ev) => {
    if (!ev.submitter || ev.submitter.value !== 'save') return;   // 취소는 그냥 닫는다
    ev.preventDefault();
    const f = ev.target;
    const data = Object.fromEntries(new FormData(f).entries());
    $(msgId).hidden = true;
    try {
      await handler(data, f);
      f.closest('dialog').close();
      go(state.page);
    } catch (e) {
      $(msgId).textContent = e.message;
      $(msgId).hidden = false;
    }
  };
}

function setupDialogs() {
  onSubmit('taskForm', 'taskMsg', async (d, f) => {
    const body = {
      title: d.title, body: d.body,
      assignee_id: Number(d.assignee_id),
      priority: Number(d.priority || 0),
      due_at: d.due_at ? new Date(d.due_at).toISOString() : null,
    };
    if (f.dataset.requestId) { body.request_id = Number(f.dataset.requestId); delete f.dataset.requestId; }
    if (d.id) await api('/tasks/' + d.id, { method: 'PATCH', body: JSON.stringify(body) });
    else await api('/tasks', { method: 'POST', body: JSON.stringify(body) });
  });

  onSubmit('reqForm', 'reqMsg', (d) => api('/requests', {
    method: 'POST',
    body: JSON.stringify({ title: d.title, body: d.body, priority: Number(d.priority || 0) }),
  }));

  onSubmit('userForm', 'userMsg', async (d) => {
    const r = await api('/admin/users', {
      method: 'POST',
      body: JSON.stringify({
        login_id: d.login_id, name: d.name, role: d.role,
        org_id: d.role === 'partner' ? Number(d.org_id) : null,
        phone: d.phone || '', memo: d.memo || '',
      }),
    });
    showTemp(r.temp_password);
  });

  onSubmit('pwForm', 'pwMsg', async (d) => {
    await api('/me/password', {
      method: 'POST',
      body: JSON.stringify({
        current_password: d.current_password || '',
        new_password: d.new_password,
      }),
    });
    state.me.must_change_password = false;
    $('notice').hidden = true;
  });

  $('userForm').role.onchange = async (ev) => {
    const isPartner = ev.target.value === 'partner';
    $('orgWrap').hidden = !isPartner;
    if (!isPartner) return;
    // 기업이 하나도 없으면 빈 드롭다운만 열려서 왜 안 되는지 알 수가 없다.
    if (!(window.__orgs || []).length) {
      $('userMsg').textContent = '등록된 협업기업이 없습니다. 먼저 기업을 추가해 주세요.';
      $('userMsg').hidden = false;
      if (confirm('등록된 협업기업이 없습니다. 지금 추가할까요?')) {
        $('userDlg').close();
        await newOrg();
      }
    }
  };
}

// ───────────────────────────────────────────────────────────────────────────
// 켜기
// ───────────────────────────────────────────────────────────────────────────

function openPw() {
  $('pwForm').reset();
  $('pwMsg').hidden = true;
  $('curWrap').hidden = !!(state.me && state.me.must_change_password);
  $('pwDlg').showModal();
}

async function enter() {
  state.me = await api('/me');
  state.canSettle = false;
  state.canSales = false;
  if (state.me.role === 'partner') {
    try { await api('/settlement/months?count=1'); state.canSettle = true; } catch (_) { /* 정산 대상 아님 */ }
    // 매출 통계는 지정된 홈페이지가 있는 협력사면 볼 수 있다(그 사이트 매출만).
    const d = new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 10);
    try { await api(`/sales?start=${d}&end=${d}`); state.canSales = true; } catch (_) { /* 지정 사이트 없음 */ }
  }
  $('loginView').hidden = true;
  $('appView').hidden = false;
  if (state.me.must_change_password) {
    $('notice').hidden = false;
    $('notice').innerHTML = '처음 받은 비밀번호를 쓰고 있습니다. '
      + '<b style="cursor:pointer;text-decoration:underline" onclick="openPw()">지금 바꾸기</b>';
  } else {
    $('notice').hidden = true;
  }
  go((MENU[state.me.role] || [['home']])[0][0]);
}

/** 위젯 모드. 주소에 ?widget=1 이 있거나 창이 아주 좁으면 켜진다.
 *  내용은 '한눈에' 그대로다 — 권한에 따라 이미 달라지므로 화면을 따로 만들지 않는다. */
function setupWidget() {
  const params = new URLSearchParams(location.search);
  const on = params.has('widget')
    ? params.get('widget') !== '0'
    : innerWidth < 560;
  document.body.classList.toggle('widget', on);
  if (!on) return;

  // 위젯은 띄워 두고 안 건드리는 물건이라, 새 업무가 들어오면 알아서 보여야 한다.
  // 탭이 가려져 있으면 쉰다 — 안 보는 화면을 갱신하느라 서버를 부를 이유가 없다.
  setInterval(() => {
    if (!document.hidden && state.me && state.page === 'home') go('home');
  }, 60000);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && state.me && state.page === 'home') go('home');
  });
}

async function start() {
  setupDialogs();
  setupWidget();
  $('pwBtn').onclick = openPw;
  $('outBtn').onclick = logout;

  $('loginForm').onsubmit = async (ev) => {
    ev.preventDefault();
    const d = Object.fromEntries(new FormData(ev.target).entries());
    $('loginMsg').hidden = true;
    try {
      const r = await api('/auth/login', { method: 'POST', body: JSON.stringify(d) });
      state.token = r.token;
      localStorage.setItem('work_token', r.token);
      await enter();
    } catch (e) {
      $('loginMsg').textContent = e.message;
      $('loginMsg').hidden = false;
    }
  };

  if (state.token) {
    try { await enter(); return; } catch (_) { /* 만료된 토큰이면 로그인 화면 */ }
  }
  $('loginView').hidden = false;
}

start();
