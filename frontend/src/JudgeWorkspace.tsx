import { useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  AiReviewResult,
  Assignment,
  Evaluation,
  JudgeEventInfo,
  JudgeOverview,
  RubricCriterion,
  Runbook,
} from "./api";

type Filter = "all" | "pending" | "evaluated" | "ai";

interface ReviewCard {
  key: string;
  result: AiReviewResult;
  persisted: boolean;
}

function slugify(title: string): string {
  return title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

function errorText(err: unknown): string {
  const msg = err instanceof Error ? err.message : String(err);
  return msg.startsWith("Not authorized") ? "Not linked to this event — enter its code at login." : msg;
}

function strengthsOf(f: AiReviewResult["result"]["findings"]): string[] {
  const good: string[] = [];
  if (f.files_scanned > 0) good.push(`Scanned ${f.files_scanned} source files`);
  if (f.summary.security === 0) good.push("No security red-flag patterns (secrets, injection, TLS)");
  if (f.summary.errors === 0) good.push("No error patterns (bare excepts, TODO density, mega-functions)");
  const has = (needle: string) => !f.improvements.some((i) => i.file.toLowerCase().includes(needle));
  if (has("readme")) good.push("README present");
  if (has("license")) good.push("License file present");
  if (has("test")) good.push("Tests or CI detected");
  return good;
}

function ScoreCard({ scores }: { scores: { criterion: string; suggested: number; max: number; reason: string }[] }) {
  const [open, setOpen] = useState(false);
  if (scores.length === 0) return null;
  return (
    <div style={{ marginTop: "0.8rem" }}>
      <h2 style={{ marginTop: 0 }}>Suggested scores (advisory)</h2>
      <table>
        <thead>
          <tr>
            <th>Criterion</th>
            <th>AI suggests</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {scores.map((s) => (
            <tr key={s.criterion}>
              <td>{s.criterion}</td>
              <td><strong>{s.suggested}</strong> / {s.max}</td>
              <td>
                <button type="button" className="ghost" onClick={() => setOpen((v) => !v)}>
                  {open ? "Hide why" : "Why?"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {open && (
        <div className="detail" style={{ marginTop: "0.8rem" }}>
          {scores.map((s) => (
            <p key={s.criterion} style={{ margin: "0.4rem 0" }}>
              <strong>{s.criterion} — {s.suggested}/{s.max}:</strong> {s.reason}
            </p>
          ))}
          <p style={{ margin: "0.4rem 0", color: "var(--emerald)" }}>
            The AI's suggestions and reasoning — enter your own marks below; the AI never decides them.
          </p>
        </div>
      )}
    </div>
  );
}

function RunbookCard({ ext }: { ext: string }) {
  const [rb, setRb] = useState<Runbook | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [showReadme, setShowReadme] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);

  const load = () => {
    setBusy(true);
    setErr(null);
    api.repoRunbook(ext)
      .then(setRb)
      .catch((e) => setErr(errorText(e)))
      .finally(() => setBusy(false));
  };

  const copy = (text: string) => {
    navigator.clipboard?.writeText(text).then(
      () => {
        setCopied(text);
        setTimeout(() => setCopied(null), 1500);
      },
      () => undefined,
    );
  };

  if (!rb) {
    return (
      <div style={{ marginTop: "0.8rem" }}>
        <button type="button" className="ghost" onClick={load} disabled={busy}>
          {busy ? "Loading…" : "▶ How to run this repo"}
        </button>
        {err && <p className="error" style={{ marginTop: "0.5rem" }}>{err}</p>}
      </div>
    );
  }

  return (
    <div style={{ marginTop: "0.8rem" }}>
      <h2 style={{ marginTop: 0 }}>Run it locally</h2>
      {!rb.found ? (
        <p className="meta">{rb.note}</p>
      ) : (
        <>
          <p className="meta">
            Checkout: <code>{rb.checkout}</code>
            {rb.repo_url && (
              <> · <a href={rb.repo_url}>{rb.repo_url}</a></>
            )}
          </p>
          {rb.launch && (
            <p className="meta">
              Open a terminal inside it with: {" "}
              <code>{rb.launch}</code>{" "}
              <button type="button" className="ghost" onClick={() => copy(rb.launch!)}>
                {copied === rb.launch ? "Copied ✓" : "Copy"}
              </button>{" "}
              <a className="ghost" href={`/api/judge/repos/${ext}/terminal-script`}>
                ⬇ run-{rb.checkout}.bat (double-click to open)
              </a>
            </p>
          )}
          {(rb.commands?.length ?? 0) > 0 && (
            <>
              <strong className="meta">Detected run commands</strong>
              <table>
                <tbody>
                  {rb.commands!.map((c) => (
                    <tr key={c.command}>
                      <td>{c.label}</td>
                      <td><code>{c.command}</code></td>
                      <td>
                        <button type="button" className="ghost" onClick={() => copy(c.command)}>
                          {copied === c.command ? "Copied ✓" : "Copy"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          {rb.readme && (
            <p>
              <button type="button" className="ghost" onClick={() => setShowReadme((v) => !v)}>
                {showReadme ? "Hide README" : `📄 Show README (${rb.readme.name})`}
              </button>
            </p>
          )}
          {showReadme && rb.readme && (
            <pre className="detail" style={{
              whiteSpace: "pre-wrap", maxWidth: 860, maxHeight: 420, overflow: "auto",
              background: "var(--panel)", border: "1px solid var(--line)",
              borderRadius: 6, padding: "0.8rem 1rem",
            }}>{rb.readme.text}</pre>
          )}
          <p className="meta">The commands are suggestions from the repo's own manifests — run them in your own terminal at your own discretion.</p>
        </>
      )}
    </div>
  );
}

function FindingsCard({ card }: { card: ReviewCard }) {
  const f = card.result.result.findings;
  const llm = card.result.result.llm;
  const mode = card.result.result.mode;
  const [showAll, setShowAll] = useState(false);
  const strengths = llm ? llm.best_parts : strengthsOf(f);
  const totalRows = llm
    ? llm.loopholes.length + llm.errors.length + llm.suggestions.length
    : f.security.length + f.errors.length + f.improvements.length;
  const sections: { label: string; rows: { file: string; note: string }[]; cls: string }[] = llm
    ? [
        { label: "Security loopholes", rows: llm.loopholes, cls: "error" },
        { label: "Code errors", rows: llm.errors, cls: "error" },
        { label: "Suggestions", rows: llm.suggestions, cls: "meta" },
      ]
    : [
        { label: "Security loopholes", rows: f.security, cls: "error" },
        { label: "Code errors", rows: f.errors, cls: "error" },
        { label: "Improvements", rows: f.improvements, cls: "meta" },
      ];
  const visibleRows = showAll ? 9999 : 2;
  return (
    <article className="card">
      <h3>
        {card.result.title}{" "}
        <span className="tag">{card.persisted ? "saved to your workspace" : "preview only"}</span>
      </h3>
      <p className="meta">
        {card.result.repo_url} · {card.result.result.source} · {f.files_scanned} file(s) scanned
        {mode === "groq" && " · AI judgment via Groq (advisory)"}
      </p>

      {llm && (
        <>
          <h2 style={{ marginTop: "1rem" }}>AI judgment</h2>
          <p className="summary">{llm.summary}</p>
          <ScoreCard scores={llm.scores ?? []} />
        </>
      )}

      <h2 style={{ marginTop: "1rem" }}>How the AI evaluated it</h2>
      <div className="stats">
        <div className="card stat">
          <p className="stat-label">Security loopholes</p>
          <p className="stat-value" style={f.summary.security > 0 ? { color: "var(--crimson)" } : {}}>
            {f.summary.security}
          </p>
        </div>
        <div className="card stat">
          <p className="stat-label">Code errors</p>
          <p className="stat-value" style={f.summary.errors > 0 ? { color: "var(--crimson)" } : {}}>
            {f.summary.errors}
          </p>
        </div>
        <div className="card stat">
          <p className="stat-label">Improvements</p>
          <p className="stat-value">{f.summary.improvements}</p>
        </div>
      </div>

      {strengths.length > 0 && (
        <>
          <strong className="meta">Best parts</strong>
          <ul className="meta">
            {strengths.map((s) => (
              <li key={s}>✓ {s}</li>
            ))}
          </ul>
        </>
      )}
      {sections.map(
        (s) =>
          s.rows.length > 0 && (
            <div key={s.label}>
              <strong className="meta">{s.label} ({s.rows.length})</strong>
              <ul className="meta">
                {s.rows.slice(0, visibleRows).map((row, i) => (
                  <li key={`${s.label}-${i}`}>
                    <code>{row.file}</code> — {row.note}
                  </li>
                ))}
              </ul>
            </div>
          ),
      )}
      {totalRows > 6 && (
        <p>
          <button type="button" className="ghost" onClick={() => setShowAll((v) => !v)}>
            {showAll ? "Show less" : `Show all ${totalRows} findings`}
          </button>
        </p>
      )}
      {f.files_scanned === 0 && (
        <p className="meta">
          {f.improvements.some((i) => i.note.includes("auto-clone"))
            ? "Couldn't fetch this repository automatically (git or network unavailable) — place a checkout under repos/ and re-run."
            : "Offline tip: no source files were found for this link — place a checkout under repos/ and re-run to scan real code."}
        </p>
      )}
      <p className="meta">Advisory only — the AI never assigns marks; your scoring stays human.</p>
    </article>
  );
}

export default function JudgeWorkspace() {
  const [overview, setOverview] = useState<JudgeOverview | null>(null);
  const [event, setEvent] = useState<JudgeEventInfo | null>(null);
  const [rubric, setRubric] = useState<RubricCriterion[]>([]);
  const [myScores, setMyScores] = useState<Evaluation[]>([]);
  const [assignments, setAssignments] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState<Filter>("all");

  // AI review state, keyed by project external_id:
  // undefined = not loaded yet, null = none stored for this judge.
  const [aiMap, setAiMap] = useState<Record<string, AiReviewResult | null | undefined>>({});
  const aiLoading = useRef<Set<string>>(new Set());
  const [aiBusyFor, setAiBusyFor] = useState<string | null>(null);
  const [aiError, setAiError] = useState<string | null>(null);

  // Opened project panel (open & evaluate / re-evaluate).
  const [openId, setOpenId] = useState<string | null>(null);
  const [scores, setScores] = useState<Record<string, number>>({});
  const [comment, setComment] = useState("");
  const [submitMsg, setSubmitMsg] = useState<string | null>(null);
  const [submitErr, setSubmitErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Add a repo by GitHub link.
  const [showAddRepo, setShowAddRepo] = useState(false);
  const [repoUrl, setRepoUrl] = useState("");
  const [addBusy, setAddBusy] = useState(false);
  const [addMsg, setAddMsg] = useState<string | null>(null);
  const [addErr, setAddErr] = useState<string | null>(null);

  const addRepo = (e: React.FormEvent) => {
    e.preventDefault();
    setAddBusy(true);
    setAddMsg(null);
    setAddErr(null);
    api.addRepo(repoUrl.trim())
      .then((res) => {
        setAddMsg(
          res.clone_state === "cloned"
            ? `"${res.title}" added and cloned — it is now in your list below.`
            : res.clone_state === "already-present"
            ? `"${res.title}" is already in your list (reusing the existing checkout).`
            : `"${res.title}" added, but the clone failed: ${res.clone_note || "unknown error"}. AI review will use the link only.`,
        );
        setRepoUrl("");
        refresh();
      })
      .catch((err) => setAddErr(errorText(err)))
      .finally(() => setAddBusy(false));
  };

  const refresh = () => {
    api.judgeOverview().then(setOverview).catch(() => setOverview(null));
    api.judgeScores().then(setMyScores).catch(() => setMyScores([]));
  };

  useEffect(() => {
    refresh();
    api.judgeEvent().then(setEvent).catch(() => setEvent(null));
    api.judgeRubric().then((r) => setRubric(r.criteria)).catch(() => setRubric([]));
    api.judgeAssignments()
      .then((rows: Assignment[]) => setAssignments(new Set(rows.map((a) => a.project))))
      .catch(() => setAssignments(new Set()));
  }, []);

  const projects = overview?.projects ?? [];
  const pending = useMemo(() => projects.filter((p) => !p.evaluated), [projects]);
  const evaluatedRows = useMemo(() => projects.filter((p) => p.evaluated), [projects]);
  const aiRows = useMemo(() => projects.filter((p) => p.has_ai_review), [projects]);
  const chosen = openId === null ? null : projects.find((p) => p.external_id === openId) ?? null;
  const locked = event !== null && event.via === "event";

  // Load stored AI reviews lazily; rows without one resolve to null so cards
  // render their "AI evaluate" action instead of "Checking…" forever.
  useEffect(() => {
    for (const p of projects) {
      if (aiLoading.current.has(p.external_id)) continue;
      aiLoading.current.add(p.external_id);
      if (!p.has_ai_review) {
        setAiMap((m) => ({ ...m, [p.external_id]: null }));
        continue;
      }
      api.getAiReview(p.external_id)
        .then((r) => setAiMap((m) => ({ ...m, [p.external_id]: r })))
        .catch(() => setAiMap((m) => ({ ...m, [p.external_id]: null })));
    }
  }, [projects]);

  const runAi = (ext: string) => {
    setAiBusyFor(ext);
    setAiError(null);
    api.runAiReview([ext])
      .then(() => api.getAiReview(ext))
      .then((r) => setAiMap((m) => ({ ...m, [ext]: r })))
      .then(refresh)
      .catch((err) => setAiError(errorText(err)))
      .finally(() => setAiBusyFor(null));
  };

  const runAiOnAllPending = () => {
    if (pending.length === 0) return;
    setAiBusyFor("__all__");
    setAiError(null);
    api.runAiReview(pending.map((p) => p.external_id))
      .then(() => Promise.all(pending.map((p) => api.getAiReview(p.external_id).catch(() => null))))
      .then((results) => {
        setAiMap((m) => {
          const next = { ...m };
          pending.forEach((p, i) => { next[p.external_id] = results[i]; });
          return next;
        });
      })
      .then(refresh)
      .catch((err) => setAiError(errorText(err)))
      .finally(() => setAiBusyFor(null));
  };

  const openProject = (ext: string) => {
    setOpenId(ext);
    setSubmitMsg(null);
    setSubmitErr(null);
    const ev = myScores.find((e) => e.project === ext);
    setScores(ev
      ? Object.fromEntries(ev.scores.map((s) => [s.criterion, s.score]))
      : Object.fromEntries(rubric.map((c) => [c.name, 0])));
    setComment(ev?.comment ?? "");
  };

  const submitEvaluation = (e: React.FormEvent) => {
    e.preventDefault();
    if (!chosen) return;
    setBusy(true);
    setSubmitMsg(null);
    setSubmitErr(null);
    api.submitEvaluation(chosen.external_id, scores, comment)
      .then((res: unknown) => {
        const revised = (res as { revised?: boolean }).revised === true;
        setSubmitMsg(revised
          ? "Re-evaluation saved — your previous marks for this project were replaced."
          : "Marks saved under your account. Other judges never see them — only the organizer's final result includes them.");
        refresh();
      })
      .catch((err) => setSubmitErr(errorText(err)))
      .finally(() => setBusy(false));
  };

  // AI suggested scores for the opened project, matched to the event rubric
  // by name (case-insensitive). Applying fills the form as a starting point;
  // the judge edits and saves their own marks — the AI never submits.
  const aiSuggestions = (chosen && aiMap[chosen.external_id]?.result.llm?.scores) || [];
  const applyAiSuggestions = () => {
    if (!chosen) return;
    const byName = new Map(aiSuggestions.map((s) => [s.criterion.toLowerCase(), s]));
    setScores((prev) => {
      const next = { ...prev };
      for (const c of rubric) {
        const hit = byName.get(c.name.toLowerCase());
        if (hit) next[c.name] = Math.max(0, Math.min(hit.suggested, c.max_score));
      }
      return next;
    });
    setSubmitMsg("AI suggestions filled in — review and edit them, then save your own marks.");
  };

  // Comparison context: how this project's AI findings stack up against the
  // other repos this judge has AI-reviewed (advisory, never marks).
  const aiComparison = useMemo(() => {
    if (!chosen) return null;
    const rows = projects
      .map((p) => {
        const ai = aiMap[p.external_id];
        if (!ai || !ai.result) return null;
        return { ext: p.external_id, title: p.title, total: ai.result.findings.summary.security + ai.result.findings.summary.errors };
      })
      .filter((r): r is { ext: string; title: string; total: number } => r !== null);
    if (rows.length < 2) return null;
    const mine = rows.find((r) => r.ext === chosen.external_id);
    if (!mine) return null;
    const betterThan = rows.filter((r) => r.total > mine.total).length;
    const cleanest = [...rows].sort((a, b) => a.total - b.total)[0];
    return { reviewedCount: rows.length, betterThan, cleanest };
  }, [chosen, projects, aiMap]);

  if (!overview) return <p className="meta">Loading dashboard…</p>;

  const showPending = filter === "all" || filter === "pending";
  const showEvaluated = filter === "all" || filter === "evaluated";
  const showAllTable = filter === "all";

  const FILTERS: { key: Filter; label: string; count: number; hint: string }[] = [
    { key: "all", label: "All projects", count: overview.totals.projects, hint: "everything in the event" },
    { key: "pending", label: "Pending", count: overview.totals.pending, hint: "not judged yet" },
    { key: "evaluated", label: "Already judged", count: overview.totals.evaluated, hint: "completed" },
    { key: "ai", label: "AI reviewed", count: overview.totals.ai_reviewed, hint: "have AI findings" },
  ];

  const aiSummaryLine = (ext: string) => {
    const ai = aiMap[ext];
    if (ai === undefined) return "Checking for a saved AI review…";
    if (ai === null) return "No AI review yet.";
    return `AI: ${ai.result.findings.summary.security} security · ${ai.result.findings.summary.errors} errors · ${ai.result.findings.summary.improvements} improvements`;
  };

  return (
    <section>
      <h1>Evaluator dashboard</h1>
      <p className="meta">
        Signed in as <strong>{overview.judge.name}</strong> ({overview.judge.email})
        {overview.event && (
          <> · evaluating <strong>{overview.event.name}</strong> (code {overview.event.code})</>
        )}
        {locked && <> — <span className="error">read-only: enter this event's code at login to score.</span></>}
      </p>

      <div className="stats">
        {FILTERS.map(({ key, label, count, hint }) => (
          <button key={key} type="button"
                  className={`card stat stat-btn ${filter === key ? "active" : ""}`}
                  aria-pressed={filter === key}
                  onClick={() => setFilter(key)}>
            <p className="stat-label">{label}</p>
            <p className="stat-value"
               style={key === "pending" && count > 0 ? { color: "var(--crimson)" } : {}}>
              {count}
            </p>
            <p className="meta">{filter === key ? `▼ showing ${hint}` : hint}</p>
          </button>
        ))}
      </div>

      {showPending && (
        <>
          <h2>Pending repositories — not judged yet ({pending.length})</h2>
          <p className="meta">
            <button type="button" className="ghost" onClick={() => setShowAddRepo((v) => !v)}>
              {showAddRepo ? "Cancel" : "+ Add repo by GitHub link"}
            </button>
          </p>
          {showAddRepo && (
            <form onSubmit={addRepo} className="login-form" style={{ maxWidth: 640 }}>
              <label>
                GitHub repository link
                <input
                  value={repoUrl}
                  onChange={(e) => setRepoUrl(e.target.value)}
                  placeholder="https://github.com/owner/repo"
                  required
                  maxLength={512}
                />
              </label>
              {addMsg && <p className="summary">{addMsg}</p>}
              {addErr && <p className="error">{addErr}</p>}
              <button type="submit" disabled={addBusy}>
                {addBusy ? "Cloning…" : "Add repo"}
              </button>
            </form>
          )}
          {pending.length === 0 ? (
            <p className="meta">Nothing pending — you have evaluated every project. 🎉</p>
          ) : (
            <>
              <p className="meta">
                <button type="button" onClick={runAiOnAllPending} disabled={aiBusyFor !== null || locked}>
                  {aiBusyFor === "__all__" ? "AI is evaluating…" : `AI-evaluate all ${pending.length} pending`}
                </button>{" "}
                <span className="meta">(runs the offline analyzer on every pending repo; scanning is local — no internet needed)</span>
              </p>
              <div className="grid">
                {pending.map((p) => (
                  <article key={p.external_id} className="card">
                    <h3>{p.title}</h3>
                    <p className="summary">{p.summary}</p>
                    <p className="meta">
                      <span className="tag">{p.track}</span> · team {p.team}
                      {assignments.has(p.external_id) && " · assigned to you"}
                    </p>
                    <p className="meta">{aiSummaryLine(p.external_id)}</p>
                    <p>
                      <button type="button" disabled={aiBusyFor !== null || locked}
                              onClick={() => runAi(p.external_id)}>
                        {aiBusyFor === p.external_id ? "AI evaluating…" : "AI evaluate"}
                      </button>{" "}
                      <button type="button" className="ghost" onClick={() => openProject(p.external_id)}>
                        Open &amp; evaluate
                      </button>
                    </p>
                  </article>
                ))}
              </div>
            </>
          )}
        </>
      )}
      {aiError && <p className="error">{aiError}</p>}

      {filter === "ai" && (
        <>
          <h2>AI-reviewed repositories ({aiRows.length})</h2>
          {aiRows.length === 0 ? (
            <p className="meta">Nothing AI-reviewed yet — run the analyzer from the Pending list.</p>
          ) : (
            <div className="grid">
              {aiRows.map((p) => (
                <article key={p.external_id} className="card">
                  <h3>{p.title}</h3>
                  <p className="summary">{p.summary}</p>
                  <p className="meta">
                    <span className="tag">{p.track}</span> · team {p.team} ·{" "}
                    {p.evaluated ? "judged ✓" : "pending"}
                  </p>
                  <p className="meta">{aiSummaryLine(p.external_id)}</p>
                  <p>
                    <button type="button" disabled={aiBusyFor !== null || locked}
                            onClick={() => runAi(p.external_id)}>
                      {aiBusyFor === p.external_id ? "Re-running…" : "Re-run AI evaluation"}
                    </button>{" "}
                    <button type="button" className="ghost" onClick={() => openProject(p.external_id)}>
                      Open full result
                    </button>
                  </p>
                </article>
              ))}
            </div>
          )}
        </>
      )}

      {showEvaluated && (
        <>
          <h2>Your evaluated projects ({evaluatedRows.length})</h2>
          {evaluatedRows.length === 0 ? (
            <p className="meta">Nothing evaluated yet — open a pending repository to judge it.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Project</th>
                  <th>Your marks</th>
                  <th>Your rank</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {evaluatedRows.map((p) => (
                  <tr key={p.external_id}>
                    <td>{p.title}</td>
                    <td>{p.my_weighted !== null ? `${p.my_weighted}%` : "—"}</td>
                    <td>{p.my_rank !== null ? `#${p.my_rank} of ${p.ranked_count}` : "—"}</td>
                    <td>
                      <button type="button" className="ghost" onClick={() => openProject(p.external_id)}>
                        Open &amp; re-evaluate
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}

      {chosen && (
        <article className="card" style={{ marginTop: "1.5rem" }}>
          <h3>
            {chosen.title} <span className="meta">({chosen.external_id})</span>
            {" "}<button type="button" className="ghost" onClick={() => setOpenId(null)}>Close</button>
          </h3>
          <p className="summary">{chosen.summary}</p>
          <p className="meta">
            Track {chosen.track} · team {chosen.team}
            {chosen.repo_url && (
              <> · repo: <a href={chosen.repo_url}>{chosen.repo_url}</a></>
            )}
          </p>

          <h2 style={{ marginTop: "1.2rem" }}>AI evaluation</h2>
          {aiMap[chosen.external_id] === undefined && <p className="meta">Checking for a saved review…</p>}
          {aiMap[chosen.external_id] === null && (
            <p className="meta">
              No AI review yet.{" "}
              <button type="button" className="ghost" disabled={aiBusyFor !== null || locked}
                      onClick={() => runAi(chosen.external_id)}>
                {aiBusyFor === chosen.external_id ? "Running…" : "Run AI evaluation"}
              </button>
            </p>
          )}
          {aiMap[chosen.external_id] != null && (
            <>
              <FindingsCard card={{ key: chosen.external_id, result: aiMap[chosen.external_id]!, persisted: true }} />
              {aiComparison && (
                <p className="meta">
                  Across the {aiComparison.reviewedCount} repos you have AI-reviewed, this one has
                  fewer red flags than {aiComparison.betterThan} of them
                  {aiComparison.cleanest.ext !== chosen.external_id
                    ? `; cleanest so far: ${aiComparison.cleanest.title}.`
                    : " — it is the cleanest so far."}
                </p>
              )}
              <p className="meta">
                <button type="button" className="ghost" disabled={aiBusyFor !== null || locked}
                        onClick={() => runAi(chosen.external_id)}>
                  {aiBusyFor === chosen.external_id ? "Re-running…" : "Re-run AI evaluation"}
                </button>
              </p>
            </>
          )}

          {chosen.repo_url && (
            <RunbookCard ext={chosen.external_id} />
          )}

          <h2 style={{ marginTop: "1.2rem" }}>
            {chosen.evaluated ? "Re-evaluate (replaces your previous marks)" : "Your marks"}
            {aiSuggestions.length > 0 && (
              <button type="button" className="ghost" style={{ marginLeft: "0.75rem" }}
                      title="Fills the form with the AI's suggested scores — edit freely before saving"
                      onClick={applyAiSuggestions}>
                Apply AI suggestions
              </button>
            )}
          </h2>
          {chosen.repo_url && (
            <p className="meta">
              Local checkout: <code>repos/{slugify(chosen.title)}</code> — open it in a terminal and
              follow its README to run it; no internet needed.
            </p>
          )}
          {rubric.length === 0 ? (
            <p className="meta">This event has no rubric yet.</p>
          ) : (
            <form onSubmit={submitEvaluation}>
              {rubric.map((c) => (
                <label key={c.name}>
                  {c.name} (0–{c.max_score}, weight {Math.round(c.weight * 100)}%)
                  <input
                    type="number"
                    min={0}
                    max={c.max_score}
                    value={scores[c.name] ?? 0}
                    onChange={(e) => setScores({ ...scores, [c.name]: Number(e.target.value) })}
                    required
                  />
                </label>
              ))}
              <label>
                Comment
                <textarea
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  rows={3}
                  style={{ width: "100%", background: "var(--panel)",
                           border: "1px solid var(--line)", color: "var(--text)",
                           borderRadius: 6, padding: "0.55rem 0.8rem", font: "inherit" }}
                />
              </label>
              {submitMsg && <p className="summary">{submitMsg}</p>}
              {submitErr && <p className="error">{submitErr}</p>}
              <button type="submit" disabled={busy || locked}>
                {busy ? "Saving…" : chosen.evaluated ? "Save re-evaluation" : "Save my marks"}
              </button>
            </form>
          )}
        </article>
      )}

      {showAllTable && (
        <>
          <h2>All projects in this event</h2>
          <table>
            <thead>
              <tr>
                <th>Project</th>
                <th>Track</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {projects.map((p) => (
                <tr key={p.external_id}>
                  <td>{p.title}</td>
                  <td>{p.track}</td>
                  <td>
                    {p.evaluated ? "Evaluated ✓" : "Pending"}
                    {p.has_ai_review && " · AI reviewed"}
                  </td>
                  <td>
                    <button type="button" className="ghost" onClick={() => openProject(p.external_id)}>
                      Open
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}
