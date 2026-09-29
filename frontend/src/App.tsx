import { useEffect, useState } from "react";
import { api, Me } from "./api";
import Welcome from "./Welcome";
import Mission from "./Mission";
import MyEvents from "./MyEvents";
import Results from "./Results";
import Trust from "./Trust";
import JudgeWorkspace from "./JudgeWorkspace";

type View =
  | { name: "gallery" }
  | { name: "judge" }
  | { name: "mission" }
  | { name: "events" }
  | { name: "results" }
  | { name: "trust" };

function homeFor(me: Me): View {
  if (me.role === "judge") return { name: "judge" };
  if (me.role === "organizer" || me.role === "admin") return { name: "events" };
  // Everyone else (participants included) lands on the public gallery.
  return { name: "gallery" };
}

function Nav({ me, view, onNav }: { me: Me | null; view: View; onNav: (v: View) => void }) {
  const isOrg = me?.role === "organizer" || me?.role === "admin";
  return (
    <nav className="nav">
      <span className="brand">
        ISR <span className="brand-sub">RUN → JUDGE → VERIFY → EXPLAIN</span>
      </span>
      <div className="nav-links">
        {me && (
          <button className={view.name === "gallery" ? "active" : ""} onClick={() => onNav({ name: "gallery" })}>
            Gallery
          </button>
        )}
        {me?.role === "judge" && (
          <button className={view.name === "judge" ? "active" : ""} onClick={() => onNav({ name: "judge" })}>
            My Reviews
          </button>
        )}
        {isOrg && (
          <>
            <button className={view.name === "events" ? "active" : ""} onClick={() => onNav({ name: "events" })}>
              My Events
            </button>
            <button className={view.name === "mission" ? "active" : ""} onClick={() => onNav({ name: "mission" })}>
              Mission Control
            </button>
            <button className={view.name === "results" ? "active" : ""} onClick={() => onNav({ name: "results" })}>
              Results
            </button>
            <button className={view.name === "trust" ? "active" : ""} onClick={() => onNav({ name: "trust" })}>
              Trust Center
            </button>
          </>
        )}
        {me && (
          <span className="who">
            {me.name} ({me.role})
            <button onClick={() => api.logout().then(() => window.location.reload())}>Log out</button>
          </span>
        )}
      </div>
    </nav>
  );
}

function Gallery() {
  const [projects, setProjects] = useState<import("./api").Project[] | null>(null);
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.gallery(q).then(setProjects).catch((e) => setError(String(e.message ?? e)));
  }, [q]);

  if (error) return <p className="error">{error}</p>;
  return (
    <section>
      <h1>Public Gallery</h1>
      <input
        placeholder="Search projects…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        aria-label="Search projects"
      />
      {projects === null ? (
        <p>Loading…</p>
      ) : (
        <div className="grid">
          {projects.map((p) => (
            <article key={p.external_id} className="card">
              <h2>{p.title}</h2>
              <p className="summary">{p.summary}</p>
              <p className="meta">
                <span className="tag">{p.track}</span> · team {p.team}
              </p>
              {p.repo_url && (
                <a href={p.repo_url} target="_blank" rel="noreferrer">
                  Repository
                </a>
              )}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

export default function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [view, setView] = useState<View>({ name: "gallery" });
  const [ready, setReady] = useState(false);

  useEffect(() => {
    // Restoring a session lands on the role's home; anonymous users get the
    // welcome splash (login/signup) — the gallery is behind login now.
    api.me()
      .then((m) => {
        setMe(m);
        setView(homeFor(m));
      })
      .catch(() => setMe(null))
      .finally(() => setReady(true));
  }, []);

  if (!ready) return <main className="app" />;

  if (!me) {
    return (
      <Welcome
        onDone={(m) => {
          setMe(m);
          setView(homeFor(m));
        }}
      />
    );
  }

  return (
    <main className="app">
      <Nav me={me} view={view} onNav={setView} />
      {view.name === "gallery" && <Gallery />}
      {view.name === "judge" && me?.role === "judge" && <JudgeWorkspace />}
      {view.name === "events" && (me?.role === "organizer" || me?.role === "admin") && <MyEvents />}
      {view.name === "mission" && (me?.role === "organizer" || me?.role === "admin") && <Mission />}
      {view.name === "results" && (me?.role === "organizer" || me?.role === "admin") && <Results />}
      {view.name === "trust" && (me?.role === "organizer" || me?.role === "admin") && <Trust />}
    </main>
  );
}
