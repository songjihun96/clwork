import { ActivityIndicator, StyleSheet, Text, View } from "react-native";

import { describeError } from "../../features/auth/errorMessages";
import { useTheme } from "../../theme/ThemeProvider";
import { Button } from "./Button";

interface QueryStateProps {
  loading?: boolean;
  error?: unknown;
  onRetry?: () => void;
}

/** Shared loading / error presentation for data-driven screens. Renders nothing when there is data. */
export function QueryState({ loading, error, onRetry }: QueryStateProps) {
  const { colors, spacing, typography } = useTheme();
  if (error) {
    return (
      <View style={[styles.center, { gap: spacing.md, padding: spacing.xl }]}>
        <Text accessibilityLiveRegion="polite" style={[typography.body, { color: colors.textMuted, textAlign: "center" }]}>
          {describeError(error)}
        </Text>
        {onRetry ? <Button label="다시 시도" variant="secondary" onPress={onRetry} /> : null}
      </View>
    );
  }
  if (loading) {
    return (
      <View style={[styles.center, { padding: spacing.xl }]}>
        <ActivityIndicator accessibilityLabel="불러오는 중" color={colors.primary} />
      </View>
    );
  }
  return null;
}

const styles = StyleSheet.create({ center: { flex: 1, alignItems: "center", justifyContent: "center" } });
