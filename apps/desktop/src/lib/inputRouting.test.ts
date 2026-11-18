import { describe, expect, it } from "vitest";
import {
  batchProjectName,
  directoriesForPaths,
  folderLooksTranslated,
  hasLanguageSuffix,
  routePaths,
} from "./inputRouting";
import type { TaskSpec } from "./models";

const BILINGUAL: TaskSpec = {
  id: "batch_translated_to_bilingual",
  recipe_id: "batch_translated_to_bilingual",
  kind: "workflow",
  group: "主流程",
  order: 20,
  title: "双语合并",
  description: "",
  inputs: [
    { name: "original", label: "原版字幕", kind: "files", accept: [".srt"], required: true },
    { name: "translated", label: "译文字幕", kind: "files", accept: [".srt"], required: true },
  ],
  requires_project: false,
};

const VIDEO_TASK: TaskSpec = {
  ...BILINGUAL,
  id: "batch_video_to_clean_srt",
  recipe_id: "batch_video_to_clean_srt",
  inputs: [
    { name: "video", label: "视频文件", kind: "file", accept: [".mkv", ".mp4"], required: true },
  ],
};

describe("inputRouting", () => {
  it("clean 原版与语言后缀译文分别进入两个槽", () => {
    const result = routePaths(BILINGUAL, {}, [
      "C:/show/EP01.clean.srt",
      "C:/show/EP01.zh.srt",
    ]);
    expect(result.assigned).toEqual([
      { input: "original", paths: ["C:/show/EP01.clean.srt"] },
      { input: "translated", paths: ["C:/show/EP01.zh.srt"] },
    ]);
    expect(result.ambiguous).toEqual([]);
  });

  it("文件夹名包含译文时优先进入译文槽", () => {
    expect(folderLooksTranslated("D:/剧集/EP01 译文")).toBe(true);
    const result = routePaths(BILINGUAL, {}, ["D:/剧集/EP01 译文"]);
    expect(result.assigned).toEqual([{ input: "translated", paths: ["D:/剧集/EP01 译文"] }]);
  });

  it("英文 translated 文件夹也按译文处理", () => {
    const result = routePaths(BILINGUAL, {}, ["D:/show/translated/EP01.srt"]);
    expect(result.assigned).toEqual([{ input: "translated", paths: ["D:/show/translated/EP01.srt"] }]);
  });

  it("普通 SRT 文件夹默认进入原版槽", () => {
    const result = routePaths(BILINGUAL, {}, ["D:/show/EP01"]);
    expect(result.assigned).toEqual([{ input: "original", paths: ["D:/show/EP01"] }]);
    expect(result.ambiguous).toEqual(["D:/show/EP01"]);
  });

  it("批量项目优先使用拖入的文件夹名", () => {
    expect(
      batchProjectName(
        ["D:/剧集/第一季/EP01.mkv", "D:/剧集/第一季/EP02.mkv"],
        ["D:/剧集/第一季"],
      ),
    ).toBe("第一季");
  });

  it("批量项目没有文件夹时使用第一个视频名", () => {
    expect(batchProjectName(["D:/a/EP01.mkv", "D:/b/EP02.mkv"])).toBe("EP01");
    expect(batchProjectName([])).toBe("未命名项目");
  });

  it("只使用确实包含视频的文件夹名", () => {
    const directories = ["D:/剧集/第一季", "D:/旧目录"];
    expect(
      directoriesForPaths(directories, [
        "D:\\剧集\\第一季\\EP01.mkv",
        "D:/剧集/第一季/EP02.mkv",
      ]),
    ).toEqual(["D:/剧集/第一季"]);
  });

  it("视频与字幕按扩展名分流", () => {
    const task: TaskSpec = {
      ...BILINGUAL,
      inputs: [
        { name: "video", label: "视频文件", kind: "file", accept: [".mkv"], required: true },
        { name: "subs", label: "字幕文件", kind: "files", accept: [".srt"], required: true },
      ],
    };
    const result = routePaths(task, {}, ["C:/show/EP01.mkv", "C:/show/EP01.srt"]);
    expect(result.assigned).toEqual([
      { input: "video", paths: ["C:/show/EP01.mkv"] },
      { input: "subs", paths: ["C:/show/EP01.srt"] },
    ]);
  });

  it("默认不覆盖已有槽，覆盖模式下替换", () => {
    const current = { original: ["C:/old/EP00.srt"] };
    const skipped = routePaths(BILINGUAL, current, ["C:/new/EP01.clean.srt"]);
    expect(skipped.assigned).toEqual([]);
    expect(skipped.unassigned[0]?.reason).toContain("覆盖");

    const replaced = routePaths(BILINGUAL, current, ["C:/new/EP01.clean.srt"], {
      overwrite: true,
    });
    expect(replaced.assigned).toEqual([
      { input: "original", paths: ["C:/new/EP01.clean.srt"] },
    ]);
  });

  it("不支持的扩展名进入未分配", () => {
    const result = routePaths(BILINGUAL, {}, ["C:/show/readme.txt"]);
    expect(result.assigned).toEqual([]);
    expect(result.unassigned[0]?.path).toBe("C:/show/readme.txt");
  });

  it("重复路径只分配一次", () => {
    const result = routePaths(BILINGUAL, {}, [
      "C:/show/EP01.zh.srt",
      "C:/show/EP01.zh.srt",
    ]);
    expect(result.assigned).toEqual([
      { input: "translated", paths: ["C:/show/EP01.zh.srt"] },
    ]);
  });

  it("单视频任务只接收视频", () => {
    const result = routePaths(VIDEO_TASK, {}, ["C:/show/EP01.mkv", "C:/show/EP01.srt"]);
    expect(result.assigned).toEqual([{ input: "video", paths: ["C:/show/EP01.mkv"] }]);
    expect(result.unassigned[0]?.path).toBe("C:/show/EP01.srt");
  });

  it("多视频任务保留全部视频", () => {
    const task: TaskSpec = {
      ...VIDEO_TASK,
      inputs: [
        {
          name: "video",
          label: "视频文件",
          kind: "file",
          accept: [".mkv", ".mp4"],
          required: true,
          multiple: true,
        },
      ],
    };
    const result = routePaths(task, {}, [
      "C:/show/EP01.mkv",
      "C:/show/EP02.mp4",
      "C:/show/EP03.mkv",
    ]);
    expect(result.assigned).toEqual([
      {
        input: "video",
        paths: ["C:/show/EP01.mkv", "C:/show/EP02.mp4", "C:/show/EP03.mkv"],
      },
    ]);
  });

  it("识别语言后缀", () => {
    expect(hasLanguageSuffix("EP01.zh-CN.srt")).toBe(true);
    expect(hasLanguageSuffix("EP01.en.srt")).toBe(true);
    expect(hasLanguageSuffix("EP01.srt")).toBe(false);
  });
});
