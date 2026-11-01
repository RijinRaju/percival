// Shapes of what the server returns. Kept by hand, it's a small API.

export type Me = { username: string; kind: "user" | "token"; csrf_token: string | null; scopes: string[] };

export type CronSpec = {
  type: "crontab";
  minute: string;
  hour: string;
  day_of_week: string;
  day_of_month: string;
  month_of_year: string;
};
export type IntervalSpec = { type: "interval"; every: number };
export type OnceSpec = { type: "once"; at: string };
export type ScheduleSpec = CronSpec | IntervalSpec | OnceSpec;

export type RunStatus =
  | "running"
  | "success"
  | "failure"
  | "retry"
  | "revoked"
  | "skipped_duplicate"
  | "blocked_stale_worker"
  | "dedupe_unavailable";

export type Schedule = {
  name: string;
  task: string;
  schedule: ScheduleSpec | { type: string; [k: string]: unknown };
  human: string;
  timezone: string | null;
  args: unknown[];
  kwargs: Record<string, unknown>;
  queue: string | null;
  priority: number | null;
  expires: number | null;
  required_version: string | null;
  origin: string | null;
  enabled: boolean;
  last_run_at: string | null;
  total_run_count: number | null;
  next_runs: string[];
  notes?: string;
  updated_at?: string | null;
  updated_by?: string | null;
  last_run?: { id: number; status: RunStatus; ts: string; worker: string | null } | null;
  coverage?: { queue: string; consumers: number; matching: number; stale: number };
  applied?: boolean | null;
  warnings?: string[];
};

export type Run = {
  id: number;
  task_id: string | null;
  task: string;
  schedule: string | null;
  status: RunStatus;
  worker: string | null;
  code_version: string | null;
  required_version: string | null;
  queue: string | null;
  args: unknown[] | null;
  kwargs: Record<string, unknown> | null;
  started_at: string | null;
  finished_at: string | null;
  duration: number | null;
  exc_type: string | null;
  exc_message: string | null;
  retries: number | null;
  ts: string;
};

export type RunDetail = Run & {
  traceback: string | null;
  extra: Record<string, unknown> | null;
  attempts: Run[];
};

export type Page<T> = { items: T[]; next_before_id: number | null };

export type Worker = {
  hostname: string;
  code_version: string | null;
  queues: string[];
  pid: number | null;
  started_at: string | null;
  last_seen: string | null;
  alive: boolean;
  client_version?: string;
};

export type VersionSummary = {
  current: string | null;
  mismatch: boolean;
  versions: { version: string; count: number; workers: string[]; stale: boolean }[];
};

export type Status = {
  beat: {
    hostname: string;
    last_tick: string | null;
    started_at: string | null;
    max_interval: number;
    scheduler: string;
  } | null;
  lock: { key: string; ttl: number | null } | null;
  workers_alive: number;
  versions: VersionSummary;
  affected_schedules: { name: string; queue: string; required_version: string | null; protected: boolean }[];
  runs_24h: Partial<Record<RunStatus, number>>;
};

export type TaskRow = {
  name: string;
  module: string | null;
  signature: string | null;
  doc: string;
  workers: string[];
  versions: string[];
  schedules: number;
  last_run: { status: RunStatus; ts: string } | null;
};

export type TaskDetail = {
  name: string;
  meta: {
    module?: string;
    signature?: string;
    doc?: string;
    source?: string;
    code_version?: string;
    hostname?: string;
    published_at?: string;
    queue?: string | null;
  } | null;
  workers: { hostname: string; code_version: string | null }[];
  schedules: string[];
  recent_runs: Run[];
};

export type AuditEntry = {
  id: number;
  ts: string;
  actor: string;
  actor_type: string;
  source: "ui" | "api" | "mcp";
  action: string;
  target: string | null;
  before: unknown;
  after: unknown;
};

export type User = { id: number; username: string; created_at: string; last_login_at: string | null };

export type Token = {
  id: number;
  name: string;
  prefix: string;
  scopes: string[];
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
  token?: string;
};

export type ConnectionSettings = {
  broker_url: string;
  redis_url: string;
  redbeat_key_prefix: string;
  key_prefix: string;
  retention_days: number;
};
