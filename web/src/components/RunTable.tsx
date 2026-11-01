import { useNavigate } from "react-router-dom";
import { duration, json, short, stamp } from "../format";
import type { Run } from "../types";
import { cx, Empty, StatusMark, Td, Th } from "../ui";

export function RunTable({
  runs,
  hide = [],
  empty = "No runs recorded yet.",
}: {
  runs: Run[];
  hide?: ("task" | "schedule")[];
  empty?: string;
}) {
  const navigate = useNavigate();
  if (!runs.length) return <Empty>{empty}</Empty>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] border-collapse text-sm">
        <thead>
          <tr>
            <Th className="w-44">When</Th>
            <Th className="w-28">Outcome</Th>
            {hide.includes("task") ? null : <Th>Task</Th>}
            {hide.includes("schedule") ? null : <Th>Schedule</Th>}
            <Th>Worker</Th>
            <Th className="w-24">Version</Th>
            <Th className="w-20 text-right">Took</Th>
            <Th>Args</Th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr
              key={r.id}
              className={cx(
                "cursor-pointer hover:bg-paper-2",
                (r.status === "failure" || r.status === "blocked_stale_worker") && "bg-signal-wash/40",
              )}
              onClick={() => navigate(`/runs/${r.id}`)}
            >
              <Td className="tabular font-mono text-xs">{stamp(r.started_at ?? r.ts)}</Td>
              <Td>
                <StatusMark status={r.status} />
              </Td>
              {hide.includes("task") ? null : <Td className="font-mono text-xs">{r.task}</Td>}
              {hide.includes("schedule") ? null : (
                <Td className="font-mono text-xs text-ink-2">{r.schedule ?? "—"}</Td>
              )}
              <Td className="font-mono text-xs">{r.worker ?? "—"}</Td>
              <Td className="font-mono text-xs" title={r.code_version ?? undefined}>
                {short(r.code_version)}
              </Td>
              <Td className="tabular text-right font-mono text-xs">{duration(r.duration)}</Td>
              <Td className="max-w-[18rem] truncate font-mono text-xs text-ink-2" title={json({ args: r.args, kwargs: r.kwargs })}>
                {r.args?.length ? json(r.args) : ""}
                {r.kwargs && Object.keys(r.kwargs).length ? ` ${json(r.kwargs)}` : ""}
              </Td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
