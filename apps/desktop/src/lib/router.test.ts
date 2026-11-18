import { describe, expect, it } from "vitest";
import { parseRoute, routeHash } from "./router";

describe("hash 路由", () => {
  it("空 hash 回到首页", () => {
    expect(parseRoute("")).toEqual({ name: "home" });
    expect(parseRoute("#/")).toEqual({ name: "home" });
    expect(parseRoute("#/unknown")).toEqual({ name: "home" });
  });

  it("解析编辑器与配方 id", () => {
    expect(parseRoute("#/editor")).toEqual({ name: "editor", recipeId: null });
    expect(parseRoute("#/editor/batch_video_to_clean_srt")).toEqual({
      name: "editor",
      recipeId: "batch_video_to_clean_srt",
    });
    expect(parseRoute("#/editor/a%20b")).toEqual({ name: "editor", recipeId: "a b" });
  });

  it("生成 hash 与解析互逆", () => {
    expect(routeHash({ name: "home" })).toBe("#/");
    expect(routeHash({ name: "editor", recipeId: null })).toBe("#/editor");
    const route = { name: "editor", recipeId: "my.recipe-1" } as const;
    expect(parseRoute(routeHash(route))).toEqual(route);
  });

  it("解析审核路由", () => {
    expect(parseRoute("#/review/run_01")).toEqual({ name: "review", runId: "run_01" });
    expect(parseRoute("#/review/run%2001/")).toEqual({ name: "review", runId: "run 01" });
    expect(parseRoute("#/review/")).toEqual({ name: "home" });
    expect(routeHash({ name: "review", runId: "run_01" })).toBe("#/review/run_01");
    const route = { name: "review", runId: "run 01" } as const;
    expect(parseRoute(routeHash(route))).toEqual(route);
  });

  it("解析设置路由", () => {
    expect(parseRoute("#/settings")).toEqual({ name: "settings" });
    expect(parseRoute("#/settings/")).toEqual({ name: "settings" });
    expect(routeHash({ name: "settings" })).toBe("#/settings");
    expect(parseRoute(routeHash({ name: "settings" }))).toEqual({ name: "settings" });
  });

  it("解析任务深链接", () => {
    expect(parseRoute("#/task/batch_video_to_clean_srt")).toEqual({
      name: "task",
      taskId: "batch_video_to_clean_srt",
    });
    expect(parseRoute("#/task/a%20b/")).toEqual({ name: "task", taskId: "a b" });
    expect(parseRoute("#/task/")).toEqual({ name: "home" });
    const route = { name: "task", taskId: "fn_extract_subtitles" } as const;
    expect(routeHash(route)).toBe("#/task/fn_extract_subtitles");
    expect(parseRoute(routeHash(route))).toEqual(route);
  });
});
