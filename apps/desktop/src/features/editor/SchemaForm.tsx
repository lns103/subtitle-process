import { useEffect, useId, useMemo, useState } from "react";
import type { ReactElement } from "react";
import type { JsonSchema } from "../../lib/models";
import {
  parseJsonValue,
  resolveSchema,
  schemaDefault,
  schemaProperties,
  schemaType,
  toJsonString,
  type SchemaKind,
} from "../../lib/schema";

export interface SchemaFormProps {
  schema: JsonSchema;
  value: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
  disabled?: boolean;
}

const inputClass =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-900 outline-none transition focus:border-slate-500 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-400";
const labelClass = "text-sm font-medium text-slate-700";
const hintClass = "text-xs leading-relaxed text-slate-500";
const markerClass = "ml-1 text-xs font-normal text-rose-600";
const buttonClass =
  "rounded-lg border border-slate-300 px-2 py-1 text-xs text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-300";

function stringValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

function numberValue(value: unknown): string {
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  if (typeof value === "string") return value;
  return "";
}

function itemsOf(value: unknown, fallback: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  if (Array.isArray(fallback)) return fallback;
  return [];
}

function emptyItem(schema: JsonSchema): unknown {
  const fallback = schemaDefault(schema);
  if (fallback !== undefined) return fallback;
  const kind = schemaType(schema);
  if (kind === "number" || kind === "integer") return 0;
  if (kind === "boolean") return false;
  if (kind === "array") return [];
  if (kind === "object") return {};
  return "";
}

function coerceItem(schema: JsonSchema, text: string): unknown {
  const kind = schemaType(schema);
  if (kind === "number" || kind === "integer") {
    if (text.trim() === "") return "";
    const parsed = Number(text);
    return Number.isFinite(parsed) ? parsed : text;
  }
  return text;
}

function optionLabel(option: unknown): string {
  if (option === null || option === undefined) return "null";
  return String(option);
}

function setField(
  value: Record<string, unknown>,
  key: string,
  next: unknown,
): Record<string, unknown> {
  const copy: Record<string, unknown> = { ...value };
  if (next === undefined) delete copy[key];
  else copy[key] = next;
  return copy;
}

function itemsSchemaOf(schema: JsonSchema): JsonSchema {
  return resolveSchema(
    typeof schema.items === "object" && schema.items !== null && !Array.isArray(schema.items)
      ? (schema.items as JsonSchema)
      : {},
  );
}

interface FieldProps {
  fieldKey: string;
  schema: JsonSchema;
  required: boolean;
  value: unknown;
  onChange: (next: unknown) => void;
  disabled: boolean;
  id: string;
}

interface ObjectFieldProps {
  id: string;
  title: string;
  description: string;
  requiredMarker: ReactElement | null;
  value: unknown;
  onChange: (next: unknown) => void;
  disabled: boolean;
}

function ObjectField({
  id,
  title,
  description,
  requiredMarker,
  value,
  onChange,
  disabled,
}: ObjectFieldProps): ReactElement {
  const external = toJsonString(value);
  const [text, setText] = useState(external);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setText(external);
    setError(null);
  }, [external]);

  const apply = () => {
    const parsed = parseJsonValue(text);
    if (!parsed.ok) {
      setError(parsed.error);
      return;
    }
    setError(null);
    onChange(parsed.value);
  };

  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className={labelClass}>
        {title}
        {requiredMarker}
      </label>
      <textarea
        id={id}
        className={`${inputClass} font-mono`}
        rows={6}
        spellCheck={false}
        value={text}
        disabled={disabled}
        onChange={(event) => setText(event.target.value)}
        onBlur={apply}
      />
      {description ? <p className={hintClass}>{description}</p> : null}
      {error ? (
        <p role="alert" className="text-xs text-rose-600">
          JSON 无效：{error}
        </p>
      ) : (
        <p className={hintClass}>失焦后应用；留空表示不设置。</p>
      )}
    </div>
  );
}

function SchemaField({
  fieldKey,
  schema,
  required,
  value,
  onChange,
  disabled,
  id,
}: FieldProps): ReactElement {
  const kind: SchemaKind = schemaType(schema);
  const title = typeof schema.title === "string" && schema.title.trim() !== "" ? schema.title : fieldKey;
  const description = typeof schema.description === "string" ? schema.description : "";
  const fallback = schemaDefault(schema);
  const current = value === undefined ? fallback : value;
  const missing =
    required &&
    (current === undefined ||
      current === null ||
      current === "" ||
      (Array.isArray(current) && current.length === 0));
  const requiredMarker = missing ? <span className={markerClass}>必填</span> : null;
  const update = (next: unknown) => onChange(next);

  if (kind === "boolean") {
    return (
      <div data-testid={`schema-field-${fieldKey}`} className="space-y-1">
        <div className="flex items-center gap-2">
          <input
            id={id}
            type="checkbox"
            className="h-4 w-4 rounded border-slate-300"
            checked={current === true}
            disabled={disabled}
            onChange={(event) => update(event.target.checked)}
          />
          <label htmlFor={id} className={labelClass}>
            {title}
            {requiredMarker}
          </label>
        </div>
        {description ? <p className={hintClass}>{description}</p> : null}
      </div>
    );
  }

  if (kind === "enum") {
    const options = Array.isArray(schema.enum) ? schema.enum : [];
    const selected = current === undefined || current === null ? "" : String(current);
    return (
      <div data-testid={`schema-field-${fieldKey}`} className="space-y-1.5">
        <label htmlFor={id} className={labelClass}>
          {title}
          {requiredMarker}
        </label>
        <select
          id={id}
          className={inputClass}
          value={selected}
          disabled={disabled}
          onChange={(event) => {
            const raw = event.target.value;
            if (raw === "") {
              update(undefined);
              return;
            }
            const match = options.find((option) => optionLabel(option) === raw);
            update(match === undefined ? raw : match);
          }}
        >
          <option value="">（未设置）</option>
          {options.map((option, index) => (
            <option key={`${optionLabel(option)}-${index}`} value={optionLabel(option)}>
              {optionLabel(option)}
            </option>
          ))}
        </select>
        {description ? <p className={hintClass}>{description}</p> : null}
      </div>
    );
  }

  if (kind === "number" || kind === "integer") {
    const minimum = typeof schema.minimum === "number" ? schema.minimum : undefined;
    const maximum = typeof schema.maximum === "number" ? schema.maximum : undefined;
    return (
      <div data-testid={`schema-field-${fieldKey}`} className="space-y-1.5">
        <label htmlFor={id} className={labelClass}>
          {title}
          {requiredMarker}
        </label>
        <input
          id={id}
          type="number"
          className={inputClass}
          step={kind === "integer" ? 1 : "any"}
          min={minimum}
          max={maximum}
          value={numberValue(current)}
          disabled={disabled}
          onChange={(event) => {
            const raw = event.target.value;
            if (raw.trim() === "") {
              update(undefined);
              return;
            }
            const parsed = Number(raw);
            if (Number.isFinite(parsed)) update(parsed);
          }}
        />
        {description ? <p className={hintClass}>{description}</p> : null}
      </div>
    );
  }

  if (kind === "array") {
    const itemsSchema = itemsSchemaOf(schema);
    const items = itemsOf(value, fallback);
    const enumOptions = Array.isArray(itemsSchema.enum) ? itemsSchema.enum : null;
    const labelId = `${id}-label`;
    const add = () => update([...items, emptyItem(itemsSchema)]);
    const remove = (index: number) => update(items.filter((_, position) => position !== index));

    return (
      <div data-testid={`schema-field-${fieldKey}`} className="space-y-1.5">
        <div className="flex items-center justify-between gap-2">
          <span id={labelId} className={labelClass}>
            {title}
            {requiredMarker}
          </span>
          <button type="button" className={buttonClass} disabled={disabled} onClick={add}>
            添加
          </button>
        </div>
        {description ? <p className={hintClass}>{description}</p> : null}
        <div role="group" aria-labelledby={labelId} className="space-y-2">
          {items.length === 0 ? (
            <p className="text-xs text-slate-400">暂无条目</p>
          ) : enumOptions ? (
            enumOptions.map((option, optionIndex) => {
              const checked = items.some((item) => optionLabel(item) === optionLabel(option));
              return (
                <label key={`${optionLabel(option)}-${optionIndex}`} className="flex items-center gap-2 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    className="h-4 w-4 rounded border-slate-300"
                    checked={checked}
                    disabled={disabled}
                    onChange={(event) =>
                      update(
                        event.target.checked
                          ? [...items, option]
                          : items.filter((item) => optionLabel(item) !== optionLabel(option)),
                      )
                    }
                  />
                  <span>{optionLabel(option)}</span>
                </label>
              );
            })
          ) : (
            items.map((item, index) => (
              <div key={index} className="flex items-center gap-2">
                <input
                  type={schemaType(itemsSchema) === "number" || schemaType(itemsSchema) === "integer" ? "number" : "text"}
                  className={inputClass}
                  aria-label={`${title} 第 ${index + 1} 项`}
                  value={
                    typeof item === "object" && item !== null ? toJsonString(item) : stringValue(item)
                  }
                  disabled={disabled}
                  onChange={(event) => {
                    const next = [...items];
                    next[index] = coerceItem(itemsSchema, event.target.value);
                    update(next);
                  }}
                />
                <button
                  type="button"
                  className={buttonClass}
                  aria-label={`删除${title} 第 ${index + 1} 项`}
                  disabled={disabled}
                  onClick={() => remove(index)}
                >
                  删除
                </button>
              </div>
            ))
          )}
        </div>
      </div>
    );
  }

  if (kind === "object") {
    return (
      <div data-testid={`schema-field-${fieldKey}`}>
        <ObjectField
          id={id}
          title={title}
          description={description}
          requiredMarker={requiredMarker}
          value={current}
          onChange={update}
          disabled={disabled}
        />
      </div>
    );
  }

  if (kind === "string") {
    return (
      <div data-testid={`schema-field-${fieldKey}`} className="space-y-1.5">
        <label htmlFor={id} className={labelClass}>
          {title}
          {requiredMarker}
        </label>
        <input
          id={id}
          type="text"
          className={inputClass}
          value={stringValue(current)}
          disabled={disabled}
          onChange={(event) => update(event.target.value)}
        />
        {description ? <p className={hintClass}>{description}</p> : null}
      </div>
    );
  }

  // 未知结构：只读 JSON，保证面板不崩。
  return (
    <div data-testid={`schema-field-${fieldKey}`} className="space-y-1.5">
      <label htmlFor={id} className={labelClass}>
        {title}
        {requiredMarker}
      </label>
      <textarea
        id={id}
        className={`${inputClass} font-mono`}
        rows={4}
        readOnly
        spellCheck={false}
        value={toJsonString(current)}
      />
      <p className="text-xs text-amber-600">不支持的结构，仅显示只读 JSON。</p>
      {description ? <p className={hintClass}>{description}</p> : null}
    </div>
  );
}

export function SchemaForm({
  schema,
  value,
  onChange,
  disabled = false,
}: SchemaFormProps): ReactElement {
  const baseId = useId();
  const root = useMemo(() => resolveSchema(schema), [schema]);
  const properties = useMemo(() => schemaProperties(root), [root]);
  const kind = schemaType(root);

  if (kind === "object" && properties.length === 0) {
    return <p className="text-sm text-slate-500">该步骤没有可配置参数。</p>;
  }

  if (kind !== "object") {
    return (
      <div className="space-y-1.5">
        <label htmlFor={`${baseId}-fallback`} className={labelClass}>
          原始参数（只读）
        </label>
        <textarea
          id={`${baseId}-fallback`}
          className={`${inputClass} font-mono`}
          rows={8}
          readOnly
          spellCheck={false}
          value={toJsonString(value)}
        />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {properties.map((property) => (
        <SchemaField
          key={property.key}
          fieldKey={property.key}
          schema={property.schema}
          required={property.required}
          value={value[property.key]}
          disabled={disabled}
          id={`${baseId}-${property.key}`}
          onChange={(next) => onChange(setField(value, property.key, next))}
        />
      ))}
    </div>
  );
}
