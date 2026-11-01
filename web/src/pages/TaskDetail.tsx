import hljs from "highlight.js/lib/core";
import python from "highlight.js/lib/languages/python";
import { useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import { enc } from "../api";
import { RunTable } from "../components/RunTable";
import { short, stamp } from "../format";
import { useApi } from "../hooks";
import type { TaskDetail as TaskDetailT } from "../types";
import { Button, ErrorLine, Heading, Kv } from "../ui";

hljs.registerLanguage("python", python);

export default function TaskDetail() {
  const { name = "" } = useParams();
  const { data, error } = useApi<TaskDetailT>(`/tasks/${enc(name)}`);

  const highlighted = useMemo(() => {
    const source = data?.meta?.source;
    return source ? hljs.highlight(source, { language: "python" }).value : null;
  }, [data?.meta?.source]);

  if (error) return <ErrorLine error={error} />;
  if (!data) return <p className="font-mono text-sm text-ink-2">loading…</p>;
  const meta = data.meta;

  return (
    <>
      <Heading kicker={<Link to="/tasks" className="hover:text-ink">← tasks</Link>} title={<span className="font-mono">{data.name}</span>}>
        <Link to={`/schedules/new`} state={{ task: data.name }}>
          <Button>schedule it</Button>
        </Link>
      </Heading>

      {meta?.doc ? <p className="mb-6 max-w-3xl whitespace-pre-wrap">{meta.doc}</p> : null}

      <dl className="mb-10 max-w-3xl">
        <Kv k="signature">
          {data.name.split(".").pop()}
          {meta?.signature ?? "(?)"}
        </Kv>
        <Kv k="module">{meta?.module ?? "—"}</Kv>
        <Kv k="workers">
          {data.workers.length
            ? data.workers.map((w) => `${w.hostname} (${short(w.code_version)})`).join(", ")
            : <span className="text-signal">▲ no live worker has it</span>}
        </Kv>
        <Kv k="schedules">
          {data.schedules.length
            ? data.schedules.map((s, i) => (
                <span key={s}>
                  {i ? ", " : ""}
                  <Link to={`/schedules/${enc(s)}`} className="underline decoration-rule underline-offset-4">{s}</Link>
                </span>
              ))
            : "—"}
        </Kv>
        {meta?.published_at ? (
          <Kv k="source from">
            {meta.hostname} on {short(meta.code_version)}, {stamp(meta.published_at)}
          </Kv>
        ) : null}
      </dl>

      {highlighted ? (
        <>
          <h2 className="mb-2 border-b border-ink pb-2 text-lg font-semibold">Source</h2>
          <p className="mb-2 text-xs text-ink-2">As published by the worker at startup. For reading only.</p>
          <pre className="mb-10 overflow-x-auto bg-paper-2 p-4 font-mono text-[12.5px] leading-relaxed">
            <code dangerouslySetInnerHTML={{ __html: highlighted }} />
          </pre>
        </>
      ) : null}

      <h2 className="mb-3 border-b border-ink pb-2 text-lg font-semibold">Recent runs</h2>
      <RunTable runs={data.recent_runs} hide={["task"]} />
    </>
  );
}
