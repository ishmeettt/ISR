import { useEffect, useState } from "react";
import { api, RankedRow, RunInfo, WhyExplanation } from "./api";

function Why({ runId, project, onClose }: { runId: number; project: string; onClose: () => void }) {
  const [why, setWhy] = useState<WhyExplanation | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.why(runId, project).then(setWhy).catch((e) => setError(String(e.message ?? e)));
  }, [runId, project]);

  if (error) return <p className="error">{error}</p>;
  if (!why) return <p>Loading…</p>;
  const fmt = (x: number) => x.toFixed(4);

  return (
    <section className="card why-card">
      <h3>
        Why #{why.rank} of {why.of} — {why.project.title}{" "}
        <button onClick={onClose}>close</button>
      </h3>
      <p className="summary">
        Method <code>{why.run.method}</code>: z = (raw − judge_mean) / judge_sd, final =
        mean z. Deterministic; same inputs re-derive this exactly.
      </p>
      <table>
        <thead>
          <tr>
            <th>Judge</th>
            <th>Raw composite</th>
            <th>Judge mean</th>
            <th>Judge SD</th>
            <th>z</th>
          </tr>
        </thead>
        <tbody>
          {why.evaluations.map((e, i) => (
            <tr key={i}>
              <td>{e.judge}</td>
              <td>{fmt(e.raw_weighted)}</td>
              <td>{fmt(e.judge_mean)}</td>
              <td>{fmt(e.judge_sd)}</td>
              <td>
                <strong>{fmt(e.z_score)}</strong>
              </td>
            </tr>
          ))}
          <tr>
            <td>
              <strong>Final (mean z)</strong>
            </td>
            <td colSpan={4}>
              <strong>{fmt(why.final_score)}</strong>
            </td>
          </tr>
        </tbody>
      </table>
      <p className="meta">
        Mean raw composite {fmt(why.raw_weighted)} · {why.judge_count} judge(s) · coverage{" "}
        {why.coverage_ok ? "complete" : "below modal"}
      </p>
      {(why.neighbors.above.length > 0 || why.neighbors.below.length > 0) && (
        <p className="meta">
          {why.neighbors.above.map((n) => `#${n.rank} ${n.title} (${fmt(n.final_score)})`).join(", ")}
          {why.neighbors.above.length > 0 && why.neighbors.below.length > 0 ? " — " : ""}
          {why.neighbors.below.map((n) => `#${n.rank} ${n.title} (${fmt(n.final_score)})`).join(", ")}
        </p>
      )}
    </section>
  );
}

export default function Results() {
  const [run, setRun] = useState<RunInfo | null>(null);
  const [ranking, setRanking] = useState<RankedRow[]>([]);
  const [why, setWhy] = useState<{ runId: number; project: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = (runId?: number) =>
    api.results(runId).then((r) => {
      setRun(r.run);
      setRanking(r.ranking);
    }).catch((e) => setError(String(e.message ?? e)));

  useEffect(() => {
    load();
  }, []);

  const recompute = () => {
    setBusy(true);
    api.resultsRun()
      .then(() => load())
      .catch((e) => setError(String(e.message ?? e)))
      .finally(() => setBusy(false));
  };

  return (
    <section>
      <h1>Results — FairScore</h1>
      {run && (
        <p className="meta">
          Run #{run.id} · {run.method} · {run.project_count} projects · {run.evaluation_count}{" "}
          evaluations · {new Date(run.created_at).toLocaleString()}
        </p>
      )}
      <button onClick={recompute} disabled={busy}>
        {busy ? "Computing…" : "Recompute ranking"}
      </button>
      {error && <p className="error">{error}</p>}
      {ranking.length === 0 ? (
        <p>No results yet — compute a run.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Rank</th>
              <th>Project</th>
              <th>Track</th>
              <th>Final (mean z)</th>
              <th>Raw</th>
              <th>Judges</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {ranking.map((r) => (
              <tr key={r.project}>
                <td>#{r.rank}</td>
                <td>
                  {r.title} <span className="meta">({r.team})</span>
                </td>
                <td>{r.track}</td>
                <td>
                  <strong>{r.final_score.toFixed(4)}</strong>
                </td>
                <td>{r.raw_weighted.toFixed(4)}</td>
                <td>
                  {r.judge_count}
                  {!r.coverage_ok && <span className="error"> *</span>}
                </td>
                <td>
                  {run && (
                    <button onClick={() => setWhy({ runId: run.id, project: r.project })}>
                      Why?
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {why && run && (
        <Why
          runId={why.runId}
          project={why.project}
          onClose={() => setWhy(null)}
        />
      )}
    </section>
  );
}
