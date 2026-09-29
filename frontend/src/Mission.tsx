import { useEffect, useState } from "react";
import { api, MissionControl } from "./api";

function Card({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="card stat">
      <p className="stat-label">{label}</p>
      <p className="stat-value">{value}</p>
      {sub && <p className="meta">{sub}</p>}
    </div>
  );
}

export default function Mission() {
  const [mc, setMc] = useState<MissionControl | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.missionControl().then(setMc).catch((e) => setError(String(e.message ?? e)));
  }, []);

  if (error) return <p className="error">{error}</p>;
  if (!mc) return <p>Loading…</p>;

  const j = mc.judging;

  return (
    <section>
      <h1>Mission Control</h1>
      <p className="meta">
        {mc.event.name} · submissions closed {mc.event.submissions_close?.slice(0, 10)} (server-enforced)
      </p>

      <div className="stats">
        <Card label="Participants" value={mc.participation.participants} />
        <Card label="Teams" value={mc.participation.teams} />
        <Card label="Projects" value={mc.participation.projects} sub={`${mc.participation.submitted} submitted`} />
        <Card label="Judges" value={j.judges} />
        <Card label="Reviews" value={`${j.completed}/${j.assigned}`} sub={`${j.pending} pending`} />
        <Card
          label="Trust flags open"
          value={mc.trust.by_status.open ?? 0}
          sub={Object.entries(mc.trust.open_by_detector).map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`).join(" · ") || "none"}
        />
      </div>

      <h2>Judging progress</h2>
      <div className="progress-track" role="progressbar" aria-valuenow={j.completion_percent} aria-valuemin={0} aria-valuemax={100}>
        <div className="progress-fill" style={{ width: `${j.completion_percent}%` }} />
      </div>
      <p className="meta">{j.completion_percent}% complete · {j.completed} of {j.assigned} reviews</p>

      {mc.leader && (
        <>
          <h2>Current leader (run #{mc.runs[0]?.id})</h2>
          <p>
            #1 <strong>{mc.leader.title}</strong>{" "}
            <span className="meta">final score {mc.leader.final_score}</span>
          </p>
        </>
      )}

      <h2>Judge workload</h2>
      <table>
        <thead>
          <tr>
            <th>Judge</th>
            <th>Assigned</th>
            <th>Completed</th>
            <th>Pending</th>
          </tr>
        </thead>
        <tbody>
          {mc.workload.map((w) => (
            <tr key={w.email}>
              <td>{w.judge}</td>
              <td>{w.assigned}</td>
              <td>{w.completed}</td>
              <td>{w.pending > 0 ? <span className="error">{w.pending}</span> : 0}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Coverage gaps ({mc.coverage_gaps.length})</h2>
      {mc.coverage_gaps.length === 0 ? (
        <p className="meta">Every project has the modal review count.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Project</th>
              <th>Reviews</th>
              <th>Typical</th>
            </tr>
          </thead>
          <tbody>
            {mc.coverage_gaps.map((g) => (
              <tr key={g.project}>
                <td>{g.project}</td>
                <td className="error">{g.reviews}</td>
                <td>{g.modal}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h2>Normalization runs</h2>
      {mc.runs.length === 0 ? (
        <p className="meta">No runs yet — compute one from the Results view.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Run</th>
              <th>Method</th>
              <th>Projects</th>
              <th>Evaluations</th>
              <th>When</th>
            </tr>
          </thead>
          <tbody>
            {mc.runs.map((r) => (
              <tr key={r.id}>
                <td>#{r.id}</td>
                <td>{r.method}</td>
                <td>{r.project_count}</td>
                <td>{r.evaluation_count}</td>
                <td className="meta">{new Date(r.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
