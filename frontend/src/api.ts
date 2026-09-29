const API = "/api";

export interface Me {
  email: string;
  name: string;
  role: string;
  event?: { name: string; code: string } | null;
}

export interface Project {
  external_id: string;
  title: string;
  summary: string;
  repo_url: string | null;
  track: string;
  team: string;
  submitted_at: string | null;
}

export interface Evaluation {
  project: string;
  project_title: string;
  comment: string;
  submitted_at: string;
  scores: { criterion: string; weight: number; max_score: number; score: number }[];
}

export interface Assignment {
  project: string;
  project_title: string;
  track: string;
  completed: boolean;
}

export interface RunInfo {
  id: number;
  method: string;
  params: string;
  created_at: string;
  project_count: number;
  evaluation_count: number;
}

export interface RankedRow {
  rank: number;
  project: string;
  title: string;
  track: string;
  team: string;
  final_score: number;
  raw_weighted: number;
  judge_count: number;
  coverage_ok: boolean;
}

export interface TrustFlag {
  id: number;
  detector: string;
  severity: string;
  subject_type: string;
  subject_id: number | null;
  title: string;
  detail: string;
  status: string;
  created_at: string;
  resolved_at: string | null;
}

export interface MissionControl {
  event: { name: string | null; submissions_close: string | null; closed: boolean };
  participation: { participants: number; teams: number; projects: number; submitted: number };
  judging: { judges: number; assigned: number; completed: number; pending: number; completion_percent: number };
  workload: { judge: string; email: string; assigned: number; completed: number; pending: number }[];
  coverage_gaps: { project: string; reviews: number; modal: number }[];
  trust: { by_status: Record<string, number>; open_by_detector: Record<string, number> };
  runs: { id: number; method: string; created_at: string; project_count: number; evaluation_count: number }[];
  leader: { project: string; title: string; final_score: number } | null;
}

export interface EventRow {
  id: number;
  code: string | null;
  name: string;
  description: string;
  judge_count: number;
  submissions_open: string | null;
  submissions_close: string;
  judging_close: string | null;
  registration_open: string | null;
  registration_close: string | null;
  is_open: boolean;
  tracks: string[];
  project_count?: number;
  share_link?: string;
  message?: string;
  ai_configured?: boolean;
}

export interface AiReviewResult {
  project: string;
  title: string;
  repo_url: string | null;
  result: {
    source: string;
    advisory: boolean;
    mode?: "static" | "groq";
    model?: string;
    findings: {
      files_scanned: number;
      security: { file: string; note: string }[];
      errors: { file: string; note: string }[];
      improvements: { file: string; note: string }[];
      summary: { security: number; errors: number; improvements: number };
    };
    llm?: {
      summary: string;
      best_parts: string[];
      errors: { file: string; note: string }[];
      loopholes: { file: string; note: string }[];
      suggestions: { file: string; note: string }[];
      scores: { criterion: string; suggested: number; max: number; reason: string }[];
    } | null;
  };
}

export interface JudgeProject {
  external_id: string;
  title: string;
  summary: string;
  repo_url: string | null;
  track: string;
  team: string;
  submitted_at: string | null;
}

export interface JudgeOverviewRow {
  external_id: string;
  title: string;
  summary: string;
  repo_url: string | null;
  track: string;
  team: string;
  submitted_at: string | null;
  evaluated: boolean;
  has_ai_review: boolean;
  my_weighted: number | null;
  my_rank: number | null;
  ranked_count: number;
}

export interface JudgeOverview {
  judge: { name: string; email: string };
  event: { id: number; name: string; code: string | null } | null;
  projects: JudgeOverviewRow[];
  totals: { projects: number; evaluated: number; pending: number; ai_reviewed: number };
}

export interface JudgeEventInfo {
  event: { id: number; name: string; code: string; judge_count: number } | null;
  via?: "linked" | "event";
}

export interface RubricCriterion {
  name: string;
  weight: number;
  max_score: number;
}

export interface WhyExplanation {
  run: { id: number; method: string; params: Record<string, string>; created_at: string };
  project: { id: string; title: string };
  rank: number;
  of: number;
  final_score: number;
  raw_weighted: number;
  judge_count: number;
  coverage_ok: boolean;
  evaluations: {
    judge: string;
    raw_weighted: number;
    judge_mean: number;
    judge_sd: number;
    z_score: number;
  }[];
  neighbors: {
    above: { rank: number; title: string; final_score: number }[];
    below: { rank: number; title: string; final_score: number }[];
  };
}

export interface Runbook {
  found: boolean;
  repo_url: string | null;
  note?: string;
  checkout?: string;
  commands?: { label: string; command: string }[];
  readme?: { name: string; text: string } | null;
  launch?: string | null;
}

async function json<T>(res: Response): Promise<T> {
  if (res.ok) return (await res.json()) as T;
  // Prefer the server's own explanation (FastAPI puts it in `detail`) so the
  // user sees "An account with that email already exists" or "Invalid email
  // or password" instead of a bare status code.
  let detail = "";
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (body && typeof body.detail === "string") detail = body.detail;
  } catch {
    // non-JSON error body — fall through to the generic message
  }
  if (res.status === 401 || res.status === 403) {
    throw new Error(detail || `Not authorized (${res.status})`);
  }
  if (res.status === 409) {
    throw new Error(detail || "That record already exists");
  }
  throw new Error(detail || `Request failed (${res.status})`);
}

// Wrap fetch so network-level failures (server down, container restarting,
// host asleep) surface as a clear, actionable message instead of the
// browser's raw "Failed to fetch" TypeError.
function request(url: string, init?: RequestInit): Promise<Response> {
  return fetch(url, init).catch(() => {
    throw new Error(
      "Cannot reach the ISR server — it may be starting up. Wait a few seconds and try again.",
    );
  });
}

export const api = {
  me: (): Promise<Me> => request(`${API}/auth/me`).then(json<Me>),
  login: (email: string, password: string, eventCode?: string): Promise<Me> =>
    request(`${API}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, event_code: eventCode || undefined }),
    }).then(json<Me>),
  signup: (email: string, name: string, password: string): Promise<Me> =>
    request(`${API}/auth/signup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, name, password }),
    }).then(json<Me>),
  logout: (): Promise<void> =>
    request(`${API}/auth/logout`, { method: "POST" }).then(() => undefined),
  gallery: (q?: string): Promise<Project[]> =>
    request(`${API}/gallery${q ? `?q=${encodeURIComponent(q)}` : ""}`).then(json<Project[]>),
  judgeScores: (): Promise<Evaluation[]> =>
    request(`${API}/judge/scores`).then(json<Evaluation[]>),
  judgeAssignments: (): Promise<Assignment[]> =>
    request(`${API}/judge/assignments`).then(json<Assignment[]>),
  results: (runId?: number): Promise<{ run: RunInfo | null; ranking: RankedRow[] }> =>
    request(`${API}/results${runId ? `?run_id=${runId}` : ""}`).then(json<{ run: RunInfo | null; ranking: RankedRow[] }>),
  resultsRun: (): Promise<{ run_id: number; top: { rank: number }[] }> =>
    request(`${API}/results/run`, { method: "POST" }).then(json<{ run_id: number; top: { rank: number }[] }>),
  why: (runId: number, project: string): Promise<WhyExplanation> =>
    request(`${API}/results/why/${runId}/${project}`).then(json<WhyExplanation>),
  trustScan: (): Promise<{ created: number; updated: number; open: number }> =>
    request(`${API}/trust/scan`, { method: "POST" }).then(
      json<{ created: number; updated: number; open: number }>,
    ),
  trustFlags: (status?: string): Promise<{ counts: Record<string, number>; flags: TrustFlag[] }> =>
    request(`${API}/trust/flags${status ? `?flag_status=${status}` : ""}`).then(
      json<{ counts: Record<string, number>; flags: TrustFlag[] }>,
    ),
  trustDispose: (id: number, disposition: "resolved" | "dismissed"): Promise<TrustFlag> =>
    request(`${API}/trust/flags/${id}/${disposition}`, { method: "POST" }).then(json<TrustFlag>),
  missionControl: (): Promise<MissionControl> =>
    request(`${API}/mission-control`).then(json<MissionControl>),
  myEvents: (): Promise<EventRow[]> =>
    request(`${API}/organizer/events`).then(json<EventRow[]>),
  createEvent: (payload: Record<string, unknown>): Promise<unknown> =>
    request(`${API}/organizer/events`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then(json<unknown>),
  editEvent: (id: number, payload: Record<string, unknown>): Promise<unknown> =>
    request(`${API}/organizer/events/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then(json<unknown>),
  judgeEvent: (): Promise<JudgeEventInfo> =>
    request(`${API}/judge/event`).then(json<JudgeEventInfo>),
  judgeRubric: (): Promise<{ criteria: RubricCriterion[] }> =>
    request(`${API}/judge/rubric`).then(json<{ criteria: RubricCriterion[] }>),
  judgeProjects: (): Promise<JudgeProject[]> =>
    request(`${API}/judge/projects`).then(json<JudgeProject[]>),
  judgeOverview: (): Promise<JudgeOverview> =>
    request(`${API}/judge/overview`).then(json<JudgeOverview>),
  addRepo: (repoUrl: string): Promise<{ project: string; title: string; repo_url: string; clone_state: string; clone_note: string; scan_hint: string }> =>
    request(`${API}/judge/repos/add`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ repo_url: repoUrl }),
    }).then(json<{ project: string; title: string; repo_url: string; clone_state: string; clone_note: string; scan_hint: string }>),
  runAiReview: (projects: string[]): Promise<{ reviewed: { project: string; title: string; summary: { security: number; errors: number; improvements: number }; source: string }[]; skipped: string[]; advisory: boolean }> =>
    request(`${API}/judge/ai-review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ projects }),
    }).then(json<{ reviewed: { project: string; title: string; summary: { security: number; errors: number; improvements: number }; source: string }[]; skipped: string[]; advisory: boolean }>),
  getAiReview: (project: string): Promise<AiReviewResult> =>
    request(`${API}/judge/ai-review/${project}`).then(json<AiReviewResult>),
  repoRunbook: (project: string): Promise<Runbook> =>
    request(`${API}/judge/repos/${project}/runbook`).then(json<Runbook>),
  previewRepo: (repoUrl: string): Promise<AiReviewResult> =>
    request(`${API}/judge/ai-review/preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ repo_url: repoUrl }),
    }).then(json<AiReviewResult>),
  submitEvaluation: (project: string, scores: Record<string, number>, comment: string): Promise<unknown> =>
    request(`${API}/judge/evaluate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project, scores, comment }),
    }).then(json<unknown>),
};
