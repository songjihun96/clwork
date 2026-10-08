/* 매출 통계 — 기간·결제 유형별.
 *
 * app.js(api, esc, state, go, $)와 visits.js(fmtN, statTile), settlement.js(won)를
 * 쓴다. index.html 에서 그 셋 다음에 읽혀야 한다.
 *
 * 정산 화면과 같이 **계산은 서버가 한다.** 여기서는 받은 합계를 그대로 보여 준다
 * (합계를 다시 더하면 반올림·필터 규칙이 두 군데로 갈라진다).
 */

'use strict';

const salesState = { start: '', end: '', type: '' };

// 결제 유형 색. 색만으로 가르지 않도록 표에는 늘 이름을 같이 쓴다.
const PTYPE_COLOR = {
  personal: 'var(--c-personal)', school: 'var(--c-school)', udj: 'var(--c-udj)',
  video: 'var(--c-video)', other: 'var(--c-other)',
};

function kstToday() {
  return new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 10);
}

function salesPreset(k) {
  const today = kstToday();
  const [y, m] = today.split('-').map(Number);
  const pad = (n) => String(n).padStart(2, '0');
  const lastDay = (yy, mm) => new Date(Date.UTC(yy, mm, 0)).getUTCDate();
  if (k === 'this') { salesState.start = `${y}-${pad(m)}-01`; salesState.end = today; }
  if (k === 'last') {
    const [ly, lm] = m === 1 ? [y - 1, 12] : [y, m - 1];
    salesState.start = `${ly}-${pad(lm)}-01`;
    salesState.end = `${ly}-${pad(lm)}-${pad(lastDay(ly, lm))}`;
  }
  if (k === 'year') { salesState.start = `${y}-01-01`; salesState.end = today; }
  go('sales');
}

function salesApply() {
  salesState.start = $('slStart').value;
  salesState.end = $('slEnd').value;
  salesState.type = $('slType').value;
  go('sales');
}

function salesPickType(k) {
  salesState.type = salesState.type === k ? '' : k;
  go('sales');
}

async function pageSales() {
  const admin = state.me.role === 'admin';
  const qs = new URLSearchParams();
  if (salesState.start) qs.set('start', salesState.start);
  if (salesState.end) qs.set('end', salesState.end);
  if (salesState.type) qs.set('payment_type', salesState.type);

  let d, settings = null;
  try {
    [d, settings] = await Promise.all([
      api('/sales?' + qs.toString()),
      admin ? api('/settlement/settings') : Promise.resolve(null),
    ]);
  } catch (e) {
    $('page').innerHTML = `<div class="card"><div class="card-head"><h2>매출 통계</h2></div>
      <div class="empty">${esc(e.message)}</div></div>`;
    return;
  }
  salesState.start = d.start;
  salesState.end = d.end;

  const typeLabel = (k) => (d.payment_types.find((t) => t.key === k) || {}).label || k;

  let html = `
    <div class="card">
      <div class="card-head"><h2>매출 통계</h2>
        <span class="muted">결제 유형별 · 매출은 입금 확인일, 환불은 환불한 날 기준</span></div>
      ${d.sites ? `<p class="muted small" style="margin:0 0 10px">지정된 홈페이지의 매출만 보입니다: <b>${d.sites.map(esc).join(', ')}</b></p>` : ''}
      <div class="filterbar">
        <label style="margin:0">기간
          <span class="daterange">
            <input id="slStart" type="date" value="${esc(d.start)}" max="${esc(kstToday())}"> ~
            <input id="slEnd" type="date" value="${esc(d.end)}" max="${esc(kstToday())}">
          </span>
        </label>
        <label style="margin:0">결제 유형
          <select id="slType">
            <option value="">전체</option>
            ${d.payment_types.map((t) => `<option value="${t.key}" ${t.key === d.payment_type ? 'selected' : ''}>${esc(t.label)}</option>`).join('')}
          </select>
        </label>
        <div class="btnrow" style="align-self:flex-end">
          <button class="primary" onclick="salesApply()">조회</button>
          <button class="mini" onclick="salesPreset('this')">이번 달</button>
          <button class="mini" onclick="salesPreset('last')">지난 달</button>
          <button class="mini" onclick="salesPreset('year')">올해</button>
        </div>
      </div>
      ${d.warnings.length ? `<div class="notice warn-box">${d.warnings.map(esc).join('<br>')}</div>` : ''}
    </div>`;

  // ── 요약 ──
  const sel = d.selected;
  html += `<div class="grid g4">
    ${statTile(d.total.sales, '전체 매출(원)', 'brand')}
    ${statTile(d.total.count, '결제 건수')}
    ${statTile(d.total.refunds, '환불(원)')}
    ${statTile(d.total.net, '순매출(원)')}
  </div>`;
  if (sel) {
    html += `<div class="card"><div class="kv-card">
      <div class="kv"><span><span class="swatch" style="background:${PTYPE_COLOR[sel.key]}"></span>${esc(sel.label)} 매출</span>
        <b>${won(sel.sales)} · ${fmtN(sel.count)}건 · 전체의 ${sel.ratio}%</b></div>
    </div></div>`;
  }

  // ── 유형별 표 + 비율 막대 ──
  const maxSales = Math.max(1, ...d.types.map((t) => t.sales));
  html += `<div class="card">
    <div class="card-head"><h2>결제 유형별 매출</h2><span class="muted">${esc(d.start)} ~ ${esc(d.end)} · 줄을 누르면 그 유형만 봅니다</span></div>
    ${d.total.sales > 0 ? `<div class="splitbar" role="img" aria-label="결제 유형별 매출 비율">${d.types.map((t) =>
      t.sales > 0 ? `<span style="flex:${t.sales};background:${PTYPE_COLOR[t.key]}" title="${esc(t.label)} ${t.ratio}%"></span>` : '').join('')}</div>` : ''}
    <div class="tablewrap" style="margin-top:10px"><table class="sales-table">
      <tr><th>결제 유형</th><th style="text-align:right">결제 건수</th><th style="text-align:right">매출</th>
        <th style="text-align:right">환불</th><th style="text-align:right">순매출</th><th>비율</th></tr>
      ${d.types.map((t) => `<tr class="${t.key === d.payment_type ? 'row-on' : ''}" style="cursor:pointer" onclick="salesPickType('${t.key}')">
        <td><span class="swatch" style="background:${PTYPE_COLOR[t.key]}"></span><b>${esc(t.label)}</b></td>
        <td class="num">${fmtN(t.count)}건</td>
        <td class="num"><b>${won(t.sales)}</b></td>
        <td class="num">${t.refunds ? '− ' + won(t.refunds) : '-'}</td>
        <td class="num">${won(t.net)}</td>
        <td style="min-width:120px"><div class="ratio-bar"><span style="width:${t.sales / maxSales * 100}%;background:${PTYPE_COLOR[t.key]}"></span></div>
          <span class="muted small">${t.ratio}%</span></td>
      </tr>`).join('')}
      <tr class="sum-row"><td><b>총합</b></td><td class="num"><b>${fmtN(d.total.count)}건</b></td>
        <td class="num"><b>${won(d.total.sales)}</b></td><td class="num">${d.total.refunds ? '− ' + won(d.total.refunds) : '-'}</td>
        <td class="num"><b>${won(d.total.net)}</b></td><td class="muted small">100%</td></tr>
    </table></div>
    ${d.test.count || d.test.refunds ? `<p class="muted small" style="margin:8px 0 0">
      <span class="tag hold">테스트 결제 제외</span> 토스 테스트 키로 승인된 결제 ${fmtN(d.test.count)}건 · ${won(d.test.sales)}은 실제 돈이 오가지 않아 위 합계에서 뺐습니다.</p>` : ''}
  </div>`;

  // ── 매출 내역 ──
  html += `<div class="card">
    <div class="card-head"><h2>매출 내역 <span class="muted">${d.lines.length}건${d.payment_type ? ' · ' + esc(typeLabel(d.payment_type)) : ''}</span></h2></div>
    <div class="tablewrap"><table>
      <tr><th>날짜</th><th>구분</th><th>결제 유형</th><th>사이트</th><th>항목</th><th style="text-align:right">금액</th>${admin ? '<th>참고</th>' : ''}</tr>
      ${d.lines.slice(0, 500).map((x) => `<tr>
        <td>${esc(x.day || '-')}</td>
        <td>${x.kind === 'sale' ? '<span class="tag done">매출</span>' : '<span class="tag new">환불</span>'}</td>
        <td><span class="swatch" style="background:${PTYPE_COLOR[x.payment_type] || PTYPE_COLOR.other}"></span>${esc(typeLabel(x.payment_type))}</td>
        <td>${esc(x.site)}</td>
        <td>${esc(x.label)}${x.source === 'manual' ? ' <span class="tag hold">수기</span>' : ''}</td>
        <td class="num"><b>${x.kind === 'sale' ? '+' : '−'} ${won(x.amount)}</b></td>
        ${admin ? `<td class="muted small">${esc(x.ref || '')}</td>` : ''}
      </tr>`).join('') || `<tr><td colspan="${admin ? 7 : 6}" class="empty">이 기간 매출이 없습니다</td></tr>`}
    </table></div>
    ${d.lines.length > 500 ? '<p class="muted small">최근 500건만 보여 줍니다. 기간을 좁혀 보세요.</p>' : ''}
    <p class="muted small" style="margin:8px 0 0">마감한 달도 지금의 결제 기록으로 다시 계산합니다. 마감 뒤 환불 등이 있었다면 정산 화면의 고정 금액과 다를 수 있습니다.</p>
  </div>`;

  // ── 결제 유형 분류 (관리자) ──
  if (admin && settings) {
    html += `<div class="card">
      <div class="card-head"><h2>결제 유형 분류</h2><span class="muted">어느 결제 기록을 어느 유형으로 셀지 · 직접 입력은 입력할 때 고릅니다</span></div>
      <div class="tablewrap"><table>
        <tr><th>사이트</th><th>결제 기록</th><th>결제 유형</th></tr>
        ${settings.sources.map((s) => `<tr><td>${esc(s.site)}</td><td>${esc(s.label)}</td>
          <td><select data-src="${s.key}" class="ptype-sel">${settings.payment_types.map((t) =>
            `<option value="${t.key}" ${settings.ptype_map[s.key] === t.key ? 'selected' : ''}>${esc(t.label)}${t.key === s.default ? ' (기본)' : ''}</option>`).join('')}</select></td></tr>`).join('')}
      </table></div>
      <div class="btnrow" style="justify-content:flex-end"><button class="primary" onclick="salesSaveMap()">분류 저장</button></div>
    </div>`;
  }

  $('page').innerHTML = html;
}

async function salesSaveMap() {
  const m = {};
  document.querySelectorAll('.ptype-sel').forEach((el) => { m[el.dataset.src] = el.value; });
  try {
    await api('/settlement/settings', { method: 'PUT', body: JSON.stringify({ ptype_map: m }) });
    go('sales');
  } catch (e) { alert(e.message); }
}
