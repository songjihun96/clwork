/**
 * Design tokens. Kept flat so they can later be mapped 1:1 onto a Tailwind/NativeWind theme
 * (docs/mobile-architecture.md §7.3).
 */
import type { TextStyle } from "react-native";

export interface ThemeColors {
  background: string;
  surface: string;
  surfaceMuted: string;
  text: string;
  textMuted: string;
  primary: string;
  onPrimary: string;
  border: string;
  danger: string;
  highlight: string;
  statusActive: string;
  statusListening: string;
  statusThinking: string;
}

export interface Theme {
  dark: boolean;
  colors: ThemeColors;
  spacing: { xs: number; sm: number; md: number; lg: number; xl: number; xxl: number };
  radius: { sm: number; md: number; lg: number; pill: number };
  typography: Record<"title" | "heading" | "body" | "reading" | "caption" | "label", TextStyle>;
}

const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 };
const radius = { sm: 8, md: 12, lg: 20, pill: 999 };
const typography: Theme["typography"] = {
  title: { fontSize: 26, fontWeight: "700", lineHeight: 34 },
  heading: { fontSize: 18, fontWeight: "600", lineHeight: 26 },
  body: { fontSize: 16, lineHeight: 24 },
  reading: { fontSize: 19, lineHeight: 32 },
  caption: { fontSize: 13, lineHeight: 18 },
  label: { fontSize: 15, fontWeight: "600", lineHeight: 20 },
};

export const lightTheme: Theme = {
  dark: false,
  colors: {
    background: "#FBF8F3",
    surface: "#FFFFFF",
    surfaceMuted: "#EFE9DF",
    text: "#1F1B16",
    textMuted: "#6B6358",
    primary: "#3D5A80",
    onPrimary: "#FFFFFF",
    border: "#DDD5C8",
    danger: "#B3261E",
    highlight: "#F5E3B3",
    statusActive: "#2E7D5B",
    statusListening: "#3D5A80",
    statusThinking: "#9A6A00",
  },
  spacing,
  radius,
  typography,
};

export const darkTheme: Theme = {
  dark: true,
  colors: {
    background: "#15130F",
    surface: "#211E19",
    surfaceMuted: "#2C2822",
    text: "#EFE9DF",
    textMuted: "#A89F92",
    primary: "#98B6DC",
    onPrimary: "#10223A",
    border: "#3A352D",
    danger: "#F2B8B5",
    highlight: "#4A3F22",
    statusActive: "#7FD1A8",
    statusListening: "#98B6DC",
    statusThinking: "#E6C35C",
  },
  spacing,
  radius,
  typography,
};
