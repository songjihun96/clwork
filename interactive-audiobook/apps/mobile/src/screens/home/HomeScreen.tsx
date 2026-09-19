import type { BottomTabScreenProps } from "@react-navigation/bottom-tabs";
import type { CompositeScreenProps } from "@react-navigation/native";
import type { NativeStackScreenProps } from "@react-navigation/native-stack";
import { Pressable, Text, View } from "react-native";

import { Button } from "../../components/common/Button";
import { QueryState } from "../../components/common/QueryState";
import { Screen } from "../../components/common/Screen";
import { ProgressBar } from "../../components/reader/ProgressBar";
import { useMe } from "../../features/auth/queries";
import { useActiveSessions } from "../../features/reading/api";
import type { AppStackParamList, MainTabParamList } from "../../navigation/types";
import { useTheme } from "../../theme/ThemeProvider";

type Props = CompositeScreenProps<
  BottomTabScreenProps<MainTabParamList, "Home">,
  NativeStackScreenProps<AppStackParamList>
>;

export function HomeScreen({ navigation }: Props) {
  const { colors, radius, spacing, typography } = useTheme();
  const me = useMe();
  const sessions = useActiveSessions();
  const name = me.data?.display_name ?? me.data?.email ?? "";

  return (
    <Screen>
      <Text style={[typography.title, { color: colors.text }]}>{name ? `${name}님, 안녕하세요` : "안녕하세요"}</Text>

      <Text style={[typography.heading, { color: colors.text }]}>이어 듣기</Text>
      {sessions.data && sessions.data.length === 0 ? (
        <View style={{ gap: spacing.md }}>
          <Text style={[typography.body, { color: colors.textMuted }]}>아직 읽기 시작한 책이 없어요.</Text>
          <Button label="서재 둘러보기" variant="secondary" onPress={() => navigation.navigate("Tabs", { screen: "Library" })} />
        </View>
      ) : null}
      {!sessions.data ? (
        <QueryState loading={sessions.isPending} error={sessions.error} onRetry={() => void sessions.refetch()} />
      ) : null}

      {sessions.data?.map((session) => (
        <Pressable
          key={session.id}
          accessibilityRole="button"
          accessibilityLabel={`${session.book.title} 이어 읽기, ${Math.round(session.progress * 100)}퍼센트`}
          onPress={() => navigation.navigate("Reader", { bookId: session.book.id })}
          style={({ pressed }) => ({
            backgroundColor: colors.surface,
            borderColor: colors.border,
            borderWidth: 1,
            borderRadius: radius.lg,
            padding: spacing.lg,
            gap: spacing.sm,
            opacity: pressed ? 0.85 : 1,
          })}
        >
          <Text style={[typography.heading, { color: colors.text }]}>{session.book.title}</Text>
          {session.book.author ? (
            <Text style={[typography.caption, { color: colors.textMuted }]}>{session.book.author}</Text>
          ) : null}
          <View style={{ marginTop: spacing.sm, gap: spacing.xs }}>
            <ProgressBar value={session.progress} />
            <Text style={[typography.caption, { color: colors.textMuted }]}>{Math.round(session.progress * 100)}%</Text>
          </View>
        </Pressable>
      ))}
    </Screen>
  );
}
