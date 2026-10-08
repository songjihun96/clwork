import React from "react";

// 선 아이콘(24×24, stroke). 영상 전용으로 직접 그린 단순 도형이다.
const P: Record<string, React.ReactNode> = {
  search: (<><circle cx="10.5" cy="10.5" r="6.5" /><path d="M15.5 15.5 21 21" /></>),
  map: (<><path d="M12 21s-7-6.2-7-11.5a7 7 0 0 1 14 0C19 14.8 12 21 12 21Z" /><circle cx="12" cy="9.5" r="2.6" /></>),
  school: (<><path d="M3 9.5 12 5l9 4.5-9 4.5-9-4.5Z" /><path d="M7 11.5V16c0 1.4 2.2 3 5 3s5-1.6 5-3v-4.5" /><path d="M21 9.5V15" /></>),
  compare: (<><rect x="3" y="4" width="7.5" height="16" rx="1.8" /><rect x="13.5" y="4" width="7.5" height="16" rx="1.8" /><path d="M5.5 8.5h2.5M5.5 12h2.5M16 8.5h2.5M16 12h2.5" /></>),
  chart: (<><path d="M4 20V4" /><path d="M4 20h16" /><rect x="7" y="12" width="3" height="5" rx="0.6" /><rect x="12" y="8" width="3" height="9" rx="0.6" /><rect x="17" y="5" width="3" height="12" rx="0.6" /></>),
  compass: (<><circle cx="12" cy="12" r="9" /><path d="m15.5 8.5-2 5-5 2 2-5 5-2Z" /></>),
  user: (<><circle cx="12" cy="8" r="3.6" /><path d="M5 20c.8-3.6 3.6-5.6 7-5.6s6.2 2 7 5.6" /></>),
  family: (<><circle cx="8.5" cy="7.5" r="3" /><circle cx="16.5" cy="9.5" r="2.4" /><path d="M2.8 19.5c.6-3.3 2.9-5.3 5.7-5.3s5.1 2 5.7 5.3" /><path d="M14.2 14.3c.7-.4 1.5-.6 2.3-.6 2.3 0 4.1 1.7 4.6 4.6" /></>),
  building: (<><path d="M4 20V6.5L12 3l8 3.5V20" /><path d="M2.5 20h19" /><path d="M9 20v-4.5h6V20" /><path d="M8 9.5h1.5M14.5 9.5H16M8 13h1.5M14.5 13H16" /></>),
  home: (<><path d="M4 11 12 4l8 7" /><path d="M6 9.5V20h12V9.5" /><path d="M10 20v-5h4v5" /></>),
  mail: (<><rect x="3" y="5.5" width="18" height="13" rx="2" /><path d="m3.5 7 8.5 6 8.5-6" /></>),
  link: (<><path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1" /><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" /></>),
};

export const Icon: React.FC<{ name: keyof typeof P | string; size?: number; color?: string; stroke?: number }> = ({
  name, size = 32, color = "currentColor", stroke = 1.9,
}) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={stroke}
    strokeLinecap="round" strokeLinejoin="round">
    {P[name]}
  </svg>
);

export const ICON_NAMES = Object.keys(P);
