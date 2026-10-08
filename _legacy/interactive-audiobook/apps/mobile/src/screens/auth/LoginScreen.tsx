import type { NativeStackScreenProps } from "@react-navigation/native-stack";
import { useState } from "react";
import { Text } from "react-native";

import { Button } from "../../components/common/Button";
import { Screen } from "../../components/common/Screen";
import { TextField } from "../../components/common/TextField";
import { signIn } from "../../features/auth/authActions";
import { describeError } from "../../features/auth/errorMessages";
import { validateEmail } from "../../features/auth/validation";
import type { AuthStackParamList } from "../../navigation/types";
import { useTheme } from "../../theme/ThemeProvider";

type Props = NativeStackScreenProps<AuthStackParamList, "Login">;

export function LoginScreen({ navigation }: Props) {
  const { colors, typography } = useTheme();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fieldErrors, setFieldErrors] = useState<{ email?: string | null; password?: string | null }>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit() {
    const errors = { email: validateEmail(email), password: password ? null : "비밀번호를 입력해 주세요." };
    setFieldErrors(errors);
    setFormError(null);
    if (errors.email || errors.password) return;

    setSubmitting(true);
    try {
      await signIn(email.trim(), password);
      // Navigation switches to the app stack automatically when the auth store becomes signedIn.
    } catch (error) {
      setFormError(describeError(error));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Screen edges={["left", "right", "bottom"]}>
      <Text style={[typography.title, { color: colors.text }]}>다시 만나서 반가워요</Text>
      <Text style={[typography.body, { color: colors.textMuted }]}>읽던 이야기를 이어서 들려드릴게요.</Text>

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
        label="비밀번호"
        value={password}
        onChangeText={setPassword}
        error={fieldErrors.password}
        secureTextEntry
        autoComplete="current-password"
        textContentType="password"
        maxLength={128}
        onSubmitEditing={() => void handleSubmit()}
      />

      {formError ? (
        <Text accessibilityLiveRegion="assertive" style={[typography.body, { color: colors.danger }]}>
          {formError}
        </Text>
      ) : null}

      <Button label="로그인" onPress={() => void handleSubmit()} loading={submitting} />
      <Button label="이메일로 회원가입" variant="ghost" onPress={() => navigation.navigate("Register")} />
    </Screen>
  );
}
