import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, enc, qs } from "../api";
import { Confirm } from "../components/Confirm";
import { RunTable } from "../components/RunTable";
import { clock, day, json, relative, stamp } from "../format";
import { useApi, useNow } from "../hooks";
import { useStatus } from "../Shell";
import type { Page, Run, Schedule } from "../types";
import { Button, Code, ErrorLine, Heading, Kv } from "../ui";
import { Gate } from "./Board";

type Dialog = "run" | "delete" | null;

export default function ScheduleDetail() {
  const { name = "" } = useParams();
  const navigate = useNavigate();
  const now = useNow();
  const { reload: reloadStatus } = useStatus();
  const sched = useApi<Schedule>(`/schedules/${enc(name)}`, { every: 15_000 });
  const runs = useApi<Page<Run>>(`/runs${qs({ schedule: name, limit: 50 })}`, { every: 15_000 });
  const [dialog, setDialog] = useState<Dialog>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const s = sched.data;

  async function toggle() {
    if (!s) return;
    setActionError(null);
    try {
      await api.post(`/schedules/${enc(name)}/${s.enabled ? "pause" : "resume"}`);
      await sched.reload();
      reloadStatus();
    } catch (err) {
      setActionError(err);
    }
  }

  if (sched.error && !s) {
    return (
      <>
        <ErrorLine error={sched.error} />
        <Link to="/" className="font-mono text-sm underline">← back to the board</Link>
      </>
    );
  }
  if (!s) return <p className="font-mono text-sm text-ink-2">loading…</p>;

  return (
    <>
      <Heading kicker={<Link to="/" className="hover:text-ink">← schedules</Link>} title={s.name}>
        <Button onClick={() => setDialog("run")}>run now</Button>
        <Button onClick={toggle}>{s.enabled ? "pause" : "resume"}</Button>
        <Link to={`/schedules/${enc(name)}/edit`}><Button>edit</Button></Link>
        <Link to={`/schedules/new?from=${enc(name)}`}><Button>duplicate</Button></Link>
        <Button tone="danger" onClick={() => setDialog("delete")}>delete</Button>
      </Heading>

      <ErrorLine error={actionError} />
      {notice ? <p className="mb-4 font-mono text-[13px] text-ok">■ {notice}</p> : null}
      {!s.enabled ? (
        <p className="mb-6 border-l-2 border-hold bg-paper-2 px-3 py-2 text-sm">
          <strong className="font-mono text-xs uppercase tracking-widest text-hold">held</strong> Paused, beat will skip it until
          it's resumed.
        </p>
      ) : null}

      <div className="grid gap-10 lg:grid-cols-[1fr_20rem]">
        <dl>
          <Kv k="task">
            <Link to={`/tasks/${enc(s.task)}`} className="underline decoration-rule underline-offset-4 hover:decoration-ink">
              {s.task}
            </Link>
          </Kv>
          <Kv k="schedule">
            {s.human}
            <span className="text-ink-2"> ({s.schedule.type})</span>
          </Kv>
          <Kv k="timezone">{s.schedule.type === "crontab" ? s.timezone ?? "app timezone" : "—"}</Kv>
          <Kv k="args">{json(s.args)}</Kv>
          <Kv k="kwargs">{json(s.kwargs)}</Kv>
          <Kv k="queue">{s.queue ?? "default"}</Kv>
          {s.priority !== null ? <Kv k="priority">{s.priority}</Kv> : null}
          {s.expires !== null ? <Kv k="expires">{s.expires}s after dispatch</Kv> : null}
          <Kv k="version gate">
            <Gate s={s} />
          </Kv>
          <Kv k="last run">{s.last_run_at ? `${stamp(s.last_run_at)} (${relative(s.last_run_at, now)})` : "never"}</Kv>
          <Kv k="runs so far">{s.total_run_count ?? "—"}</Kv>
          <Kv k="origin">{s.origin ?? "—"}</Kv>
          <Kv k="changed">
            {s.updated_at ? `${stamp(s.updated_at)} by ${s.updated_by ?? "?"}` : "—"}
            {s.applied === false ? <span className="text-hold"> · beat hasn't picked this up yet</span> : null}
            {s.applied === true ? <span className="text-ok"> · applied</span> : null}
          </Kv>
          {s.notes ? (
            <div className="mt-6">
              <div className="label mb-1">notes</div>
              <p className="whitespace-pre-wrap text-sm">{s.notes}</p>
            </div>
          ) : null}
        </dl>

        <aside>
          <div className="label mb-2 border-b border-ink pb-2">next departures</div>
          {s.enabled && s.next_runs.length ? (
            <ol className="font-mono text-sm">
              {s.next_runs.map((t, i) => (
                <li key={t} className="flex justify-between border-b border-rule py-1.5">
                  <span className={i === 0 ? "font-semibold" : ""}>
                    {day(t)} <span className="tabular">{clock(t)}</span>
                  </span>
                  <span className="text-xs text-ink-2">{relative(t, now)}</span>
                </li>
              ))}
            </ol>
          ) : (
            <p className="font-mono text-sm text-ink-2">{s.enabled ? "no more runs" : "held"}</p>
          )}
        </aside>
      </div>

      <h2 className="mb-3 mt-12 border-b border-ink pb-2 text-lg font-semibold">History</h2>
      <ErrorLine error={runs.error} />
      <RunTable runs={runs.data?.items ?? []} hide={["schedule"]} empty="Hasn't run yet." />

      <Confirm
        open={dialog === "run"}
        title={`Run ${s.name} now?`}
        confirmLabel="send it"
        onClose={() => setDialog(null)}
        onConfirm={async () => {
          const res = await api.post<{ task_id: string }>(`/schedules/${enc(name)}/run-now`);
          setNotice(`sent, task id ${res.task_id}`);
          window.setTimeout(() => runs.reload(), 1500);
        }}
      >
        <p>
          This sends <code className="font-mono">{s.task}</code> to {s.queue ?? "the default queue"} right away, with:
        </p>
        <Code>{`args   ${json(s.args)}\nkwargs ${json(s.kwargs)}`}</Code>
        {s.required_version ? (
          <p className="text-ink-2">Workers not on {s.required_version} will refuse it, same as a scheduled run.</p>
        ) : null}
      </Confirm>

      <Confirm
        open={dialog === "delete"}
        title={`Delete ${s.name}?`}
        confirmLabel="delete"
        danger
        onClose={() => setDialog(null)}
        onConfirm={async () => {
          await api.del(`/schedules/${enc(name)}`);
          reloadStatus();
          navigate("/");
        }}
      >
        <p>Beat stops running it on its next tick. Run history stays.</p>
      </Confirm>
    </>
  );
}
