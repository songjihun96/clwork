import type { NativeStackScreenProps } from "@react-navigation/native-stack";
import { Text, View } from "react-native";

import { Button } from "../../components/common/Button";
import { QueryState } from "../../components/common/QueryState";
import { Screen } from "../../components/common/Screen";
import { ProgressBar } from "../../components/reader/ProgressBar";
import { useBook } from "../../features/books/api";
import { useActiveSessions } from "../../features/reading/api";
import type { AppStackParamList } from "../../navigation/types";
import { useTheme } from "../../theme/ThemeProvider";

type Props = NativeStackScreenProps<AppStackParamList, "BookDetail">;

export function BookDetailScreen({ navigation, route }: Props) {
  const { colors, spacing, typography } = useTheme();
  const { bookId } = route.params;
  const book = useBook(bookId);
  const sessions = useActiveSessions();
  const session = sessions.data?.find((s) => s.book.id === bookId);

  if (!book.data) {
    return <QueryState loading={book.isPending} error={book.error} onRetry={() => void book.refetch()} />;
  }
  const detail = book.data;

  return (
    <Screen edges={["left", "right", "bottom"]}>
      <Text style={[typography.title, { color: colors.text }]}>{detail.title}</Text>
      {detail.author ? <Text style={[typography.body, { color: colors.textMuted }]}>{detail.author}</Text> : null}
      {detail.description ? <Text style={[typography.body, { color: colors.text }]}>{detail.description}</Text> : null}

      {session ? (
        <View style={{ gap: spacing.xs }}>
          <Text style={[typography.caption, { color: colors.textMuted }]}>{Math.round(session.progress * 100)}% 읽음</Text>
          <ProgressBar value={session.progress} />
        </View>
      ) : null}

      <Button
        label={session ? "이어 읽기" : "읽기 시작"}
        onPress={() => navigation.navigate("Reader", { bookId })}
      />

      <View style={{ gap: spacing.sm }}>
        <Text style={[typography.heading, { color: colors.text }]}>목차</Text>
        {detail.chapters.map((chapter) => (
          <Text key={chapter.id} style={[typography.body, { color: colors.text }]}>
            {chapter.title}
          </Text>
        ))}
      </View>
    </Screen>
  );
}
