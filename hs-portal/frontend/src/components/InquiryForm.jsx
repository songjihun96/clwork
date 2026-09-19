import { useEffect, useState } from "react";
import { api } from "../api";

/** 교육·컨설팅 문의 폼.
 *
 * 신청폼(ApplyForm)과 묻는 것이 다르다. 저쪽은 **개인**이 신청하는 것이라
 * 본인/학부모와 이메일을 묻지만, 이쪽은 **학교나 기관**이 남기는 문의라
 * 지역과 학교 이름이 필요하다. 금액도 없다 — 무엇을 얼마나 할지는
 * 이야기해 봐야 정해진다.
 *
 * 지역 목록은 서버에서 받는다. 화면에 박아 두면 학교 검색 쪽과 어긋난다.
 */
export default function InquiryForm({
  onDone, via = "",
  messagePlaceholder = "어떤 교육이나 컨설팅이 필요하신지 적어주세요. 대상과 인원, 원하시는 시기를 함께 적어주시면 준비가 빠릅니다.",
  submitLabel = "문의 남기기",
}) {
  const [regions, setRegions] = useState([]);
  const [form, setForm] = useState({
    found_path: "", found_etc: "", region: "",
    school_name: "", name: "", phone: "", message: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  useEffect(() => {
    api.applicationRegions().then((r) => setRegions(r.regions || [])).catch(() => setRegions([]));
  }, []);

  const set = (patch) => setForm({ ...form, ...patch });

  const submit = async (e) => {
    e.preventDefault();
    if (!form.name.trim() || !form.phone.trim()) {
      setError("이름과 연락 가능한 전화번호는 꼭 입력해 주세요.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.submitApplication({
        kind: "education_inquiry",
        name: form.name.trim(),
        phone: form.phone.trim(),
        found_path: form.found_path,
        found_etc: form.found_etc.trim(),
        message: form.message.trim(),
        extra: {
          "지역": form.region || "-",
          "학교/기관": form.school_name.trim() || "-",
          // 같은 폼이지만 들어온 길에 따라 신청하는 것이 다르다(오프라인
          // 설명회 / 교육·컨설팅 문의). 적어 두지 않으면 관리자 목록에서
          // 둘을 구분할 수 없다.
          ...(via ? { "신청 내용": via } : {}),
        },
      });
      setDone(true);
      if (onDone) onDone();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <div style={{ textAlign: "center", padding: "10px 0" }}>
        <h3 style={{ border: "none", padding: 0, margin: "0 0 8px" }}>
          {via ? `${via} 신청이 접수되었습니다` : "문의가 접수되었습니다"}
        </h3>
        <p style={{ fontSize: 14, color: "var(--steel)", margin: 0, lineHeight: 1.7 }}>
          남겨주신 번호로 연락드리겠습니다.
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={submit} style={{ display: "grid", gap: 14 }}>
      <div className="field">
        <label className="label">우리동네직업계고를 알게 된 경로</label>
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
          {["소개", "검색", "기타"].map((v) => (
            <label key={v} style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 14 }}>
              <input type="radio" name="inq-found" checked={form.found_path === v}
                onChange={() => set({ found_path: v })} />
              {v}
            </label>
          ))}
        </div>
        {form.found_path === "기타" && (
          <input className="input" style={{ marginTop: 8, maxWidth: 320 }}
            placeholder="어떻게 알게 되셨나요?"
            value={form.found_etc}
            onChange={(e) => set({ found_etc: e.target.value })} />
        )}
      </div>

      <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
        <div className="field" style={{ flex: "1 1 140px" }}>
          <label className="label">지역</label>
          <select className="select" value={form.region}
            onChange={(e) => set({ region: e.target.value })}>
            <option value="">선택하세요</option>
            {regions.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </div>
        <div className="field" style={{ flex: "2 1 220px" }}>
          <label className="label">신청 학교 이름</label>
          <input className="input" value={form.school_name}
            placeholder="예) 양주중학교"
            onChange={(e) => set({ school_name: e.target.value })} />
        </div>
      </div>

      <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
        <div className="field" style={{ flex: "1 1 160px" }}>
          <label className="label">신청자 이름</label>
          <input className="input" required value={form.name}
            onChange={(e) => set({ name: e.target.value })} />
        </div>
        <div className="field" style={{ flex: "1 1 180px" }}>
          <label className="label">연락 가능한 전화번호</label>
          <input className="input" required inputMode="tel" placeholder="010-0000-0000"
            value={form.phone}
            onChange={(e) => set({ phone: e.target.value })} />
        </div>
      </div>

      <div className="field">
        <label className="label">기타 및 문의사항</label>
        <textarea className="textarea" rows={5} value={form.message}
          placeholder={messagePlaceholder}
          onChange={(e) => set({ message: e.target.value })} />
      </div>

      {error && <div className="notice notice-error">{error}</div>}

      <div>
        <button className="btn btn-signal" type="submit" disabled={busy}>
          {busy ? "보내는 중…" : submitLabel}
        </button>
      </div>
    </form>
  );
}
