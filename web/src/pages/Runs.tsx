import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, qs } from "../api";
import { RunTable } from "../components/RunTable";
import type { Page, Run, RunStatus } from "../types";
import { Button, cx, ErrorLine, Heading, Input, StatusMark } from "../ui";

const STATUSES: RunStatus[] = [
  "success",
  "failure",
  "retry",
  "blocked_stale_worker",
  "skipped_duplicate",
  "revoked",
  "running",
];

export default function Runs() {
  const [params, setParams] = useSearchParams();
  const statuses = params.getAll("status");
  const task = params.get("task") ?? "";
  const schedule = params.get("schedule") ?? "";
  const worker = params.get("worker") ?? "";

  const [items, setItems] = useState<Run[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  const filterKey = params.toString();

  async function load(before?: number) {
    setLoading(true);
    try {
      const page = await api.get<Page<Run>>(
        `/runs${qs({ status: statuses, task, schedule, worker, before_id: before, limit: 100 })}`,
      );
      setItems((prev) => (before ? [...prev, ...page.items] : page.items));
      setNext(page.next_before_id);
      setError(null);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, [filterKey]);

  function update(key: string, value: string | string[]) {
    const p = new URLSearchParams(params);
    p.delete(key);
    (Array.isArray(value) ? value : [value]).filter(Boolean).forEach((v) => p.append(key, v));
    setParams(p, { replace: true });
  }

  function toggleStatus(s: string) {
    update("status", statuses.includes(s) ? statuses.filter((x) => x !== s) : [...statuses, s]);
  }

  return (
    <>
      <Heading kicker="history" title="Runs">
        <Button onClick={() => load()}>refresh</Button>
      </Heading>

      <div className="mb-5 flex flex-wrap items-end gap-x-6 gap-y-3">
        <div>
          <div className="label mb-1">outcome</div>
          <div className="flex flex-wrap gap-1">
            {STATUSES.map((s) => (
              <button
                key={s}
                onClick={() => toggleStatus(s)}
                className={cx(
                  "border px-2 py-0.5",
                  statuses.includes(s) ? "border-ink bg-paper-2" : "border-rule hover:border-ink-2",
                )}
              >
                <StatusMark status={s} />
              </button>
            ))}
          </div>
        </div>
        <label>
          <span className="label mb-1 block">task</span>
          <Input defaultValue={task} onBlur={(e) => update("task", e.target.value.trim())} className="w-56" />
        </label>
        <label>
          <span className="label mb-1 block">schedule</span>
          <Input defaultValue={schedule} onBlur={(e) => update("schedule", e.target.value.trim())} className="w-44" />
        </label>
        <label>
          <span className="label mb-1 block">worker</span>
          <Input defaultValue={worker} onBlur={(e) => update("worker", e.target.value.trim())} className="w-44" />
        </label>
        {filterKey ? (
          <button className="pb-1.5 font-mono text-xs underline" onClick={() => setParams({}, { replace: true })}>
            clear
          </button>
        ) : null}
      </div>

      <ErrorLine error={error} />
      <RunTable runs={items} empty={loading ? "loading…" : "No runs match."} />
      {next ? (
        <div className="mt-4">
          <Button onClick={() => load(next)} disabled={loading}>
            older →
          </Button>
        </div>
      ) : null}
    </>
  );
}
