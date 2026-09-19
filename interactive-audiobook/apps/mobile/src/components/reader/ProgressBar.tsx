import { View } from "react-native";

import { useTheme } from "../../theme/ThemeProvider";

export function ProgressBar({ value }: { value: number }) {
  const { colors, radius } = useTheme();
  const percent = Math.round(Math.min(Math.max(value, 0), 1) * 100);
  return (
    <View
      accessibilityRole="progressbar"
      accessibilityValue={{ min: 0, max: 100, now: percent }}
      style={{ height: 4, borderRadius: radius.pill, backgroundColor: colors.surfaceMuted, overflow: "hidden" }}
    >
      <View style={{ width: `${percent}%`, height: "100%", backgroundColor: colors.primary }} />
    </View>
  );
}
