import React from "react";
import { Composition } from "remotion";
import { Main } from "./Main";
import { TIMELINES } from "./lib";
import { SCHOOL_TIMELINES, SchoolMain } from "./school/SchoolMain";

export const Root: React.FC = () => (
  <>
    {Object.values(TIMELINES).map((tl) => (
      <Composition
        key={tl.version}
        id={`udj-${tl.version}`}
        component={Main}
        durationInFrames={tl.frames}
        fps={tl.fps}
        width={1920}
        height={1080}
        defaultProps={{ version: tl.version }}
      />
    ))}
    {/* 학교·교사용 기능 소개영상 */}
    {Object.values(SCHOOL_TIMELINES).map((tl) => (
      <Composition
        key={tl.version}
        id={`school-${tl.version.replace(/_/g, "-")}`}
        component={SchoolMain}
        durationInFrames={tl.frames}
        fps={tl.fps}
        width={1920}
        height={1080}
        defaultProps={{ version: tl.version }}
      />
    ))}
  </>
);
