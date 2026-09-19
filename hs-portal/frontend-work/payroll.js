/* 급여 화면 — 출퇴근 기반 시급 계산, 월별 급여명세서, PDF.
 *
 * app.js(api, esc, state, go, $), visits.js(fmtN), settlement.js(won, curMonth,
 * shiftMonth) 다음에 읽혀야 한다.
 *
 * 계산은 전부 서버(payroll.py)가 한다. 이 파일은 보여 주고 입력만 받는다.
 */

'use strict';

const payState = { month: '', open: null };

const hmText = (min) => {
  const h = Math.floor((min || 0) / 60), m = (min || 0) % 60;
  return m ? `${h}시간 ${m}분` : `${h}시간`;
};

function lastMonth() { return shiftMonth(curMonth(), -1); }

async function downloadPayslip(month, userId, name) {
  const q = new URLSearchParams({ month });
  if (userId) q.set('user_id', userId);
  const r = await fetch(`${API}/payroll/pdf?${q}`, { headers: { Authorization: 'Bearer ' + state.token } });
  if (!r.ok) {
    let msg = `받지 못했습니다 (${r.status})`;
    try { msg = (await r.json()).detail || msg; } catch (_) { /* 본문 없음 */ }
    alert(msg);
    return;
  }
  const blob = await r.blob();
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `급여명세서_${month}_${name || state.me.name}.pdf`;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

// ───────────────────────────────────────────────────────────────────────────
// 관리자
// ───────────────────────────────────────────────────────────────────────────

async function pagePayroll() {
  if (state.me.role !== 'admin') return pageMyPayslips();
  const month = payState.month || lastMonth();
  payState.month = month;

  const [list, profiles, rates] = await Promise.all([
    api('/payroll?month=' + month), api('/payroll/profiles'), api('/payroll/settings'),
  ]);

  let html = `<div class="card">
    <div class="filterbar">
      <div class="btnrow">
        <button class="mini" onclick="payGo(-1)">◀ 이전 달</button>
        <b style="font-size:16px;padding:0 6px">${esc(month.replace('-', '년 '))}월 급여</b>
        <button class="mini" onclick="payGo(1)" ${month >= curMonth() ? 'disabled' : ''}>다음 달 ▶</button>
        ${list.locked ? '<span class="tag done">정산 완료 · 명세서 확정</span>'
          : '<span class="tag p1">초안 · 출퇴근이 바뀌면 따라 바뀜</span>'}
      </div>
      <div class="btnrow" style="margin-left:auto">
        <button class="mini" onclick="settleState.month='${month}';go('settlement')">정산 탭에서 ${list.locked ? '확인' : '정산 완료하기'}</button>
      </div>
    </div>
    <p class="muted small" style="margin:8px 0 0">정산 탭에서 이 달을 <b>정산 완료</b>하면 명세서가 확정되고 PDF 로 받을 수 있습니다.
      확정 전까지는 출퇴근 기록과 명세서 항목을 고칠 수 있습니다.</p>
  </div>

  <div class="grid g3">
    ${statTile(list.totals.gross, '지급 총액(원)', 'brand')}
    ${statTile(list.totals.total_deduction, '공제 총액(원)')}
    ${statTile(list.totals.net, '실수령 합계(원)', 'good')}
  </div>

  <div class="card">
    <div class="card-head"><h2>직원별 명세 <span class="muted">${list.slips.length}명</span></h2></div>
    <div class="tablewrap"><table>
      <tr><th>이름</th><th>구분</th><th>시급</th><th>근무</th><th style="text-align:right">지급</th>
        <th style="text-align:right">공제</th><th style="text-align:right">실수령</th><th></th></tr>
      ${list.slips.map((x) => `<tr>
        <td><b>${esc(x.name)}</b>${x.warnings.length ? ' <span class="tag late" title="' + esc(x.warnings.join('\n')) + '">확인 필요</span>' : ''}</td>
        <td>${x.employment === 'freelancer' ? '프리랜서' : '근로자'}</td>
        <td>${won(x.hourly_wage)}</td>
        <td>${x.work_days}일 · ${hmText(x.work_minutes)}</td>
        <td style="text-align:right">${won(x.gross)}</td>
        <td style="text-align:right">− ${won(x.total_deduction)}</td>
        <td style="text-align:right"><b>${won(x.net)}</b></td>
        <td><div class="btnrow">
          <button class="mini ${payState.open === x.user_id ? 'on' : ''}" onclick="payOpen(${x.user_id})">상세</button>
          ${x.status === 'final' ? `<button class="mini" onclick="downloadPayslip('${month}', ${x.user_id}, window.__payNames[${x.user_id}])">PDF</button>` : ''}
        </div></td>
      </tr>`).join('') || '<tr><td colspan="8" class="empty">이 달 급여 대상이 없습니다. 아래에서 직원 시급을 정해 주세요.</td></tr>'}
    </table></div>
  </div>

  <div id="payDetail"></div>

  <div class="card">
    <div class="card-head"><h2>직원별 급여 기본값</h2>
      <span class="muted">최저시급 ${won(rates.min_wage)} · 식대 비과세 월 ${won(rates.meal_limit)}까지</span></div>
    <div class="tablewrap"><table>
      <tr><th>이름</th><th>구분</th><th>시급(원)</th><th>식대(원)</th><th>고정수당 이름</th><th>고정수당(원)</th><th>사번</th><th>소속</th><th></th></tr>
      ${profiles.map((p) => `<tr id="prof${p.user_id}" ${p.is_active ? '' : 'style="opacity:.55"'}>
        <td><b>${esc(p.name)}</b>${p.configured ? '' : ' <span class="tag p1">미설정</span>'}</td>
        <td><select data-k="employment" style="margin:0;min-width:92px">
          <option value="employee" ${p.employment === 'employee' ? 'selected' : ''}>근로자</option>
          <option value="freelancer" ${p.employment === 'freelancer' ? 'selected' : ''}>프리랜서</option></select></td>
        <td><input data-k="hourly_wage" type="number" min="0" step="10" value="${p.hourly_wage}" style="margin:0;width:100px"></td>
        <td><input data-k="meal_allowance" type="number" min="0" step="1000" value="${p.meal_allowance}" style="margin:0;width:100px"></td>
        <td><input data-k="fixed_allowance_name" value="${esc(p.fixed_allowance_name)}" style="margin:0;width:100px"></td>
        <td><input data-k="fixed_allowance" type="number" min="0" step="1000" value="${p.fixed_allowance}" style="margin:0;width:100px"></td>
        <td><input data-k="employee_no" value="${esc(p.employee_no)}" style="margin:0;width:80px"></td>
        <td><input data-k="department" value="${esc(p.department)}" style="margin:0;width:90px"></td>
        <td><button class="mini on" onclick="saveProfile(${p.user_id})">저장</button></td>
      </tr>`).join('') || '<tr><td colspan="9" class="empty">직원 계정이 없습니다</td></tr>'}
    </table></div>
  </div>

  <div class="card">
    <div class="card-head"><h2>공제 요율</h2><span class="muted">해마다 바뀝니다 · 공단 고지 요율로 확인해 주세요 · 정산 완료된 달에는 적용되지 않음</span></div>
    <div class="rate-grid">
      ${[['company_name', '회사명', 'text'], ['pay_day', '지급일(다음 달 며칠)', 'number'],
         ['min_wage', '최저시급(원)', 'number'], ['meal_limit', '식대 비과세 한도(원)', 'number'],
         ['pension_rate', '국민연금 근로자(%)', 'number'], ['pension_min', '연금 기준소득 하한(원)', 'number'],
         ['pension_max', '연금 기준소득 상한(원)', 'number'], ['health_rate', '건강보험 근로자(%)', 'number'],
         ['ltc_rate', '장기요양(건보료의 %)', 'number'], ['employment_rate', '고용보험 근로자(%)', 'number'],
         ['freelancer_rate', '프리랜서 원천징수(%)', 'number']].map(([k, l, t]) =>
        `<label>${l}<input id="rate_${k}" type="${t}" step="any" value="${esc(rates[k])}"></label>`).join('')}
    </div>
    <div class="btnrow" style="justify-content:flex-end"><button class="primary" onclick="saveRates()">요율 저장</button></div>
  </div>`;

  window.__payNames = Object.fromEntries(list.slips.map((x) => [x.user_id, x.name]));
  $('page').innerHTML = html;
  if (payState.open) payOpen(payState.open, true);
}

function payGo(d) { payState.month = shiftMonth(payState.month, d); payState.open = null; go('payroll'); }

async function saveProfile(uid) {
  const row = $('prof' + uid);
  const body = {};
  row.querySelectorAll('[data-k]').forEach((el) => {
    body[el.dataset.k] = el.type === 'number' ? Number(el.value || 0) : el.value;
  });
  try {
    await api(`/payroll/profiles/${uid}`, { method: 'PUT', body: JSON.stringify(body) });
    go('payroll');
  } catch (e) { alert(e.message); }
}

async function saveRates() {
  const body = {};
  document.querySelectorAll('[id^="rate_"]').forEach((el) => { body[el.id.slice(5)] = el.value; });
  try { await api('/payroll/settings', { method: 'PUT', body: JSON.stringify(body) }); go('payroll'); }
  catch (e) { alert(e.message); }
}

async function payOpen(uid, keep) {
  if (!keep && payState.open === uid) { payState.open = null; $('payDetail').innerHTML = ''; return; }
  payState.open = uid;
  let d;
  try { d = await api(`/payroll/slip?month=${payState.month}&user_id=${uid}`); }
  catch (e) { alert(e.message); return; }
  const final = d.status === 'final';
  window.__slip = d;

  $('payDetail').innerHTML = `<div class="card slip">
    <div class="card-head"><h2>${esc(d.name)} · ${esc(d.month)} ${final ? '<span class="tag done">확정</span>' : '<span class="tag p1">초안</span>'}</h2>
      <div class="btnrow">
        ${final ? `<button class="primary" onclick="downloadPayslip('${d.month}', ${d.user_id}, window.__slip.name)">PDF 받기</button>` : ''}
        <button class="mini" onclick="payOpen(${uid})">닫기</button>
      </div></div>
    ${d.warnings.length ? `<div class="notice warn-box" style="margin:0 0 12px">${d.warnings.map(esc).join('<br>')}</div>` : ''}

    <div class="grid g2">
      <div>
        <h3 class="subh">지급 항목</h3>
        <table>${d.items.map((x) => `<tr><td>${esc(x.name)}${x.taxable ? '' : ' <span class="tag hold">비과세</span>'}
            <div class="muted small">${esc(x.calc)}</div></td><td style="text-align:right"><b>${won(x.amount)}</b></td></tr>`).join('')}
          <tr class="row-on"><td><b>지급 총액</b></td><td style="text-align:right"><b>${won(d.gross)}</b></td></tr></table>
      </div>
      <div>
        <h3 class="subh">공제 항목</h3>
        <table>${d.deductions.map((x) => `<tr><td>${esc(x.name)}<div class="muted small">${esc(x.calc)}</div></td>
            <td style="text-align:right"><b>${won(x.amount)}</b></td></tr>`).join('')}
          <tr class="row-on"><td><b>공제 총액</b></td><td style="text-align:right"><b>${won(d.total_deduction)}</b></td></tr>
          <tr><td><b>실수령액</b></td><td style="text-align:right;font-size:18px"><b>${won(d.net)}</b></td></tr></table>
      </div>
    </div>

    ${final ? '' : `<div class="card-inner">
      <h3 class="subh">이 달 입력</h3>
      <div class="row">
        ${d.employment === 'employee' ? `<label>근로소득세(원)<input id="pIncomeTax" type="number" min="0" step="10" value="${d.income_tax_input}">
          <small>간이세액표·세무사가 알려준 금액. 지방소득세 10%는 자동</small></label>` : ''}
        <label>비고<input id="pNote" maxlength="300" value="${esc(d.note || '')}"></label>
      </div>
      <div id="pExtras">${(d.extras || []).map(extraRow).join('')}</div>
      <div class="btnrow" style="justify-content:space-between">
        <button class="mini" onclick="$('pExtras').insertAdjacentHTML('beforeend', extraRow({}))">+ 추가 지급·조정 항목</button>
        <button class="primary" onclick="saveSlip(${uid})">이 달 입력 저장</button>
      </div>
    </div>`}

    <h3 class="subh" style="margin-top:14px">출퇴근 기록 <span class="muted small">${d.work_days}일 · ${hmText(d.work_minutes)}</span></h3>
    <div class="tablewrap"><table>
      <tr><th>날짜</th><th>출근</th><th>퇴근</th><th>휴게</th><th>근무</th><th></th><th></th></tr>
      ${d.days.map((x) => `<tr>
        <td>${esc(x.day)}</td><td>${esc(x.first)}</td><td>${esc(x.left || (x.in_progress ? '근무 중' : '-'))}</td>
        <td>${x.break}분</td><td><b>${hmText(x.minutes)}</b></td>
        <td>${x.auto_closed && !x.edited ? '<span class="tag late">자동 마감 · 확인</span>' : ''}${x.edited ? '<span class="tag hold">수정됨</span>' : ''}</td>
        <td>${final ? '' : `<button class="mini" onclick="payEditDay(${uid}, '${x.day}', '${x.first}', '${x.left || ''}')">고치기</button>`}</td>
      </tr>`).join('') || '<tr><td colspan="7" class="empty">이 달 출퇴근 기록이 없습니다</td></tr>'}
    </table></div>
    ${final ? '' : `<div class="btnrow" style="margin-top:8px"><button class="mini" onclick="payAddDay(${uid})">+ 기록 없는 날 추가</button></div>`}

    ${d.weeks && d.weeks.length ? `<h3 class="subh" style="margin-top:14px">주휴수당</h3>
    <div class="tablewrap"><table>
      <tr><th>주</th><th>주 근무</th><th>주휴 인정</th><th style="text-align:right">주휴수당</th></tr>
      ${d.weeks.map((w) => `<tr><td>${esc(w.from)} ~ ${esc(w.to)}</td><td>${hmText(w.minutes)}</td>
        <td>${w.eligible ? hmText(w.juhyu_minutes) : (w.finished ? '15시간 미만' : '진행 중')}</td>
        <td style="text-align:right">${won(w.pay)}</td></tr>`).join('')}
    </table></div>` : ''}
  </div>`;
  $('payDetail').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function extraRow(e) {
  return `<div class="row extra-row">
    <label>항목<input data-x="name" value="${esc(e.name || '')}" placeholder="예: 상여금, 교통비, 결근 공제"></label>
    <label>금액(원, 빼려면 −)<input data-x="amount" type="number" step="10" value="${e.amount ?? ''}"></label>
    <label>과세<select data-x="taxable"><option value="1" ${e.taxable === false ? '' : 'selected'}>과세</option>
      <option value="0" ${e.taxable === false ? 'selected' : ''}>비과세</option></select></label>
    <button class="mini danger" style="align-self:center" onclick="this.parentNode.remove()">빼기</button>
  </div>`;
}

async function saveSlip(uid) {
  const extras = [...document.querySelectorAll('#pExtras .extra-row')].map((r) => ({
    name: r.querySelector('[data-x="name"]').value,
    amount: Number(r.querySelector('[data-x="amount"]').value || 0),
    taxable: r.querySelector('[data-x="taxable"]').value === '1',
  })).filter((x) => x.name.trim());
  const body = { extras, note: $('pNote').value };
  if ($('pIncomeTax')) body.income_tax = Number($('pIncomeTax').value || 0);
  try {
    await api(`/payroll/slip?month=${payState.month}&user_id=${uid}`, { method: 'PATCH', body: JSON.stringify(body) });
    go('payroll');
  } catch (e) { alert(e.message); }
}

async function payEditDay(uid, day, first, left) {
  const f = prompt(`${day} 출근 시각 (09:30 형식)`, first);
  if (f === null) return;
  const l = prompt(`${day} 퇴근 시각 (비우면 퇴근 기록을 지웁니다)`, left);
  if (l === null) return;
  try {
    await api(`/attendance/${uid}?on=${day}`, { method: 'PATCH', body: JSON.stringify({ first_seen: f, left_at: l }) });
    go('payroll');
  } catch (e) { alert(e.message); }
}

function payAddDay(uid) {
  const day = prompt('날짜 (2026-09-01 형식)', `${payState.month}-01`);
  if (!day) return;
  payEditDay(uid, day, '09:00', '18:00');
}

// ───────────────────────────────────────────────────────────────────────────
// 직원 본인
// ───────────────────────────────────────────────────────────────────────────

async function pageMyPayslips() {
  const rows = await api('/payroll/me');
  $('page').innerHTML = `<div class="card">
    <div class="card-head"><h2>내 급여명세서</h2><span class="muted">정산 완료된 달만 보입니다</span></div>
    <div class="tablewrap"><table>
      <tr><th>월</th><th>지급일</th><th>근무</th><th style="text-align:right">지급</th><th style="text-align:right">공제</th><th style="text-align:right">실수령</th><th></th></tr>
      ${rows.map((x) => `<tr>
        <td><b>${esc(x.month)}</b></td><td>${esc(x.pay_date)}</td><td>${hmText(x.work_minutes)}</td>
        <td style="text-align:right">${won(x.gross)}</td><td style="text-align:right">− ${won(x.total_deduction)}</td>
        <td style="text-align:right"><b>${won(x.net)}</b></td>
        <td><div class="btnrow"><button class="mini" onclick="myPayOpen('${x.month}')">보기</button>
          <button class="mini on" onclick="downloadPayslip('${x.month}')">PDF</button></div></td>
      </tr>`).join('') || '<tr><td colspan="7" class="empty">아직 확정된 급여명세서가 없습니다</td></tr>'}
    </table></div>
  </div><div id="payDetail"></div>`;
}

async function myPayOpen(month) {
  let d;
  try { d = await api(`/payroll/slip?month=${month}`); } catch (e) { alert(e.message); return; }
  $('payDetail').innerHTML = `<div class="card slip">
    <div class="card-head"><h2>${esc(d.month)} 급여명세서</h2>
      <button class="primary" onclick="downloadPayslip('${d.month}')">PDF 받기</button></div>
    <div class="grid g2">
      <div><h3 class="subh">지급 항목</h3><table>${d.items.map((x) => `<tr><td>${esc(x.name)}<div class="muted small">${esc(x.calc)}</div></td>
        <td style="text-align:right"><b>${won(x.amount)}</b></td></tr>`).join('')}
        <tr class="row-on"><td><b>지급 총액</b></td><td style="text-align:right"><b>${won(d.gross)}</b></td></tr></table></div>
      <div><h3 class="subh">공제 항목</h3><table>${d.deductions.map((x) => `<tr><td>${esc(x.name)}<div class="muted small">${esc(x.calc)}</div></td>
        <td style="text-align:right"><b>${won(x.amount)}</b></td></tr>`).join('')}
        <tr class="row-on"><td><b>공제 총액</b></td><td style="text-align:right"><b>${won(d.total_deduction)}</b></td></tr>
        <tr><td><b>실수령액</b></td><td style="text-align:right;font-size:18px"><b>${won(d.net)}</b></td></tr></table></div>
    </div>
    <h3 class="subh" style="margin-top:14px">근무 내역 <span class="muted small">${d.work_days}일 · ${hmText(d.work_minutes)}</span></h3>
    <div class="tablewrap"><table><tr><th>날짜</th><th>출근</th><th>퇴근</th><th>휴게</th><th>근무</th></tr>
      ${d.days.map((x) => `<tr><td>${esc(x.day)}</td><td>${esc(x.first)}</td><td>${esc(x.left || '-')}</td><td>${x.break}분</td><td>${hmText(x.minutes)}</td></tr>`).join('')}
    </table></div>
  </div>`;
}
