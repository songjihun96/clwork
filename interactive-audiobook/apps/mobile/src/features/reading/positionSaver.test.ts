import { PositionSaver, type SaveOutcome, type PositionTarget } from "./positionSaver";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

const p = (paragraphId: string, sentenceIndex = 0): PositionTarget => ({ paragraphId, sentenceIndex });

describe("PositionSaver", () => {
  it("sends positions with the latest version and coalesses rapid updates (latest wins)", async () => {
    const calls: { target: PositionTarget; version: number }[] = [];
    const first = deferred<SaveOutcome>();
    const save = jest.fn((target: PositionTarget, version: number) => {
      calls.push({ target, version });
      return calls.length === 1 ? first.promise : Promise.resolve<SaveOutcome>({ type: "saved", version: version + 1 });
    });
    const saver = new PositionSaver({ save, initialVersion: 1, onConflict: jest.fn() });

    const a = saver.update(p("a"));
    void saver.update(p("b"));
    void saver.update(p("c")); // replaces "b" while "a" is in flight
    first.resolve({ type: "saved", version: 2 });
    await a;

    expect(calls).toEqual([
      { target: p("a"), version: 1 },
      { target: p("c"), version: 2 },
    ]);
    expect(saver.currentVersion).toBe(3);
    expect(saver.hasPending).toBe(false);
  });

  it("stops on conflict until resolved, then continues with the server version", async () => {
    const onConflict = jest.fn();
    const save = jest
      .fn<Promise<SaveOutcome>, [PositionTarget, number]>()
      .mockResolvedValueOnce({ type: "conflict" })
      .mockImplementation(async (_t, version) => ({ type: "saved", version: version + 1 }));
    const saver = new PositionSaver({ save, initialVersion: 4, onConflict });

    await saver.update(p("mine"));
    expect(onConflict).toHaveBeenCalledTimes(1);
    await saver.update(p("mine-later"));
    expect(save).toHaveBeenCalledTimes(1); // blocked: no silent overwrite

    await saver.resolveConflict(9, true);
    expect(save).toHaveBeenLastCalledWith(p("mine-later"), 9);
    expect(saver.currentVersion).toBe(10);
  });

  it("can discard the local position when the user adopts the other device's position", async () => {
    const save = jest.fn<Promise<SaveOutcome>, [PositionTarget, number]>().mockResolvedValue({ type: "conflict" });
    const saver = new PositionSaver({ save, initialVersion: 1, onConflict: jest.fn() });
    await saver.update(p("local"));
    await saver.resolveConflict(7, false);
    expect(save).toHaveBeenCalledTimes(1);
    expect(saver.hasPending).toBe(false);
    expect(saver.currentVersion).toBe(7);
  });

  it("keeps the position after a transient failure and retries on flush", async () => {
    const save = jest
      .fn<Promise<SaveOutcome>, [PositionTarget, number]>()
      .mockResolvedValueOnce({ type: "failed", error: new Error("offline") })
      .mockResolvedValueOnce({ type: "saved", version: 2 });
    const saver = new PositionSaver({ save, initialVersion: 1, onConflict: jest.fn() });

    await saver.update(p("x"));
    expect(saver.hasPending).toBe(true);
    await saver.flush();
    expect(save).toHaveBeenCalledTimes(2);
    expect(saver.hasPending).toBe(false);
  });
});
