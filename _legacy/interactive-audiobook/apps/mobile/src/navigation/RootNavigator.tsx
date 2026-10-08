import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import { NavigationContainer } from "@react-navigation/native";
import { createNativeStackNavigator } from "@react-navigation/native-stack";

import { useAuthStore } from "../features/auth/authStore";
import { LoginScreen } from "../screens/auth/LoginScreen";
import { RegisterScreen } from "../screens/auth/RegisterScreen";
import { SplashScreen } from "../screens/auth/SplashScreen";
import { HomeScreen } from "../screens/home/HomeScreen";
import { BookDetailScreen } from "../screens/library/BookDetailScreen";
import { LibraryScreen } from "../screens/library/LibraryScreen";
import { ReaderScreen } from "../screens/reader/ReaderScreen";
import { SettingsScreen } from "../screens/settings/SettingsScreen";
import { useNavigationTheme } from "../theme/ThemeProvider";
import type { AppStackParamList, AuthStackParamList, MainTabParamList } from "./types";

const AuthStack = createNativeStackNavigator<AuthStackParamList>();
const AppStack = createNativeStackNavigator<AppStackParamList>();
const Tabs = createBottomTabNavigator<MainTabParamList>();

function MainTabs() {
  return (
    <Tabs.Navigator screenOptions={{ headerShown: false }}>
      <Tabs.Screen name="Home" component={HomeScreen} options={{ title: "홈" }} />
      <Tabs.Screen name="Library" component={LibraryScreen} options={{ title: "서재" }} />
      <Tabs.Screen name="Settings" component={SettingsScreen} options={{ title: "설정" }} />
    </Tabs.Navigator>
  );
}

export function RootNavigator() {
  const status = useAuthStore((s) => s.status);
  const navigationTheme = useNavigationTheme();

  if (status === "bootstrapping" || status === "bootstrapFailed") {
    return <SplashScreen />;
  }

  return (
    <NavigationContainer theme={navigationTheme}>
      {status === "signedIn" ? (
        <AppStack.Navigator>
          <AppStack.Screen name="Tabs" component={MainTabs} options={{ headerShown: false }} />
          <AppStack.Screen name="BookDetail" component={BookDetailScreen} options={{ title: "" }} />
          <AppStack.Screen name="Reader" component={ReaderScreen} options={{ title: "" }} />
        </AppStack.Navigator>
      ) : (
        <AuthStack.Navigator>
          <AuthStack.Screen name="Login" component={LoginScreen} options={{ title: "로그인" }} />
          <AuthStack.Screen name="Register" component={RegisterScreen} options={{ title: "회원가입" }} />
        </AuthStack.Navigator>
      )}
    </NavigationContainer>
  );
}
