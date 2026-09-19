/* 방문 통계 화면 — 관리자와 협업기업이 본다.
 *
 * app.js 의 전역(api, esc, state, go, $)을 그대로 쓴다. 빌드 없이 <script> 로
 * 이어 붙이는 구조라, app.js 다음에 읽혀야 한다.
 *
 * 차트 규칙 몇 가지를 지킨다.
 *   - **색은 사이트에 붙는다.** 서버가 준 site_index(전체 순번)로 색을 고른다.
 *     권한 때문에 기록해만 보이는 기업에서도 기록해는 늘 같은 색이다.
 *   - 날이 비어도 막대 자리를 남긴다. 빈 날을 빼면 추세가 거짓말을 한다.
 *   - 표를 같이 둔다. 색을 구분하기 어려운 사람도 숫자로 읽을 수 있게.
 */

'use strict';

// 검증된 계열색(밝은 바탕용) 1~3번. 순서가 곧 색맹 안전성이라 바꾸지 않는다.
const SITE_COLORS = ['#2a78d6', '#eb6834', '#1baf7a'];

// allowed: 사이트를 거르지 않았을 때 받은 목록(= 이 사람이 볼 수 있는 전부).
// 한 사이트를 고르면 서버가 그 사이트만 돌려주므로, 버튼은 이 목록으로 그린다.
// 전체 순번(site_index)으로 그리면 권한 없는 사이트 이름까지 보이게 된다.
const visitState = { range: 'today', start: '', end: '', site: '', allowed: null };

const siteColor = (d, name) => SITE_COLORS[(d.site_index || {})[name] ?? 0] || '#8b8ba7';

const RANGE_LABEL = [
  ['today', '오늘'], ['week', '이번주'], ['month', '이번달'],
  ['custom', '기간설정'], ['all', '전체'],
];

function kstToday() {
  return new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 10);
}

async function pageVisits() {
  const q = new URLSearchParams({ range: visitState.range });
  if (visitState.range === 'custom') {
    q.set('start', visitState.start || kstToday());
    q.set('end', visitState.end || visitState.start || kstToday());
  }
  if (visitState.site) q.set('site', visitState.site);
  const d = await api('/visits?' + q.toString());

  if (!d.sites || !d.sites.length) {
    $('page').innerHTML = `<div class="card"><div class="card-head"><h2>방문 통계</h2></div>
      <div class="empty">${esc(d.empty_reason || '볼 수 있는 사이트가 없습니다.')}</div></div>`;
    return;
  }

  if (!visitState.site) visitState.allowed = d.sites.slice();
  const siteChoices = visitState.allowed || d.sites;
  const isToday = d.range.key === 'today';
  const nowTotal = d.now ? Object.values(d.now).reduce((a, b) => a + b, 0) : null;

  $('page').innerHTML = `
    <div class="card">
      <div class="filterbar">
        <div class="btnrow" role="group" aria-label="기간">
          ${RANGE_LABEL.map(([k, l]) =>
            `<button class="mini ${visitState.range === k ? 'on' : ''}" onclick="setRange('${k}')">${l}</button>`).join('')}
        </div>
        ${visitState.range === 'custom' ? `<div class="btnrow daterow">
          <input type="date" id="vStart" value="${esc(visitState.start || d.range.from)}" max="${kstToday()}">
          <span class="muted">~</span>
          <input type="date" id="vEnd" value="${esc(visitState.end || d.range.to)}" max="${kstToday()}">
          <button class="mini on" onclick="applyCustom()">적용</button>
        </div>` : ''}
        ${siteChoices.length > 1 ? `<div class="btnrow" role="group" aria-label="사이트">
          <button class="mini ${visitState.site ? '' : 'on'}" onclick="setSite('')">전체 사이트</button>
          ${siteChoices.map((n, i) => `<button class="mini ${visitState.site === n ? 'on' : ''}"
              onclick="setSite(visitState.allowed[${i}])">
              <span class="swatch" style="background:${siteColor(d, n)}"></span>${esc(n)}</button>`).join('')}
        </div>` : ''}
      </div>
      <p class="muted small" style="margin:8px 0 0">${esc(d.range.from)}${
        d.range.from !== d.range.to ? ' ~ ' + esc(d.range.to) : ''} · ${d.range.days}일</p>
    </div>

    <div class="grid g4">
      ${statTile(d.totals.visitors, '방문자', 'brand')}
      ${statTile(d.totals.pageviews, '페이지 열람')}
      ${statTile(d.totals.peak_5m, '가장 붐빈 5분')}
      ${nowTotal !== null ? statTile(nowTotal, '지금 접속자', nowTotal ? 'good' : '')
        : statTile('–', '지금 접속자 (오늘 포함 시)')}
    </div>

    <div class="card">
      <div class="card-head">
        <h2>${isToday ? '시간대별 방문자' : '날짜별 방문자'}</h2>
        <div class="legend-inline">${d.sites.map((n) =>
          `<span><span class="swatch" style="background:${siteColor(d, n)}"></span>${esc(n)}</span>`).join('')}</div>
      </div>
      <div class="chartbox"><svg id="visitChart" role="img" aria-label="방문자 막대그래프"></svg>
        <div id="visitTip" class="vtip" hidden></div></div>
    </div>

    <div class="grid g2">
      <div class="card">
        <div class="card-head"><h2>사이트별</h2></div>
        <div class="tablewrap"><table>
          <tr><th>사이트</th><th>방문자</th><th>페이지 열람</th><th>가장 붐빈 5분</th>${d.now ? '<th>지금</th>' : ''}<th title="요청은 했지만 페이지를 연 흔적이 없어 뺀 접근(스캐너 등)">걸러냄</th></tr>
          ${d.sites.map((n) => `<tr>
            <td><span class="swatch" style="background:${siteColor(d, n)}"></span> ${esc(n)}</td>
            <td><b>${fmtN(d.by_site[n].visitors)}</b></td>
            <td>${fmtN(d.by_site[n].pageviews)}</td>
            <td>${fmtN(d.by_site[n].peak_5m)}</td>
            ${d.now ? `<td>${fmtN(d.now[n] || 0)}</td>` : ''}
            <td class="muted">${fmtN(d.by_site[n].excluded || 0)}</td></tr>`).join('')}
        </table></div>
      </div>
      <div class="card">
        <div class="card-head"><h2>이 숫자를 읽는 법</h2></div>
        <div class="kv-card small">
          <div class="kv"><span>방문자</span><b>하루 안에서 중복을 뺀 사람 수</b></div>
          <div class="kv"><span>여러 날</span><b>날마다의 방문자를 더한 값</b></div>
          <div class="kv"><span>페이지 열람</span><b>화면을 처음 열거나 새로고침한 횟수</b></div>
          <div class="kv"><span>지금 접속자</span><b>최근 10분 안에 들어온 사람</b></div>
          <div class="kv"><span>제외</span><b>검색엔진·자동화 요청, 페이지를 실제로 열지 않은 접근(보안 스캐너 등)</b></div>
          <div class="kv"><span>기록 시작</span><b>${esc(d.since)}</b></div>
        </div>
      </div>
    </div>

    ${isToday ? '' : `<div class="card">
      <div class="card-head"><h2>날짜별 표</h2></div>
      <div class="tablewrap"><table>
        <tr><th>날짜</th>${d.sites.map((n) => `<th>${esc(n)}</th>`).join('')}<th>합계</th></tr>
        ${d.daily.slice().reverse().map((row) => {
          const tot = d.sites.reduce((a, n) => a + row.sites[n].visitors, 0);
          return `<tr><td>${esc(row.day)}</td>${d.sites.map((n) =>
            `<td>${fmtN(row.sites[n].visitors)} <span class="muted small">/ ${fmtN(row.sites[n].pageviews)}</span></td>`).join('')}
            <td><b>${fmtN(tot)}</b></td></tr>`;
        }).join('')}
      </table></div>
      <p class="muted small" style="margin:8px 0 0">칸마다 방문자 / 페이지 열람</p>
    </div>`}`;

  window.__visitData = d;
  drawVisitChart(d);
}

const fmtN = (n) => (n === null || n === undefined) ? '–' : Number(n).toLocaleString('ko-KR');

const statTile = (n, t, tone) =>
  `<div class="card stat"><span class="n ${tone || ''}">${typeof n === 'number' ? fmtN(n) : esc(n)}</span>`
  + `<span class="t">${esc(t)}</span></div>`;

function setRange(k) {
  visitState.range = k;
  if (k === 'custom' && !visitState.start) {
    const t = kstToday();
    visitState.start = t.slice(0, 8) + '01';
    visitState.end = t;
  }
  go('visits');
}

function applyCustom() {
  visitState.start = $('vStart').value;
  visitState.end = $('vEnd').value;
  go('visits');
}

function setSite(n) { visitState.site = n; go('visits'); }

// ───────────────────────────────────────────────────────────────────────────
// 막대그래프 — 사이트별로 쌓는다
// ───────────────────────────────────────────────────────────────────────────

/** 기간이 길면 막대를 묶는다. 1년치 365개 막대는 읽을 수가 없다. */
function bucketize(d) {
  if (d.range.key === 'today' && d.hourly) {
    return Array.from({ length: 24 }, (_, h) => ({
      label: `${h}시`, full: `${d.range.from} ${h}시`,
      sites: Object.fromEntries(d.sites.map((n) => [n, (d.hourly[n] || [])[h] || 0])),
    }));
  }
  const days = d.daily;
  const unit = days.length <= 62 ? 1 : days.length <= 400 ? 7 : 30;
  const out = [];
  for (let i = 0; i < days.length; i += unit) {
    const chunk = days.slice(i, i + unit);
    const first = chunk[0].day, last = chunk[chunk.length - 1].day;
    out.push({
      label: unit === 1 ? first.slice(5) : unit === 7 ? `${first.slice(5)}~` : first.slice(0, 7),
      full: unit === 1 ? first : `${first} ~ ${last}`,
      sites: Object.fromEntries(d.sites.map((n) =>
        [n, chunk.reduce((a, r) => a + r.sites[n].visitors, 0)])),
    });
  }
  return out;
}

function niceMax(v) {
  if (v <= 5) return 5;
  const mag = Math.pow(10, Math.floor(Math.log10(v)));
  return Math.ceil(v / mag * 2) / 2 * mag;
}

function drawVisitChart(d) {
  const svg = $('visitChart');
  if (!svg) return;
  const NS = 'http://www.w3.org/2000/svg';
  const w = Math.max(280, svg.clientWidth || svg.parentNode.clientWidth);
  const h = document.body.classList.contains('widget') ? 150 : 240;
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
  svg.style.height = h + 'px';
  svg.innerHTML = '';
  const el = (tag, a, text) => {
    const n = document.createElementNS(NS, tag);
    for (const k in a) n.setAttribute(k, a[k]);
    if (text !== undefined) n.textContent = text;
    return n;
  };

  const bars = bucketize(d);
  const total = (b) => d.sites.reduce((a, n) => a + b.sites[n], 0);
  const top = niceMax(Math.max(0, ...bars.map(total)));
  const L = 38, R = 8, T = 10, B = 24;
  const plotW = w - L - R, plotH = h - T - B;
  const slot = plotW / bars.length;
  const bw = Math.max(2, Math.min(28, slot - Math.max(2, slot * 0.28)));
  const Y = (v) => T + plotH - (v / top) * plotH;

  // 눈금 — 가는 실선
  for (let k = 0; k <= 4; k++) {
    const v = top * k / 4, y = Y(v);
    svg.appendChild(el('line', { x1: L, x2: w - R, y1: y, y2: y,
      stroke: k === 0 ? '#c3c2b7' : '#ebebf3', 'stroke-width': 1 }));
    svg.appendChild(el('text', { x: L - 6, y: y + 4, 'text-anchor': 'end',
      fill: '#8b8ba7', 'font-size': 10 }, Math.round(v).toLocaleString('ko-KR')));
  }

  const every = Math.ceil(bars.length / Math.max(1, Math.floor(plotW / 56)));
  bars.forEach((b, i) => {
    const x = L + slot * i + (slot - bw) / 2;
    let yBase = T + plotH;
    const segs = d.sites.filter((n) => b.sites[n] > 0);
    segs.forEach((n, j) => {
      const hh = (b.sites[n] / top) * plotH;
      const isTop = j === segs.length - 1;
      const gap = isTop ? 0 : Math.min(2, hh / 2);          // 조각 사이 바탕 틈
      const y = yBase - hh;
      const segH = Math.max(1, hh - gap);
      if (isTop && segH > 4) {
        const r = Math.min(4, bw / 2);
        svg.appendChild(el('path', {
          d: `M${x} ${y + segH}V${y + r}Q${x} ${y} ${x + r} ${y}H${x + bw - r}Q${x + bw} ${y} ${x + bw} ${y + r}V${y + segH}Z`,
          fill: siteColor(d, n),
        }));
      } else {
        svg.appendChild(el('rect', { x, y: y + gap, width: bw, height: segH, fill: siteColor(d, n) }));
      }
      yBase = y;
    });

    if (i % every === 0) {
      svg.appendChild(el('text', { x: x + bw / 2, y: h - 7, 'text-anchor': 'middle',
        fill: '#8b8ba7', 'font-size': 10 }, b.label));
    }

    // 막대보다 넓은 투명 칸을 덮어 마우스를 대기 쉽게 한다.
    const hit = el('rect', { x: L + slot * i, y: T, width: slot, height: plotH, fill: 'transparent' });
    hit.addEventListener('mousemove', (ev) => showVisitTip(ev, d, b));
    hit.addEventListener('mouseleave', () => { $('visitTip').hidden = true; });
    svg.appendChild(hit);
  });
}

function showVisitTip(ev, d, b) {
  const tip = $('visitTip');
  const box = $('visitChart').getBoundingClientRect();
  const sum = d.sites.reduce((a, n) => a + b.sites[n], 0);
  tip.innerHTML = `<div class="muted small">${esc(b.full)}</div>`
    + d.sites.map((n) => `<div class="trow"><span class="swatch" style="background:${siteColor(d, n)}"></span>
        <span>${esc(n)}</span><b>${fmtN(b.sites[n])}</b></div>`).join('')
    + (d.sites.length > 1 ? `<div class="trow total"><span>합계</span><b>${fmtN(sum)}</b></div>` : '');
  tip.hidden = false;
  const x = ev.clientX - box.left;
  tip.style.left = Math.min(box.width - tip.offsetWidth - 4, Math.max(4, x + 12)) + 'px';
  tip.style.top = '6px';
}

addEventListener('resize', () => {
  if (state.page === 'visits' && window.__visitData) drawVisitChart(window.__visitData);
});

// ───────────────────────────────────────────────────────────────────────────
// 첫 화면에 붙는 작은 카드
// ───────────────────────────────────────────────────────────────────────────

async function loadVisitCard() {
  const box = $('visitCard');
  if (!box) return;
  let d;
  try { d = await api('/visits?range=today'); } catch (_) { return; }
  if (!d.sites || !d.sites.length) { box.innerHTML = ''; return; }
  box.innerHTML = `<div class="card">
    <div class="card-head"><h2>오늘 방문</h2>
      <button class="mini" onclick="visitState.range='today';go('visits')">자세히</button></div>
    <div class="visit-mini">${d.sites.map((n) => `<div>
      <div class="muted small"><span class="swatch" style="background:${siteColor(d, n)}"></span> ${esc(n)}</div>
      <b>${fmtN(d.by_site[n].visitors)}</b><span class="muted small"> 명</span>
      <div class="muted small">지금 ${fmtN((d.now || {})[n] || 0)}명</div>
    </div>`).join('')}</div>
  </div>`;
}

// ───────────────────────────────────────────────────────────────────────────
// 기업별 공개 범위 (관리자)
// ───────────────────────────────────────────────────────────────────────────

async function editOrgVisits(orgId, orgName) {
  let cfg;
  try { cfg = await api(`/admin/orgs/${orgId}/visit-sites`); } catch (e) { alert(e.message); return; }
  const dlg = $('visitDlg');
  $('visitDlgTitle').textContent = `${orgName} — 방문 통계 공개 범위`;
  $('visitDlgList').innerHTML = cfg.all.map((n) => `<label class="checkrow">
      <input type="checkbox" value="${esc(n)}" ${cfg.allowed.includes(n) ? 'checked' : ''}> ${esc(n)}
    </label>`).join('') || '<div class="empty">집계하는 사이트가 없습니다</div>';
  $('visitDlgForm').onsubmit = async (ev) => {
    if (!ev.submitter || ev.submitter.value !== 'save') return;
    ev.preventDefault();
    const allowed = [...$('visitDlgList').querySelectorAll('input:checked')].map((x) => x.value);
    try {
      await api(`/admin/orgs/${orgId}/visit-sites`, { method: 'PUT', body: JSON.stringify({ allowed }) });
      dlg.close();
      go('users');
    } catch (e) { alert(e.message); }
  };
  dlg.showModal();
}
