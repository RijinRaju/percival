import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { short } from "../format";
import { useApi } from "../hooks";
import { useStatus } from "../Shell";
import { Button, Code, cx, Empty, ErrorLine, Heading, Input, Td, Th } from "../ui";

type Available = {
  available: boolean;
  timezone?: string;
  code_version?: string;
  hostname?: string;
  entries: { name: string; task: string; human: string; action: "create" | "exists" | "redacted" | "unsupported" }[];
};

const WHY: Record<string, string> = {
  exists: "already on the board",
  redacted: "has redacted values, use the CLI",
  unsupported: "solar/custom schedule, not supported",
};

export default function Import() {
  const navigate = useNavigate();
  const { status } = useStatus();
  const { data, error } = useApi<Available>("/schedules/import/available");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [version, setVersion] = useState("");
  const [busy, setBusy] = useState(false);
  const [importError, setImportError] = useState<unknown>(null);

  useEffect(() => {
    if (data) setPicked(new Set(data.entries.filter((e) => e.action === "create").map((e) => e.name)));
  }, [data]);

  useEffect(() => {
    if (status?.versions.current && !version) setVersion(status.versions.current);
  }, [status?.versions.current, version]);

  async function go() {
    setBusy(true);
    setImportError(null);
    try {
      await api.post("/schedules/import", { names: [...picked], required_version: version.trim() || null });
      navigate("/");
    } catch (err) {
      setImportError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Heading kicker={<Link to="/" className="hover:text-ink">← schedules</Link>} title="Import beat_schedule" />
      <ErrorLine error={error} />
      {data && !data.available ? (
        <Empty>
          <p className="mb-2 text-ink">No worker has published a beat_schedule yet.</p>
          <p className="mb-2">Workers publish it on startup after <code className="font-mono">percival.init()</code>. Or run the importer from your project:</p>
          <Code>percival import --app proj.celery:app --redis-url redis://… --apply</Code>
        </Empty>
      ) : null}
      {data?.available ? (
        <>
          <p className="mb-6 max-w-2xl text-sm text-ink-2">
            From <code className="font-mono">{data.hostname}</code> on <code className="font-mono">{short(data.code_version)}</code>, app
            timezone <code className="font-mono">{data.timezone}</code>. After importing, remove these entries from{" "}
            <code className="font-mono">beat_schedule</code> in your config, otherwise beat will put the config version back on its next
            restart.
          </p>
          <table className="mb-6 w-full max-w-4xl border-collapse text-sm">
            <thead>
              <tr>
                <Th className="w-10" />
                <Th>Name</Th>
                <Th>Task</Th>
                <Th>When</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {data.entries.map((e) => {
                const can = e.action === "create";
                return (
                  <tr key={e.name} className={cx(!can && "text-ink-3")}>
                    <Td>
                      <input
                        type="checkbox"
                        className="accent-[var(--ink)]"
                        disabled={!can}
                        checked={picked.has(e.name)}
                        onChange={(ev) => {
                          const next = new Set(picked);
                          if (ev.target.checked) next.add(e.name);
                          else next.delete(e.name);
                          setPicked(next);
                        }}
                      />
                    </Td>
                    <Td className="font-medium">{e.name}</Td>
                    <Td className="font-mono text-xs">{e.task}</Td>
                    <Td className="font-mono text-xs">{e.human}</Td>
                    <Td className="font-mono text-xs">{WHY[e.action] ?? ""}</Td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="mb-4 flex flex-wrap items-end gap-3">
            <label>
              <span className="label mb-1 block">require version</span>
              <Input value={version} onChange={(e) => setVersion(e.target.value)} className="w-64" placeholder="blank = no gate" />
            </label>
            <Button tone="solid" onClick={go} disabled={busy || !picked.size}>
              {busy ? "importing…" : `import ${picked.size}`}
            </Button>
          </div>
          <ErrorLine error={importError} />
        </>
      ) : null}
    </>
  );
}
