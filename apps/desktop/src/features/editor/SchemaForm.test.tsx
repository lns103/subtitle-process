// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import type { JsonSchema } from "../../lib/models";
import {
  isNullSchema,
  parseJsonValue,
  resolveSchema,
  schemaProperties,
  schemaType,
  toJsonString,
} from "../../lib/schema";
import { SchemaForm } from "./SchemaForm";

afterEach(cleanup);

interface HarnessProps {
  schema: JsonSchema;
  initial: Record<string, unknown>;
  onChange?: (next: Record<string, unknown>) => void;
}

function Harness({ schema, initial, onChange }: HarnessProps) {
  const [value, setValue] = useState<Record<string, unknown>>(initial);
  return (
    <SchemaForm
      schema={schema}
      value={value}
      onChange={(next) => {
        onChange?.(next);
        setValue(next);
      }}
    />
  );
}

function lastPayload(spy: ReturnType<typeof vi.fn>): Record<string, unknown> {
  const calls = spy.mock.calls;
  return calls[calls.length - 1]?.[0] as Record<string, unknown>;
}

describe("SchemaForm", () => {
  it("编辑 string 字段时回传完整 options", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const schema: JsonSchema = {
      type: "object",
      properties: {
        filename: { type: "string", title: "文件名", description: "留空自动生成" },
      },
    };
    render(<Harness schema={schema} initial={{}} onChange={onChange} />);

    const input = screen.getByLabelText("文件名");
    await user.type(input, "clean");

    expect(screen.getByText("留空自动生成")).toBeTruthy();
    expect(lastPayload(onChange)).toEqual({ filename: "clean" });
  });

  it("number 字段转换为数字，清空时删除键", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const schema: JsonSchema = {
      type: "object",
      properties: { delay: { type: "number", title: "延迟" } },
    };
    render(<Harness schema={schema} initial={{ delay: 2 }} onChange={onChange} />);

    const input = screen.getByLabelText("延迟") as HTMLInputElement;
    expect(input.value).toBe("2");

    await user.clear(input);
    expect(lastPayload(onChange)).toEqual({});

    await user.type(input, "3");
    const payload = lastPayload(onChange);
    expect(payload).toEqual({ delay: 3 });
    expect(typeof payload.delay).toBe("number");
  });

  it("boolean 字段渲染为复选框并切换", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const schema: JsonSchema = {
      type: "object",
      properties: { backup: { type: "boolean", title: "保留备份" } },
    };
    render(<Harness schema={schema} initial={{ backup: true }} onChange={onChange} />);

    const checkbox = screen.getByRole("checkbox", { name: "保留备份" });
    expect((checkbox as HTMLInputElement).checked).toBe(true);
    await user.click(checkbox);

    expect(lastPayload(onChange)).toEqual({ backup: false });
  });

  it("enum 字段渲染为下拉框并保留原始值类型", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const schema: JsonSchema = {
      type: "object",
      properties: {
        format: { enum: ["srt", "ass", "vtt"], default: "srt", title: "输出格式" },
        levels: { enum: [1, 2], title: "层级" },
      },
    };
    render(<Harness schema={schema} initial={{}} onChange={onChange} />);

    const select = screen.getByLabelText("输出格式") as HTMLSelectElement;
    expect(select.value).toBe("srt");
    await user.selectOptions(select, "ass");
    expect(lastPayload(onChange)).toEqual({ format: "ass" });

    await user.selectOptions(screen.getByLabelText("层级"), "2");
    expect(lastPayload(onChange)).toEqual({ format: "ass", levels: 2 });
  });

  it("array 字段支持添加与删除条目", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const schema: JsonSchema = {
      type: "object",
      properties: { tracks: { type: "array", title: "轨道", items: { type: "integer" } } },
    };
    render(<Harness schema={schema} initial={{ tracks: [1, 2] }} onChange={onChange} />);

    expect((screen.getByLabelText("轨道 第 1 项") as HTMLInputElement).value).toBe("1");

    await user.click(screen.getByRole("button", { name: "添加" }));
    expect(lastPayload(onChange)).toEqual({ tracks: [1, 2, 0] });

    await user.click(screen.getByRole("button", { name: "删除轨道 第 1 项" }));
    expect(lastPayload(onChange)).toEqual({ tracks: [2, 0] });
  });

  it("object 字段失焦时应用 JSON，并在无效时报错", async () => {
    const onChange = vi.fn();
    const schema: JsonSchema = {
      type: "object",
      properties: { config: { type: "object", title: "配置" } },
    };
    render(<Harness schema={schema} initial={{ config: { a: 1 } }} onChange={onChange} />);

    const textarea = screen.getByLabelText("配置") as HTMLTextAreaElement;
    expect(textarea.value).toBe(toJsonString({ a: 1 }));

    fireEvent.change(textarea, { target: { value: "{oops" } });
    fireEvent.blur(textarea);
    expect(screen.getByRole("alert").textContent).toContain("JSON 无效");
    expect(onChange).not.toHaveBeenCalled();

    fireEvent.change(textarea, { target: { value: '{"a":2,"b":"x"}' } });
    fireEvent.blur(textarea);

    expect(lastPayload(onChange)).toEqual({ config: { a: 2, b: "x" } });
    expect(screen.queryByRole("alert")).toBeNull();
    expect(parseJsonValue("")).toEqual({ ok: true, value: undefined });
  });

  it("required 且无值时显示必填标记", () => {
    const schema: JsonSchema = {
      type: "object",
      properties: {
        seed: { type: "string", title: "随机种子" },
        name: { type: "string", title: "名称" },
      },
      required: ["seed"],
    };
    render(<Harness schema={schema} initial={{}} />);

    const seed = screen.getByTestId("schema-field-seed");
    expect(within(seed).getByText("必填")).toBeTruthy();
    expect(within(screen.getByTestId("schema-field-name")).queryByText("必填")).toBeNull();
  });

  it("resolveSchema 展开 $ref 与可空 anyOf", () => {
    const root: JsonSchema = {
      type: "object",
      properties: {
        format: { $ref: "#/$defs/Format", description: "节点说明" },
      },
      $defs: {
        Format: { title: "输出格式", enum: ["srt", "ass"], description: "定义说明" },
      },
    };

    const property = (root.properties as Record<string, JsonSchema>).format;
    const resolved = resolveSchema(property, root);
    expect(resolved.$ref).toBeUndefined();
    expect(resolved.enum).toEqual(["srt", "ass"]);
    expect(resolved.title).toBe("输出格式");
    expect(resolved.description).toBe("节点说明");
    expect(schemaType(resolved)).toBe("enum");

    const props = schemaProperties(root);
    expect(props.map((item) => item.key)).toEqual(["format"]);
    expect(props[0]?.required).toBe(false);
    expect(schemaType(props[0]?.schema ?? {})).toBe("enum");

    const nullable = resolveSchema({
      anyOf: [{ type: "string" }, { type: "null" }],
      title: "备注",
    });
    expect(schemaType(nullable)).toBe("string");
    expect(nullable.title).toBe("备注");
    expect(isNullSchema({ type: "null" })).toBe(true);
  });

  it("未知 schema 结构降级为只读 JSON", () => {
    const nested: JsonSchema = {
      type: "object",
      properties: {
        blob: { title: "未知字段", anyOf: [{ type: "object" }, { type: "string" }] },
      },
    };
    render(<Harness schema={nested} initial={{ blob: { a: 1 } }} />);

    const textarea = screen.getByLabelText("未知字段") as HTMLTextAreaElement;
    expect(textarea.readOnly).toBe(true);
    expect(textarea.value).toContain('"a": 1');

    cleanup();
    render(<Harness schema={{ type: "string" }} initial={{ anything: 1 }} />);
    const fallback = screen.getByLabelText("原始参数（只读）") as HTMLTextAreaElement;
    expect(fallback.readOnly).toBe(true);
    expect(fallback.value).toContain('"anything": 1');
  });
});
