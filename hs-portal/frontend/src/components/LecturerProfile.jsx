/** 사람 소개 — 강사·컨설턴트.
 *
 * 같은 사람이라도 어디에 붙느냐에 따라 부르는 이름이 다르다. 특강에서는
 * 강사고, 컨설팅·상담 신청서에서는 컨설턴트다. 소개할 내용(사진·경력·링크)이
 * 똑같아서 카드는 한 벌로 두고 이름표만 `role` 로 받는다.
 *
 * 이름표는 카드 **안** 왼쪽 위에 둔다. 바깥에 제목으로 띄우면
 * 카드와 따로 노는 글자가 하나 더 생겨서, 좁은 옆칸에서는 그만큼 세로가
 * 길어지고 무엇에 붙은 이름인지도 덜 분명해진다.
 *
 * 경력은 **표처럼** 세운다. 번호 칸과 글자 칸을 따로 두어, 줄이 넘어가도
 * 이어지는 글자가 번호 밑으로 파고들지 않고 첫 줄 글자와 나란히 선다.
 * (좁은 칸에서 "…강승구 대 / 표" 처럼 어긋나 보이던 것이 이 때문이다.)
 */
export default function LecturerProfile({
  profile, narrow = false, role = "강사", showCta = true,
}) {
  if (!profile?.name && !(profile?.careers || []).length) return null;
  const careers = profile.careers || [];
  const links = profile.links || [];
  const photoSize = narrow ? 76 : 64;

  return (
    <section>
      {/* 카드 */}
      <div style={{
        padding: 16, borderRadius: "var(--radius-sm)",
        border: "1px solid var(--line)", background: "var(--surface)",
      }}>
        <div style={{
          fontSize: 13, fontWeight: 700, color: "var(--steel)",
          marginBottom: narrow ? 12 : 10,
        }}>{role}</div>

        <div style={{
          display: "flex", gap: 14,
          flexDirection: narrow ? "column" : "row",
          alignItems: "center",
          textAlign: narrow ? "center" : "left",
        }}>
          {profile.photo ? (
            <img src={profile.photo} alt={`${profile.name} ${role} 사진`}
              style={{
                width: photoSize, height: photoSize, borderRadius: "50%",
                objectFit: "cover", border: "1px solid var(--line)", flexShrink: 0,
              }} />
          ) : (
            <div style={{
              width: photoSize, height: photoSize, borderRadius: "50%", flexShrink: 0,
              display: "grid", placeItems: "center",
              background: "var(--raised)", color: "var(--steel)", fontSize: 24,
            }}>👤</div>
          )}

          <div style={narrow ? {} : { flex: 1, minWidth: 0 }}>
            <div style={{ fontWeight: 700, fontSize: 16 }}>{profile.name || role}</div>
            {profile.title && (
              <div style={{ fontSize: 13, color: "var(--steel)", marginTop: 2 }}>
                {profile.title}
              </div>
            )}
          </div>
        </div>

        {/* 신청 버튼은 **파는 화면에서는 뺀다.** 이미 돈을 낸 사람에게 다른
            것을 사라고 권하는 자리가 되고, 무엇보다 지금 보던 영상에서
            눈을 떼게 만든다. */}
        {showCta && profile.cta_label && profile.cta_url && (
          <a className="btn btn-signal btn-sm" href={profile.cta_url}
            style={{
              display: "block", marginTop: 14,
              textAlign: "center", lineHeight: 1.45,
            }}>
            {profile.cta_label}
          </a>
        )}

        {links.length > 0 && (
          <div style={{
            display: "grid", gap: 2, marginTop: 12,
            paddingTop: 12, borderTop: "1px solid var(--line)",
          }}>
            {links.map((l, i) => (
              <a key={i} href={l.url} target="_blank" rel="noreferrer noopener"
                style={{
                  display: "flex", gap: 8, alignItems: "center",
                  fontSize: 13.5, padding: "4px 0", color: "var(--color-accent)",
                }}>
                <span style={{ opacity: .7 }}>🔗</span>{l.label}
              </a>
            ))}
          </div>
        )}
      </div>

      {/* 경력 */}
      {careers.length > 0 && (
        <div style={{
          marginTop: 10, padding: "14px 16px",
          border: "1px solid var(--line)", borderRadius: "var(--radius-sm)",
          background: "var(--surface)",
        }}>
          <div style={{ display: "grid", gap: 6 }}>
            {careers.map((c, i) => (
              <div key={i} style={{
                display: "grid", gridTemplateColumns: "1.6em 1fr",
                gap: 6, alignItems: "start",
                fontSize: narrow ? 12.5 : 13.5, lineHeight: 1.6,
              }}>
                <span style={{ color: "var(--steel)", textAlign: "right" }}>{i + 1}.</span>
                <span>{c}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
