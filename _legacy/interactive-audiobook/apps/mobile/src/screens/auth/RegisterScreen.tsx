import { useState } from "react";
import { Text } from "react-native";

import { Button } from "../../components/common/Button";
import { Screen } from "../../components/common/Screen";
import { TextField } from "../../components/common/TextField";
import { register } from "../../features/auth/authActions";
import { describeError } from "../../features/auth/errorMessages";
import { validateEmail, validateNewPassword } from "../../features/auth/validation";
import { useTheme } from "../../theme/ThemeProvider";

export function RegisterScreen() {
  const { colors, typography } = useTheme();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [fieldErrors, setFieldErrors] = useState<{ email?: string | null; password?: string | null }>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit() {
    const errors = { email: validateEmail(email), password: validateNewPassword(password) };
    setFieldErrors(errors);
    setFormError(null);
    if (errors.email || errors.password) return;

    setSubmitting(true);
    try {
      await register(email.trim(), password, displayName);
    } catch (error) {
      setFormError(describeError(error));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Screen edges={["left", "right", "bottom"]}>
      <Text style={[typography.title, { color: colors.text }]}>계정 만들기</Text>
      <TextField
        label="이메일"
        value={email}
        onChangeText={setEmail}
        error={fieldErrors.email}
        autoCapitalize="none"
        autoComplete="email"
        keyboardType="email-address"
        textContentType="emailAddress"
        maxLength={320}
      />
      <TextField
        label="비밀번호 (8자 이상)"
        value={password}
        onChangeText={setPassword}
        error={fieldErrors.password}
        secureTextEntry
        autoComplete="new-password"
        textContentType="newPassword"
        maxLength={128}
      />
      <TextField
        label="이름 (선택)"
        value={displayName}
        onChangeText={setDisplayName}
        autoComplete="name"
        maxLength={80}
      />
      {formError ? (
        <Text accessibilityLiveRegion="assertive" style={[typography.body, { color: colors.danger }]}>
          {formError}
        </Text>
      ) : null}
      <Button label="가입하기" onPress={() => void handleSubmit()} loading={submitting} />
    </Screen>
  );
}
