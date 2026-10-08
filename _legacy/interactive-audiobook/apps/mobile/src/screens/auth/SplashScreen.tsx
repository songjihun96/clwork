import { ActivityIndicator, StyleSheet, Text, View } from "react-native";

import { Button } from "../../components/common/Button";
import { bootstrapSession } from "../../features/auth/authActions";
import { useAuthStore } from "../../features/auth/authStore";
import { useTheme } from "../../theme/ThemeProvider";

export function SplashScreen() {
  const { colors, spacing, typography } = useTheme();
  const failed = useAuthStore((s) => s.status === "bootstrapFailed");

  return (
    <View style={[styles.container, { backgroundColor: colors.background, gap: spacing.lg, padding: spacing.xl }]}>
      <Text style={[typography.title, { color: colors.text }]}>Interactive Audiobook</Text>
      {failed ? (
        <>
          <Text style={[typography.body, { color: colors.textMuted, textAlign: "center" }]}>
            서버에 연결할 수 없어요. 네트워크를 확인한 뒤 다시 시도해 주세요.
          </Text>
          <Button label="다시 시도" onPress={() => void bootstrapSession()} />
        </>
      ) : (
        <ActivityIndicator accessibilityLabel="불러오는 중" color={colors.primary} />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, alignItems: "center", justifyContent: "center" },
});
