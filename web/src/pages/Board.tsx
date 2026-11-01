import { Fragment, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { enc } from "../api";
import { clock, day, relative, short } from "../format";
import { useApi, useNow } from "../hooks";
import type { Schedule } from "../types";
import { Button, Code, cx, Empty, ErrorLine, Heading, Input, StatusMark, Td, Th } from "../ui";

function sortKey(s: Schedule): number {
  if (!s.enabled) return Number.MAX_SAFE_INTEGER;
  const next = s.next_runs[0];
  return next ? new Date(next).getTime() : Number.MAX_SAFE_INTEGER - 1;
}

export function Gate({ s }: { s: Schedule }) {
  const c = s.coverage;
  if (!c) return null;
  if (c.consumers === 0) {
    return <span className="text-signal" title={`no live worker consumes ${c.queue}`}>▲ nobody on {c.queue}</span>;
  }
  if (!s.required_version) {
    return <span className="text-ink-3" title="any worker version will run this">ungated</span>;
  }
  if (c.matching === 0) {
    return (
      <span className="text-signal" title="every worker on this queue runs a different version, all of them will refuse it">
        ▲ no {short(s.required_version)} worker
      </span>
    );
  }
  return (
    <span title={`${c.matching} of ${c.consumers} workers on ${c.queue} run ${s.required_version}`}>
      <span className="text-ok">■</span> {short(s.required_version)}
      {c.stale ? <span className="text-ink-2"> · {c.stale} would refuse</span> : null}
    </span>
  );
}

function Departure({ s, now }: { s: Schedule; now: number }) {
  if (!s.enabled) {
    return <div className="font-mono text-lg font-medium text-hold">held</div>;
  }
  const next = s.next_runs[0];
  if (!next) return <div className="font-mono text-lg text-ink-3">—</div>;
  return (
    <>
      <div className="tabular font-mono text-lg font-medium leading-tight">{clock(next)}</div>
      <div className="font-mono text-[11px] text-ink-2">
        {day(next)} · {relative(next, now)}
      </div>
    </>
  );
}

export default function Board() {
  const { data, error, loading } = useApi<Schedule[]>("/schedules", { every: 15_000 });
  const now = useNow(5000);
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<string | null>(null);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (data ?? [])
      .filter((s) => !q || s.name.toLowerCase().includes(q) || s.task.toLowerCase().includes(q))
      .sort((a, b) => sortKey(a) - sortKey(b) || a.name.localeCompare(b.name));
  }, [data, query]);

  const held = (data ?? []).filter((s) => !s.enabled).length;

  return (
    <>
      <Heading
        kicker="departures"
        title="Schedules"
      >
        <Input
          placeholder="filter by name or task"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-56"
        />
        <Link to="/import"><Button>import</Button></Link>
        <Link to="/schedules/new"><Button tone="solid">+ new schedule</Button></Link>
      </Heading>

      <ErrorLine error={error} />

      {!loading && data && data.length === 0 ? (
        <Empty>
          <p className="mb-3 text-ink">Nothing on the board yet.</p>
          <p className="mb-2">Create one with the button above, or bring over an existing <code className="font-mono">beat_schedule</code>:</p>
          <Code>percival import --app proj.celery:app --redis-url redis://… --apply</Code>
        </Empty>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px] border-collapse text-sm">
            <thead>
              <tr>
                <Th className="w-36">Next</Th>
                <Th>Schedule</Th>
                <Th className="w-56">When</Th>
                <Th className="w-36">Last run</Th>
                <Th className="w-48">Version gate</Th>
                <Th className="w-10" />
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <Fragment key={s.name}>
                  <tr
                    className={cx("cursor-pointer hover:bg-paper-2", !s.enabled && "text-ink-2")}
                    onClick={() => navigate(`/schedules/${enc(s.name)}`)}
                  >
                    <Td>
                      <Departure s={s} now={now} />
                    </Td>
                    <Td>
                      <div className="font-medium">{s.name}</div>
                      <div className="font-mono text-xs text-ink-2">{s.task}</div>
                    </Td>
                    <Td>
                      <div className="font-mono text-[13px]">{s.human}</div>
                      <div className="font-mono text-[11px] text-ink-2">
                        {s.schedule.type === "crontab" ? s.timezone ?? "app timezone" : s.schedule.type}
                        {s.queue ? ` · ${s.queue}` : ""}
                        {s.applied === false ? <span className="text-hold"> · waiting for beat</span> : null}
                      </div>
                    </Td>
                    <Td>
                      <StatusMark status={s.last_run?.status} />
                      <div className="font-mono text-[11px] text-ink-2">{s.last_run ? relative(s.last_run.ts, now) : "never"}</div>
                    </Td>
                    <Td className="font-mono text-xs">
                      <Gate s={s} />
                    </Td>
                    <Td>
                      {s.enabled && s.next_runs.length > 1 ? (
                        <button
                          className="font-mono text-xs text-ink-2 hover:text-ink"
                          title="next departures"
                          aria-expanded={open === s.name}
                          onClick={(e) => {
                            e.stopPropagation();
                            setOpen(open === s.name ? null : s.name);
                          }}
                        >
                          {open === s.name ? "−" : "+"}
                        </button>
                      ) : null}
                    </Td>
                  </tr>
                  {open === s.name ? (
                    <tr className="bg-paper-2">
                      <td colSpan={6} className="border-b border-rule px-3 py-2">
                        <div className="flex flex-wrap gap-x-6 gap-y-1 font-mono text-xs">
                          <span className="label">then</span>
                          {s.next_runs.slice(1).map((t) => (
                            <span key={t} className="tabular">
                              {day(t)} {clock(t)}
                            </span>
                          ))}
                        </div>
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              ))}
            </tbody>
          </table>
          {data ? (
            <p className="mt-3 font-mono text-xs text-ink-2">
              {data.length} schedule{data.length === 1 ? "" : "s"}
              {held ? ` · ${held} held` : ""}
            </p>
          ) : null}
        </div>
      )}
    </>
  );
}
