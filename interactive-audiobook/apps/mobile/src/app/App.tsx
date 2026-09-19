import { QueryClientProvider } from "@tanstack/react-query";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { bootstrapSession } from "../features/auth/authActions";
import { queryClient } from "../lib/queryClient";
import { RootNavigator } from "../navigation/RootNavigator";
import { ThemeProvider, useTheme } from "../theme/ThemeProvider";

function ThemedStatusBar() {
  const { dark } = useTheme();
  return <StatusBar style={dark ? "light" : "dark"} />;
}

export default function App() {
  useEffect(() => {
    void bootstrapSession();
  }, []);

  return (
    <SafeAreaProvider>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>
          <ThemedStatusBar />
          <RootNavigator />
        </ThemeProvider>
      </QueryClientProvider>
    </SafeAreaProvider>
  );
}
