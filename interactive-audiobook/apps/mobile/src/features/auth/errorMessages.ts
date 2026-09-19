import { ApiError, NetworkError } from "@audiobook/api-client";

const MESSAGES: Record<string, string> = {
  invalid_credentials: "이메일 또는 비밀번호가 올바르지 않아요.",
  email_taken: "이미 가입된 이메일이에요.",
  rate_limited: "시도가 너무 많아요. 잠시 후 다시 시도해 주세요.",
  validation_error: "입력한 내용을 다시 확인해 주세요.",
  reauthentication_required: "비밀번호가 올바르지 않아요.",
  account_link_required: "이미 이메일로 가입된 계정이에요. 이메일로 로그인해 주세요.",
};

export function describeError(error: unknown): string {
  if (error instanceof NetworkError) return "서버에 연결할 수 없어요. 네트워크를 확인해 주세요.";
  if (error instanceof ApiError) return MESSAGES[error.code] ?? "요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.";
  return "알 수 없는 오류가 발생했어요.";
}
