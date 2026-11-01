// Times are shown in the viewer's local zone, with the zone named, because
// "09:00" on its own is exactly the kind of ambiguity that bit us.

const localZone = Intl.DateTimeFormat().resolvedOptions().timeZone;

export function zoneLabel(): string {
  return localZone;
}

export function clock(iso: string | null | undefined, opts: { seconds?: boolean } = {}): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: opts.seconds ? "2-digit" : undefined,
    hour12: false,
  });
}

export function day(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const today = new Date();
  const tomorrow = new Date(today);
  tomorrow.setDate(today.getDate() + 1);
  if (d.toDateString() === today.toDateString()) return "today";
  if (d.toDateString() === tomorrow.toDateString()) return "tomorrow";
  return d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
}

export function stamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

export function relative(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "never";
  const diff = Math.round((new Date(iso).getTime() - now) / 1000);
  const abs = Math.abs(diff);
  let text: string;
  if (abs < 5) return "now";
  if (abs < 60) text = `${abs}s`;
  else if (abs < 3600) text = `${Math.round(abs / 60)}m`;
  else if (abs < 86400) text = `${Math.floor(abs / 3600)}h ${Math.round((abs % 3600) / 60)}m`;
  else text = `${Math.round(abs / 86400)}d`;
  return diff > 0 ? `in ${text}` : `${text} ago`;
}

export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  return `${m}m ${Math.round(seconds % 60)}s`;
}

export function every(seconds: number): string {
  const units: [string, number][] = [
    ["d", 86400],
    ["h", 3600],
    ["m", 60],
  ];
  for (const [unit, size] of units) {
    if (seconds >= size && seconds % size === 0) return `${seconds / size}${unit}`;
  }
  return `${seconds}s`;
}

export function short(version: string | null | undefined): string {
  if (!version) return "—";
  // git shas are long, the first 7 are what people recognise
  return /^[0-9a-f]{12,}$/i.test(version) ? version.slice(0, 7) : version;
}

export function json(value: unknown): string {
  return JSON.stringify(value);
}
