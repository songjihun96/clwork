import { useEffect, useState } from "react";
import { api } from "../api";
import LecturerProfile from "./LecturerProfile";

/** 신청서 아래에 붙는 **누가 봐 주는지**.
 *
 * 컨설팅·상담은 30만 원, 10만 원을 선입금하고 기다리는 신청이다. 파는 쪽이
 * 누구인지 모르는 채로 계좌부터 받으라고 하면 대부분 거기서 멈춘다. 그래서
 * 신청폼 바로 아래에 사람을 보여 준다 — 폼을 채우다 망설이는 자리가 거기다.
 *
 * 프로필은 설명회(특강)와 **같은 것을 쓴다**. 같은 사람이라 두 벌로 두면
 * 경력 한 줄을 고칠 때 한쪽만 고쳐 놓고 잊는다. 부르는 이름만 자리에 맞게
 * 바꾼다 — 특강에서는 강사, 여기서는 컨설턴트.
 *
 * 아직 프로필을 안 채웠으면 아무것도 안 보여 준다(LecturerProfile 이
 * 알아서 빈 카드를 안 그린다).
 */
export default function ConsultantProfile({ role = "컨설턴트" }) {
  const [profile, setProfile] = useState(null);

  useEffect(() => {
    let alive = true;
    api.lecturer()
      .then((d) => { if (alive) setProfile(d); })
      .catch(() => { if (alive) setProfile(null); });
    return () => { alive = false; };
  }, []);

  if (!profile) return null;

  return (
    <div style={{ marginTop: 24 }}>
      {/* 이 화면에는 이미 바로 위에 신청폼이 있다. 프로필에 붙은 신청
          버튼까지 띄우면 같은 화면에서 신청하라는 말을 두 번 하는 셈이고,
          그 버튼이 다른 상품을 가리키면 방금 채우던 폼에서 눈을 떼게 된다. */}
      <LecturerProfile profile={profile} role={role} showCta={false} />
    </div>
  );
}
