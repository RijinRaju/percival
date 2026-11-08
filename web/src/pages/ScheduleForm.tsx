import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, enc } from "../api";
import { clock, day, modernZone, short } from "../format";
import { useApi } from "../hooks";
import { useStatus } from "../Shell";
import type { CronSpec, Schedule, ScheduleSpec, TaskDetail, TaskRow } from "../types";
import { Button, cx, ErrorLine, Field, Heading, Input, Select, Textarea } from "../ui";

const PRESETS: [string, Omit<CronSpec, "type">][] = [
  ["every 5 min", { minute: "*/5", hour: "*", day_of_week: "*", day_of_month: "*", month_of_year: "*" }],
  ["hourly", { minute: "0", hour: "*", day_of_week: "*", day_of_month: "*", month_of_year: "*" }],
  ["daily 09:00", { minute: "0", hour: "9", day_of_week: "*", day_of_month: "*", month_of_year: "*" }],
  ["weekdays 09:00", { minute: "0", hour: "9", day_of_week: "mon-fri", day_of_month: "*", month_of_year: "*" }],
  ["mon + thu 09:00", { minute: "0", hour: "9", day_of_week: "mon,thu", day_of_month: "*", month_of_year: "*" }],
  ["1st of month", { minute: "0", hour: "6", day_of_week: "*", day_of_month: "1", month_of_year: "*" }],
];

const CRON_FIELDS: [keyof Omit<CronSpec, "type">, string][] = [
  ["minute", "minute"],
  ["hour", "hour"],
  ["day_of_month", "day (month)"],
  ["month_of_year", "month"],
  ["day_of_week", "day (week)"],
];

const UNITS: [string, number][] = [
  ["seconds", 1],
  ["minutes", 60],
  ["hours", 3600],
  ["days", 86400],
];

// formatting with a zone the browser doesn't know throws, and a throw during
// render blanks the page, so fall back to UTC
function inZone(t: string, zone: string): string {
  const opts = { weekday: "short", hour: "2-digit", minute: "2-digit", hour12: false } as const;
  try {
    return new Date(t).toLocaleString(undefined, { ...opts, timeZone: zone });
  } catch {
    return new Date(t).toLocaleString(undefined, { ...opts, timeZone: "UTC" });
  }
}

const ZONES: string[] = (() => {
  try {
    const all = (Intl as unknown as { supportedValuesOf(k: string): string[] }).supportedValuesOf("timeZone");
    return ["UTC", ...Array.from(new Set(all.map(modernZone))).filter((z) => z !== "UTC").sort()];
  } catch {
    return ["UTC"];
  }
})();

type Param = { name: string; annotation: string | null; optional: boolean };

// "(user_id: int, *, dry_run: bool = False)" -> fields for a form. Only
// needs to be good enough to save typing, raw JSON is always there.
function parseSignature(sig: string | null | undefined): Param[] | null {
  if (!sig) return null;
  const inner = sig.trim().replace(/^\(/, "").replace(/\)(\s*->.*)?$/, "");
  const parts: string[] = [];
  let depth = 0;
  let buf = "";
  for (const ch of inner) {
    if ("([{".includes(ch)) depth++;
    if (")]}".includes(ch)) depth--;
    if (ch === "," && depth === 0) {
      parts.push(buf);
      buf = "";
    } else buf += ch;
  }
  if (buf.trim()) parts.push(buf);
  const params: Param[] = [];
  for (const raw of parts.map((p) => p.trim())) {
    if (!raw || raw === "*" || raw === "/" || raw.startsWith("*") || raw === "self") continue;
    const [left, def] = raw.split(/=(.*)/s);
    const [name, annotation] = left.split(/:(.*)/s);
    params.push({ name: name.trim(), annotation: annotation?.trim() || null, optional: def !== undefined });
  }
  return params;
}

function coerce(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

type FormState = {
  name: string;
  task: string;
  kind: ScheduleSpec["type"];
  cron: Omit<CronSpec, "type">;
  every: number;
  unit: number;
  at: string;
  timezone: string;
  rawArgs: boolean;
  argsJson: string;
  kwargsJson: string;
  fields: Record<string, string>;
  queue: string;
  priority: string;
  expires: string;
  gate: boolean;
  version: string;
  notes: string;
  enabled: boolean;
};

function fromSchedule(s: Schedule): Partial<FormState> {
  const spec = s.schedule as ScheduleSpec;
  const base: Partial<FormState> = {
    task: s.task,
    kind: spec.type,
    timezone: s.timezone ?? "UTC",
    argsJson: JSON.stringify(s.args ?? []),
    kwargsJson: JSON.stringify(s.kwargs ?? {}, null, 2),
    rawArgs: true,
    queue: s.queue ?? "",
    priority: s.priority?.toString() ?? "",
    expires: s.expires?.toString() ?? "",
    gate: !!s.required_version,
    version: s.required_version ?? "",
    notes: s.notes ?? "",
    enabled: s.enabled,
  };
  if (spec.type === "crontab") {
    const { type: _, ...cron } = spec;
    base.cron = cron;
  } else if (spec.type === "interval") {
    const unit = [...UNITS].reverse().find(([, size]) => spec.every % size === 0)?.[1] ?? 1;
    base.every = spec.every / unit;
    base.unit = unit;
  } else if (spec.type === "once") {
    base.at = spec.at.slice(0, 16);
  }
  return base;
}

export default function ScheduleForm() {
  const { name: editing } = useParams();
  const [params] = useSearchParams();
  const copyFrom = params.get("from");
  const navigate = useNavigate();
  const location = useLocation();
  const { status } = useStatus();
  const tasks = useApi<TaskRow[]>("/tasks");
  const source = useApi<Schedule>(editing || copyFrom ? `/schedules/${enc((editing ?? copyFrom)!)}` : null);

  const [form, setForm] = useState<FormState>({
    name: "",
    task: (location.state as { task?: string } | null)?.task ?? "",
    kind: "crontab",
    cron: PRESETS[2][1],
    every: 5,
    unit: 60,
    at: "",
    timezone: modernZone(Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"),
    rawArgs: false,
    argsJson: "[]",
    kwargsJson: "{}",
    fields: {},
    queue: "",
    priority: "",
    expires: "",
    gate: true,
    version: "",
    notes: "",
    enabled: true,
  });
  const [loaded, setLoaded] = useState(false);
  const [preview, setPreview] = useState<{ runs: string[]; error: string | null }>({ runs: [], error: null });
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  // fill from the schedule being edited/duplicated, once
  useEffect(() => {
    if (loaded || !source.data) return;
    setForm((f) => ({ ...f, ...fromSchedule(source.data!), name: editing ? source.data!.name : `${source.data!.name}-copy` }));
    setLoaded(true);
  }, [source.data, loaded, editing]);

  // default the gate to whatever the newest worker runs
  useEffect(() => {
    const current = status?.versions.current;
    if (current && !form.version && !editing) setForm((f) => ({ ...f, version: current }));
  }, [status?.versions.current, form.version, editing]);

  const taskDetail = useApi<TaskDetail>(form.task ? `/tasks/${enc(form.task)}` : null);
  const signature = taskDetail.data?.meta?.signature ?? null;
  const signatureParams = useMemo(() => parseSignature(signature), [signature]);

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setForm((f) => ({ ...f, [k]: v }));

  const scheduleSpec: ScheduleSpec = useMemo(() => {
    if (form.kind === "crontab") return { type: "crontab", ...form.cron };
    if (form.kind === "interval") return { type: "interval", every: form.every * form.unit };
    return { type: "once", at: form.at };
  }, [form.kind, form.cron, form.every, form.unit, form.at]);

  // live preview, debounced
  useEffect(() => {
    if (form.kind === "once" && !form.at) {
      setPreview({ runs: [], error: null });
      return;
    }
    const id = window.setTimeout(async () => {
      try {
        const runs = await api.post<string[]>("/schedules/preview", {
          schedule: scheduleSpec,
          timezone: form.timezone,
          count: 5,
        });
        setPreview({ runs, error: null });
      } catch (err) {
        setPreview({ runs: [], error: err instanceof Error ? err.message : String(err) });
      }
    }, 350);
    return () => window.clearTimeout(id);
  }, [scheduleSpec, form.timezone, form.kind, form.at]);

  function buildArgs(): { args: unknown[]; kwargs: Record<string, unknown> } {
    if (form.rawArgs || !signatureParams) {
      const args = JSON.parse(form.argsJson || "[]");
      const kwargs = JSON.parse(form.kwargsJson || "{}");
      if (!Array.isArray(args)) throw new Error("args has to be a JSON list");
      if (typeof kwargs !== "object" || Array.isArray(kwargs) || kwargs === null) {
        throw new Error("kwargs has to be a JSON object");
      }
      return { args, kwargs };
    }
    const kwargs: Record<string, unknown> = {};
    for (const p of signatureParams) {
      const text = form.fields[p.name];
      if (text === undefined || text === "") {
        if (!p.optional) throw new Error(`${p.name} is required by the task signature`);
        continue;
      }
      kwargs[p.name] = coerce(text);
    }
    return { args: [], kwargs };
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    let argBits;
    try {
      argBits = buildArgs();
    } catch (err) {
      setError(err);
      return;
    }
    const body = {
      ...(editing ? {} : { name: form.name.trim() }),
      task: form.task.trim(),
      schedule: scheduleSpec,
      timezone: form.timezone,
      ...argBits,
      options: {
        queue: form.queue.trim() || null,
        priority: form.priority === "" ? null : Number(form.priority),
        expires: form.expires === "" ? null : Number(form.expires),
        required_version: form.gate ? form.version.trim() || null : null,
      },
      enabled: form.enabled,
      notes: form.notes,
    };
    setBusy(true);
    try {
      const saved = editing
        ? await api.patch<Schedule>(`/schedules/${enc(editing)}`, body)
        : await api.post<Schedule>("/schedules", body);
      const warn = saved.warnings?.length ? `?warn=${enc(saved.warnings.join(" "))}` : "";
      navigate(`/schedules/${enc(saved.name)}${warn}`);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const versions = status?.versions.versions ?? [];

  return (
    <>
      <Heading
        kicker={<Link to={editing ? `/schedules/${enc(editing)}` : "/"} className="hover:text-ink">← back</Link>}
        title={editing ? `Edit ${editing}` : "New schedule"}
      />

      <form onSubmit={submit} className="grid gap-10 lg:grid-cols-[1fr_22rem]">
        <div className="space-y-8">
          <fieldset className="grid gap-4 sm:grid-cols-2">
            <Field label="Name" hint={editing ? "names can't change, duplicate it instead" : "unique, no slashes"}>
              <Input value={form.name} onChange={(e) => set("name", e.target.value)} disabled={!!editing} required />
            </Field>
            <Field label="Task" hint={tasks.data?.length ? "tasks your workers have registered" : "no worker has reported its tasks yet"}>
              <Input list="known-tasks" value={form.task} onChange={(e) => set("task", e.target.value)} required />
              <datalist id="known-tasks">
                {(tasks.data ?? []).map((t) => (
                  <option key={t.name} value={t.name} />
                ))}
              </datalist>
            </Field>
          </fieldset>

          <fieldset>
            <legend className="label mb-2">When</legend>
            <div className="mb-4 inline-flex border border-ink font-mono text-xs">
              {(["crontab", "interval", "once"] as const).map((k) => (
                <button
                  key={k}
                  type="button"
                  onClick={() => set("kind", k)}
                  className={cx("px-3 py-1.5", form.kind === k ? "bg-ink text-paper" : "hover:bg-paper-2")}
                >
                  {k === "crontab" ? "cron" : k === "interval" ? "every" : "once at"}
                </button>
              ))}
            </div>

            {form.kind === "crontab" ? (
              <>
                <div className="mb-3 flex flex-wrap gap-1.5">
                  {PRESETS.map(([label, cron]) => (
                    <button
                      key={label}
                      type="button"
                      onClick={() => set("cron", cron)}
                      className="border border-rule px-2 py-0.5 font-mono text-xs text-ink-2 hover:border-ink hover:text-ink"
                    >
                      {label}
                    </button>
                  ))}
                </div>
                <div className="grid grid-cols-5 gap-2">
                  {CRON_FIELDS.map(([key, label]) => (
                    <Field key={key} label={label}>
                      <Input value={form.cron[key]} onChange={(e) => set("cron", { ...form.cron, [key]: e.target.value })} />
                    </Field>
                  ))}
                </div>
              </>
            ) : null}

            {form.kind === "interval" ? (
              <div className="flex max-w-sm gap-2">
                <Input type="number" min={1} value={form.every} onChange={(e) => set("every", Number(e.target.value))} />
                <Select value={form.unit} onChange={(e) => set("unit", Number(e.target.value))}>
                  {UNITS.map(([label, size]) => (
                    <option key={size} value={size}>
                      {label}
                    </option>
                  ))}
                </Select>
              </div>
            ) : null}

            {form.kind === "once" ? (
              <Input type="datetime-local" value={form.at} onChange={(e) => set("at", e.target.value)} className="max-w-xs" required />
            ) : null}

            {form.kind !== "interval" ? (
              <Field label="Timezone" className="mt-4 max-w-sm" hint="the clock this schedule follows, DST included">
<Select value={form.timezone} onChange={(e) => set("timezone", e.target.value)}>
                  {(ZONES.includes(form.timezone) ? ZONES : [form.timezone, ...ZONES]).map((z) => (
                    <option key={z} value={z}>
                      {z}
                    </option>
                  ))}
                </Select>
              </Field>
            ) : null}
          </fieldset>

          <fieldset>
            <div className="mb-2 flex items-center justify-between">
              <legend className="label">Arguments</legend>
              {signatureParams ? (
                <button type="button" className="font-mono text-xs underline" onClick={() => set("rawArgs", !form.rawArgs)}>
                  {form.rawArgs ? "use fields" : "raw JSON"}
                </button>
              ) : null}
            </div>
            {signature ? <p className="mb-3 font-mono text-xs text-ink-2">{form.task}{signature}</p> : null}
            {signatureParams && !form.rawArgs ? (
              signatureParams.length ? (
                <div className="grid gap-3 sm:grid-cols-2">
                  {signatureParams.map((p) => (
                    <Field
                      key={p.name}
                      label={p.name}
                      hint={`${p.annotation ?? "any"}${p.optional ? ", optional" : ""} · JSON or plain text`}
                    >
                      <Input
                        value={form.fields[p.name] ?? ""}
                        onChange={(e) => set("fields", { ...form.fields, [p.name]: e.target.value })}
                      />
                    </Field>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-ink-2">This task takes no arguments.</p>
              )
            ) : (
              <div className="grid gap-3 sm:grid-cols-[1fr_2fr]">
                <Field label="args (list)">
                  <Textarea rows={4} value={form.argsJson} onChange={(e) => set("argsJson", e.target.value)} />
                </Field>
                <Field label="kwargs (object)">
                  <Textarea rows={4} value={form.kwargsJson} onChange={(e) => set("kwargsJson", e.target.value)} />
                </Field>
              </div>
            )}
          </fieldset>

          <fieldset>
            <legend className="label mb-2">Delivery</legend>
            <div className="grid gap-4 sm:grid-cols-3">
              <Field label="Queue" hint="blank = default">
                <Input value={form.queue} onChange={(e) => set("queue", e.target.value)} placeholder="celery" />
              </Field>
              <Field label="Priority" hint="0–255, blank = none">
                <Input type="number" min={0} max={255} value={form.priority} onChange={(e) => set("priority", e.target.value)} />
              </Field>
              <Field label="Expires" hint="seconds after it's sent">
                <Input type="number" min={1} value={form.expires} onChange={(e) => set("expires", e.target.value)} />
              </Field>
            </div>
          </fieldset>

          <fieldset className="border-l-2 border-ink pl-4">
            <label className="flex items-start gap-3">
              <input type="checkbox" className="mt-1 accent-[var(--ink)]" checked={form.gate} onChange={(e) => set("gate", e.target.checked)} />
              <span>
                <span className="font-medium">Block if the worker runs a different version</span>
                <span className="block text-sm text-ink-2">
                  A worker on any other version won't run this task. It puts it back on the queue for one that matches.
                </span>
              </span>
            </label>
            {form.gate ? (
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Input value={form.version} onChange={(e) => set("version", e.target.value)} className="max-w-xs" placeholder="git sha or version" />
                {versions.map((v) => (
                  <button
                    key={v.version}
                    type="button"
                    onClick={() => set("version", v.version)}
                    className={cx("border px-2 py-0.5 font-mono text-xs", v.stale ? "border-rule text-ink-3" : "border-ink")}
                    title={`${v.count} live worker(s)`}
                  >
                    {short(v.version)} ×{v.count}
                    {v.stale ? " (old)" : ""}
                  </button>
                ))}
              </div>
            ) : null}
          </fieldset>

          <Field label="Notes" hint="why it exists, who to ask. shown on the schedule page">
            <Textarea rows={3} value={form.notes} onChange={(e) => set("notes", e.target.value)} />
          </Field>

          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="accent-[var(--ink)]" checked={form.enabled} onChange={(e) => set("enabled", e.target.checked)} />
            active (uncheck to save it held)
          </label>

          <div className="border-t border-ink pt-4">
            <ErrorLine error={error} />
            <Button tone="solid" type="submit" disabled={busy}>
              {busy ? "saving…" : editing ? "save changes" : "create schedule"}
            </Button>
          </div>
        </div>

        <aside className="lg:sticky lg:top-6 lg:self-start">
          <div className="label mb-2 border-b border-ink pb-2">would run next</div>
          {preview.error ? (
            <p className="font-mono text-xs text-signal">▲ {preview.error}</p>
          ) : preview.runs.length ? (
            <ol className="font-mono text-sm">
              {preview.runs.map((t) => (
                <li key={t} className="border-b border-rule py-1.5">
                  <div>
                    {day(t)} <span className="tabular">{clock(t)}</span>
                  </div>
                  {form.kind !== "interval" ? (
                    <div className="text-xs text-ink-2">
                      {inZone(t, form.timezone)}{" "}
                      {form.timezone}
                    </div>
                  ) : null}
                </li>
              ))}
            </ol>
          ) : (
            <p className="font-mono text-xs text-ink-2">nothing to show yet</p>
          )}
          <p className="mt-3 text-xs text-ink-2">Worked out by the server with the same code beat uses.</p>
        </aside>
      </form>
    </>
  );
}
