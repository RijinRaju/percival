import { createContext, useContext, useState, type ReactNode } from "react";
import { Link, NavLink, Outlet } from "react-router-dom";
import { relative, short, zoneLabel } from "./format";
import { useApi, useNow } from "./hooks";
import { Wordmark } from "./pages/Login";
import { useSession } from "./session";
import type { Status } from "./types";
import { cx } from "./ui";

const StatusCtx = createContext<{ status: Status | undefined; reload: () => void }>({
  status: undefined,
  reload: () => undefined,
});

export function useStatus() {
  return useContext(StatusCtx);
}

const NAV = [
  ["/", "Board"],
  ["/runs", "Runs"],
  ["/tasks", "Tasks"],
  ["/workers", "Workers"],
  ["/audit", "Audit"],
  ["/settings", "Settings"],
] as const;

function Sep() {
  return <span className="text-ink-3">·</span>;
}

function StatusLine({ status }: { status: Status | undefined }) {
  const now = useNow(5000);
  if (!status) return <span className="text-ink-3">reading status…</span>;

  const beat = status.beat;
  const beatLate = beat?.last_tick ? now - new Date(beat.last_tick).getTime() > Math.max(beat.max_interval * 3, 60) * 1000 : false;
  const counts = status.runs_24h;
  const bad = (counts.failure ?? 0) + (counts.blocked_stale_worker ?? 0);

  return (
    <>
      <span className={cx(!beat || beatLate ? "text-signal" : "text-ink")}>
        beat{" "}
        {beat ? (
          <span title={`${beat.hostname} · ${beat.scheduler}`}>
            {beatLate ? "▲ quiet since" : "■ ticked"} {relative(beat.last_tick, now)}
          </span>
        ) : (
          <span>▲ no heartbeat</span>
        )}
      </span>
      <Sep />
      <span>
        {status.workers_alive} worker{status.workers_alive === 1 ? "" : "s"}
      </span>
      {status.versions.versions.length ? (
        <>
          <Sep />
          <span className={cx(status.versions.mismatch && "text-signal")}>
            {status.versions.versions.map((v) => `${short(v.version)}×${v.count}`).join(" ")}
          </span>
        </>
      ) : null}
      <Sep />
      <span>
        24h <span className="text-ok">{counts.success ?? 0} ok</span>
        {bad ? <span className="text-signal"> · {bad} bad</span> : null}
      </span>
      <span className="ml-auto hidden text-ink-3 md:inline">times in {zoneLabel()}</span>
    </>
  );
}

function Banner({ tone = "signal", children }: { tone?: "signal" | "hold"; children: ReactNode }) {
  return (
    <div
      className={cx(
        "border-b px-4 py-3 text-sm sm:px-8",
        tone === "signal" ? "border-signal bg-signal-wash" : "border-hold bg-paper-2",
      )}
    >
      <div className="mx-auto max-w-[1400px]">{children}</div>
    </div>
  );
}

function Warnings({ status }: { status: Status | undefined }) {
  const [open, setOpen] = useState(false);
  if (!status) return null;
  const out: ReactNode[] = [];

  const v = status.versions;
  if (v.mismatch) {
    const stale = v.versions.filter((x) => x.stale);
    const staleCount = stale.reduce((n, x) => n + x.count, 0);
    const exposed = status.affected_schedules.filter((a) => !a.protected);
    out.push(
      <Banner key="versions">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <strong className="font-mono text-xs uppercase tracking-widest text-signal">stale workers</strong>
          <span>
            {staleCount} worker{staleCount === 1 ? "" : "s"} on{" "}
            {stale.map((x) => <code key={x.version} className="font-mono">{short(x.version)}</code>)} while the newest run{" "}
            <code className="font-mono">{short(v.current)}</code>.{" "}
            {status.affected_schedules.length ? (
              <>
                {status.affected_schedules.length} schedule{status.affected_schedules.length === 1 ? "" : "s"} share a queue with them
                {exposed.length ? (
                  <strong className="text-signal">, {exposed.length} with no version gate</strong>
                ) : (
                  ", all gated"
                )}
                .
              </>
            ) : null}
          </span>
          <span className="ml-auto flex gap-3 font-mono text-xs">
            {status.affected_schedules.length ? (
              <button className="underline" onClick={() => setOpen((o) => !o)}>
                {open ? "hide" : "which ones"}
              </button>
            ) : null}
            <Link to="/workers" className="underline">workers →</Link>
          </span>
        </div>
        {open ? (
          <ul className="mt-2 grid gap-1 font-mono text-xs sm:grid-cols-2 lg:grid-cols-3">
            {status.affected_schedules.map((a) => (
              <li key={a.name}>
                <Link to={`/schedules/${encodeURIComponent(a.name)}`} className="underline">{a.name}</Link>{" "}
                <span className={a.protected ? "text-ok" : "text-signal"}>
                  {a.protected ? `gated on ${short(a.required_version)}` : "not gated, a stale worker will run it"}
                </span>
              </li>
            ))}
          </ul>
        ) : null}
      </Banner>,
    );
  }

  if (!status.beat && status.lock?.ttl) {
    out.push(
      <Banner key="lock" tone="hold">
        <strong className="font-mono text-xs uppercase tracking-widest text-hold">beat lock held</strong>{" "}
        No beat is ticking, but <code className="font-mono">{status.lock.key}</code> is held for another{" "}
        {Math.round(status.lock.ttl / 60)} min. A beat that was killed keeps the lock until it expires and any new beat
        waits for it. Nothing will be scheduled until then.
      </Banner>,
    );
  }
  return <>{out}</>;
}

export default function Shell() {
  const { me, signOut } = useSession();
  const { data: status, reload } = useApi<Status>("/status", { every: 10_000 });

  return (
    <StatusCtx.Provider value={{ status, reload }}>
      <header className="border-b border-ink">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-8 gap-y-2 px-4 pt-4 sm:px-8">
          <Link to="/" aria-label="percival home">
            <Wordmark small />
          </Link>
          <nav className="-mb-px flex flex-wrap gap-x-5 text-sm">
            {NAV.map(([to, label]) => (
              <NavLink
                key={to}
                to={to}
                end={to === "/"}
                className={({ isActive }) =>
                  cx("border-b-2 pb-2.5 pt-1", isActive ? "border-ink font-medium" : "border-transparent text-ink-2 hover:text-ink")
                }
              >
                {label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3 pb-2 font-mono text-xs text-ink-2">
            <span>{me?.username}</span>
            <button onClick={signOut} className="underline hover:text-ink">log out</button>
          </div>
        </div>
      </header>
      <div className="border-b border-rule bg-paper-2">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-3 gap-y-1 px-4 py-1.5 font-mono text-xs text-ink-2 sm:px-8">
          <StatusLine status={status} />
        </div>
      </div>
      <Warnings status={status} />
      <main className="mx-auto max-w-[1400px] px-4 py-8 sm:px-8">
        <Outlet />
      </main>
    </StatusCtx.Provider>
  );
}
