import { useEffect, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, LabelList, Legend,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api } from "../api";
import { Empty, Note, fmtDate } from "../components/ui";

/** 통계.
 *
 *  막대는 가로로 눕힌다. 상담원 이름과 문의 유형은 한글이라 세로 축에
 *  두면 글자가 겹치거나 기울어진다. 눕히면 이름이 그대로 읽힌다.
 *
 *  색은 두 가지만 쓴다. 주황(상담)과 파랑(통화). 색각이상에서도 구분되는
 *  조합인지 확인하고 골랐다. 숫자·이름은 색을 입히지 않고 본문 먹색 그대로
 *  둔다. 색은 계열을 가리키는 데만 쓴다.
 */

const SERIES = {
  consult: "#f26522", // 상담 건수 — 패밀리 브랜드 주황
  call: "#2f6fb0",    // 통화 건수 — 대비되는 파랑
};

const CHANNEL_LABEL = { PHONE: "전화", HOMEPAGE: "홈페이지", EMAIL: "이메일", OTHER: "기타" };

const axisStyle = { fontSize: 12, fill: "#69737d" };

function Tip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="charttip">
      <div className="charttip-k">{label}</div>
      {payload.map((p) => (
        <div key={p.dataKey} className="charttip-v">
          <span className="swatch" style={{ background: p.color }} />
          <span>{p.name}</span>
          <strong>{p.value?.toLocaleString?.() ?? p.value}</strong>
        </div>
      ))}
    </div>
  );
}

export default function Statistics() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [asTable, setAsTable] = useState(false);

  useEffect(() => {
    api.statistics().then(setData).catch((e) => setError(e.message));
  }, []);

  if (error) {
    return (
      <>
        <div className="page-head"><h1>통계</h1></div>
        <Note kind="bad">{error}</Note>
      </>
    );
  }
  if (!data) return <Empty>불러오는 중…</Empty>;

  const counselors = (data.per_counselor || []).filter((x) => x.consultations || x.calls);
  const types = (data.per_type || []).filter((x) => x.count > 0);

  return (
    <>
      <div className="page-head">
        <h1>통계</h1>
        <p>기준일 {fmtDate(new Date().toISOString())} · 상담과 통화는 세는 대상이 달라 따로 봅니다.</p>
      </div>

      <div className="queue">
        <Tile n={data.consultations_today} k="오늘 상담" />
        <Tile n={data.consultations_week} k="이번 주 상담" />
        <Tile n={data.consultations_month} k="이번 달 상담" />
        <Tile n={data.consultations_open} k="미처리 상담" warn />
        <Tile n={data.calls_in_progress} k="현재 통화 중" />
        <Tile n={data.calls_waiting} k="상담 대기" warn />
        <Tile n={data.missed_today} k="오늘 부재중" warn />
        <Tile n={data.calls_today} k="오늘 통화" />
      </div>

      <div className="card">
        <h2>
          상담원별 실적
          <button className="btn sm" style={{ float: "right" }} onClick={() => setAsTable(!asTable)}>
            {asTable ? "그래프로 보기" : "표로 보기"}
          </button>
        </h2>

        {counselors.length === 0 ? (
          <Empty>아직 쌓인 기록이 없습니다.</Empty>
        ) : asTable ? (
          <table>
            <thead>
              <tr>
                <th>상담원</th><th>상담</th><th>완료</th><th>통화</th><th>평균 통화시간</th>
              </tr>
            </thead>
            <tbody>
              {counselors.map((c) => (
                <tr key={c.counselor_id}>
                  <td>{c.name}</td>
                  <td>{c.consultations}</td>
                  <td>{c.completed}</td>
                  <td>{c.calls}</td>
                  <td>{c.avg_call_seconds}초</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <ResponsiveContainer width="100%" height={Math.max(160, counselors.length * 62)}>
            <BarChart data={counselors} layout="vertical"
                      margin={{ top: 4, right: 28, bottom: 4, left: 8 }} barGap={2}>
              <CartesianGrid horizontal={false} stroke="#eaeef2" />
              <XAxis type="number" allowDecimals={false} tick={axisStyle}
                     axisLine={{ stroke: "#dde3e9" }} tickLine={false} />
              <YAxis type="category" dataKey="name" width={78} tick={axisStyle}
                     axisLine={false} tickLine={false} />
              <Tooltip content={<Tip />} cursor={{ fill: "#f7f9fb" }} />
              <Legend iconType="circle" iconSize={8}
                      wrapperStyle={{ fontSize: 12, color: "#69737d" }} />
              <Bar dataKey="consultations" name="상담" fill={SERIES.consult}
                   radius={[0, 4, 4, 0]} barSize={11}>
                <LabelList dataKey="consultations" position="right"
                           style={{ fontSize: 11, fill: "#3b444d" }} />
              </Bar>
              <Bar dataKey="calls" name="통화" fill={SERIES.call}
                   radius={[0, 4, 4, 0]} barSize={11}>
                <LabelList dataKey="calls" position="right"
                           style={{ fontSize: 11, fill: "#3b444d" }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className="card">
        <h2>문의 유형별</h2>
        {types.length === 0 ? (
          <Empty>아직 분류된 상담이 없습니다.</Empty>
        ) : (
          <ResponsiveContainer width="100%" height={Math.max(150, types.length * 34)}>
            <BarChart data={types} layout="vertical"
                      margin={{ top: 4, right: 34, bottom: 4, left: 8 }}>
              <CartesianGrid horizontal={false} stroke="#eaeef2" />
              <XAxis type="number" allowDecimals={false} tick={axisStyle}
                     axisLine={{ stroke: "#dde3e9" }} tickLine={false} />
              <YAxis type="category" dataKey="name" width={124} tick={axisStyle}
                     axisLine={false} tickLine={false} />
              <Tooltip content={<Tip />} cursor={{ fill: "#f7f9fb" }} />
              {/* 계열이 하나뿐이라 범례를 두지 않는다. 제목이 이미 무엇인지 말한다. */}
              <Bar dataKey="count" name="상담" fill={SERIES.consult}
                   radius={[0, 4, 4, 0]} barSize={13}>
                {types.map((t) => (
                  <Cell key={t.id ?? "none"}
                        fill={t.id === null ? "#98a2ac" : SERIES.consult} />
                ))}
                <LabelList dataKey="count" position="right"
                           style={{ fontSize: 11, fill: "#3b444d" }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className="card">
        <h2>채널별</h2>
        <table>
          <thead><tr><th>채널</th><th>상담 건수</th></tr></thead>
          <tbody>
            {(data.per_channel || []).map((x) => (
              <tr key={x.channel}>
                <td>{CHANNEL_LABEL[x.channel] || x.channel}</td>
                <td>{x.count.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function Tile({ n, k, warn = false }) {
  const value = n ?? 0;
  return (
    <div className="tile">
      <div className={`n ${value === 0 ? "zero" : ""}`}
           style={warn && value > 0 ? { color: "var(--signal-deep)" } : undefined}>
        {value.toLocaleString()}
      </div>
      <div className="k">{k}</div>
    </div>
  );
}
