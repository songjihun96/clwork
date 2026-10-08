import { StyleSheet, Text, View } from "react-native";

import { useTheme } from "../../theme/ThemeProvider";

/** Scene image area. Phase 9 renders the cached scene image with a cross-fade here. */
export function ScenePlaceholder({ caption }: { caption: string }) {
  const { colors, radius, spacing, typography } = useTheme();
  return (
    <View
      accessibilityRole="image"
      accessibilityLabel={`장면: ${caption}`}
      style={[styles.frame, { backgroundColor: colors.surfaceMuted, borderRadius: radius.lg, padding: spacing.lg }]}
    >
      <Text style={[typography.caption, { color: colors.textMuted }]}>장면 이미지</Text>
      <Text style={[typography.heading, { color: colors.text, textAlign: "center" }]}>{caption}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  frame: { width: "100%", aspectRatio: 16 / 10, alignItems: "center", justifyContent: "center", gap: 4 },
});
