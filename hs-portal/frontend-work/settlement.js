/* 정산 화면 — 매출 명세, 40:60 배분, 직원 인센티브.
 *
 * app.js 의 전역(api, esc, state, go, $)과 visits.js 의 fmtN/statTile 을 쓴다.
 * index.html 에서 그 둘 다음에 읽혀야 한다.
 *
 * 돈 화면이라 지키는 것:
 *   - 계산은 전부 서버가 한다. 여기서 더하거나 곱하지 않는다(반올림 규칙이
 *     두 군데로 갈라지면 화면과 실제 지급액이 1원이라도 달라진다).
 *   - 매출은 +, 환불은 − 로 **부호와 글자를 같이** 보여 준다. 색만으로 가르지 않는다.
 */

'use strict';

const settleState = { month: '' };

const won = (n) => `${fmtN(Math.round(n || 0))}원`;

function curMonth() {
  return new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 7);
}

function shiftMonth(month, delta) {
  let [y, m] = month.split('-').map(Number);
  m += delta;
  while (m < 1) { m += 12; y -= 1; }
  while (m > 12) { m -= 12; y += 1; }
  return `${y}-${String(m).padStart(2, '0')}`;
}

async function pageSettlement() {
  const month = settleState.month || curMonth();
  settleState.month = month;
  const admin = state.me.role === 'admin';

  let d, months, settings = null;
  try {
    [d, months, settings] = await Promise.all([
      api('/settlement?month=' + month),
      api('/settlement/months?count=12'),
      admin ? api('/settlement/settings') : Promise.resolve(null),
    ]);
  } catch (e) {
    $('page').innerHTML = `<div class="card"><div class="card-head"><h2>정산</h2></div>
      <div class="empty">${esc(e.message)}</div></div>`;
    return;
  }

  const isCur = month === curMonth();
  const status = d.locked
    ? `<span class="tag done">정산 완료 ${esc(d.locked_at)}</span>`
    : isCur ? '<span class="tag p1">진행 중 · 예상</span>' : '<span class="tag">마감 전</span>';

  let html = `
    <div class="card">
      <div class="filterbar">
        <div class="btnrow">
          <button class="mini" onclick="settleGo(-1)">◀ 이전 달</button>
          <b style="font-size:16px;padding:0 6px">${esc(month.replace('-', '년 '))}월</b>
          <button class="mini" onclick="settleGo(1)" ${isCur ? 'disabled' : ''}>다음 달 ▶</button>
          ${status}
        </div>
        ${admin ? `<div class="btnrow" style="margin-left:auto">
          ${d.locked
            ? `<button class="mini" onclick="payState.month='${month}';go('payroll')">급여명세서 보기</button>
               <button class="mini" onclick="settleUnlock()">정산 완료 취소</button>`
            : (!isCur ? '<button class="primary" onclick="settleLock()">정산 완료</button>' : '')}
        </div>` : ''}
      </div>
      ${d.warnings && d.warnings.length ? `<div class="notice warn-box">${d.warnings.map(esc).join('<br>')}</div>` : ''}
      ${d.negative_net ? '<div class="notice warn-box">이 달은 환불이 매출보다 많아 나눌 금액이 없습니다(배분 0원).</div>' : ''}
    </div>`;

  // ── 흐름 ────────────────────────────────────────────────────────────────
  if (admin) {
    const r = d.rules;
    html += `<div class="card">
      <div class="card-head"><h2>자금 흐름</h2>
        <span class="muted">${esc(r.partner_org_name || '협력사 미지정')} ${r.partner_pct}% · 우리동네 소프트 ${r.our_pct}%</span></div>
      <div class="flow">
        ${flowBox('매출', d.sales)}
        <div class="flow-op">−</div>${flowBox('환불', d.refunds)}
        <div class="flow-op">=</div>${flowBox('순매출', d.net, 'brand')}
      </div>
      <div class="flow split">
        <div class="flow-col">
          ${flowBox(`협력사 몫 ${r.partner_pct}%`, d.partner_share, 'partner')}
          <div class="muted small">${esc(r.partner_org_name || '받는 협력사를 설정해 주세요')}
            ${d.locked ? paidToggle('partner', '협력사 지급', d.paid) : ''}</div>
        </div>
        <div class="flow-col">
          ${flowBox(`우리동네 소프트 몫 ${r.our_pct}%`, d.our_share, 'ours')}
          <div class="flow-sub">
            <div class="kv"><span>직원 인센티브 ${d.incentives.length}명 × ${won(d.incentive_each)}</span><b>− ${won(d.incentive_total)}</b></div>
            <div class="kv"><span>남는 금액</span><b>${won(d.our_remaining)}</b></div>
          </div>
        </div>
      </div>
      ${splitBar(d)}
    </div>`;

    html += `<div class="card">
      <div class="card-head"><h2>직원 인센티브</h2>
        <span class="muted">우리 몫의 ${r.incentive_pct}% · 1인당 월 최대 ${won(r.incentive_cap)} · 직원 각자</span></div>
      ${d.incentives.length ? `<div class="tablewrap"><table>
        <tr><th>직원</th><th>인센티브</th><th></th>${d.locked ? '<th>지급</th>' : ''}</tr>
        ${d.incentives.map((x) => `<tr>
          <td><b>${esc(x.name)}</b></td>
          <td><b>${won(x.amount)}</b></td>
          <td>${x.capped ? '<span class="tag p1">상한 적용</span>' : ''}</td>
          ${d.locked ? `<td>${paidToggle('user:' + x.user_id, '', d.paid)}</td>` : ''}
        </tr>`).join('')}
      </table></div>` : '<div class="empty">이 달 인센티브 대상 직원이 없습니다</div>'}
      <p class="muted small" style="margin:8px 0 0">대상: 그 달 말일까지 만들어져 있고 중지되지 않은 직원 계정.
        ${d.locked ? '마감 시점의 명단으로 고정됐습니다.' : '마감하면 이 명단과 금액이 고정됩니다.'}</p>
    </div>`;
  } else {
    html += `<div class="grid g4">
      ${statTile(d.sales, '매출(원)')}
      ${statTile(d.refunds, '환불(원)')}
      ${statTile(d.net, '순매출(원)', 'brand')}
      ${statTile(d.partner_share, `${esc(d.rules.partner_org_name)} 몫 ${d.rules.partner_pct}%(원)`, 'good')}
    </div>
    <div class="card"><div class="kv-card">
      <div class="kv"><span>지급 상태</span><b class="${d.partner_paid ? 'good' : ''}">${
        d.partner_paid ? '지급 완료' : d.locked ? '마감됨 · 지급 대기' : '마감 전(금액이 바뀔 수 있음)'}</b></div>
    </div></div>`;
  }

  // ── 결제 유형별 ─────────────────────────────────────────────────────────
  if (d.by_type) {
    html += `<div class="card">
      <div class="card-head"><h2>결제 유형별</h2>
        <button class="mini" onclick="salesState.start='${month}-01';salesState.end='';salesState.type='';go('sales')">기간·유형으로 자세히</button></div>
      <div class="tablewrap"><table>
        <tr><th>결제 유형</th><th style="text-align:right">건수</th><th style="text-align:right">매출</th><th style="text-align:right">환불</th><th style="text-align:right">순매출</th><th style="text-align:right">비율</th></tr>
        ${d.by_type.map((t) => `<tr><td><span class="swatch" style="background:${PTYPE_COLOR[t.key]}"></span>${esc(t.label)}</td>
          <td class="num">${fmtN(t.count)}건</td><td class="num">${won(t.sales)}</td>
          <td class="num">${t.refunds ? '− ' + won(t.refunds) : '-'}</td><td class="num"><b>${won(t.net)}</b></td>
          <td class="num">${t.ratio}%</td></tr>`).join('')}
      </table></div>
    </div>`;
  }

  // ── 사이트별 ────────────────────────────────────────────────────────────
  html += `<div class="grid g2">
    <div class="card">
      <div class="card-head"><h2>사이트별</h2></div>
      <div class="tablewrap"><table>
        <tr><th>사이트</th><th>매출</th><th>환불</th><th>순매출</th></tr>
        ${Object.entries(d.by_site).map(([k, v]) => `<tr><td>${esc(k)}</td>
          <td>${won(v.sales)}</td><td>− ${won(v.refunds)}</td><td><b>${won(v.net)}</b></td></tr>`).join('')
          || '<tr><td colspan="4" class="empty">이 달 매출이 없습니다</td></tr>'}
      </table></div>
    </div>
    <div class="card">
      <div class="card-head"><h2>월별 매출</h2><span class="muted">결제된 달 기준 · 줄을 누르면 그 달로 이동</span></div>
      <div class="tablewrap"><table>
        <tr><th>월</th><th>결제</th><th>매출</th><th>순매출</th><th>협력사</th>${admin ? '<th>인센티브</th><th>우리 남음</th>' : '<th>지급</th>'}<th></th></tr>
        ${months.map((x) => `<tr class="${x.month === month ? 'row-on' : ''}" style="cursor:pointer"
            onclick="settleState.month='${x.month}';go('settlement')">
          <td>${esc(x.month)}</td><td>${fmtN(x.order_count || 0)}건</td><td>${won(x.sales)}</td>
          <td><b>${won(x.net)}</b></td><td>${won(x.partner_share)}</td>
          ${admin ? `<td>${won(x.incentive_total)}</td><td>${won(x.our_remaining)}</td>`
            : `<td>${x.partner_paid ? '<span class="tag done">완료</span>' : ''}</td>`}
          <td>${x.locked ? '<span class="tag done">마감</span>' : ''}</td></tr>`).join('')}
      </table></div>
    </div>
  </div>`;

  // ── 명세 ────────────────────────────────────────────────────────────────
  html += `<div class="card">
    <div class="card-head"><h2>매출·환불 명세 <span class="muted">${d.lines.length}건</span></h2>
      ${admin && !d.locked ? '<button class="primary" onclick="settleAdd()">+ 직접 입력</button>' : ''}</div>
    <div class="tablewrap"><table>
      <tr><th>날짜</th><th>구분</th><th>사이트</th><th>항목</th><th style="text-align:right">금액</th>${admin ? '<th>참고</th><th></th>' : ''}</tr>
      ${d.lines.map((x) => `<tr>
        <td>${esc(x.day || '-')}</td>
        <td>${x.kind === 'sale' ? '<span class="tag done">매출</span>' : '<span class="tag new">환불</span>'}</td>
        <td>${esc(x.site)}</td>
        <td>${esc(x.label)}${x.source === 'manual' ? ' <span class="tag hold">수기</span>' : ''}</td>
        <td style="text-align:right;font-variant-numeric:tabular-nums"><b>${x.kind === 'sale' ? '+' : '−'} ${won(x.amount)}</b></td>
        ${admin ? `<td class="muted small">${esc(x.ref || '')}</td>
          <td>${x.source === 'manual' && !d.locked ? `<button class="mini danger" onclick="settleDel(${x.id})">삭제</button>` : ''}</td>` : ''}
      </tr>`).join('') || `<tr><td colspan="${admin ? 7 : 5}" class="empty">이 달 명세가 없습니다</td></tr>`}
    </table></div>
    <p class="muted small" style="margin:8px 0 0">매출은 입금 확인일, 환불은 환불한 날이 속한 달에 잡힙니다.
      유료 신청은 입금 확인 시각 기록이 없어 신청일 기준입니다.</p>
  </div>`;

  // ── 설정 (관리자) ───────────────────────────────────────────────────────
  if (admin && settings) {
    const orgs = await api('/admin/orgs').catch(() => []);
    html += `<div class="card">
      <div class="card-head"><h2>정산 규칙</h2><span class="muted">마감한 달에는 적용되지 않습니다</span></div>
      <div class="row">
        <label>협력사(몫을 받는 곳)
          <select id="sOrg"><option value="">— 선택 —</option>${orgs.map((o) =>
            `<option value="${o.id}" ${String(o.id) === settings.partner_org_id ? 'selected' : ''}>${esc(o.name)}</option>`).join('')}</select>
        </label>
        <label>협력사 몫(%)<input id="sPct" type="number" min="0" max="100" step="0.1" value="${esc(settings.partner_pct)}"></label>
        <label>인센티브(우리 몫의 %)<input id="sInc" type="number" min="0" max="100" step="0.1" value="${esc(settings.incentive_pct)}"></label>
        <label>1인당 월 상한(원)<input id="sCap" type="number" min="0" step="10000" value="${esc(settings.incentive_cap)}"></label>
      </div>
      <div class="btnrow" style="justify-content:space-between;align-items:center">
        <span class="muted small">기록해 결제 기록 연결: ${settings.diary_connected
          ? '<b class="good">연결됨</b>' : '<b class="crit">안 됨</b> — work-backend/.env 에 SALES_DIARY_DATABASE_URL 을 넣어 주세요'}</span>
        <button class="primary" onclick="settleSaveRules()">규칙 저장</button>
      </div>
    </div>`;
  }

  $('page').innerHTML = html;
}

const flowBox = (label, n, tone) =>
  `<div class="flow-box ${tone || ''}"><div class="muted small">${esc(label)}</div><b>${won(n)}</b></div>`;

function paidToggle(target, label, paid) {
  const at = (paid || {})[target];
  const safe = target.replace(/'/g, '');
  return `<label class="paidchk"><input type="checkbox" ${at ? 'checked' : ''}
    onchange="settlePaid('${safe}', this.checked)"> ${esc(label || '지급')}${at ? ` <span class="muted small">${esc(at)}</span>` : ''}</label>`;
}

/** 순매출이 어디로 가는지 한 줄 막대. 조각이 셋이라 누적 막대가 맞는 모양이다. */
function splitBar(d) {
  const total = Math.max(1, d.net);
  if (d.net <= 0) return '';
  const parts = [
    ['협력사', d.partner_share, 'var(--c-partner)'],
    ['직원 인센티브', d.incentive_total, 'var(--c-inc)'],
    ['우리동네 소프트 남음', d.our_remaining, 'var(--c-ours)'],
  ];
  return `<div class="splitbar" role="img" aria-label="순매출 배분">${parts.map(([l, v, c]) =>
      v > 0 ? `<span style="flex:${v / total};background:${c}" title="${esc(l)} ${won(v)}"></span>` : '').join('')}</div>
    <div class="legend-inline" style="margin-top:6px">${parts.map(([l, v, c]) =>
      `<span><span class="swatch" style="background:${c}"></span>${esc(l)} ${Math.round(v / total * 1000) / 10}%</span>`).join('')}</div>`;
}

function settleGo(delta) { settleState.month = shiftMonth(settleState.month, delta); go('settlement'); }

async function settleAct(fn) {
  try { await fn(); go('settlement'); } catch (e) { alert(e.message); }
}

function settleLock() {
  if (!confirm(`${settleState.month} 정산을 완료할까요?\n\n· 매출·배분·인센티브 금액이 고정됩니다\n· 직원별 급여명세서가 확정되고 PDF 로 받을 수 있습니다\n· 이 달 출퇴근 기록은 더 고칠 수 없습니다`)) return;
  settleAct(() => api(`/settlement/${settleState.month}/lock`, { method: 'POST' }));
}

function settleUnlock() {
  if (!confirm('정산 완료를 취소하면 금액과 급여명세서를 다시 계산합니다. 그사이 바뀐 결제·출퇴근 기록과 규칙이 반영됩니다. 취소할까요?')) return;
  settleAct(() => api(`/settlement/${settleState.month}/unlock`, { method: 'POST' }));
}

function settlePaid(target, on) {
  settleAct(() => api(`/settlement/${settleState.month}/paid`, {
    method: 'PATCH', body: JSON.stringify({ target, paid: on }),
  }));
}

function settleDel(id) {
  if (!confirm('이 줄을 지울까요?')) return;
  settleAct(() => api(`/settlement/entries/${id}`, { method: 'DELETE' }));
}

function settleAdd() {
  const f = $('ledgerForm');
  f.reset();
  f.month.value = settleState.month;
  $('ledgerMsg').hidden = true;
  $('ledgerDlg').showModal();
}

function settleSaveRules() {
  settleAct(() => api('/settlement/settings', {
    method: 'PUT',
    body: JSON.stringify({
      partner_org_id: $('sOrg').value,
      partner_pct: Number($('sPct').value),
      incentive_pct: Number($('sInc').value),
      incentive_cap: Number($('sCap').value),
    }),
  }));
}

function setupLedgerDialog() {
  const f = $('ledgerForm');
  if (!f) return;
  f.onsubmit = async (ev) => {
    if (!ev.submitter || ev.submitter.value !== 'save') return;
    ev.preventDefault();
    const d = Object.fromEntries(new FormData(f).entries());
    try {
      await api('/settlement/entries', {
        method: 'POST',
        body: JSON.stringify({
          month: d.month, kind: d.kind, site: d.site, amount: Number(d.amount),
          payment_type: d.payment_type || 'other',
          memo: d.memo || '', day: d.day || null,
        }),
      });
      $('ledgerDlg').close();
      go('settlement');
    } catch (e) {
      $('ledgerMsg').textContent = e.message;
      $('ledgerMsg').hidden = false;
    }
  };
}
setupLedgerDialog();

// ── 관리자 첫 화면: 이번 달 정산 요약 ──────────────────────────────────────

async function loadSettleCard() {
  const box = $('settleCard');
  if (!box) return;
  let d;
  try { d = await api('/settlement?month=' + curMonth()); } catch (_) { return; }
  box.innerHTML = `<div class="card">
    <div class="card-head"><h2>이번 달 정산 <span class="tag p1">예상</span></h2>
      <button class="mini" onclick="settleState.month='';go('settlement')">자세히</button></div>
    <div class="visit-mini">
      <div><div class="muted small">순매출</div><b>${won(d.net)}</b></div>
      <div><div class="muted small">협력사 ${d.rules.partner_pct}%</div><b>${won(d.partner_share)}</b></div>
      <div><div class="muted small">우리 몫 ${d.rules.our_pct}%</div><b>${won(d.our_share)}</b></div>
      <div><div class="muted small">인센티브 ${d.incentives.length}명</div><b>${won(d.incentive_total)}</b>
        <div class="muted small">1인 ${won(d.incentive_each)}</div></div>
    </div>
    ${d.warnings.length ? `<p class="muted small" style="margin:8px 0 0;color:var(--critical)">${d.warnings.map(esc).join(' / ')}</p>` : ''}
  </div>`;
}

// ── 직원 첫 화면: 내 인센티브 ─────────────────────────────────────────────

async function loadIncentiveCard() {
  const box = $('incentiveCard');
  if (!box) return;
  let d;
  try { d = await api('/incentive/me'); } catch (_) { return; }
  const cur = d.months[0];
  box.innerHTML = `<div class="card">
    <div class="card-head"><h2>내 인센티브</h2><span class="muted">월 최대 ${won(d.cap)}</span></div>
    <div class="visit-mini">
      <div><div class="muted small">${esc(cur.month)} ${cur.estimate ? '(예상)' : ''}</div>
        <b>${won(cur.amount)}</b>${cur.capped ? ' <span class="tag p1">상한</span>' : ''}</div>
    </div>
    <div class="tablewrap" style="margin-top:10px"><table>
      ${d.months.slice(1).map((x) => `<tr><td>${esc(x.month)}</td><td><b>${won(x.amount)}</b></td>
        <td>${x.paid_at ? '<span class="tag done">지급 완료</span>' : x.locked ? '<span class="tag">지급 대기</span>' : '<span class="muted small">마감 전</span>'}</td></tr>`).join('')}
    </table></div>
    <p class="muted small" style="margin:8px 0 0">이번 달 금액은 매출이 쌓이는 대로 바뀌며, 마감 후 확정됩니다.</p>
  </div>`;
}
