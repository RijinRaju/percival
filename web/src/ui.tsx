import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";
import type { RunStatus } from "./types";

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  tone?: "plain" | "solid" | "danger";
  small?: boolean;
};

export function Button({ tone = "plain", small, className, ...rest }: ButtonProps) {
  return (
    <button
      {...rest}
      className={cx(
        "inline-flex items-center gap-2 border font-mono tracking-tight transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-40",
        small ? "px-2 py-0.5 text-xs" : "px-3 py-1.5 text-[13px]",
        tone === "solid" && "border-ink bg-ink text-paper hover:bg-ink-2 hover:border-ink-2",
        tone === "plain" && "border-ink/60 text-ink hover:bg-paper-2 hover:border-ink",
        tone === "danger" && "border-signal text-signal hover:bg-signal hover:text-paper",
        className,
      )}
    />
  );
}

export function Field({
  label,
  hint,
  error,
  children,
  className,
}: {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label className={cx("block", className)}>
      <span className="label mb-1 block">{label}</span>
      {children}
      {error ? (
        <span className="mt-1 block font-mono text-xs text-signal">{error}</span>
      ) : hint ? (
        <span className="mt-1 block text-xs text-ink-2">{hint}</span>
      ) : null}
    </label>
  );
}

const inputClass =
  "w-full border border-rule bg-paper px-2 py-1.5 font-mono text-[13px] text-ink placeholder:text-ink-3 " +
  "focus:border-ink focus:outline-none";

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx(inputClass, props.className)} />;
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cx(inputClass, "pr-6", props.className)} />;
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cx(inputClass, "leading-relaxed", props.className)} />;
}

// One glyph per outcome, so status reads without relying on colour alone.
const MARKS: Record<RunStatus, { glyph: string; word: string; tone: string }> = {
  success: { glyph: "■", word: "ok", tone: "text-ok" },
  running: { glyph: "▶", word: "running", tone: "text-ink" },
  failure: { glyph: "▲", word: "failed", tone: "text-signal" },
  retry: { glyph: "↻", word: "retry", tone: "text-hold" },
  revoked: { glyph: "✕", word: "revoked", tone: "text-ink-2" },
  skipped_duplicate: { glyph: "○", word: "duplicate", tone: "text-ink-2" },
  blocked_stale_worker: { glyph: "◆", word: "blocked", tone: "text-signal" },
  dedupe_unavailable: { glyph: "◇", word: "no dedupe", tone: "text-hold" },
};

export function StatusMark({ status, long }: { status: RunStatus | string | null | undefined; long?: boolean }) {
  if (!status) return <span className="font-mono text-xs text-ink-3">—</span>;
  const mark = MARKS[status as RunStatus] ?? { glyph: "·", word: status, tone: "text-ink-2" };
  return (
    <span className={cx("inline-flex items-center gap-1.5 font-mono text-xs", mark.tone)} title={status}>
      <span aria-hidden>{mark.glyph}</span>
      {long ? status.replaceAll("_", " ") : mark.word}
    </span>
  );
}

export function Heading({ title, kicker, children }: { title: ReactNode; kicker?: ReactNode; children?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4 border-b border-ink pb-3">
      <div className="min-w-0">
        {kicker ? <div className="label mb-1">{kicker}</div> : null}
        <h1 className="truncate font-sans text-2xl font-semibold tracking-tight">{title}</h1>
      </div>
      {children ? <div className="flex flex-wrap items-center gap-2">{children}</div> : null}
    </div>
  );
}

export function ErrorLine({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : String(error);
  return (
    <p className="my-3 border-l-2 border-signal bg-signal-wash px-3 py-2 font-mono text-[13px] text-signal">
      {message}
    </p>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="border border-dashed border-rule px-6 py-10 text-ink-2">{children}</div>;
}

export function Code({ children }: { children: ReactNode }) {
  return (
    <code className="block overflow-x-auto whitespace-pre bg-paper-2 px-3 py-2 font-mono text-[12.5px] text-ink">
      {children}
    </code>
  );
}

export function Th({ children, className }: { children?: ReactNode; className?: string }) {
  return <th className={cx("label border-b border-ink px-3 pb-2 text-left font-normal", className)}>{children}</th>;
}

export function Td({ children, className, title }: { children?: ReactNode; className?: string; title?: string }) {
  return (
    <td title={title} className={cx("border-b border-rule px-3 py-2.5 align-top", className)}>
      {children}
    </td>
  );
}

export function Kv({ k, children }: { k: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[9rem_1fr] gap-3 border-b border-rule py-2 text-sm">
      <dt className="label pt-0.5">{k}</dt>
      <dd className="min-w-0 break-words font-mono text-[13px]">{children}</dd>
    </div>
  );
}
