import { StyleSheet, Text, View } from "react-native";

import type { TalkConnectionState, TalkError } from "../../features/talk/types";
import { useTheme } from "../../theme/ThemeProvider";
import { Button } from "../common/Button";

/** Connection state in the reader's words, not the SDK's. */
const LABELS: Record<TalkConnectionState, { label: string; tone: "neutral" | "active" | "listening" | "error" }> = {
  idle: { label: "대화 모드 꺼짐", tone: "neutral" },
  requesting: { label: "연결 준비 중", tone: "listening" },
  connecting: { label: "연결 중", tone: "listening" },
  connected: { label: "대화 모드", tone: "active" },
  reconnecting: { label: "다시 연결 중", tone: "listening" },
  disconnected: { label: "연결 끊김", tone: "neutral" },
  error: { label: "연결 실패", tone: "error" },
};

export interface TalkControlsProps {
  state: TalkConnectionState;
  error: TalkError | null;
  /** False in Expo Go and on the web: Talk mode needs a development build. */
  available: boolean;
  onConnect: () => void;
  onDisconnect: () => void;
}

export function TalkControls({ state, error, available, onConnect, onDisconnect }: TalkControlsProps) {
  const { colors, radius, spacing, typography } = useTheme();
  const { label, tone } = LABELS[state];
  const toneColor = {
    neutral: colors.textMuted,
    active: colors.statusActive,
    listening: colors.statusListening,
    error: colors.danger,
  }[tone];
  const live = state === "connected" || state === "connecting" || state === "requesting" || state === "reconnecting";

  if (!available) {
    return (
      <Text testID="talk-unavailable" style={[typography.caption, { color: colors.textMuted }]}>
        대화 모드는 개발 빌드에서만 동작해요.
      </Text>
    );
  }

  return (
    <View style={[styles.row, { gap: spacing.md }]}>
      <View
        accessibilityRole="text"
        accessibilityLabel={`대화 연결 상태: ${label}`}
        accessibilityLiveRegion="polite"
        testID="talk-status"
        style={[
          styles.pill,
          { borderRadius: radius.pill, backgroundColor: colors.surfaceMuted, paddingHorizontal: spacing.md },
        ]}
      >
        <View style={[styles.dot, { backgroundColor: toneColor }]} />
        <Text style={[typography.caption, { color: colors.text }]}>{label}</Text>
      </View>
      <Button
        label={live ? "대화 종료" : "대화 시작"}
        variant="secondary"
        onPress={live ? onDisconnect : onConnect}
      />
      {error ? (
        <Text accessibilityLiveRegion="polite" style={[typography.caption, { color: colors.danger }]}>
          {error.message}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", flexWrap: "wrap" },
  pill: { flexDirection: "row", alignItems: "center", gap: 6, paddingVertical: 4 },
  dot: { width: 8, height: 8, borderRadius: 4 },
});
