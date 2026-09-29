import { useEffect, useState } from "react";
import { api, TrustFlag } from "./api";

function Detail({ flag }: { flag: TrustFlag }) {
  let evidence: unknown = null;
  try {
    evidence = JSON.parse(flag.detail);
  } catch {
    evidence = flag.detail;
  }
  if (evidence === null || evidence === "" || evidence === "{}") return null;
  return <pre className="detail">{JSON.stringify(evidence, null, 2)}</pre>;
}

export default function Trust() {
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [flags, setFlags] = useState<TrustFlag[]>([]);
  const [filter, setFilter] = useState<"open" | "all">("open");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () =>
    api.trustFlags(filter === "open" ? "open" : undefined)
      .then((r) => {
        setCounts(r.counts);
        setFlags(r.flags);
      })
      .catch((e) => setError(String(e.message ?? e)));

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  const scan = () => {
    setBusy(true);
    api.trustScan()
      .then(load)
      .catch((e) => setError(String(e.message ?? e)))
      .finally(() => setBusy(false));
  };

  const dispose = (id: number, disposition: "resolved" | "dismissed") =>
    api.trustDispose(id, disposition).then(load).catch((e) => setError(String(e.message ?? e)));

  return (
    <section>
      <h1>Trust Center</h1>
      <p className="summary">
        Flags surface anomalies — they never change scores or rankings. Disposition
        (resolve/dismiss) is an organizer decision and is audited.
      </p>
      <p className="meta">
        {counts.open ?? 0} open · {counts.resolved ?? 0} resolved · {counts.dismissed ?? 0} dismissed
      </p>
      <button onClick={scan} disabled={busy}>
        {busy ? "Scanning…" : "Run detection scan"}
      </button>{" "}
      <button onClick={() => setFilter(filter === "open" ? "all" : "open")}>
        {filter === "open" ? "Show all" : "Show open only"}
      </button>
      {error && <p className="error">{error}</p>}
      {flags.length === 0 ? (
        <p>No {filter === "open" ? "open " : ""}flags. Run a scan to detect anomalies.</p>
      ) : (
        <div className="grid">
          {flags.map((f) => (
            <article key={f.id} className="card">
              <h3>
                [{f.severity}] {f.detector.replace(/_/g, " ")}
              </h3>
              <p>{f.title}</p>
              <Detail flag={f} />
              <p className="meta">
                {f.status}
                {f.subject_type === "user" ? " · judge " : " · project "}#{f.subject_id}
              </p>
              {f.status === "open" && (
                <p>
                  <button onClick={() => dispose(f.id, "resolved")}>Resolve</button>{" "}
                  <button onClick={() => dispose(f.id, "dismissed")}>Dismiss</button>
                </p>
              )}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
