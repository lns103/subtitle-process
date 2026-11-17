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
    expect(parseRoute("#/editor/video_to_clean_srt")).toEqual({
      name: "editor",
      recipeId: "video_to_clean_srt",
    });
    expect(parseRoute("#/editor/a%20b")).toEqual({ name: "editor", recipeId: "a b" });
  });

  it("生成 hash 与解析互逆", () => {
    expect(routeHash({ name: "home" })).toBe("#/");
    expect(routeHash({ name: "editor", recipeId: null })).toBe("#/editor");
    const route = { name: "editor", recipeId: "my.recipe-1" } as const;
    expect(parseRoute(routeHash(route))).toEqual(route);
  });
});
