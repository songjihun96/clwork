import { useEffect, useState } from "react";
import { api } from "../api";

// 내 학과·학년. 일지의 과목 목록을 이 값으로 좁힌다.
// 학교에서 받아온 과목 자료가 있을 때만 보여준다(고를 게 없으면 띄울 이유가 없다).
export default function MyClassBar() {
  const [info, setInfo] = useState(null);
  const [saving, setSaving] = useState(false);

  const load = () => api.journalSubjects().then(setInfo).catch(() => setInfo(null));

  useEffect(() => { load(); }, []);

  const change = async (params) => {
    setSaving(true);
    try {
      await api.setSchoolProfile(params);
      await load();
    } finally {
      setSaving(false);
    }
  };

  if (!info || info.subjects.length === 0) return null;

  const deptOptions = info.departments.length > 0 ? info.departments : info.school_departments;

  return (
    <div className="myclass">
      <span className="t">내 학과 · 학년</span>

      <select
        value={info.department || ""}
        disabled={saving}
        aria-label="학과"
        onChange={(e) => change({ department: e.target.value })}
      >
        <option value="">학과 선택</option>
        {deptOptions.map((d) => <option key={d} value={d}>{d}</option>)}
      </select>

      <select
        value={info.grade || ""}
        disabled={saving}
        aria-label="학년"
        onChange={(e) => change({ grade: e.target.value })}
      >
        <option value="">학년 선택</option>
        {(info.grades.length > 0 ? info.grades : [1, 2, 3]).map((g) => (
          <option key={g} value={g}>{g}학년</option>
        ))}
      </select>

      <span className="hint">
        {info.school_name && `${info.school_name} · `}
        수업일지의 교과 목록이 {info.scope} 기준으로 {info.subjects.length}개 나옵니다.
        {info.scope === "전체" && " 학과와 학년을 고르면 내 과목만 보입니다."}
      </span>
    </div>
  );
}
