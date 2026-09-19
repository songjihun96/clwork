import { useState } from "react";
import { Alert, Pressable, Text, View } from "react-native";

import { Button } from "../../components/common/Button";
import { Screen } from "../../components/common/Screen";
import { TextField } from "../../components/common/TextField";
import { deleteAccount, signOut } from "../../features/auth/authActions";
import { describeError } from "../../features/auth/errorMessages";
import { useMe } from "../../features/auth/queries";
import { useSettingsStore, type ThemePreference } from "../../stores/settingsStore";
import { useTheme } from "../../theme/ThemeProvider";

const THEME_OPTIONS: { value: ThemePreference; label: string }[] = [
  { value: "system", label: "시스템" },
  { value: "light", label: "라이트" },
  { value: "dark", label: "다크" },
];

export function SettingsScreen() {
  const { colors, radius, spacing, typography } = useTheme();
  const { themePreference, setThemePreference } = useSettingsStore();
  const me = useMe();
  const [password, setPassword] = useState("");
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  function confirmDelete() {
    setDeleteError(null);
    if (!password) {
      setDeleteError("계정을 삭제하려면 비밀번호를 입력해 주세요.");
      return;
    }
    Alert.alert("계정 삭제", "계정과 독서 기록이 영구적으로 삭제되며 되돌릴 수 없어요.", [
      { text: "취소", style: "cancel" },
      {
        text: "삭제",
        style: "destructive",
        onPress: async () => {
          setDeleting(true);
          try {
            await deleteAccount(password);
          } catch (error) {
            setDeleteError(describeError(error));
          } finally {
            setDeleting(false);
          }
        },
      },
    ]);
  }

  return (
    <Screen>
      <Text style={[typography.title, { color: colors.text }]}>설정</Text>

      <View style={{ gap: spacing.sm }}>
        <Text style={[typography.heading, { color: colors.text }]}>화면 테마</Text>
        <View accessibilityRole="radiogroup" style={{ flexDirection: "row", gap: spacing.sm }}>
          {THEME_OPTIONS.map((option) => {
            const selected = option.value === themePreference;
            return (
              <Pressable
                key={option.value}
                accessibilityRole="radio"
                accessibilityState={{ selected }}
                onPress={() => setThemePreference(option.value)}
                style={{
                  flex: 1,
                  minHeight: 44,
                  alignItems: "center",
                  justifyContent: "center",
                  borderRadius: radius.md,
                  borderWidth: 1,
                  borderColor: selected ? colors.primary : colors.border,
                  backgroundColor: selected ? colors.surfaceMuted : colors.surface,
                }}
              >
                <Text style={[typography.label, { color: colors.text }]}>{option.label}</Text>
              </Pressable>
            );
          })}
        </View>
      </View>

      <View style={{ gap: spacing.sm }}>
        <Text style={[typography.heading, { color: colors.text }]}>계정</Text>
        <Text style={[typography.body, { color: colors.textMuted }]}>{me.data?.email ?? "이메일 없음"}</Text>
        <Button label="로그아웃" variant="secondary" onPress={() => void signOut()} />
      </View>

      <View style={{ gap: spacing.sm, marginTop: spacing.lg }}>
        <Text style={[typography.heading, { color: colors.danger }]}>계정 삭제</Text>
        <TextField
          label="비밀번호 확인"
          value={password}
          onChangeText={setPassword}
          secureTextEntry
          autoComplete="current-password"
          error={deleteError}
          maxLength={128}
        />
        <Button label="계정 영구 삭제" variant="danger" loading={deleting} onPress={confirmDelete} />
      </View>
    </Screen>
  );
}
