import { ApiError } from "@audiobook/api-client";
import { fireEvent, render, screen, waitFor } from "@testing-library/react-native";

import { signIn } from "../../features/auth/authActions";
import { ThemeProvider } from "../../theme/ThemeProvider";
import { LoginScreen } from "./LoginScreen";

jest.mock("../../features/auth/authActions", () => ({ signIn: jest.fn() }));
jest.mock("react-native-safe-area-context", () => {
  const { View } = jest.requireActual("react-native");
  return { SafeAreaView: View };
});

const mockedSignIn = jest.mocked(signIn);

async function renderLogin() {
  const navigation = { navigate: jest.fn() };
  // Only `navigation.navigate` is used by the screen.
  const props = { navigation, route: { key: "Login", name: "Login" } } as unknown as Parameters<typeof LoginScreen>[0];
  await render(
    <ThemeProvider>
      <LoginScreen {...props} />
    </ThemeProvider>,
  );
  return navigation;
}

describe("LoginScreen", () => {
  beforeEach(() => mockedSignIn.mockReset());

  it("validates input before calling the API", async () => {
    await renderLogin();
    await fireEvent.press(screen.getByRole("button", { name: "로그인" }));

    expect(await screen.findByText("이메일을 입력해 주세요.")).toBeTruthy();
    expect(screen.getByText("비밀번호를 입력해 주세요.")).toBeTruthy();
    expect(mockedSignIn).not.toHaveBeenCalled();
  });

  it("signs in with trimmed email", async () => {
    mockedSignIn.mockResolvedValue();
    await renderLogin();
    await fireEvent.changeText(screen.getByLabelText("이메일"), "  reader@example.com ");
    await fireEvent.changeText(screen.getByLabelText("비밀번호"), "correct horse");
    await fireEvent.press(screen.getByRole("button", { name: "로그인" }));

    await waitFor(() => expect(mockedSignIn).toHaveBeenCalledWith("reader@example.com", "correct horse"));
  });

  it("shows a friendly message for invalid credentials", async () => {
    mockedSignIn.mockRejectedValue(new ApiError(401, "invalid_credentials", "Invalid email or password", "rid"));
    await renderLogin();
    await fireEvent.changeText(screen.getByLabelText("이메일"), "reader@example.com");
    await fireEvent.changeText(screen.getByLabelText("비밀번호"), "wrong");
    await fireEvent.press(screen.getByRole("button", { name: "로그인" }));

    expect(await screen.findByText("이메일 또는 비밀번호가 올바르지 않아요.")).toBeTruthy();
  });

  it("navigates to registration", async () => {
    const navigation = await renderLogin();
    await fireEvent.press(screen.getByRole("button", { name: "이메일로 회원가입" }));
    expect(navigation.navigate).toHaveBeenCalledWith("Register");
  });
});
