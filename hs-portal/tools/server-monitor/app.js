/* 서버 감시 대시보드.
 *
 * 차트는 라이브러리 없이 SVG 로 직접 그린다. 설치할 것을 하나도 안 만들겠다는
 * 원칙이 이 파일에도 그대로 적용된다 — CDN 이 막히거나 인터넷이 끊겨도 화면은
 * 뜬다.
 *
 * 색에 대한 규칙 두 가지만 지킨다.
 *   - **계열색은 대상에 붙는다.** '기록해'는 처음 본 순간 정해진 색을 끝까지
 *     쓴다. 범례에서 하나를 끄더라도 남은 것들의 색이 바뀌지 않는다 —
 *     "기록해는 주황" 을 외운 사람을 속이지 않기 위해서다.
 *   - **상태색은 상태에만 쓴다.** 초록/노랑/빨강은 좋다·주의·위험을 뜻하고,
 *     사이트를 구분하는 데는 절대 안 쓴다. 색만으로 뜻을 전하지 않도록 옆에
 *     항상 글자를 같이 둔다.
 */

'use strict';

const $ = (id) => document.getElementById(id);
const css = (name) => getComputedStyle(document.documentElement)
  .getPropertyValue(name).trim();

const state = {
  snap: null,
  hist: null,
  hours: 24,
  interval: 10,
  hidden: new Set(),      // 범례에서 끈 사이트
  colorOf: new Map(),     // 사이트 이름 -> 계열 슬롯 (한 번 정하면 안 바뀐다)
  timer: null,
  histAt: 0,
};

const SLOTS = ['--s1', '--s2', '--s3'];

/** 사이트 색. 처음 본 순서대로 슬롯을 주고, 그 뒤로는 바뀌지 않는다.
 *  슬롯이 떨어지면 새 색을 만들어 내지 않고 회색으로 둔다 — 구별 안 되는
 *  색을 만들어 쓰느니 "그 밖"으로 두는 편이 정직하다. */
function colorFor(name) {
  if (!state.colorOf.has(name)) {
    const used = state.colorOf.size;
    state.colorOf.set(name, used < SLOTS.length ? SLOTS[used] : null);
  }
  const slot = state.colorOf.get(name);
  return slot ? css(slot) : css('--muted');
}

const fmt = (n) => (n === null || n === undefined || Number.isNaN(n))
  ? '–' : Number(n).toLocaleString('ko-KR');
const pct = (n) => (n === null || n === undefined) ? '–' : `${n}%`;

// ───────────────────────────────────────────────────────────────────────────
// SVG 만들기
// ───────────────────────────────────────────────────────────────────────────

const NS = 'http://www.w3.org/2000/svg';
function el(tag, attrs = {}, text) {
  const n = document.createElementNS(NS, tag);
  for (const k in attrs) if (attrs[k] !== null) n.setAttribute(k, attrs[k]);
  if (text !== undefined) n.textContent = text;
  return n;
}

/** 컨테이너 실제 크기를 viewBox 로 맞춘다.
 *  고정 viewBox 를 늘려 쓰면 글자까지 같이 늘어나 찌그러진다. */
function sizeOf(svg) {
  const w = Math.max(120, Math.round(svg.clientWidth || svg.parentNode.clientWidth));
  const h = Math.max(60, Math.round(svg.clientHeight || 200));
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  return { w, h };
}

// ───────────────────────────────────────────────────────────────────────────
// 꺾은선 — 사이트별 접속자 추이
// ───────────────────────────────────────────────────────────────────────────

function drawTrend() {
  const svg = $('trend');
  const { w, h } = sizeOf(svg);
  const pts = (state.hist && state.hist.points) || [];
  const names = ((state.snap && state.snap.traffic.site_order) || [])
    .filter((n) => !state.hidden.has(n));

  // 끝점에 이름을 직접 붙이면 범례를 오가지 않아도 되지만, 좁은 창에서는
  // 이름 셋이 같은 자리에 겹쳐 글자만 뭉갠다. 자리가 있을 때만 붙인다.
  const endLabels = svg.clientWidth >= 620;
  const L = 44, R = endLabels ? 96 : 14, T = 14, B = 26;
  if (pts.length < 2) {
    svg.appendChild(el('text', {
      x: w / 2, y: h / 2, 'text-anchor': 'middle',
      fill: css('--muted'), 'font-size': 12,
    }, '표본을 모으는 중입니다 — 1분에 한 점씩 쌓입니다'));
    return;
  }

  const valueAt = (p, name) => (p.sites && p.sites[name] !== undefined)
    ? p.sites[name] : (names.length === 1 ? p.visitors : 0);

  let top = 0;
  for (const p of pts) for (const n of names) top = Math.max(top, valueAt(p, n) || 0);
  top = niceTop(top);

  const X = (i) => L + (w - L - R) * (i / (pts.length - 1));
  const Y = (v) => h - B - (h - T - B) * (v / top);

  // 눈금선 — 가는 실선 한 겹. 점선은 '예측'처럼 읽혀서 안 쓴다.
  for (let k = 0; k <= 4; k++) {
    const v = top * k / 4, y = Y(v);
    svg.appendChild(el('line', {
      x1: L, x2: w - R, y1: y, y2: y,
      stroke: k === 0 ? css('--axis') : css('--grid'), 'stroke-width': 1,
    }));
    svg.appendChild(el('text', {
      x: L - 8, y: y + 4, 'text-anchor': 'end',
      fill: css('--muted'), 'font-size': 11,
    }, fmt(Math.round(v))));
  }

  // 서비스가 내려가 있던 구간. 골짜기가 한산해서인지 죽어서인지 구분된다.
  let run = null;
  pts.forEach((p, i) => {
    if (!p.up && run === null) run = i;
    if ((p.up || i === pts.length - 1) && run !== null) {
      svg.appendChild(el('rect', {
        x: X(run), y: T, width: Math.max(1, X(i) - X(run)), height: h - T - B,
        fill: css('--critical'), opacity: .12,
      }));
      run = null;
    }
  });

  // x 축 이름표 — 다섯 개면 충분하다.
  const step = Math.max(1, Math.floor(pts.length / 5));
  for (let i = 0; i < pts.length; i += step) {
    svg.appendChild(el('text', {
      x: X(i), y: h - 8, 'text-anchor': 'middle',
      fill: css('--muted'), 'font-size': 11,
    }, pts[i].at.slice(6)));
  }

  const ends = [];
  names.forEach((name) => {
    const d = pts.map((p, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)} ${Y(valueAt(p, name)).toFixed(1)}`).join(' ');
    svg.appendChild(el('path', {
      d, fill: 'none', stroke: colorFor(name), 'stroke-width': 2,
      'stroke-linejoin': 'round', 'stroke-linecap': 'round',
    }));
    const last = valueAt(pts[pts.length - 1], name);
    ends.push({ name, y: Y(last), last });
  });

  if (endLabels) {
    // 값이 붙어 있으면 이름표도 겹친다. 위에서부터 최소 간격을 지키며 민다.
    ends.sort((a, b) => a.y - b.y);
    const MIN = 13;
    for (let i = 1; i < ends.length; i++) {
      if (ends[i].y - ends[i - 1].y < MIN) ends[i].y = ends[i - 1].y + MIN;
    }
    ends.forEach((e) => {
      svg.appendChild(el('text', {
        x: w - R + 8, y: Math.min(h - B, e.y) + 4,
        fill: css('--ink-2'), 'font-size': 11,
      }, `${e.name} ${fmt(e.last)}`));
    });
  }

  // 십자선 + 말풍선
  const hair = el('line', {
    y1: T, y2: h - B, stroke: css('--axis'), 'stroke-width': 1, opacity: 0,
  });
  svg.appendChild(hair);
  const dots = names.map((name) => {
    const c = el('circle', {
      r: 4, fill: colorFor(name), stroke: css('--surface'), 'stroke-width': 2, opacity: 0,
    });
    svg.appendChild(c);
    return { name, c };
  });

  const tip = $('trendTip');
  const wrap = $('trendWrap');
  svg.onmousemove = (ev) => {
    const box = svg.getBoundingClientRect();
    const rel = (ev.clientX - box.left) / box.width * w;
    let i = Math.round((rel - L) / (w - L - R) * (pts.length - 1));
    i = Math.max(0, Math.min(pts.length - 1, i));
    hair.setAttribute('x1', X(i)); hair.setAttribute('x2', X(i));
    hair.setAttribute('opacity', 1);
    dots.forEach(({ name, c }) => {
      c.setAttribute('cx', X(i));
      c.setAttribute('cy', Y(valueAt(pts[i], name)));
      c.setAttribute('opacity', 1);
    });
    tip.hidden = false;
    tip.innerHTML = `<div class="t-when">${pts[i].at}${pts[i].up ? '' : ' · 서비스 내려감'}</div>`
      + names.map((n) => `<div class="t-row"><span class="swatch" style="background:${colorFor(n)}"></span>`
        + `<span>${n}</span><span class="val">${fmt(valueAt(pts[i], n))}명</span></div>`).join('');
    const px = X(i) / w * box.width;
    tip.style.left = Math.min(box.width - tip.offsetWidth - 6, Math.max(6, px + 14)) + 'px';
    tip.style.top = '12px';
  };
  svg.onmouseleave = () => {
    hair.setAttribute('opacity', 0);
    dots.forEach(({ c }) => c.setAttribute('opacity', 0));
    tip.hidden = true;
  };

  $('trendCap').textContent = `${pts[0].at} ~ ${pts[pts.length - 1].at} · 1분 간격`;
}

function niceTop(v) {
  if (v <= 5) return 5;
  const mag = Math.pow(10, Math.floor(Math.log10(v)));
  return Math.ceil(v / mag * 2) / 2 * mag;
}

function drawTrendLegend() {
  const box = $('trendLegend');
  const names = (state.snap && state.snap.traffic.site_order) || [];
  box.innerHTML = '';
  names.forEach((name) => {
    const on = !state.hidden.has(name);
    const b = document.createElement('button');
    b.type = 'button';
    b.setAttribute('aria-pressed', String(on));
    b.innerHTML = `<span class="swatch" style="background:${colorFor(name)}"></span>${name}`;
    b.onclick = () => {
      if (on) state.hidden.add(name); else state.hidden.delete(name);
      drawTrendLegend(); drawTrend();
    };
    box.appendChild(b);
  });
}

// ───────────────────────────────────────────────────────────────────────────
// 도넛 — 사이트별 요청 비중
// ───────────────────────────────────────────────────────────────────────────

function drawDonut() {
  const svg = $('donut');
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  const t = state.snap.traffic;
  const items = (t.site_order || []).map((n) => ({
    name: n, value: (t.sites[n] || {}).requests_60m || 0,
  })).filter((x) => x.value > 0);

  const total = items.reduce((a, b) => a + b.value, 0);
  const cx = 80, cy = 80, r = 62, thick = 20;
  if (!total) {
    svg.appendChild(el('circle', {
      cx, cy, r: r - thick / 2, fill: 'none',
      stroke: css('--grid'), 'stroke-width': thick,
    }));
    $('donutLegend').innerHTML = '<li class="empty">최근 60분 요청이 없습니다</li>';
    return;
  }

  let a0 = -Math.PI / 2;
  const gap = 0.012;                 // 조각 사이 바탕 틈. 테두리 대신 이걸 쓴다.
  items.forEach((it) => {
    const span = it.value / total * Math.PI * 2;
    const a1 = a0 + Math.max(span - gap, span * 0.4);
    svg.appendChild(el('path', {
      d: arcPath(cx, cy, r - thick / 2, a0, a1),
      fill: 'none', stroke: colorFor(it.name), 'stroke-width': thick,
    }));
    a0 += span;
  });

  svg.appendChild(el('text', {
    x: cx, y: cy - 2, 'text-anchor': 'middle', fill: css('--ink'),
    'font-size': 22, 'font-weight': 680,
  }, fmt(total)));
  svg.appendChild(el('text', {
    x: cx, y: cy + 15, 'text-anchor': 'middle', fill: css('--muted'), 'font-size': 11,
  }, '요청'));

  $('donutLegend').innerHTML = items.map((it) =>
    `<li><span class="swatch" style="background:${colorFor(it.name)}"></span>`
    + `<span>${it.name}</span>`
    + `<span class="val">${Math.round(it.value / total * 100)}% · ${fmt(it.value)}</span></li>`
  ).join('');
}

function arcPath(cx, cy, r, a0, a1) {
  const x0 = cx + r * Math.cos(a0), y0 = cy + r * Math.sin(a0);
  const x1 = cx + r * Math.cos(a1), y1 = cy + r * Math.sin(a1);
  return `M${x0} ${y0} A${r} ${r} 0 ${a1 - a0 > Math.PI ? 1 : 0} 1 ${x1} ${y1}`;
}

// ───────────────────────────────────────────────────────────────────────────
// 상태코드 — 가로 누적 막대 (상태색을 쓰는 자리)
// ───────────────────────────────────────────────────────────────────────────

function drawStatus() {
  const svg = $('statusBar');
  const { w, h } = sizeOf(svg);
  const s = state.snap.traffic.status;
  const parts = [
    { k: '2xx', label: '정상', v: s['2xx'], color: css('--good') },
    { k: '3xx', label: '이동', v: s['3xx'], color: css('--muted') },
    { k: '4xx', label: '요청 오류', v: s['4xx'], color: css('--warning') },
    { k: '5xx', label: '서버 오류', v: s['5xx'], color: css('--critical') },
  ];
  const total = parts.reduce((a, b) => a + b.v, 0);
  if (!total) {
    svg.appendChild(el('rect', { x: 0, y: 0, width: w, height: h, rx: 5, fill: css('--grid') }));
    $('statusLegend').innerHTML = '<li class="empty">최근 60분 요청이 없습니다</li>';
    return;
  }
  let x = 0;
  parts.filter((p) => p.v > 0).forEach((p) => {
    const bw = Math.max(3, (p.v / total) * w - 2);   // 2px 바탕 틈
    svg.appendChild(el('rect', {
      x, y: 0, width: bw, height: h, rx: 5, fill: p.color,
    }));
    x += bw + 2;
  });
  $('statusLegend').innerHTML = parts.map((p) =>
    `<li><span class="swatch" style="background:${p.color}"></span>`
    + `<span>${p.k} ${p.label}</span>`
    + `<span class="val">${fmt(p.v)}</span></li>`).join('');
}

// ───────────────────────────────────────────────────────────────────────────
// 게이지 — 쓰는 만큼 / 전체
// ───────────────────────────────────────────────────────────────────────────

function drawGauge(id, percent, warn, crit) {
  const svg = $(id);
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  const p = Math.max(0, Math.min(100, Number(percent) || 0));
  const cx = 60, cy = 66, r = 46, thick = 11;
  const A0 = Math.PI * 0.82, A1 = Math.PI * 2.18;   // 아래가 트인 반원

  svg.appendChild(el('path', {
    d: arcPath(cx, cy, r, A0, A1), fill: 'none',
    stroke: css('--grid'), 'stroke-width': thick, 'stroke-linecap': 'round',
  }));
  const color = p >= crit ? css('--critical') : p >= warn ? css('--warning') : css('--good');
  if (p > 0.5) {
    svg.appendChild(el('path', {
      d: arcPath(cx, cy, r, A0, A0 + (A1 - A0) * p / 100), fill: 'none',
      stroke: color, 'stroke-width': thick, 'stroke-linecap': 'round',
    }));
  }
  svg.appendChild(el('text', {
    x: cx, y: cy + 4, 'text-anchor': 'middle', fill: css('--ink'),
    'font-size': 21, 'font-weight': 680,
  }, `${p}%`));
}

// ───────────────────────────────────────────────────────────────────────────
// 가로 막대 — 한 계열이므로 색은 하나만 쓴다
// ───────────────────────────────────────────────────────────────────────────

function drawBars(id, rows, labelKey, valueKey, unit) {
  const svg = $(id);
  const { w, h } = sizeOf(svg);
  if (!rows || !rows.length) {
    svg.appendChild(el('text', {
      x: w / 2, y: h / 2, 'text-anchor': 'middle', fill: css('--muted'), 'font-size': 12,
    }, '기록이 없습니다'));
    return;
  }
  const items = rows.slice(0, 6);
  const top = Math.max(...items.map((r) => r[valueKey])) || 1;
  const rowH = Math.min(30, h / items.length);
  const labelW = Math.min(190, w * 0.42);
  const barMax = w - labelW - 52;

  items.forEach((r, i) => {
    const y = i * rowH + (rowH - 12) / 2;
    const text = String(r[labelKey]);
    svg.appendChild(el('text', {
      x: 0, y: y + 10, fill: css('--ink-2'), 'font-size': 12,
    }, text.length > 30 ? text.slice(0, 29) + '…' : text));
    svg.appendChild(el('rect', {
      x: labelW, y, width: Math.max(2, barMax * r[valueKey] / top), height: 12,
      rx: 4, fill: css('--s1'),
    }));
    svg.appendChild(el('text', {
      x: w, y: y + 10, 'text-anchor': 'end', fill: css('--ink'), 'font-size': 12,
    }, fmt(r[valueKey]) + (unit || '')));
  });
}

// ───────────────────────────────────────────────────────────────────────────
// 화면 채우기
// ───────────────────────────────────────────────────────────────────────────

function render() {
  const s = state.snap;
  if (!s) return;
  const lvl = s.status === 'critical' ? 'critical' : s.status === 'warn' ? 'warn' : 'ok';

  $('statusDot').className = 'dot ' + lvl;
  $('hostname').textContent = s.system.hostname || '서버';
  const st = $('statusText');
  st.className = 'pill ' + lvl;
  st.textContent = lvl === 'ok' ? '정상' : lvl === 'warn' ? '주의' : '위험';

  // 경보
  const banner = $('banner');
  if (s.alerts.length) {
    banner.hidden = false;
    const isWidget = document.body.classList.contains('widget');
    const cap = isWidget ? 3 : 8;
    banner.innerHTML = s.alerts.slice(0, cap).map((a) => {
      const k = a.level === 'critical' ? 'critical' : 'warn';
      return `<div class="alert ${k}"><span class="lv">${k === 'critical' ? '위험' : '주의'}</span>`
        + `<b>${escapeHtml(a.message)}</b></div>`;
    }).join('')
      + (s.alerts.length > cap
        ? `<div class="more-alerts">그 밖에 ${s.alerts.length - cap}건</div>` : '');
  } else {
    banner.hidden = true;
  }

  // 사이트 타일
  const t = s.traffic;
  $('siteTiles').innerHTML = (t.site_order || []).map((n) => {
    const v = t.sites[n] || {};
    return `<div class="tile" style="border-left-color:${colorFor(n)};--tile-color:${colorFor(n)}">
      <div class="name">${escapeHtml(n)}</div>
      <div class="big">${fmt(v.visitors_now)}</div>
      <div class="sub">60분 ${fmt(v.visitors_60m)}명 · 분당 ${v.requests_per_min_5m}건</div>
    </div>`;
  }).join('') || '<div class="empty">읽는 로그가 없습니다</div>';

  drawTrendLegend();
  drawTrend();
  drawDonut();
  drawStatus();

  const rt = t.response_time;
  $('p50').textContent = rt.p50 === null ? '–' : rt.p50 + 's';
  $('p95').textContent = rt.p95 === null ? '–' : rt.p95 + 's';
  $('rtNote').textContent = rt.p50 === null
    ? 'nginx 로그에 응답시간이 없습니다 (log_format 에 $request_time 을 넣으면 나옵니다)'
    : `표본 ${fmt(rt.samples)}건 · 봇 ${t.bot_percent}% · 전송 ${t.bandwidth_60m_mb}MB`;

  // 서버
  const sys = s.system, disk = s.disk, db = s.db;
  drawGauge('gCpu', sys.cpu_percent, 70, 88);
  drawGauge('gMem', sys.mem_percent, 80, 92);
  drawGauge('gDisk', disk.percent, 75, 88);
  $('memSub').textContent = `${fmt(sys.mem_used_mb)}/${fmt(sys.mem_total_mb)}MB`;
  $('diskSub').textContent = `${fmt(disk.free_mb)}MB 남음`;
  $('sysNote').textContent = `${sys.cores}코어 · ${sys.booted_at} 부팅`;
  $('load').textContent = `${sys.load_per_core} (1분 ${sys.load1})`;
  $('load').className = sys.load_per_core >= 1 ? 'warn' : '';
  $('uptime').textContent = `${fmt(sys.uptime_hours)}시간`;
  $('uppct').textContent = s.uptime.percent === null
    ? '표본 모으는 중' : `${s.uptime.percent}% (내려감 ${s.uptime.down_minutes}분)`;
  $('dbconn').textContent = db.connections === null
    ? '–' : `${db.connections} / ${db.max_connections}`;

  // 서비스
  const units = s.services.units.map((u) => chip(
    u.unit, u.ok ? 'good' : 'critical',
    `${u.state}${u.restarts ? ` · 재시작 ${u.restarts}회` : ''}${u.mem_mb ? ` · ${u.mem_mb}MB` : ''}`));
  const probes = s.services.probes.map((p) => chip(
    p.name, p.ok ? 'good' : 'critical',
    p.status ? `${p.status} · ${p.ms}ms` : (p.error || '무응답')));
  $('services').innerHTML = units.concat(probes).join('');
  const down = s.services.units.filter((u) => !u.ok).length
    + s.services.probes.filter((p) => !p.ok).length;
  $('svcNote').textContent = down ? `${down}개 내려감` : '모두 정상';

  const full = !document.body.classList.contains('widget');
  if (full) {
    drawBars('paths', t.top_paths, 'path', 'hits', '회');
    drawBars('refs', t.top_referrers, 'host', 'hits', '회');
  }

  // 오늘
  const b = s.business;
  $('today').innerHTML = [
    kv('가입', `${fmt(b.signups_today)}명`),
    kv('적성검사', `${fmt(b.quiz_today)}회`),
    kv('문의', `${fmt(b.inquiries_today)}건`),
    kv('통화', `${fmt(b.calls_today)}통 (진행 중 ${b.active_calls})`),
    kv('대기 중 주문', `${fmt(b.pending_orders)}건`, b.pending_orders ? 'warn' : ''),
    kv('미답변 문의', `${fmt(b.unanswered_inquiries)}건`, b.unanswered_inquiries >= 5 ? 'warn' : ''),
  ].join('');

  // 인증서·백업
  const ssl = s.ssl.map((c) => kv(c.domain, `${c.days_left}일 남음`,
    c.days_left <= 3 ? 'critical' : c.days_left <= 14 ? 'warn' : 'good'));
  const bk = s.backup.found
    ? kv('마지막 백업', `${s.backup.at} (${s.backup.age_hours}시간 전)`, s.backup.ok ? 'good' : 'critical')
    : kv('백업', '못 찾음', 'warn');
  $('upkeep').innerHTML = (ssl.join('') || '<div class="empty">인증서를 못 읽었습니다</div>') + bk;

  // 외부 연동
  $('deps').innerHTML = s.deps.items.map((d) =>
    chip(d.name, d.ok ? (d.configured ? 'good' : 'muted') : 'warning', d.note)).join('');

  // 보안
  const sec = s.security;
  $('security').innerHTML = [
    kv('로그인 실패 / 성공', `${fmt(sec.login_failures_60m)} / ${fmt(sec.login_success_60m)}`),
    kv('실패 비율', pct(sec.login_failure_ratio), sec.login_failure_ratio >= 70 ? 'warn' : ''),
    kv('스캐너로 보이는 IP', sec.scanner_ips.length
      ? sec.scanner_ips.map((x) => `${x.ip}(${x.hits})`).join(', ') : '없음',
      sec.scanner_ips.length ? 'warn' : 'good'),
    kv('404 많은 IP', sec.top_404_ips.length
      ? sec.top_404_ips.map((x) => `${x.ip}(${x.hits})`).join(', ') : '없음'),
    kv('관리자 작업 24시간', `${fmt(sec.admin_actions_24h)}건`),
  ].join('');

  // 에러
  const er = s.errors;
  $('errNote').textContent = `${er.hours}시간 · ${fmt(er.total)}줄 (훑은 줄 ${fmt(er.scanned)})`;
  $('errors').innerHTML = er.top.length
    ? er.top.map((x) => `<div class="logrow"><span class="n">${x.count}</span>`
      + `<code>${escapeHtml(x.sample)}</code></div>`).join('')
    : '<div class="empty">최근 에러가 없습니다</div>';

  // DB
  $('dbNote').textContent = db.ok
    ? `${db.dialect} · ${db.size_mb}MB · 응답 ${db.ping_ms}ms · 느린 질의 ${db.slow_queries}건`
    : 'DB 에 붙지 못했습니다';
  if (full) {
    drawBars('tables', (db.tables || []).map((x) => ({ name: x.name, mb: x.size_mb })),
      'name', 'mb', 'MB');
  }

  $('stamp').textContent = `${s.collected_at.slice(11)} 기준`;
}

const chip = (name, tone, note) =>
  `<div class="chip-item"><span class="dot ${tone === 'good' ? 'ok' : tone === 'critical' ? 'critical' : tone === 'warning' ? 'warn' : ''}"></span>`
  + `<span class="nm">${escapeHtml(name)}</span><span class="mt">${escapeHtml(note || '')}</span></div>`;

const kv = (label, value, tone) =>
  `<div class="kv"><span>${escapeHtml(label)}</span><b class="${tone || ''}">${escapeHtml(String(value))}</b></div>`;

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// ───────────────────────────────────────────────────────────────────────────
// 서버에 물어보기
// ───────────────────────────────────────────────────────────────────────────

async function tick() {
  try {
    const r = await fetch('/api/snapshot');
    const data = await r.json();
    if (!r.ok || data.error) throw new Error(data.error || `HTTP ${r.status}`);
    state.snap = data;
    offline(null);

    if (Date.now() - state.histAt > 55000) {
      state.histAt = Date.now();
      const hr = await fetch(`/api/history?hours=${state.hours}&points=180`);
      if (hr.ok) state.hist = await hr.json();
    }
    render();
  } catch (e) {
    offline(e.message || String(e));
  }
}

function offline(msg) {
  const banner = $('banner');
  if (!msg) return;
  $('statusDot').className = 'dot critical';
  $('hostname').textContent = '서버에 닿지 못했습니다';
  const st = $('statusText');
  st.className = 'pill critical';
  st.textContent = '끊김';
  banner.hidden = false;
  banner.innerHTML = `<div class="alert critical"><span class="lv">위험</span><b>${escapeHtml(msg)}</b></div>`;
  if (/토큰|배포/.test(msg)) $('setup').showModal();
}

// ───────────────────────────────────────────────────────────────────────────
// 켜기
// ───────────────────────────────────────────────────────────────────────────

function applyTheme(mode) {
  if (mode) document.documentElement.setAttribute('data-theme', mode);
  else document.documentElement.removeAttribute('data-theme');
  try { localStorage.setItem('theme', mode || ''); } catch (_) {}
  if (state.snap) render();
}

async function start() {
  try {
    const saved = localStorage.getItem('theme');
    if (saved) document.documentElement.setAttribute('data-theme', saved);
  } catch (_) {}

  $('themeBtn').onclick = () => {
    const now = document.documentElement.getAttribute('data-theme');
    applyTheme(now === 'dark' ? 'light' : 'dark');
  };
  $('setupBtn').onclick = () => $('setup').showModal();

  // 위젯 모드. 주소에 ?widget=1 이 있거나 창이 아주 좁으면 자동으로 켜진다.
  // 한 번 고르면 기억한다 — 브라우저를 앱 창으로 띄워 쓰는 경우가 많아서다.
  const params = new URLSearchParams(location.search);
  let widget = params.has('widget')
    ? params.get('widget') !== '0'
    : (localStorage.getItem('widget') === '1' || innerWidth < 560);
  const applyWidget = (on) => {
    document.body.classList.toggle('widget', on);
    try { localStorage.setItem('widget', on ? '1' : '0'); } catch (_) {}
    $('sizeBtn').textContent = on ? '⤢' : '⤡';
    $('sizeBtn').title = on ? '전체 보기' : '위젯 보기';
    if (state.snap) render();
  };
  applyWidget(widget);
  $('sizeBtn').onclick = () => { widget = !widget; applyWidget(widget); };

  document.querySelectorAll('.chip[data-hours]').forEach((b) => {
    b.onclick = () => {
      document.querySelectorAll('.chip[data-hours]').forEach((x) => x.classList.remove('is-on'));
      b.classList.add('is-on');
      state.hours = Number(b.dataset.hours);
      state.histAt = 0;
      tick();
    };
  });

  $('setupForm').onsubmit = async (ev) => {
    const btn = ev.submitter;
    if (!btn || btn.value !== 'save') return;         // '닫기'는 그냥 닫는다
    ev.preventDefault();
    const f = new FormData($('setupForm'));
    $('setupMsg').textContent = '확인 중…';
    const r = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        url: f.get('url'), token: f.get('token'), interval: f.get('interval'),
      }),
    });
    const data = await r.json();
    $('setupMsg').textContent = data.message || '';
    if (data.ok) {
      $('setup').close();
      state.interval = Number(f.get('interval')) || 10;
      schedule();
      tick();
    }
  };

  const cfg = await fetch('/api/config').then((r) => r.json()).catch(() => ({}));
  state.interval = cfg.interval || 10;
  state.hours = cfg.history_hours || 24;
  if (cfg.url) $('setupForm').elements.url.value = cfg.url;
  $('setupForm').elements.interval.value = state.interval;

  if (!cfg.configured) {
    $('setupMsg').textContent = '서버 주소와 감시 토큰을 넣어 주세요.';
    $('setup').showModal();
  }

  schedule();
  tick();

  let resizeT;
  addEventListener('resize', () => {
    clearTimeout(resizeT);
    resizeT = setTimeout(() => { if (state.snap) render(); }, 150);
  });
}

function schedule() {
  clearInterval(state.timer);
  state.timer = setInterval(tick, Math.max(3, state.interval) * 1000);
}

start();
