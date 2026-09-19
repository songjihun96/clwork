import { useEffect, useRef, useState } from "react";
import { api } from "../api";

// 휴대폰 본인확인 공용 컴포넌트.
// 인증에 성공하면 onVerified(token, phone) 으로 일회용 토큰을 넘긴다.
// purpose: signup | find_id | reset_pw | change_pw
export default function PhoneVerify({
  purpose,
  phone,
  onPhoneChange,
  onVerified,
  email = "",          // 메일 채널일 때 인증번호를 받을 주소
  label = "휴대폰번호",
  disabled = false,
}) {
  const [channel, setChannel] = useState("sms");
  const [sent, setSent] = useState(false);
  const [code, setCode] = useState("");
  const [verified, setVerified] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [left, setLeft] = useState(0);      // 인증번호 유효 남은 초
  const [cool, setCool] = useState(0);      // 재발송 대기 남은 초
  const timer = useRef(null);
  const coolTimer = useRef(null);

  useEffect(() => () => {
    clearInterval(timer.current);
    clearInterval(coolTimer.current);
  }, []);

  useEffect(() => {
    api.verifyConfig().then((c) => setChannel(c.channel)).catch(() => {});
  }, []);

  // 번호를 바꾸면 인증 상태를 초기화한다.
  useEffect(() => {
    setSent(false);
    setVerified(false);
    setCode("");
    setLeft(0);
    clearInterval(timer.current);
    onVerified("", "");
  }, [phone]);

  const startCountdown = (minutes) => {
    setLeft(minutes * 60);
    clearInterval(timer.current);
    timer.current = setInterval(() => {
      setLeft((v) => {
        if (v <= 1) {
          clearInterval(timer.current);
          return 0;
        }
        return v - 1;
      });
    }, 1000);
  };

  const send = async () => {
    setBusy(true);
    setError("");
    setMsg("");
    try {
      const res = await api.sendPhoneCode({ phone, purpose, email: email || undefined });
      setSent(true);
      startCountdown(res.ttl_min || 3);
      // 문자 요금이 나가므로 잠시 재발송을 막는다(서버도 동일하게 막고 있다).
      setCool(60);
      clearInterval(coolTimer.current);
      coolTimer.current = setInterval(() => {
        setCool((v) => {
          if (v <= 1) {
            clearInterval(coolTimer.current);
            return 0;
          }
          return v - 1;
        });
      }, 1000);
      const where = res.sent_to ? ` (${res.sent_to})` : "";
      setMsg(
        res.sent
          ? res.channel === "email"
            ? `인증번호를 이메일로 보냈습니다${where}. 메일함을 확인해주세요.`
            : `인증번호를 문자로 보냈습니다${where}.`
          : `${res.channel === "email" ? "메일" : "문자"} 발송에 실패했습니다. 관리자에게 문의해주세요.`
      );
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const verify = async () => {
    setBusy(true);
    setError("");
    try {
      const res = await api.verifyPhoneCode({ phone, purpose, code });
      setVerified(true);
      setMsg("인증이 완료되었습니다.");
      clearInterval(timer.current);
      onVerified(res.verification_token, phone);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const mmss = `${String(Math.floor(left / 60)).padStart(2, "0")}:${String(left % 60).padStart(2, "0")}`;
  const canSend =
    !disabled && !busy && cool === 0 && (phone || "").replace(/\D/g, "").length >= 10;

  return (
    <div className="field">
      <label className="label" htmlFor="phone">{label}</label>
      {channel === "email" && (
        <span style={{ fontSize: 12, color: "var(--steel-light)", display: "block", marginBottom: 4 }}>
          인증번호는 문자가 아니라 <b>이메일</b>로 발송됩니다
          {email ? ` (${email})` : "(가입하신 이메일 주소)"}.
        </span>
      )}
      <div style={{ display: "flex", gap: 8 }}>
        <input
          id="phone"
          className="input"
          value={phone}
          required
          inputMode="tel"
          maxLength={30}
          autoComplete="tel"
          placeholder="010-1234-5678"
          disabled={disabled || verified}
          onChange={(e) => onPhoneChange(e.target.value)}
        />
        <button
          type="button"
          className="btn btn-sm"
          style={{ whiteSpace: "nowrap" }}
          disabled={!canSend || verified}
          onClick={send}
        >
          {verified ? "인증완료" : cool > 0 ? `재발송 ${cool}초` : sent ? "재발송" : "인증번호 받기"}
        </button>
      </div>

      {sent && !verified && (
        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <input
            className="input"
            value={code}
            inputMode="numeric"
            maxLength={6}
            placeholder="인증번호 6자리"
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
          />
          <button
            type="button"
            className="btn btn-sm"
            style={{ whiteSpace: "nowrap" }}
            disabled={busy || code.length !== 6}
            onClick={verify}
          >
            확인
          </button>
        </div>
      )}

      {sent && !verified && left > 0 && (
        <span style={{ fontSize: 12, color: "var(--steel)" }}>남은 시간 {mmss}</span>
      )}
      {sent && !verified && left === 0 && (
        <span style={{ fontSize: 12, color: "var(--alert)" }}>
          인증번호가 만료되었습니다. 재발송해주세요.
        </span>
      )}
      {msg && !error && (
        <span style={{ fontSize: 12, color: verified ? "var(--signal-deep)" : "var(--steel-light)" }}>
          {msg}
        </span>
      )}
      {error && <span style={{ fontSize: 12, color: "var(--alert)" }}>{error}</span>}
    </div>
  );
}
