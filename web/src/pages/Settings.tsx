import { useState, type FormEvent, type ReactNode } from "react";
import { api } from "../api";
import { Confirm } from "../components/Confirm";
import { relative, stamp } from "../format";
import { useApi } from "../hooks";
import { useSession } from "../session";
import type { ConnectionSettings, Token, User } from "../types";
import { Button, Code, ErrorLine, Field, Heading, Input, Td, Th } from "../ui";

function Section({ title, note, children }: { title: string; note?: ReactNode; children: ReactNode }) {
  return (
    <section className="grid gap-6 border-t border-ink py-8 lg:grid-cols-[16rem_1fr]">
      <div>
        <h2 className="font-semibold">{title}</h2>
        {note ? <p className="mt-1 text-sm text-ink-2">{note}</p> : null}
      </div>
      <div className="min-w-0">{children}</div>
    </section>
  );
}

function Connections() {
  const { data, error, reload } = useApi<ConnectionSettings>("/settings/connections");
  const [draft, setDraft] = useState<Partial<ConnectionSettings>>({});
  const [saveError, setSaveError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);

  async function save(e: FormEvent) {
    e.preventDefault();
    setSaveError(null);
    setSaved(false);
    try {
      await api.put("/settings/connections", draft);
      setDraft({});
      setSaved(true);
      reload();
    } catch (err) {
      setSaveError(err);
    }
  }

  if (error) return <ErrorLine error={error} />;
  if (!data) return null;
  const locked = data.from_env;
  return (
    <form onSubmit={save} className="max-w-xl space-y-4">
      {locked ? (
        <p className="border-l-2 border-hold bg-paper-2 px-3 py-2 text-sm">
          Broker, redis and prefixes come from <code className="font-mono">PERCIVAL_*</code> environment variables. Change
          them there and restart the panel.
        </p>
      ) : null}
      <Field label="Broker URL" hint={locked ? `from env: ${data.broker_url}` : `now: ${data.broker_url} · leave blank to keep`}>
        <Input disabled={locked} value={draft.broker_url ?? ""} onChange={(e) => setDraft({ ...draft, broker_url: e.target.value || undefined })} />
      </Field>
      <Field label="Redis URL" hint={locked ? `from env: ${data.redis_url}` : `now: ${data.redis_url} · leave blank to keep`}>
        <Input disabled={locked} value={draft.redis_url ?? ""} onChange={(e) => setDraft({ ...draft, redis_url: e.target.value || undefined })} />
      </Field>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="RedBeat prefix">
          <Input disabled={locked} value={draft.redbeat_key_prefix ?? data.redbeat_key_prefix} onChange={(e) => setDraft({ ...draft, redbeat_key_prefix: e.target.value })} />
        </Field>
        <Field label="Percival prefix" hint="key_prefix in percival.init()">
          <Input disabled={locked} value={draft.key_prefix ?? data.key_prefix} onChange={(e) => setDraft({ ...draft, key_prefix: e.target.value })} />
        </Field>
        <Field label="Keep runs (days)">
          <Input
            type="number"
            min={1}
            value={draft.retention_days ?? data.retention_days}
            onChange={(e) => setDraft({ ...draft, retention_days: Number(e.target.value) })}
          />
        </Field>
      </div>
      <ErrorLine error={saveError} />
      <div className="flex items-center gap-3">
        <Button tone="solid" type="submit" disabled={!Object.keys(draft).length}>save</Button>
        {saved ? <span className="font-mono text-xs text-ok">■ saved</span> : null}
      </div>
    </form>
  );
}

function People() {
  const { me } = useSession();
  const { data, error, reload } = useApi<User[]>("/users");
  const [form, setForm] = useState({ username: "", password: "" });
  const [addError, setAddError] = useState<unknown>(null);
  const [removing, setRemoving] = useState<User | null>(null);

  async function add(e: FormEvent) {
    e.preventDefault();
    setAddError(null);
    try {
      await api.post("/users", form);
      setForm({ username: "", password: "" });
      reload();
    } catch (err) {
      setAddError(err);
    }
  }

  return (
    <>
      <ErrorLine error={error} />
      <table className="mb-6 w-full max-w-2xl border-collapse text-sm">
        <thead>
          <tr>
            <Th>Username</Th>
            <Th>Last login</Th>
            <Th className="w-20" />
          </tr>
        </thead>
        <tbody>
          {(data ?? []).map((u) => (
            <tr key={u.id}>
              <Td className="font-mono text-[13px]">
                {u.username}
                {u.username === me?.username ? <span className="text-ink-3"> (you)</span> : null}
              </Td>
              <Td className="font-mono text-xs">{u.last_login_at ? relative(u.last_login_at) : "never"}</Td>
              <Td className="text-right">
                {u.username !== me?.username ? (
                  <button className="font-mono text-xs text-signal underline" onClick={() => setRemoving(u)}>remove</button>
                ) : null}
              </Td>
            </tr>
          ))}
        </tbody>
      </table>
      <form onSubmit={add} className="flex max-w-2xl flex-wrap items-end gap-3">
        <Field label="Username" className="w-44">
          <Input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} required />
        </Field>
        <Field label="Password" className="w-56">
          <Input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} autoComplete="new-password" required />
        </Field>
        <Button type="submit">add person</Button>
      </form>
      <ErrorLine error={addError} />
      <Confirm
        open={!!removing}
        title={`Remove ${removing?.username}?`}
        confirmLabel="remove"
        danger
        onClose={() => setRemoving(null)}
        onConfirm={async () => {
          await api.del(`/users/${removing!.id}`);
          reload();
        }}
      >
        <p>They're logged out everywhere. Their past changes stay in the audit log.</p>
      </Confirm>
    </>
  );
}

function Password() {
  const [form, setForm] = useState({ current_password: "", new_password: "" });
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState(false);
  const { signOut } = useSession();

  async function change(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.post("/users/me/password", form);
      setDone(true);
      // every session is gone, including this one
      window.setTimeout(signOut, 1200);
    } catch (err) {
      setError(err);
    }
  }

  return (
    <form onSubmit={change} className="flex max-w-2xl flex-wrap items-end gap-3">
      <Field label="Current" className="w-56">
        <Input type="password" value={form.current_password} onChange={(e) => setForm({ ...form, current_password: e.target.value })} autoComplete="current-password" required />
      </Field>
      <Field label="New" className="w-56">
        <Input type="password" value={form.new_password} onChange={(e) => setForm({ ...form, new_password: e.target.value })} autoComplete="new-password" required />
      </Field>
      <Button type="submit">change</Button>
      {done ? <span className="font-mono text-xs text-ok">■ changed, logging you out</span> : null}
      <div className="w-full">
        <ErrorLine error={error} />
      </div>
    </form>
  );
}

function Tokens() {
  const { data, error, reload } = useApi<Token[]>("/tokens");
  const [name, setName] = useState("");
  const [write, setWrite] = useState(false);
  const [created, setCreated] = useState<Token | null>(null);
  const [createError, setCreateError] = useState<unknown>(null);
  const [revoking, setRevoking] = useState<Token | null>(null);

  async function create(e: FormEvent) {
    e.preventDefault();
    setCreateError(null);
    try {
      setCreated(await api.post<Token>("/tokens", { name, scopes: write ? ["read", "write"] : ["read"] }));
      setName("");
      setWrite(false);
      reload();
    } catch (err) {
      setCreateError(err);
    }
  }

  return (
    <>
      {created?.token ? (
        <div className="mb-6 border border-ink p-4">
          <p className="mb-2 text-sm">
            <strong>{created.name}</strong>: copy it now, it won't be shown again.
          </p>
          <Code>{created.token}</Code>
          <div className="mt-3 flex gap-2">
            <Button small onClick={() => navigator.clipboard?.writeText(created.token!)}>copy</Button>
            <Button small onClick={() => setCreated(null)}>done</Button>
          </div>
        </div>
      ) : null}
      <ErrorLine error={error} />
      {data?.length ? (
        <table className="mb-6 w-full border-collapse text-sm">
          <thead>
            <tr>
              <Th>Name</Th>
              <Th className="w-32">Starts with</Th>
              <Th className="w-28">Scopes</Th>
              <Th className="w-36">Created</Th>
              <Th className="w-28">Last used</Th>
              <Th className="w-20" />
            </tr>
          </thead>
          <tbody>
            {data.map((t) => (
              <tr key={t.id} className={t.revoked_at ? "text-ink-3 line-through" : ""}>
                <Td>{t.name}</Td>
                <Td className="font-mono text-xs">{t.prefix}…</Td>
                <Td className={t.scopes.includes("write") ? "font-mono text-xs text-signal" : "font-mono text-xs"}>{t.scopes.join(" + ")}</Td>
                <Td className="font-mono text-xs">{stamp(t.created_at)}</Td>
                <Td className="font-mono text-xs">{t.last_used_at ? relative(t.last_used_at) : "never"}</Td>
                <Td className="text-right">
                  {t.revoked_at ? null : (
                    <button className="font-mono text-xs text-signal underline" onClick={() => setRevoking(t)}>revoke</button>
                  )}
                </Td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      <form onSubmit={create} className="flex flex-wrap items-end gap-4">
        <Field label="Name" className="w-60" hint="what or who uses it, e.g. claude-code, ci">
          <Input value={name} onChange={(e) => setName(e.target.value)} required />
        </Field>
        <label className="flex items-center gap-2 pb-6 text-sm">
          <input type="checkbox" className="accent-[var(--ink)]" checked={write} onChange={(e) => setWrite(e.target.checked)} />
          can change things (write)
        </label>
        <div className="pb-5">
          <Button type="submit">create token</Button>
        </div>
      </form>
      <ErrorLine error={createError} />
      <Confirm
        open={!!revoking}
        title={`Revoke ${revoking?.name}?`}
        confirmLabel="revoke"
        danger
        onClose={() => setRevoking(null)}
        onConfirm={async () => {
          await api.del(`/tokens/${revoking!.id}`);
          reload();
        }}
      >
        <p>Anything using it stops working straight away.</p>
      </Confirm>
    </>
  );
}

export default function Settings() {
  return (
    <>
      <Heading kicker="panel" title="Settings" />
      <Section title="Connections" note="Broker and redis are stored encrypted. Passwords in URLs are never shown back.">
        <Connections />
      </Section>
      <Section title="People" note="Everyone is an admin for now. Roles are on the list.">
        <People />
      </Section>
      <Section title="Your password" note="Changing it logs you out everywhere.">
        <Password />
      </Section>
      <Section
        title="API tokens"
        note={<>For scripts and MCP clients. Send as <code className="font-mono">Authorization: Bearer …</code>. Read-only unless you tick write.</>}
      >
        <Tokens />
      </Section>
    </>
  );
}
