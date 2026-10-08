import {
  CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

/* 진학정보 차트 모음.
 *
 * 색은 역할로 정한다.
 *  - 구성비(대학 진학/취업/기타, 4년제/전문대/기타)는 조각이 셋 이하라
 *    도넛 + 옆 목록(색 옆에 이름·비율을 글자로)으로 보여준다.
 *  - 권역·계열처럼 항목이 많은 것은 도넛으로 그리면 조각을 구별할 수 없어
 *    한 가지 색 막대로 길이만 비교한다.
 *  - 추세 선은 계열 색을 고정 순서로 쓰고(필터로 선이 줄어도 색이 안 바뀜),
 *    범례와 아래 표를 함께 둔다 — 색만으로 구별하지 않게.
 * 계열 색 4개는 데이터 시각화 기준 팔레트의 앞 네 칸을 그 순서대로 쓴다
 * (인접 쌍 색각 이상 구분 기준 통과 순서). 노랑·청록은 흰 바탕 대비가
 * 낮아서 반드시 글자 라벨·표와 함께 쓴다. */
export const SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"];
const BAR = "#b52701";            // 사이트 강조색 한 가지로 길이만 비교
const GRID = "#e8e9ea";
const AXIS = "#8f7069";

export const pct = (v) => (v === null || v === undefined ? "—" : `${Number(v).toFixed(1)}%`);
export const cnt = (item) => (item.masked ? "소수 인원" : `${(item.count ?? 0).toLocaleString()}명`);

const tooltipStyle = {
  border: "1px solid var(--line)", borderRadius: 8, fontSize: 13, background: "#fff",
};

export function Donut({ data, title, empty = "입력된 데이터가 없습니다." }) {
  if (!data || data.length === 0) return <EmptyChart title={title} text={empty} />;
  const rows = data.slice(0, 4);
  return (
    <div className="adm-chart">
      {title && <h4 className="adm-chart-title">{title}</h4>}
      <div className="adm-donut">
        <div className="adm-donut-plot" role="img"
          aria-label={`${title}: ${rows.map((d) => `${d.label} ${pct(d.percent)}`).join(", ")}`}>
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={rows} dataKey="count" nameKey="label" innerRadius="58%" outerRadius="92%"
                startAngle={90} endAngle={-270} stroke="#fff" strokeWidth={2} isAnimationActive={false}>
                {rows.map((d, i) => <Cell key={d.key} fill={SERIES[i % SERIES.length]} />)}
              </Pie>
              <Tooltip contentStyle={tooltipStyle}
                formatter={(v, _n, p) => [`${Number(v).toLocaleString()}명 (${pct(p.payload.percent)})`, p.payload.label]} />
            </PieChart>
          </ResponsiveContainer>
        </div>
        <ul className="adm-legend">
          {rows.map((d, i) => (
            <li key={d.key}>
              <span className="adm-swatch" style={{ background: SERIES[i % SERIES.length] }} />
              <span className="adm-legend-label">{d.label}</span>
              <b>{pct(d.percent)}</b>
              <span className="adm-legend-sub">{Number(d.count).toLocaleString()}명</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

/** 항목이 많은 구성비. 막대 길이 = 비율, 숫자는 글자로. */
export function BarList({ data, title, empty = "입력된 데이터가 없습니다.", limit = 12 }) {
  if (!data || data.length === 0) return <EmptyChart title={title} text={empty} />;
  const rows = data.slice(0, limit);
  const max = Math.max(...rows.map((d) => d.percent || 0), 1);
  return (
    <div className="adm-chart">
      {title && <h4 className="adm-chart-title">{title}</h4>}
      <ul className="adm-bars">
        {rows.map((d) => (
          <li key={d.key} title={`${d.label} ${Number(d.count).toLocaleString()}명 (${pct(d.percent)})`}>
            <span className="adm-bar-label">{d.label}</span>
            <span className="adm-bar-track">
              <span className="adm-bar-fill" style={{ width: `${((d.percent || 0) / max) * 100}%`, background: BAR }} />
            </span>
            <b className="adm-bar-value">{pct(d.percent)}</b>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** 주요 대학·학과 순위. 자동 집계(입력 인원 순). */
export function RankList({ items, title, subKey, empty = "입력된 데이터가 없습니다." }) {
  return (
    <div className="adm-chart">
      {title && <h4 className="adm-chart-title">{title}</h4>}
      {!items || items.length === 0 ? (
        <p className="adm-empty">{empty}</p>
      ) : (
        <ol className="adm-rank">
          {items.map((it, i) => (
            <li key={it.name}>
              <span className="adm-rank-no">{i + 1}</span>
              <span className="adm-rank-name">
                {it.name}
                {subKey && it[subKey] && <small>{it[subKey]}</small>}
              </span>
              <b>{cnt(it)}</b>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

const TREND_SERIES = [
  { key: "admission_rate", label: "대학 진학률" },
  { key: "four_year_rate", label: "4년제" },
  { key: "junior_college_rate", label: "전문대" },
  { key: "employment_rate", label: "취업률" },
];

/** 연도별 추세. 입력하지 않은 연도는 만들지 않는다(선이 그 해를 건너뛴다). */
export function TrendChart({ trend, showEmployment = true }) {
  if (!trend || trend.length === 0) {
    return <EmptyChart title="연도별 추세" text="입력된 연도가 없습니다." />;
  }
  // 색은 계열에 붙는다. 취업률을 빼도 나머지 선의 색은 그대로다.
  const series = TREND_SERIES.map((s, i) => ({ ...s, color: SERIES[i] }))
    .filter((s) => showEmployment || s.key !== "employment_rate");
  const data = trend;
  return (
    <div className="adm-chart">
      <h4 className="adm-chart-title">연도별 추세 <small>(졸업생 대비 %)</small></h4>
      {trend.length > 1 ? (
        <div style={{ height: 260 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -18 }}>
              <CartesianGrid stroke={GRID} vertical={false} />
              {/* 연도를 숫자 축으로 둔다. 글자 축이면 2021→2023 이 한 칸으로
                  붙어서 빠진 해가 있다는 게 보이지 않는다. */}
              <XAxis dataKey="year" type="number" domain={["dataMin", "dataMax"]}
                ticks={trend.map((t) => t.year)} tickFormatter={(v) => `${v}`} allowDecimals={false}
                padding={{ left: 12, right: 12 }}
                tick={{ fontSize: 12, fill: AXIS }} tickLine={false} axisLine={{ stroke: GRID }} />
              <YAxis domain={[0, 100]} tickFormatter={(v) => `${v}%`} tick={{ fontSize: 11, fill: AXIS }}
                tickLine={false} axisLine={false} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v, n) => [pct(v), n]}
                labelFormatter={(y) => `${y}년 졸업`}
                cursor={{ stroke: AXIS, strokeDasharray: "3 3" }} />
              <Legend iconType="circle" wrapperStyle={{ fontSize: 12.5 }} />
              {series.map((s) => (
                <Line key={s.key} type="linear" dataKey={s.key} name={s.label} stroke={s.color}
                  strokeWidth={2} dot={{ r: 4, strokeWidth: 2, stroke: "#fff", fill: s.color }}
                  activeDot={{ r: 5 }} connectNulls={false} isAnimationActive={false} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <p className="adm-empty">추세 그래프는 2개 연도 이상 입력되면 표시됩니다.</p>
      )}
      <div className="adm-table-wrap">
        <table className="table adm-table">
          <thead>
            <tr>
              <th>연도</th><th>졸업생</th>
              {series.map((s) => <th key={s.key}>{s.label}</th>)}
            </tr>
          </thead>
          <tbody>
            {[...trend].reverse().map((t) => (
              <tr key={t.year}>
                <td>{t.year}</td>
                <td>{t.total_graduates.toLocaleString()}명</td>
                {series.map((s) => <td key={s.key}>{pct(t[s.key])}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function EmptyChart({ title, text }) {
  return (
    <div className="adm-chart">
      {title && <h4 className="adm-chart-title">{title}</h4>}
      <p className="adm-empty">{text}</p>
    </div>
  );
}
