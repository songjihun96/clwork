/** The reader's Talk row: what each connection state says, and what the button does. */

import { fireEvent, render, screen } from "@testing-library/react-native";
import type { ComponentProps } from "react";

import { ThemeProvider } from "../../theme/ThemeProvider";
import { TalkControls } from "./TalkControls";

function renderControls(props: Partial<ComponentProps<typeof TalkControls>> = {}) {
  return render(
    <ThemeProvider>
      <TalkControls
        state="idle"
        error={null}
        available
        onConnect={jest.fn()}
        onDisconnect={jest.fn()}
        {...props}
      />
    </ThemeProvider>,
  );
}

describe("TalkControls", () => {
  it("explains that Talk mode needs a development build when native audio is missing", async () => {
    await renderControls({ available: false });

    expect(screen.getByTestId("talk-unavailable")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it.each([
    ["idle", "대화 모드 꺼짐", "대화 시작"],
    ["requesting", "연결 준비 중", "대화 종료"],
    ["connecting", "연결 중", "대화 종료"],
    ["connected", "대화 모드", "대화 종료"],
    ["reconnecting", "다시 연결 중", "대화 종료"],
    ["disconnected", "연결 끊김", "대화 시작"],
    ["error", "연결 실패", "대화 시작"],
  ] as const)("shows %s as %s", async (state, label, button) => {
    await renderControls({ state });

    expect(screen.getByLabelText(`대화 연결 상태: ${label}`)).toBeTruthy();
    expect(screen.getByRole("button", { name: button })).toBeTruthy();
  });

  it("connects and disconnects through the button", async () => {
    const onConnect = jest.fn();
    const onDisconnect = jest.fn();
    await renderControls({ onConnect, onDisconnect });

    await fireEvent.press(screen.getByRole("button", { name: "대화 시작" }));
    expect(onConnect).toHaveBeenCalledTimes(1);

    await renderControls({ state: "connected", onConnect, onDisconnect });
    await fireEvent.press(screen.getByRole("button", { name: "대화 종료" }));
    expect(onDisconnect).toHaveBeenCalledTimes(1);
  });

  it("shows the error message next to the state", async () => {
    await renderControls({ state: "error", error: { code: "unavailable", message: "지금은 대화 모드를 쓸 수 없어요." } });

    expect(screen.getByText("지금은 대화 모드를 쓸 수 없어요.")).toBeTruthy();
  });
});
