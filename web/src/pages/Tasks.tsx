import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { enc } from "../api";
import { relative, short } from "../format";
import { useApi } from "../hooks";
import type { TaskRow } from "../types";
import { Code, cx, Empty, ErrorLine, Heading, Input, StatusMark, Td, Th } from "../ui";

export default function Tasks() {
  const { data, error, loading } = useApi<TaskRow[]>("/tasks", { every: 30_000 });
  const [query, setQuery] = useState("");
  const navigate = useNavigate();

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (data ?? []).filter((t) => !q || t.name.toLowerCase().includes(q));
  }, [data, query]);

  return (
    <>
      <Heading kicker="registered by your workers" title="Tasks">
        <Input placeholder="filter" value={query} onChange={(e) => setQuery(e.target.value)} className="w-56" />
      </Heading>
      <p className="-mt-2 mb-6 max-w-2xl text-sm text-ink-2">
        Read only. Task code lives in your repository and ships with your workers. The panel only schedules tasks a
        worker has already registered.
      </p>
      <ErrorLine error={error} />
      {!loading && rows.length === 0 ? (
        <Empty>
          <p className="mb-2 text-ink">No tasks reported yet.</p>
          <p className="mb-2">Workers publish their tasks on startup once they call:</p>
          <Code>{`import percival\npercival.init(app, redis_url="redis://…", code_version=os.environ["GIT_SHA"])`}</Code>
        </Empty>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] border-collapse text-sm">
            <thead>
              <tr>
                <Th>Task</Th>
                <Th className="w-56">Workers</Th>
                <Th className="w-32">Versions</Th>
                <Th className="w-24 text-right">Schedules</Th>
                <Th className="w-36">Last run</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((t) => (
                <tr key={t.name} className="cursor-pointer hover:bg-paper-2" onClick={() => navigate(`/tasks/${enc(t.name)}`)}>
                  <Td>
                    <div className="font-mono text-[13px] font-medium">{t.name}</div>
                    {t.doc ? <div className="mt-0.5 line-clamp-1 text-xs text-ink-2">{t.doc}</div> : null}
                  </Td>
                  <Td className={cx("font-mono text-xs", !t.workers.length && "text-signal")}>
                    {t.workers.length ? `${t.workers.length} · ${t.workers.slice(0, 2).join(", ")}${t.workers.length > 2 ? "…" : ""}` : "▲ none alive"}
                  </Td>
                  <Td className={cx("font-mono text-xs", t.versions.length > 1 && "text-signal")}>
                    {t.versions.map(short).join(" ") || "—"}
                  </Td>
                  <Td className="tabular text-right font-mono text-xs">{t.schedules || "—"}</Td>
                  <Td>
                    <StatusMark status={t.last_run?.status} />
                    {t.last_run ? <div className="font-mono text-[11px] text-ink-2">{relative(t.last_run.ts)}</div> : null}
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
