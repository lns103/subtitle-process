import { describe, expect, it } from "vitest";
import type { ProjectSummary } from "./models";
import {
  isSubtitleOnly,
  pickProjectForSubtitles,
  subtitleBaseName,
  subtitlePaths,
} from "./flow2";

function project(overrides: Partial<ProjectSummary> & { id: string; name: string }): ProjectSummary {
  return {
    status: "done",
    created_at: "2026-11-01T00:00:00Z",
    updated_at: "2026-11-01T00:00:00Z",
    media_path: "",
    workspace: `C:/projects/${overrides.id}`,
    outputs: [],
    ...overrides,
  };
}

describe("subtitleBaseName", () => {
  it("去掉扩展名与语言后缀", () => {
    expect(subtitleBaseName("C:/Shows/Ep01.zh-CN.srt")).toBe("Ep01");
    expect(subtitleBaseName("/media/Ep02.chs.ass")).toBe("Ep02");
    expect(subtitleBaseName("Ep03.cht.vtt")).toBe("Ep03");
    expect(subtitleBaseName("Show.S01E01.en.srt")).toBe("Show.S01E01");
    expect(subtitleBaseName("movie.2024.ja.srt")).toBe("movie.2024");
  });

  it("叠加的 .clean / .orig 后缀也会被移除", () => {
    expect(subtitleBaseName("Ep01.zh-CN.clean.srt")).toBe("Ep01");
    expect(subtitleBaseName("Ep01.en.orig.ass")).toBe("Ep01");
    expect(subtitleBaseName("Ep01.orig.srt")).toBe("Ep01");
  });

  it("没有可识别后缀时只去掉扩展名", () => {
    expect(subtitleBaseName("plain.srt")).toBe("plain");
    expect(subtitleBaseName("D:\\subs\\Some Episode.ass")).toBe("Some Episode");
  });
});

describe("isSubtitleOnly", () => {
  it("全部是字幕时返回 true", () => {
    expect(isSubtitleOnly(["a.srt", "b.ass", "c.vtt"])).toBe(true);
  });

  it("包含视频或空列表时返回 false", () => {
    expect(isSubtitleOnly([])).toBe(false);
    expect(isSubtitleOnly(["a.srt", "b.mkv"])).toBe(false);
  });

  it("subtitlePaths 只保留字幕", () => {
    expect(subtitlePaths(["a.srt", "b.mkv", "c.vtt"])).toEqual(["a.srt", "c.vtt"]);
  });
});

describe("pickProjectForSubtitles", () => {
  it("优先返回名称匹配的项目（大小写不敏感）", () => {
    const projects = [
      project({ id: "p2", name: "Other Show", status: "waiting_translation", updated_at: "2026-11-10T00:00:00Z" }),
      project({ id: "p1", name: "show s01e01" }),
    ];

    expect(pickProjectForSubtitles(projects, ["Show.S01E01.en.srt"])?.id).toBe("p1");
  });

  it("支持项目名作为 base 的前缀", () => {
    const projects = [
      project({ id: "p1", name: "Show", status: "waiting_translation" }),
      project({ id: "p2", name: "Unrelated" }),
    ];

    expect(pickProjectForSubtitles(projects, ["Show.S01E01.zh.srt"])?.id).toBe("p1");
  });

  it("没有名称匹配时推荐最近更新的 waiting_translation 项目", () => {
    const projects = [
      project({ id: "p1", name: "Alpha" }),
      project({
        id: "p2",
        name: "Beta",
        status: "waiting_translation",
        updated_at: "2026-11-05T00:00:00Z",
      }),
      project({
        id: "p3",
        name: "Gamma",
        status: "waiting_translation",
        updated_at: "2026-11-09T00:00:00Z",
      }),
    ];

    expect(pickProjectForSubtitles(projects, ["unknown.zh.srt"])?.id).toBe("p3");
  });

  it("没有匹配也没有等待翻译的项目时返回 null", () => {
    const projects = [project({ id: "p1", name: "Alpha", status: "done" })];
    expect(pickProjectForSubtitles(projects, ["unknown.zh.srt"])).toBeNull();
  });

  it("空项目列表或非字幕输入时返回 null", () => {
    expect(pickProjectForSubtitles([], ["a.srt"])).toBeNull();
    expect(
      pickProjectForSubtitles([project({ id: "p1", name: "Alpha" })], ["movie.mkv"]),
    ).toBeNull();
  });
});
