/**
 * Serialises reading-position writes.
 *
 * - Latest wins: while one request is in flight, only the newest pending position is kept.
 * - Optimistic concurrency: each write carries the last known ``position_version``; a 409 means another
 *   device moved on, and the caller decides what to do (the saver stops until ``resolveConflict``).
 * - Transient failures keep the pending position so ``flush()`` (e.g. on app foreground) can retry.
 */

export interface PositionTarget {
  paragraphId: string;
  sentenceIndex: number;
}

export type SaveOutcome =
  | { type: "saved"; version: number }
  | { type: "conflict" }
  | { type: "failed"; error: unknown };

export type SavePosition = (target: PositionTarget, expectedVersion: number) => Promise<SaveOutcome>;

export interface PositionSaverOptions {
  save: SavePosition;
  initialVersion: number;
  onConflict: () => void;
  onSaved?: (version: number) => void;
}

export class PositionSaver {
  private version: number;
  private pending: PositionTarget | null = null;
  private inFlight: Promise<void> | null = null;
  private blocked = false;

  constructor(private readonly options: PositionSaverOptions) {
    this.version = options.initialVersion;
  }

  get currentVersion(): number {
    return this.version;
  }

  get hasPending(): boolean {
    return this.pending !== null;
  }

  /** Queue a position; returns when this (or a newer) position has been handled. */
  update(target: PositionTarget): Promise<void> {
    this.pending = target;
    return this.flush();
  }

  flush(): Promise<void> {
    if (this.blocked || !this.pending) return this.inFlight ?? Promise.resolve();
    this.inFlight ??= this.drain().finally(() => {
      this.inFlight = null;
    });
    return this.inFlight;
  }

  /** After a conflict: continue from the server's version (keeping or discarding the local position). */
  resolveConflict(serverVersion: number, keepLocalPosition: boolean): Promise<void> {
    this.version = serverVersion;
    this.blocked = false;
    if (!keepLocalPosition) this.pending = null;
    return this.flush();
  }

  private async drain(): Promise<void> {
    while (this.pending && !this.blocked) {
      const target = this.pending;
      const outcome = await this.options.save(target, this.version);
      if (outcome.type === "saved") {
        this.version = outcome.version;
        if (this.pending === target) this.pending = null;
        this.options.onSaved?.(outcome.version);
      } else if (outcome.type === "conflict") {
        this.blocked = true;
        this.options.onConflict();
      } else {
        return; // keep pending for a later flush()
      }
    }
  }
}
