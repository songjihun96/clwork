import type { NativeStackScreenProps } from "@react-navigation/native-stack";
import { useEffect } from "react";
import { Alert, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { Button } from "../../components/common/Button";
import { QueryState } from "../../components/common/QueryState";
import { ProgressBar } from "../../components/reader/ProgressBar";
import { StatusPill } from "../../components/reader/StatusPill";
import { TalkControls } from "../../components/reader/TalkControls";
import { ScenePlaceholder } from "../../components/scene/ScenePlaceholder";
import { describeError } from "../../features/auth/errorMessages";
import type { NarrationErrorCode } from "../../features/narration/NarrationController";
import { useReader } from "../../features/reading/useReader";
import { createTalkTransport, isTalkAvailable } from "../../features/talk/transport";
import { useTalk } from "../../features/talk/useTalk";
import type { AppStackParamList } from "../../navigation/types";
import { useTheme } from "../../theme/ThemeProvider";

type Props = NativeStackScreenProps<AppStackParamList, "Reader">;

const NARRATION_ERRORS: Record<NarrationErrorCode, string> = {
  audio_unavailable: "이 부분은 음성으로 들을 수 없어요.",
  render_timeout: "음성을 준비하는 데 시간이 오래 걸리고 있어요. 잠시 후 다시 시도해 주세요.",
  playback_failed: "음성을 재생하지 못했어요.",
  network: "음성을 불러오지 못했어요. 네트워크를 확인해 주세요.",
};

// Built once per screen mount: the LiveKit transport needs native modules, so it is null in Expo Go.
const talkTransport = createTalkTransport();
const talkAvailable = isTalkAvailable();

export function ReaderScreen({ route, navigation }: Props) {
  const { colors, radius, spacing, typography } = useTheme();
  const reader = useReader(route.params.bookId);
  const { book, session, chapter, location, conflict } = reader;
  const talk = useTalk(session?.id, talkTransport);

  useEffect(() => {
    if (book) navigation.setOptions({ title: book.title });
  }, [book, navigation]);

  useEffect(() => {
    if (!conflict) return;
    Alert.alert(
      "다른 기기에서 읽은 위치가 있어요",
      `다른 기기에서 ${Math.round(conflict.serverSession.progress * 100)}%까지 읽었어요. 어느 위치에서 이어갈까요?`,
      [
        { text: "이 기기 위치", onPress: conflict.keepMine },
        { text: "다른 기기 위치", onPress: conflict.useServer },
      ],
      { cancelable: false },
    );
  }, [conflict]);

  if (reader.error && !chapter) {
    return <QueryState error={reader.error} />;
  }
  if (!book || !session || !chapter || !location) {
    return <QueryState loading />;
  }

  const playing = reader.narrationState === "playing" || reader.narrationState === "loading";
  const togglePlayback = () =>
    reader.playback(playing ? "pause" : "play").catch((error) => Alert.alert("재생", describeError(error)));

  return (
    <SafeAreaView edges={["left", "right", "bottom"]} style={[styles.fill, { backgroundColor: colors.background }]}>
      <View style={{ paddingHorizontal: spacing.xl, paddingTop: spacing.lg, gap: spacing.md }}>
        <ScenePlaceholder caption={chapter.title} />
        <StatusPill state={reader.displayState} />
        <TalkControls
          state={talk.state}
          error={talk.error}
          available={talkAvailable}
          onConnect={talk.connect}
          onDisconnect={talk.disconnect}
        />
        {reader.narrationError ? (
          <Text accessibilityLiveRegion="polite" style={[typography.caption, { color: colors.danger }]}>
            {NARRATION_ERRORS[reader.narrationError.code]}
          </Text>
        ) : null}
      </View>

      <ScrollView style={styles.fill} contentContainerStyle={{ padding: spacing.xl, gap: spacing.lg }}>
        {chapter.paragraphs.map((paragraph, paragraphIndex) => (
          <View key={paragraph.id} style={{ gap: spacing.lg }}>
            {paragraph.scene_break_before ? (
              <Text accessibilityLabel="장면 전환" style={[typography.caption, { color: colors.textMuted, textAlign: "center" }]}>
                ⁂
              </Text>
            ) : null}
            <Text style={[typography.reading, { color: colors.text }]}>
              {paragraph.sentences.map((sentence, sentenceIndex) => {
                const current =
                  paragraphIndex === location.paragraphIndex && sentenceIndex === location.sentenceIndex;
                return (
                  <Text
                    key={sentenceIndex}
                    testID={`sentence-${paragraph.id}-${sentenceIndex}`}
                    accessibilityRole="button"
                    accessibilityState={{ selected: current }}
                    onPress={() => reader.goTo({ chapterIndex: location.chapterIndex, paragraphIndex, sentenceIndex })}
                    style={current ? { backgroundColor: colors.highlight } : undefined}
                  >
                    {sentence}{" "}
                  </Text>
                );
              })}
            </Text>
          </View>
        ))}
      </ScrollView>

      <View style={{ paddingHorizontal: spacing.xl, paddingBottom: spacing.lg, gap: spacing.md }}>
        <View style={styles.row}>
          <Text style={[typography.caption, { color: colors.textMuted, flex: 1 }]} numberOfLines={1}>
            {chapter.title}
          </Text>
          <Text style={[typography.caption, { color: colors.textMuted }]}>{Math.round(reader.progress * 100)}%</Text>
        </View>
        <ProgressBar value={reader.progress} />

        <View style={[styles.row, { justifyContent: "center", gap: spacing.xl }]}>
          <ControlButton label="◀" accessibilityLabel="이전 문단" onPress={() => reader.paragraph(-1)} />
          <ControlButton label="‹" accessibilityLabel="이전 문장" onPress={() => reader.sentence(-1)} />
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={playing ? "일시정지" : "재생"}
            onPress={() => void togglePlayback()}
            style={[styles.play, { backgroundColor: colors.primary, borderRadius: radius.pill }]}
          >
            <Text style={[typography.heading, { color: colors.onPrimary }]}>{playing ? "Ⅱ" : "▶"}</Text>
          </Pressable>
          <ControlButton label="›" accessibilityLabel="다음 문장" onPress={() => reader.sentence(1)} />
          <ControlButton label="▶" accessibilityLabel="다음 문단" onPress={() => reader.paragraph(1)} />
        </View>

        <Button
          label="🎙 질문하기"
          variant="secondary"
          accessibilityHint="낭독을 멈추고 음성으로 질문합니다"
          onPress={() => Alert.alert("질문하기", "실시간 음성 질문은 다음 업데이트에서 제공돼요.")}
        />
      </View>
    </SafeAreaView>
  );
}

function ControlButton({ label, accessibilityLabel, onPress }: { label: string; accessibilityLabel: string; onPress: () => void }) {
  const { colors, typography } = useTheme();
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={accessibilityLabel} onPress={onPress} hitSlop={12} style={styles.control}>
      <Text style={[typography.heading, { color: colors.text }]}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  play: { width: 64, height: 64, alignItems: "center", justifyContent: "center" },
  control: { minWidth: 32, minHeight: 44, alignItems: "center", justifyContent: "center" },
});
