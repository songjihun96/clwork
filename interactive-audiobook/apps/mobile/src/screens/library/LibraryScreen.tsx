import type { BottomTabScreenProps } from "@react-navigation/bottom-tabs";
import type { CompositeScreenProps } from "@react-navigation/native";
import type { NativeStackScreenProps } from "@react-navigation/native-stack";
import { FlatList, Pressable, RefreshControl, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { QueryState } from "../../components/common/QueryState";
import { useBooks } from "../../features/books/api";
import type { AppStackParamList, MainTabParamList } from "../../navigation/types";
import { useTheme } from "../../theme/ThemeProvider";

type Props = CompositeScreenProps<
  BottomTabScreenProps<MainTabParamList, "Library">,
  NativeStackScreenProps<AppStackParamList>
>;

export function LibraryScreen({ navigation }: Props) {
  const { colors, radius, spacing, typography } = useTheme();
  const books = useBooks();

  return (
    <SafeAreaView edges={["top", "left", "right"]} style={{ flex: 1, backgroundColor: colors.background }}>
      <FlatList
        data={books.data?.items ?? []}
        keyExtractor={(book) => book.id}
        contentContainerStyle={{ padding: spacing.xl, gap: spacing.md, flexGrow: 1 }}
        refreshControl={
          <RefreshControl refreshing={books.isRefetching} onRefresh={() => void books.refetch()} tintColor={colors.primary} />
        }
        ListHeaderComponent={<Text style={[typography.title, { color: colors.text }]}>서재</Text>}
        ListEmptyComponent={
          books.isPending || books.error ? (
            <QueryState loading={books.isPending} error={books.error} onRetry={() => void books.refetch()} />
          ) : (
            <Text style={[typography.body, { color: colors.textMuted }]}>아직 읽을 수 있는 책이 없어요.</Text>
          )
        }
        renderItem={({ item }) => (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={`${item.title}${item.author ? `, ${item.author}` : ""}`}
            onPress={() => navigation.navigate("BookDetail", { bookId: item.id })}
            style={({ pressed }) => ({
              flexDirection: "row",
              gap: spacing.md,
              padding: spacing.md,
              borderRadius: radius.md,
              backgroundColor: colors.surface,
              opacity: pressed ? 0.85 : 1,
            })}
          >
            <View style={{ width: 56, height: 80, borderRadius: radius.sm, backgroundColor: colors.surfaceMuted }} />
            <View style={{ flex: 1, justifyContent: "center", gap: spacing.xs }}>
              <Text style={[typography.heading, { color: colors.text }]}>{item.title}</Text>
              {item.author ? (
                <Text style={[typography.caption, { color: colors.textMuted }]}>{item.author}</Text>
              ) : null}
            </View>
          </Pressable>
        )}
      />
    </SafeAreaView>
  );
}
