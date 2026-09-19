import { StyleSheet, Text, View } from "react-native";

import { statusDisplay, type ReadingState } from "../../features/reading/playbackStatus";
import { useTheme } from "../../theme/ThemeProvider";

export function StatusPill({ state }: { state: ReadingState }) {
  const { colors, radius, spacing, typography } = useTheme();
  const { label, tone, announce } = statusDisplay(state);
  const toneColor = {
    active: colors.statusActive,
    listening: colors.statusListening,
    thinking: colors.statusThinking,
    neutral: colors.textMuted,
    error: colors.danger,
  }[tone];

  return (
    <View
      accessibilityRole="text"
      accessibilityLabel={`상태: ${label}`}
      accessibilityLiveRegion={announce ? "polite" : "none"}
      style={[styles.pill, { borderRadius: radius.pill, backgroundColor: colors.surfaceMuted, paddingHorizontal: spacing.md }]}
    >
      <View style={[styles.dot, { backgroundColor: toneColor }]} />
      <Text style={[typography.caption, { color: colors.text }]}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  pill: { flexDirection: "row", alignItems: "center", gap: 6, paddingVertical: 4, alignSelf: "flex-start" },
  dot: { width: 8, height: 8, borderRadius: 4 },
});
