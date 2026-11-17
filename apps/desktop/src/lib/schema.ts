/** 轻量 JSON Schema 工具：只覆盖引擎 ``model_json_schema()`` 用到的子集。 */

import type { JsonSchema } from "./models";

export type SchemaKind =
  | "string"
  | "number"
  | "integer"
  | "boolean"
  | "array"
  | "object"
  | "enum"
  | "unknown";

export interface SchemaProperty {
  key: string;
  schema: JsonSchema;
  required: boolean;
}

function asRecord(value: unknown): JsonSchema | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as JsonSchema)
    : null;
}

function omitKeys(schema: JsonSchema, keys: readonly string[]): JsonSchema {
  const copy: JsonSchema = { ...schema };
  for (const key of keys) delete copy[key];
  return copy;
}

/** ``{"type": "null"}`` 或只含 null 的联合/枚举视为空类型。 */
export function isNullSchema(schema: JsonSchema): boolean {
  if (schema.type === "null") return true;
  const type = schema.type;
  if (Array.isArray(type) && type.length > 0 && type.every((item) => item === "null")) {
    return true;
  }
  if (Array.isArray(schema.enum) && schema.enum.length > 0) {
    return schema.enum.every((item) => item === null);
  }
  return false;
}

/** 按 JSON Pointer 片段（``#/$defs/Foo``）在节点或根 schema 中查找定义。 */
function lookupRef(ref: string, node: JsonSchema, root: JsonSchema): JsonSchema | null {
  if (!ref.startsWith("#")) return null;
  const pointer = ref.slice(1);
  const segments = pointer
    .split("/")
    .filter((segment) => segment.length > 0)
    .map((segment) => segment.replace(/~1/g, "/").replace(/~0/g, "~"));
  if (segments.length === 0) return root;

  const roots: JsonSchema[] = node === root ? [root] : [node, root];
  for (const base of roots) {
    let current: unknown = base;
    let found = true;
    for (const segment of segments) {
      const record = asRecord(current);
      if (!record || !(segment in record)) {
        found = false;
        break;
      }
      current = record[segment];
    }
    if (found) {
      const result = asRecord(current);
      if (result) return result;
    }
  }
  return null;
}

function resolveNode(input: JsonSchema, root: JsonSchema, depth: number): JsonSchema {
  if (depth > 16) return input;
  let schema = asRecord(input);
  if (!schema) return {};

  if (typeof schema.$ref === "string") {
    const target = lookupRef(schema.$ref, schema, root);
    if (target) {
      schema = { ...target, ...omitKeys(schema, ["$ref"]) };
    }
  }

  const branches = Array.isArray(schema.anyOf)
    ? schema.anyOf
    : Array.isArray(schema.oneOf)
      ? schema.oneOf
      : null;
  if (branches) {
    const parsed = branches
      .map(asRecord)
      .filter((branch): branch is JsonSchema => branch !== null);
    const hasNull = parsed.some(isNullSchema);
    const nonNull = parsed.filter((branch) => !isNullSchema(branch));
    if (hasNull && nonNull.length > 0) {
      return resolveNode(
        { ...nonNull[0], ...omitKeys(schema, ["anyOf", "oneOf"]) },
        root,
        depth + 1,
      );
    }
  }

  if (Array.isArray(schema.type)) {
    const types = schema.type.filter(
      (item): item is string => typeof item === "string" && item !== "null",
    );
    if (types.length === 1) {
      schema = { ...schema, type: types[0] };
    }
  }
  return schema;
}

/**
 * 展开 ``$ref``、去掉可空 ``anyOf``/``oneOf`` 的 null 分支，并保留节点自身的
 * ``title``/``description`` 等覆盖字段。
 *
 * ``root`` 用于在属性节点上查找根 schema 的 ``$defs``；省略时只查节点自身。
 */
export function resolveSchema(schema: JsonSchema, root: JsonSchema = schema): JsonSchema {
  return resolveNode(schema, root, 0);
}

/** 读取对象的属性列表（已展开 ``$ref``），保持 schema 中的声明顺序。 */
export function schemaProperties(
  schema: JsonSchema,
  root: JsonSchema = schema,
): SchemaProperty[] {
  const resolvedRoot = resolveSchema(root);
  const source = resolveSchema(schema, resolvedRoot);
  const properties = asRecord(source.properties);
  if (!properties) return [];

  const required = Array.isArray(source.required)
    ? source.required.filter((item): item is string => typeof item === "string")
    : [];

  const result: SchemaProperty[] = [];
  for (const [key, raw] of Object.entries(properties)) {
    const property = asRecord(raw);
    if (!property) continue;
    result.push({
      key,
      schema: resolveSchema(property, resolvedRoot),
      required: required.includes(key),
    });
  }
  return result;
}

/** 判断 schema 应渲染成哪种控件。 */
export function schemaType(input: JsonSchema): SchemaKind {
  let schema = input;
  if (typeof schema.$ref === "string" || Array.isArray(schema.anyOf) || Array.isArray(schema.oneOf)) {
    schema = resolveSchema(schema);
  }
  if (Array.isArray(schema.enum)) return "enum";

  const type = schema.type;
  if (typeof type === "string") {
    if (type === "string" || type === "number" || type === "integer" || type === "boolean") {
      return type;
    }
    if (type === "array" || type === "object") return type;
  }
  if (Array.isArray(type)) {
    const types = type.filter((item): item is string => typeof item === "string" && item !== "null");
    if (types.length === 1) return schemaType({ ...schema, type: types[0] });
  }
  return "unknown";
}

/** 返回 schema 的默认值；没有 ``default`` 字段时返回 ``undefined``。 */
export function schemaDefault(schema: JsonSchema): unknown {
  return "default" in schema ? schema.default : undefined;
}

export function toJsonString(value: unknown): string {
  if (value === undefined) return "";
  try {
    return JSON.stringify(value, null, 2) ?? "";
  } catch {
    return "";
  }
}

export function parseJsonValue(
  text: string,
): { ok: true; value: unknown } | { ok: false; error: string } {
  if (text.trim() === "") return { ok: true, value: undefined };
  try {
    return { ok: true, value: JSON.parse(text) as unknown };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}
