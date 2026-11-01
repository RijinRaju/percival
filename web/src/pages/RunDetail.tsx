import { Link, useParams } from "react-router-dom";
import { enc } from "../api";
import { duration, json, short, stamp } from "../format";
import { useApi } from "../hooks";
import type { RunDetail as RunDetailT } from "../types";
import { Code, cx, ErrorLine, Heading, Kv, StatusMark } from "../ui";

const EXPLAIN: Partial<Record<string, string>> = {
  blocked_stale_worker:
    "The message asked for a code version this worker doesn't run, so the task body never executed.",
  skipped_duplicate: "@once_per already saw this key in the current window, so the run was skipped.",
  dedupe_unavailable:
    "@once_per couldn't reach redis and fail_open is off, so the run was skipped rather than risk a duplicate.",
};

export default function RunDetail() {
  const { id = "" } = useParams();
  const { data: run, error } = useApi<RunDetailT>(`/runs/${id}`);

  if (error) return <ErrorLine error={error} />;
  if (!run) return <p className="font-mono text-sm text-ink-2">loading…</p>;

  return (
    <>
      <Heading kicker={<Link to="/runs" className="hover:text-ink">← runs</Link>} title={<>Run {run.id}</>}>
        <StatusMark status={run.status} long />
      </Heading>

      {EXPLAIN[run.status] ? (
        <p className="mb-6 border-l-2 border-ink bg-paper-2 px-3 py-2 text-sm">{EXPLAIN[run.status]}</p>
      ) : null}
      {run.exc_type ? (
        <p className="mb-6 border-l-2 border-signal bg-signal-wash px-3 py-2 font-mono text-[13px] text-signal">
          {run.exc_type}: {run.exc_message}
        </p>
      ) : null}

      <div className="grid gap-10 lg:grid-cols-[1fr_22rem]">
        <dl>
          <Kv k="task">
            <Link to={`/tasks/${enc(run.task)}`} className="underline decoration-rule underline-offset-4">{run.task}</Link>
          </Kv>
          <Kv k="schedule">
            {run.schedule ? (
              <Link to={`/schedules/${enc(run.schedule)}`} className="underline decoration-rule underline-offset-4">
                {run.schedule}
              </Link>
            ) : (
              "— (not from a schedule)"
            )}
          </Kv>
          <Kv k="task id">{run.task_id ?? "—"}</Kv>
          <Kv k="worker">{run.worker ?? "—"}</Kv>
          <Kv k="worker version">{run.code_version ?? "—"}</Kv>
          <Kv k="required">{run.required_version ?? "—"}</Kv>
          <Kv k="queue">{run.queue ?? "—"}</Kv>
          <Kv k="started">{stamp(run.started_at)}</Kv>
          <Kv k="finished">{stamp(run.finished_at)}</Kv>
          <Kv k="took">{duration(run.duration)}</Kv>
          {run.retries ? <Kv k="retries">{run.retries}</Kv> : null}
          <Kv k="args">{json(run.args)}</Kv>
          <Kv k="kwargs">{json(run.kwargs)}</Kv>
          {run.extra ? <Kv k="extra">{json(run.extra)}</Kv> : null}
        </dl>

        {run.attempts.length > 1 ? (
          <aside>
            <div className="label mb-2 border-b border-ink pb-2">this message, every attempt</div>
            <ol className="relative ml-1 border-l border-ink">
              {run.attempts.map((a) => (
                <li key={a.id} className="relative pb-4 pl-4">
                  <span className={cx("absolute -left-[5px] top-1.5 h-2 w-2", a.id === run.id ? "bg-signal" : "bg-ink")} />
                  <Link to={`/runs/${a.id}`} className="block hover:underline">
                    <StatusMark status={a.status} long />
                  </Link>
                  <div className="font-mono text-xs text-ink-2">
                    {stamp(a.started_at ?? a.ts)} · {a.worker} · {short(a.code_version)}
                  </div>
                </li>
              ))}
            </ol>
          </aside>
        ) : null}
      </div>

      {run.traceback ? (
        <>
          <h2 className="mb-2 mt-10 border-b border-ink pb-2 text-lg font-semibold">Traceback</h2>
          <Code>{run.traceback}</Code>
        </>
      ) : null}
    </>
  );
}
