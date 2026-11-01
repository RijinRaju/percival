import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { safeNext, useSession } from "../session";
import type { Me } from "../types";
import { Button, ErrorLine, Field, Input } from "../ui";

export function Wordmark({ small }: { small?: boolean }) {
  return (
    <span className={`inline-flex items-center gap-2 font-mono font-semibold tracking-tight ${small ? "text-sm" : "text-lg"}`}>
      <span aria-hidden className="relative inline-block h-3.5 w-3.5 bg-ink">
        <span className="absolute inset-[4px] bg-signal" />
      </span>
      percival
    </span>
  );
}

export default function Login() {
  const { signedIn } = useSession();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      signedIn(await api.post<Me>("/auth/login", { username, password }));
      navigate(safeNext(params.get("next")), { replace: true });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-screen items-start justify-center px-4 pt-[18vh]">
      <form onSubmit={submit} className="w-full max-w-xs">
        <Wordmark />
        <div className="mt-8 space-y-4 border-t border-ink pt-6">
          <Field label="Username">
            <Input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoFocus required />
          </Field>
          <Field label="Password">
            <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
          </Field>
          <ErrorLine error={error} />
          <Button tone="solid" type="submit" disabled={busy} className="w-full justify-center">
            {busy ? "checking…" : "log in"}
          </Button>
        </div>
      </form>
    </main>
  );
}
