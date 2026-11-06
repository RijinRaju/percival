import { useState, type FormEvent, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useApi } from "../hooks";
import { useSession } from "../session";
import type { Me } from "../types";
import { Button, ErrorLine, Field, Input } from "../ui";
import { Wordmark } from "./Login";

type Test = { ok: boolean; message: string } | "testing" | null;

function Section({ n, title, children }: { n: string; title: string; children: ReactNode }) {
  return (
    <section className="grid gap-6 border-t border-ink py-6 md:grid-cols-[12rem_1fr]">
      <div>
        <div className="font-mono text-3xl font-medium text-ink-3">{n}</div>
        <div className="mt-1 font-semibold">{title}</div>
      </div>
      <div className="space-y-4">{children}</div>
    </section>
  );
}

function TestButton({ kind, url, result, onResult }: {
  kind: "broker" | "redis";
  url: string;
  result: Test;
  onResult: (t: Test) => void;
}) {
  async function run() {
    onResult("testing");
    try {
      onResult(await api.post<{ ok: boolean; message: string }>("/setup/test", { kind, url }));
    } catch (err) {
      onResult({ ok: false, message: err instanceof Error ? err.message : String(err) });
    }
  }
  return (
    <div className="flex flex-wrap items-center gap-3">
      <Button type="button" small onClick={run} disabled={!url || result === "testing"}>
        {result === "testing" ? "testing…" : "test connection"}
      </Button>
      {result && result !== "testing" ? (
        <span className={`font-mono text-xs ${result.ok ? "text-ok" : "text-signal"}`}>
          {result.ok ? "■" : "▲"} {result.message}
        </span>
      ) : null}
    </div>
  );
}

export default function Setup() {
  const { signedIn } = useSession();
  const navigate = useNavigate();
  const fromEnv = useApi<{ connections_from_env: boolean }>("/setup").data?.connections_from_env ?? false;
  const [form, setForm] = useState({
    username: "admin",
    password: "",
    confirm: "",
    broker_url: "redis://redis:6379/0",
    redis_url: "redis://redis:6379/0",
    redbeat_key_prefix: "redbeat:",
  });
  const [brokerTest, setBrokerTest] = useState<Test>(null);
  const [redisTest, setRedisTest] = useState<Test>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const set = (k: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const mismatch = form.confirm.length > 0 && form.confirm !== form.password;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (mismatch) return;
    setBusy(true);
    setError(null);
    try {
      const { confirm: _, ...all } = form;
      const body = fromEnv ? { username: all.username, password: all.password } : all;
      const res = await api.post<{ username: string; csrf_token: string }>("/setup", body);
      const me: Me = { username: res.username, kind: "user", csrf_token: res.csrf_token, scopes: ["read", "write"] };
      signedIn(me);
      navigate("/");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-3xl px-4 py-10 sm:px-8">
      <Wordmark />
      <h1 className="mt-10 text-3xl font-semibold tracking-tight">First run</h1>
      <p className="mt-2 max-w-xl text-ink-2">
        {fromEnv ? (
          <>Broker and redis came from environment variables, so all that's left is an admin account.</>
        ) : (
          <>
            Three things and you're in. Connection URLs are stored encrypted with your{" "}
            <code className="font-mono text-[13px]">PERCIVAL_SECRET_KEY</code>.
          </>
        )}
      </p>

      <form onSubmit={submit} className="mt-8">
        <Section n="01" title="Admin account">
          <Field label="Username">
            <Input value={form.username} onChange={set("username")} autoComplete="username" required />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Password" hint="at least 10 characters">
              <Input type="password" value={form.password} onChange={set("password")} autoComplete="new-password" required />
            </Field>
            <Field label="Again" error={mismatch ? "doesn't match" : null}>
              <Input type="password" value={form.confirm} onChange={set("confirm")} autoComplete="new-password" required />
            </Field>
          </div>
        </Section>

        {fromEnv ? null : (
          <>
            <Section n="02" title="Broker">
              <Field label="Broker URL" hint="the same one your workers use. redis:// or amqp://">
                <Input value={form.broker_url} onChange={(e) => { set("broker_url")(e); setBrokerTest(null); }} required />
              </Field>
              <TestButton kind="broker" url={form.broker_url} result={brokerTest} onResult={setBrokerTest} />
            </Section>

            <Section n="03" title="Schedule store">
              <Field
                label="Redis URL"
                hint="where RedBeat keeps schedules and where percival.init() writes events. can be the broker if that's redis"
              >
                <Input value={form.redis_url} onChange={(e) => { set("redis_url")(e); setRedisTest(null); }} required />
              </Field>
              <TestButton kind="redis" url={form.redis_url} result={redisTest} onResult={setRedisTest} />
              <Field label="RedBeat key prefix" hint="only change this if you set redbeat_key_prefix in your celery config">
                <Input value={form.redbeat_key_prefix} onChange={set("redbeat_key_prefix")} className="max-w-xs" />
              </Field>
            </Section>
          </>
        )}

        <div className="border-t border-ink pt-6">
          <ErrorLine error={error} />
          <Button tone="solid" type="submit" disabled={busy || mismatch}>
            {busy ? "saving…" : "finish setup →"}
          </Button>
        </div>
      </form>
    </main>
  );
}
