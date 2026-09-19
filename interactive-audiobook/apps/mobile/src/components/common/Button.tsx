import { ActivityIndicator, Pressable, StyleSheet, Text, type StyleProp, type ViewStyle } from "react-native";

import { useTheme } from "../../theme/ThemeProvider";

type Variant = "primary" | "secondary" | "danger" | "ghost";

interface ButtonProps {
  label: string;
  onPress: () => void;
  variant?: Variant;
  loading?: boolean;
  disabled?: boolean;
  accessibilityHint?: string;
  style?: StyleProp<ViewStyle>;
}

export function Button({ label, onPress, variant = "primary", loading, disabled, accessibilityHint, style }: ButtonProps) {
  const { colors, radius, spacing, typography } = useTheme();
  const inactive = disabled || loading;

  const background = { primary: colors.primary, secondary: colors.surfaceMuted, danger: "transparent", ghost: "transparent" }[
    variant
  ];
  const foreground = { primary: colors.onPrimary, secondary: colors.text, danger: colors.danger, ghost: colors.primary }[
    variant
  ];

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityHint={accessibilityHint}
      accessibilityState={{ disabled: !!inactive, busy: !!loading }}
      disabled={inactive}
      onPress={onPress}
      style={({ pressed }) => [
        styles.base,
        {
          backgroundColor: background,
          borderRadius: radius.md,
          paddingVertical: spacing.md,
          paddingHorizontal: spacing.lg,
          borderColor: variant === "danger" ? colors.danger : "transparent",
          opacity: inactive ? 0.5 : pressed ? 0.8 : 1,
        },
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator color={foreground} />
      ) : (
        <Text style={[typography.label, { color: foreground }]}>{label}</Text>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: { alignItems: "center", justifyContent: "center", minHeight: 48, borderWidth: 1 },
});
