import { ORG } from "../org";

const cellHead = { border: "1px solid var(--line)", padding: "8px 10px", textAlign: "left", fontWeight: 700 };
const cell = { border: "1px solid var(--line)", padding: "8px 10px", verticalAlign: "top" };

// 개인정보보호법 제30조에 따른 개인정보처리방침.
// 운영 기관 정보는 src/org.js 에서 가져온다. 오픈 전 그 파일의 [ ] 값을 채우면 된다.
export default function Privacy() {
  return (
    <div className="wrap" style={{ maxWidth: 820, padding: "40px 0 70px" }}>
      <span className="label" style={{ color: "var(--signal-deep)" }}>개인정보처리방침</span>
      <h1 style={{ fontSize: 28, margin: "8px 0 6px" }}>{ORG.serviceName} 개인정보처리방침</h1>
      <p style={{ color: "var(--steel)", fontSize: 14, marginTop: 0 }}>
        시행일: {ORG.privacyEffectiveDate} · 운영: {ORG.operator}
      </p>

      <div style={{ display: "grid", gap: 26, marginTop: 28, fontSize: 14.5, lineHeight: 1.75, color: "var(--ink-soft)" }}>
        <Section title="1. 총칙">
          <p>
            {ORG.operator}(이하 ‘운영자’)은(는) {ORG.serviceName} 서비스(이하 ‘서비스’)를 운영하며,
            「개인정보 보호법」 등 관계 법령을 준수하고 이용자의 개인정보를 보호하기 위해
            본 개인정보처리방침을 수립·공개합니다.
          </p>
        </Section>

        <Section title="2. 수집하는 개인정보 항목과 방법">
          <p>서비스는 다음의 개인정보를 수집합니다.</p>
          <ul>
            <li>
              <b>회원가입(학생·학교 계정):</b> 이메일, 비밀번호, 이름, 생년월일, 휴대폰번호<br />휴대폰번호는 본인확인(SMS 인증)과 아이디·비밀번호 찾기에 사용되는 필수 항목입니다.<br />만 14세 미만 아동의 경우 법정대리인의 전자우편 주소를 추가로 수집합니다.
            </li>
            <li>
              <b>학교 문의하기:</b> 문의 내용, 그리고 답변을 받기 위한 연락처로
              이메일 또는 전화번호 중 이용자가 입력한 항목. 성명은 선택 사항입니다.
            </li>
            <li>
              <b>본인확인(SMS·이메일 인증):</b> 휴대폰번호, 인증번호 발급·확인 일시,
              요청 IP 주소를 수집합니다.
            </li>
            <li>
              <b>자동 수집:</b> 서비스 이용 과정에서 접속 로그와 학교 조회 기록이 생성됩니다.
              또한 관리자 계정이 개인정보를 처리한 경우, 「개인정보의 안전성 확보조치 기준」
              제8조에 따라 처리자의 계정·IP 주소·브라우저 정보·처리 일시가 기록됩니다.
            </li>
          </ul>
          <p>
            개인정보는 이용자가 회원가입·문의 등 서비스 이용 과정에서 직접 입력하는 방식으로 수집합니다.
          </p>
        </Section>

        <Section title="3. 개인정보의 수집·이용 목적">
          <ul>
            <li>회원 식별 및 로그인, 서비스 제공</li>
            <li>휴대폰·이메일을 통한 본인확인, 아이디·비밀번호 찾기, 부정가입 방지</li>
            <li>만 14세 미만 아동의 법정대리인 동의 확인</li>
            <li>학교 문의에 대한 답변 발송</li>
            <li>즐겨찾기 등 이용자 요청 기능 제공</li>
            <li>
              자기소개서 작성 지원 (이용자가 동의하고 요청한 경우에만,
              작성한 글의 문장 정제·경험 분석)
            </li>
            <li>서비스 운영·개선 및 통계</li>
          </ul>
        </Section>

        <Section title="4. 개인정보의 보유·이용 기간 및 파기">
          <ul>
            <li>
              <b>회원 정보:</b> 회원 탈퇴 시 지체 없이 파기합니다. 탈퇴 시 즐겨찾기·
              학교생활 일지·재학생 인증 기록·진로테스트 결과·본인확인 기록을 함께 삭제합니다.
            </li>
            <li>
              <b>본인확인 기록:</b> 인증번호 발급 후 24시간 이내에 파기합니다.
            </li>
            <li>
              <b>법정대리인 동의 기록:</b> 동의 사실을 입증하기 위해 아동 회원이 탈퇴할 때까지
              보관하며, 동의 없이 만료된 요청은 즉시 파기합니다.
            </li>
            <li>
              <b>관리자 처리 기록:</b> 「개인정보의 안전성 확보조치 기준」 제8조에 따라
              1년간 보관 후 파기합니다. 이는 법령상 보존 의무가 있는 정보로, 회원 탈퇴 시에도
              계정 연결만 끊고 기록 자체는 보존 기간까지 유지합니다(개인정보 보호법 제21조 제1항 단서).
            </li>
            <li>
              <b>학교 문의:</b> 접수일로부터 365일 보관 후 파기하며, 해당 학교가 문의를
              삭제하거나 이용자가 삭제를 요청하면 즉시 파기합니다. 답변 완료 후 연락처는
              보유기간 내에서 답변 발송 목적으로만 이용됩니다.
            </li>
          </ul>
          <p>
            파기 시 전자적 파일은 복구할 수 없는 방법으로 삭제합니다.
          </p>
        </Section>

        <Section title="5. 개인정보의 제3자 제공">
          <p>
            서비스는 원칙적으로 이용자의 개인정보를 외부에 제공하지 않습니다. 다만
            <b> 학교 문의하기</b> 기능의 경우, 답변을 위해 이용자가 남긴 문의 내용과 연락처가
            <b> 문의 대상 학교(학교 계정)</b>에 제공됩니다. 이는 이용자가 문의를 남길 때
            별도로 동의한 범위에서만 이루어지며, 답변 발송 외의 목적으로 이용되지 않습니다.
          </p>
        </Section>

        <Section title="6. 개인정보 처리업무의 위탁">
          <p>
            서비스는 원활한 운영을 위해 아래와 같이 개인정보 처리업무를 위탁하고 있습니다.
            위탁계약 시 개인정보 보호법 제26조에 따라 목적 외 처리 금지, 안전성 확보조치,
            재위탁 제한, 관리·감독, 손해배상 등 책임에 관한 사항을 계약서에 명시하고 있습니다.
          </p>
          <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 10, fontSize: 14 }}>
            <thead>
              <tr style={{ background: "var(--surface)" }}>
                <th style={cellHead}>수탁자</th>
                <th style={cellHead}>위탁업무 내용</th>
                <th style={cellHead}>보유·이용 기간</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td style={cell}>{ORG.hostingProvider}</td>
                <td style={cell}>서버 운영 및 데이터 보관(클라우드 인프라 제공)</td>
                <td style={cell}>위탁계약 종료 시까지</td>
              </tr>
              <tr>
                <td style={cell}>우리동네소프트</td>
                <td style={cell}>시스템 개발 및 유지보수(서버·데이터베이스 접근 포함)</td>
                <td style={cell}>위탁계약 종료 시까지</td>
              </tr>
              <tr>
                <td style={cell}>메일 발송 서비스 제공자</td>
                <td style={cell}>문의 답변·비밀번호 재설정 등 알림 메일 발송</td>
                <td style={cell}>발송 목적 달성 시까지</td>
              </tr>
              {/* 실제 발송 업체는 backend/.env 의 SMS_PROVIDER 로 정해진다
                  (현재 sens = 네이버 클라우드 SENS). 업체를 바꾸면 이 줄도
                  반드시 같이 고쳐야 한다 — 수탁자는 사실과 달라선 안 된다.
                  서버 호스팅과 같은 법인이지만 보유 기간이 달라 줄을 나눈다. */}
              <tr>
                <td style={cell}>{ORG.hostingProvider} (SENS)</td>
                <td style={cell}>본인확인 인증번호 및 계정 알림 문자메시지(SMS) 발송</td>
                <td style={cell}>발송 목적 달성 시까지</td>
              </tr>
              <tr>
                <td style={cell}>Anthropic PBC</td>
                <td style={cell}>
                  자기소개서 작성 지원을 위한 문장 정제·경험 분석 (이용자가
                  AI 기능 이용에 동의하고 직접 요청한 경우에만)
                </td>
                <td style={cell}>처리 완료 시까지</td>
              </tr>
            </tbody>
          </table>
          <p style={{ marginTop: 10 }}>
            위탁업무의 내용이나 수탁자가 변경될 경우, 지체 없이 본 방침을 통하여 공개합니다.
          </p>
        </Section>

        <Section title="7. 개인정보의 국외 이전">
          <p>
            서비스는 자기소개서 작성 지원 기능(AI 문장 정제·경험 분석)을 제공하기 위해
            아래와 같이 개인정보를 국외로 이전합니다. 이 기능은{" "}
            <b>이용자가 별도로 동의하고 직접 요청한 경우에만</b> 동작하며,
            동의하지 않아도 일지 작성·자기소개서 작성 등 서비스의 다른 기능은
            제한 없이 이용할 수 있습니다.
          </p>
          <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 10, fontSize: 14 }}>
            <thead>
              <tr style={{ background: "var(--surface)" }}>
                <th style={cellHead}>구분</th>
                <th style={cellHead}>내용</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td style={cell}>이전받는 자</td>
                <td style={cell}>Anthropic PBC (미국)</td>
              </tr>
              <tr>
                <td style={cell}>연락처</td>
                <td style={cell}>privacy@anthropic.com</td>
              </tr>
              <tr>
                <td style={cell}>이전 국가</td>
                <td style={cell}>미국</td>
              </tr>
              <tr>
                <td style={cell}>이전 일시 및 방법</td>
                <td style={cell}>
                  이용자가 AI 기능을 요청하는 시점에 암호화된 통신(HTTPS)으로 전송
                </td>
              </tr>
              <tr>
                <td style={cell}>이전 항목</td>
                <td style={cell}>
                  이용자가 AI 분석을 요청한 일지·자기소개서의 본문
                  <br />
                  <b>
                    이름, 학교명, 이메일, 전화번호 등 개인을 알아볼 수 있는 정보는
                    전송 전에 서비스가 가명으로 바꾸어 처리하므로 이전되지 않습니다.
                  </b>
                </td>
              </tr>
              <tr>
                <td style={cell}>이전 목적</td>
                <td style={cell}>문장 정제, 경험 분석, 자기소개서 초안 작성 지원</td>
              </tr>
              <tr>
                <td style={cell}>보유·이용 기간</td>
                <td style={cell}>
                  처리 완료 시까지. 이전받는 자는 전송된 내용을 인공지능 모델의
                  학습에 이용하지 않습니다.
                </td>
              </tr>
            </tbody>
          </table>
          <p style={{ marginTop: 10 }}>
            이용자는 개인정보의 국외 이전을 거부할 수 있습니다. 거부하시더라도
            AI 기능만 이용할 수 없을 뿐, 서비스 이용에 다른 불이익은 없습니다.
            동의는 <b>내 정보</b> 화면에서 언제든지 철회할 수 있습니다.
          </p>
        </Section>

        <Section title="8. 학교생활 일지·일기의 열람 범위">
          <p>
            서비스(기록해, diary.ggm.kr)에서 학생이 작성한 학교생활 일기와 수업 일지는
            <b> 학생이 직접 &lsquo;제출&rsquo;한 경우에만</b> 아래 계정이 열람할 수 있습니다.
            제출하지 않은 기록은 작성자 본인 외에 누구도 볼 수 없습니다.
          </p>
          <ul>
            <li>
              <b>담당 선생님:</b> 재학생 인증을 승인한 학생의 제출 기록.
              소속 학교 전체 학생의 제출 기록도 확인할 수 있습니다.
            </li>
            <li>
              <b>학교 계정:</b> 해당 학교 소속으로 인증된 학생의 제출 기록.
            </li>
            <li>
              <b>포털 관리자:</b> 문의 처리·오류 확인 등 운영에 필요한 경우에 한하여,
              학교를 특정하여 열람합니다. 전체 학생의 기록을 일괄 조회할 수 없도록
              제한하고 있습니다.
            </li>
          </ul>
          <p>
            담당 선생님이 아닌 계정(학교·포털 관리자)이 학생의 기록을 열람한 경우,
            「개인정보의 안전성 확보조치 기준」 제8조에 따라 열람자·열람 대상·일시·
            접속 IP가 기록되며 1년간 보관됩니다.
          </p>
          <p>
            학생은 언제든지 자신이 작성한 기록을 수정하거나 삭제할 수 있으며,
            삭제한 기록은 열람 대상에서도 즉시 제외됩니다.
          </p>
        </Section>

        <Section title="9. 만 14세 미만 아동의 개인정보">
          <p>
            서비스는 회원가입 시 생년월일을 확인하여 만 14세 미만 아동 여부를 확인합니다.
            만 14세 미만 아동이 회원가입을 신청하는 경우, 개인정보 보호법 제22조의2에 따라
            <b> 법정대리인의 동의를 받은 후에만 가입이 완료</b>됩니다.
          </p>
          <ul>
            <li>
              가입 신청 시 법정대리인의 전자우편 주소를 입력받아, 해당 주소로 수집 항목·이용
              목적·보유 기간을 안내한 동의 요청 메일을 발송합니다.
              (개인정보 보호법 시행령 제17조의2에 따른 동의 방법)
            </li>
            <li>
              법정대리인이 동의하기 전까지 아동의 계정은 활성화되지 않으며, 서비스를 이용할
              수 없습니다. 동의 요청 링크는 발송일로부터 7일간 유효합니다.
            </li>
            <li>
              법정대리인의 동의를 확인하기 위한 최소한의 정보(법정대리인의 전자우편 주소,
              동의 일시)만 수집하며, 이는 동의 확인 외의 목적으로 이용하지 않습니다.
            </li>
            <li>
              법정대리인은 언제든지 아동의 개인정보에 대한 열람·정정·삭제 및 처리정지를
              요구할 수 있으며, 동의를 철회할 수 있습니다.
            </li>
          </ul>
          <p>
            서비스의 학교 문의하기 기능은 만 14세 이상만 이용할 수 있습니다.
            만 14세 미만 아동으로부터는 문의 목적의 개인정보를 수집하지 않습니다.
          </p>
        </Section>

        <Section title="10. 이용자와 법정대리인의 권리와 행사 방법">
          <p>
            이용자는 언제든지 자신의 개인정보에 대해 열람·정정·삭제·처리정지를 요청할 수 있습니다.
            회원은 계정 설정에서 직접 정보를 수정하거나 탈퇴할 수 있으며, 문의로 남긴 개인정보의
            삭제는 아래 개인정보 보호책임자에게 요청할 수 있습니다.
          </p>
        </Section>

        <Section title="11. 개인정보의 안전성 확보 조치">
          <ul>
            <li>비밀번호 등 인증정보의 암호화 저장</li>
            <li>통신 구간 암호화(HTTPS) 적용</li>
            <li>개인정보 처리 시스템에 대한 접근 권한 관리</li>
            <li>보유기간이 지난 문의 정보의 자동 파기</li>
          </ul>
        </Section>

        <Section title="12. 개인정보 보호책임자">
          <p>
            서비스는 개인정보 처리에 관한 업무를 총괄하고 이용자의 문의에 대응하기 위해
            아래와 같이 개인정보 보호책임자를 지정하고 있습니다.
          </p>
          <div style={{ background: "var(--paper)", border: "1px solid var(--line)", borderRadius: "var(--radius)", padding: "16px 18px", marginTop: 8 }}>
            <div>· 성명: {ORG.privacyOfficerName}</div>
            <div>· 직책: {ORG.privacyOfficerTitle}</div>
            <div>· 이메일: {ORG.privacyOfficerEmail}</div>
            <div>· 전화: {ORG.privacyOfficerPhone}</div>
          </div>
          <p style={{ marginTop: 10 }}>
            운영 기관: {ORG.operator} · {ORG.address} · {ORG.contactEmail} · {ORG.contactPhone}
          </p>
        </Section>

        <Section title="13. 권익침해 구제 방법">
          <p>
            개인정보 침해로 인한 상담·신고가 필요한 경우 아래 기관에 문의할 수 있습니다.
          </p>
          <ul>
            <li>개인정보분쟁조정위원회 (privacy.go.kr / 국번없이 1833-6972)</li>
            <li>개인정보침해신고센터 (privacy.kisa.or.kr / 국번없이 118)</li>
            <li>대검찰청 사이버수사과 (spo.go.kr / 1301)</li>
            <li>경찰청 사이버수사국 (ecrm.police.go.kr / 182)</li>
          </ul>
        </Section>

        <Section title="14. 개인정보처리방침의 변경">
          <p>
            본 방침은 법령·서비스 변경에 따라 개정될 수 있으며, 변경 시 서비스 내 공지를 통해
            알립니다.
          </p>
        </Section>

        <p style={{ color: "var(--steel-light)", fontSize: 13, marginTop: 10 }}>
          시행일: {ORG.privacyEffectiveDate}
        </p>
      </div>
    </div>
  );
}

function Section({ title, children }) {
  return (
    <section>
      <h2 style={{ fontSize: 17, marginBottom: 10 }}>{title}</h2>
      <div>{children}</div>
    </section>
  );
}
