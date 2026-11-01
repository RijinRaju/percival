import { Link } from "react-router-dom";
import { qs } from "../api";
import { relative, short, stamp } from "../format";
import { useApi, useNow } from "../hooks";
import type { VersionSummary, Worker } from "../types";
import { cx, Empty, ErrorLine, Heading, Td, Th } from "../ui";

function Summary({ v }: { v: VersionSummary }) {
  if (!v.versions.length) return null;
  if (!v.mismatch) {
    return (
      <p className="mb-6 text-sm">
        <span className="text-ok">■</span> Every live worker runs <code className="font-mono">{v.current}</code>.
      </p>
    );
  }
  return (
    <div className="mb-6 grid gap-px border border-ink bg-ink sm:grid-cols-[repeat(auto-fill,minmax(14rem,1fr))]">
      {v.versions.map((x) => (
        <div key={x.version} className={cx("bg-paper px-4 py-3", x.stale && "bg-signal-wash")}>
          <div className="label">{x.stale ? "behind" : "newest"}</div>
          <div className={cx("font-mono text-xl", x.stale && "text-signal")}>{short(x.version)}</div>
          <div className="font-mono text-xs text-ink-2">
            {x.count} worker{x.count === 1 ? "" : "s"}
          </div>
        </div>
      ))}
    </div>
  );
}

export default function Workers() {
  const { data, error, loading } = useApi<{ workers: Worker[]; versions: VersionSummary }>("/workers", { every: 10_000 });
  const now = useNow();
  const current = data?.versions.current;

  return (
    <>
      <Heading kicker="from heartbeats, every 30s" title="Workers" />
      <ErrorLine error={error} />
      {data ? <Summary v={data.versions} /> : null}
      {!loading && data && !data.workers.length ? (
        <Empty>No worker has checked in. Workers show up here once they call percival.init() and start.</Empty>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] border-collapse text-sm">
            <thead>
              <tr>
                <Th className="w-20">State</Th>
                <Th>Hostname</Th>
                <Th className="w-28">Version</Th>
                <Th>Queues</Th>
                <Th className="w-44">Up since</Th>
                <Th className="w-28">Last seen</Th>
              </tr>
            </thead>
            <tbody>
              {(data?.workers ?? []).map((w) => {
                const stale = w.alive && current && w.code_version !== current;
                return (
                  <tr key={w.hostname} className={cx(!w.alive && "text-ink-3", stale && "bg-signal-wash/50")}>
                    <Td className="font-mono text-xs">
                      {w.alive ? <span className="text-ok">■ up</span> : <span>□ gone</span>}
                    </Td>
                    <Td className="font-mono text-[13px]">
                      <Link to={`/runs${qs({ worker: w.hostname })}`} className="hover:underline">{w.hostname}</Link>
                      {w.pid ? <span className="text-ink-3"> pid {w.pid}</span> : null}
                    </Td>
                    <Td className={cx("font-mono text-xs", stale && "font-semibold text-signal")} title={w.code_version ?? undefined}>
                      {short(w.code_version)}
                      {stale ? " behind" : ""}
                    </Td>
                    <Td className="font-mono text-xs">{w.queues.join(", ") || "—"}</Td>
                    <Td className="tabular font-mono text-xs">{stamp(w.started_at)}</Td>
                    <Td className="font-mono text-xs">{relative(w.last_seen, now)}</Td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
