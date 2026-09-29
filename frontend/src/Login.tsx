import { useState } from "react";
import { api, Me } from "./api";

type Role = "judge" | "organizer";
export type AuthMode = "login" | "signup";

const ROLE_CARDS: {
  role: Role;
  title: string;
  blurb: string;
  points: string[];
  demo: { email: string; password: string; eventCode?: string };
}[] = [
  {
    role: "judge",
    title: "Evaluator",
    blurb: "Score the event you were given a code for.",
    points: ["Event code + password unlocks that event", "Offline AI review (advisory only)", "Your scores stay private from other judges"],
    demo: { email: "diego.herrera@example.org", password: "isr-dev-password", eventCode: "SAMPLE26" },
  },
  {
    role: "organizer",
    title: "Organizer",
    blurb: "Run the event end to end.",
    points: ["Mission Control", "FairScore results & explanations", "Trust Center & exports"],
    demo: { email: "organizer@isr.local", password: "isr-dev-password" },
  },
];

export default function Login({
  onDone,
  initialMode = "login",
}: {
  onDone: (me: Me) => void;
  initialMode?: AuthMode;
}) {
  const [mode, setMode] = useState<AuthMode>(initialMode);
  const [role, setRole] = useState<Role>("judge");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [eventCode, setEventCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const chosen = ROLE_CARDS.find((c) => c.role === role)!;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    if (mode === "signup") {
      api.signup(email, name, password)
        .then(() => {
          // Account created — do NOT sign the user in. Return to the login
          // form with the email prefilled so they sign in themselves.
          setMode("login");
          setNotice("Account created. Sign in with your email and password.");
          setPassword("");
        })
        .catch((err) => setError(String(err.message ?? err)))
        .finally(() => setBusy(false));
      return;
    }
    api.login(email, password, role === "judge" ? eventCode.trim() : undefined)
      .then(onDone)
      .catch((err) => setError(String(err.message ?? err)))
      .finally(() => setBusy(false));
  };

  const useDemo = () => {
    setEmail(chosen.demo.email);
    setPassword(chosen.demo.password);
    setEventCode(chosen.demo.eventCode ?? "");
    setNotice(null);
  };

  const switchMode = (next: AuthMode) => {
    setMode(next);
    setError(null); // never carry an error from one form into the other
    setNotice(null);
  };

  if (mode === "signup") {
    return (
      <section>
        <h1>Create your account</h1>
        <p className="summary">
          New accounts join as participants. Judges and organizers get their
          accounts from the event organizer.
        </p>
        <form onSubmit={submit} className="login-form">
          <label>
            Name
            <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={255} />
          </label>
          <label>
            Email
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </label>
          <label>
            Password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
              maxLength={128}
            />
          </label>
          <p className="summary">At least 8 characters.</p>
          {error && <p className="error">{error}</p>}
          <button type="submit" disabled={busy}>
            {busy ? "Creating account…" : "Create account"}
          </button>{" "}
          <button type="button" className="ghost" onClick={() => switchMode("login")}>
            I already have an account
          </button>
        </form>
      </section>
    );
  }

  return (
    <section>
      <h1>Sign in to ISR</h1>
      <p className="summary">Choose how you take part — ISR routes you to the right workspace.</p>

      <div className="role-grid">
        {ROLE_CARDS.map((c) => (
          <button
            key={c.role}
            type="button"
            className={`card role-card ${role === c.role ? "active" : ""}`}
            onClick={() => setRole(c.role)}
          >
            <h3>{c.title}</h3>
            <p className="summary">{c.blurb}</p>
            <ul className="meta">
              {c.points.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </button>
        ))}
      </div>

      <form onSubmit={submit} className="login-form">
        {notice && <p className="meta" role="status">{notice}</p>}
        <label>
          Email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label>
          Password
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </label>
        {role === "judge" && (
          <label>
            Event code
            <input
              value={eventCode}
              onChange={(e) => setEventCode(e.target.value.toUpperCase())}
              placeholder="e.g. SAMPLE26"
              maxLength={12}
            />
          </label>
        )}
        {role === "judge" && (
          <p className="summary">
            Evaluators need the organizer's event code to score that event. Without it you land
            read-only.
          </p>
        )}
        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={busy}>
          {busy ? "Signing in…" : `Continue as ${chosen.title}`}
        </button>{" "}
        <button type="button" onClick={useDemo} className="ghost">
          Use demo account
        </button>{" "}
        <button type="button" className="ghost" onClick={() => switchMode("signup")}>
          Sign up
        </button>
      </form>
    </section>
  );
}
