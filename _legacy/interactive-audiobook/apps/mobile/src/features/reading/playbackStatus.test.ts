import { isAudible, READING_STATES, statusDisplay } from "./playbackStatus";

describe("reading status display", () => {
  it("has a label for every state", () => {
    for (const state of READING_STATES) {
      expect(statusDisplay(state).label.length).toBeGreaterThan(0);
    }
  });

  it("uses the UX labels from the product spec", () => {
    expect(statusDisplay("READING").label).toBe("읽는 중");
    expect(statusDisplay("USER_SPEAKING").label).toBe("듣는 중");
    expect(statusDisplay("AWAITING_FOLLOWUP").label).toBe("듣는 중");
    expect(statusDisplay("PROCESSING_QUESTION").label).toBe("생각 중");
    expect(statusDisplay("ANSWERING").label).toBe("답변 중");
    expect(statusDisplay("RESUMING").label).toBe("다시 읽는 중");
  });

  it("marks only narration/answer states as audible", () => {
    expect(READING_STATES.filter(isAudible)).toEqual(["READING", "ANSWERING", "RESUMING"]);
  });
});
