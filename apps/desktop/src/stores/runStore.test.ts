import { beforeEach, describe, expect, it } from "vitest";
import type { EngineEvent } from "../lib/events";
import { useRunStore } from "./runStore";

function event(overrides: Partial<EngineEvent> & { type: string }): EngineEvent {
  return {
    event_id: "evt_1",
    run_id: "run_01",
    seq: 1,
    ts: "2026-11-17T12:00:00Z",
    ...overrides,
  };
}

describe("runStore review 事件", () => {
  beforeEach(() => {
    useRunStore.getState().reset();
    useRunStore.getState().begin("run_01", "prj_01");
  });

  it("review.requested 将运行置为 waiting_review 并记录日志", () => {
    useRunStore.getState().applyEvent(
      event({
        type: "review.requested",
        step: "review",
        review_id: "rev_1",
        items: [{ id: "a" }, { id: "b" }],
      }),
    );

    const state = useRunStore.getState();
    expect(state.status).toBe("waiting_review");
    const logs = state.logs;
    expect(logs[logs.length - 1]?.message).toContain("2 项");
  });

  it("review.resolved 恢复运行状态", () => {
    useRunStore.getState().applyEvent(event({ type: "review.requested", review_id: "rev_1" }));
    expect(useRunStore.getState().status).toBe("waiting_review");

    useRunStore.getState().applyEvent(event({ type: "review.resolved", review_id: "rev_1" }));
    expect(useRunStore.getState().status).toBe("running");
  });

  it("忽略其他 run 的审核事件", () => {
    useRunStore.getState().applyEvent(
      event({ type: "review.requested", run_id: "run_02", review_id: "rev_2" }),
    );
    expect(useRunStore.getState().status).toBe("running");
  });

  it("事件早于 begin 到达时不被重置", () => {
    useRunStore.getState().reset();
    useRunStore.getState().applyEvent(
      event({ type: "review.requested", run_id: "run_early", review_id: "rev_1" }),
    );
    expect(useRunStore.getState().runId).toBe("run_early");
    expect(useRunStore.getState().status).toBe("waiting_review");

    // pipeline.run 响应随后到达，不能把 waiting_review 覆盖成 running。
    useRunStore.getState().begin("run_early", "prj_01");
    expect(useRunStore.getState().status).toBe("waiting_review");
    expect(useRunStore.getState().logs.length).toBeGreaterThan(0);
  });
});
