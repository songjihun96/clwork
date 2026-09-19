/** 학급 입력 양식. "2학년 3반" 형태의 문자열을 만들어 준다. */
export const GRADES = [1, 2, 3];
export const CLASSES = Array.from({ length: 20 }, (_, i) => i + 1);

export function formatClass(grade, ban) {
  if (!grade) return "";
  return ban ? `${grade}학년 ${ban}반` : `${grade}학년`;
}

/** "2학년 3반" → { grade: 2, ban: 3 } */
export function parseClass(text) {
  const g = /(\d+)\s*학년/.exec(text || "");
  const b = /(\d+)\s*반/.exec(text || "");
  return { grade: g ? Number(g[1]) : "", ban: b ? Number(b[1]) : "" };
}

export default function ClassPicker({ grade, ban, onChange, label = "담당 학급" }) {
  return (
    <div className="field">
      <label className="label">{label}</label>
      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
        <select
          className="select"
          style={{ minWidth: 96 }}
          value={grade || ""}
          onChange={(e) => onChange({ grade: e.target.value ? Number(e.target.value) : "", ban })}
        >
          <option value="">학년</option>
          {GRADES.map((g) => (
            <option key={g} value={g}>{g}학년</option>
          ))}
        </select>
        <select
          className="select"
          style={{ minWidth: 90 }}
          value={ban || ""}
          onChange={(e) => onChange({ grade, ban: e.target.value ? Number(e.target.value) : "" })}
        >
          <option value="">반</option>
          {CLASSES.map((b) => (
            <option key={b} value={b}>{b}반</option>
          ))}
        </select>
        <span className="label" style={{ color: "var(--steel-light)" }}>
          {formatClass(grade, ban) || "미지정"}
        </span>
      </div>
    </div>
  );
}
