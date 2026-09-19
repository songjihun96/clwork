// Mirrors backend rules (services/api/app/schemas/auth.py). The server remains the authority.
export const PASSWORD_MIN_LENGTH = 8;
export const PASSWORD_MAX_LENGTH = 128;

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function validateEmail(email: string): string | null {
  if (!email.trim()) return "이메일을 입력해 주세요.";
  if (!EMAIL_PATTERN.test(email.trim())) return "올바른 이메일 형식이 아니에요.";
  return null;
}

export function validateNewPassword(password: string): string | null {
  if (password.length < PASSWORD_MIN_LENGTH) return `비밀번호는 ${PASSWORD_MIN_LENGTH}자 이상이어야 해요.`;
  if (password.length > PASSWORD_MAX_LENGTH) return `비밀번호는 ${PASSWORD_MAX_LENGTH}자 이하여야 해요.`;
  return null;
}
