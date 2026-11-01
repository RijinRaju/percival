import { Fragment, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, enc, qs } from "../api";
import { stamp } from "../format";
import type { AuditEntry, Page } from "../types";
import { Button, cx, Empty, ErrorLine, Heading, Select, Td, Th } from "../ui";

type Flat = Record<string, string>;

function flatten(value: unknown, prefix = "", out: Flat = {}): Flat {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    for (const [k, v] of Object.entries(value)) flatten(v, prefix ? `${prefix}.${k}` : k, out);
  } else if (prefix) {
    out[prefix] = JSON.stringify(value);
  }
  return out;
}

// only the fields that changed, "schedule.hour: 9 → 10"
function Diff({ before, after }: { before: unknown; after: unknown }) {
  const a = flatten(before);
  const b = flatten(after);
  const keys = [...new Set([...Object.keys(a), ...Object.keys(b)])].filter((k) => a[k] !== b[k]).sort();
  if (!keys.length) return <p className="font-mono text-xs text-ink-2">no field changes recorded</p>;
  return (
    <table className="font-mono text-xs">
      <tbody>
        {keys.map((k) => (
          <tr key={k}>
            <td className="py-0.5 pr-4 text-ink-2">{k}</td>
            <td className="py-0.5 pr-2 text-signal line-through decoration-signal/50">{a[k] ?? ""}</td>
            <td className="py-0.5 pr-2 text-ink-3">→</td>
            <td className="py-0.5 text-ok">{b[k] ?? ""}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function target(entry: AuditEntry) {
  if (!entry.target) return "—";
  if (entry.action.startsWith("schedule.") && entry.action !== "schedule.delete") {
    return <Link to={`/schedules/${enc(entry.target)}`} className="underline decoration-rule underline-offset-4">{entry.target}</Link>;
  }
  return entry.target;
}

export default function Audit() {
  const [source, setSource] = useState("");
  const [action, setAction] = useState("");
  const [items, setItems] = useState<AuditEntry[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);

  async function load(before?: number) {
    try {
      const page = await api.get<Page<AuditEntry>>(`/audit-log${qs({ source, action, before_id: before, limit: 100 })}`);
      setItems((prev) => (before ? [...prev, ...page.items] : page.items));
      setNext(page.next_before_id);
      setError(null);
    } catch (err) {
      setError(err);
    }
  }

  useEffect(() => {
    load();
  }, [source, action]);

  return (
    <>
      <Heading kicker="every change, who and from where" title="Audit log">
        <Select value={action} onChange={(e) => setAction(e.target.value)} className="w-40">
          <option value="">all actions</option>
          <option value="schedule">schedules</option>
          <option value="token">tokens</option>
          <option value="user">users</option>
          <option value="settings">settings</option>
        </Select>
        <Select value={source} onChange={(e) => setSource(e.target.value)} className="w-32">
          <option value="">any source</option>
          <option value="ui">ui</option>
          <option value="api">api</option>
          <option value="mcp">mcp</option>
        </Select>
      </Heading>
      <ErrorLine error={error} />
      {!items.length ? (
        <Empty>Nothing recorded yet.</Empty>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] border-collapse text-sm">
            <thead>
              <tr>
                <Th className="w-48">When</Th>
                <Th className="w-40">Who</Th>
                <Th className="w-16">From</Th>
                <Th className="w-44">Action</Th>
                <Th>Target</Th>
                <Th className="w-10" />
              </tr>
            </thead>
            <tbody>
              {items.map((e) => {
                const hasDiff = e.before !== null || e.after !== null;
                return (
                  <Fragment key={e.id}>
                    <tr className={cx(hasDiff && "cursor-pointer hover:bg-paper-2")} onClick={() => hasDiff && setOpen(open === e.id ? null : e.id)}>
                      <Td className="tabular font-mono text-xs">{stamp(e.ts)}</Td>
                      <Td className="font-mono text-xs">
                        {e.actor}
                        {e.actor_type === "token" ? <span className="text-ink-3"> (token)</span> : null}
                      </Td>
                      <Td className={cx("font-mono text-xs", e.source === "mcp" && "text-signal")}>{e.source}</Td>
                      <Td className="font-mono text-xs">{e.action}</Td>
                      <Td className="font-mono text-xs">{target(e)}</Td>
                      <Td className="font-mono text-xs text-ink-2">{hasDiff ? (open === e.id ? "−" : "+") : ""}</Td>
                    </tr>
                    {open === e.id ? (
                      <tr className="bg-paper-2">
                        <td colSpan={6} className="border-b border-rule px-3 py-3">
                          <Diff before={e.before} after={e.after} />
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {next ? (
        <div className="mt-4">
          <Button onClick={() => load(next)}>older →</Button>
        </div>
      ) : null}
    </>
  );
}
