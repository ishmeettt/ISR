import { useEffect, useState } from "react";
import { api, EventRow } from "./api";

function toLocalInput(iso: string | null): string {
  if (!iso) return "";
  return iso.slice(0, 16);
}

function EventForm({
  initial, onSaved, onCancel,
}: {
  initial?: EventRow | null;
  onSaved: (e: EventRow, created: boolean) => void;
  onCancel: () => void;
}) {
  const editing = initial != null;
  const [form, setForm] = useState({
    name: initial?.name ?? "",
    description: initial?.description ?? "",
    judge_count: initial?.judge_count ?? 3,
    submissions_open: toLocalInput(initial?.submissions_open ?? null),
    submissions_close: toLocalInput(initial?.submissions_close ?? null),
    judging_close: toLocalInput(initial?.judging_close ?? null),
    registration_open: toLocalInput(initial?.registration_open ?? null),
    registration_close: toLocalInput(initial?.registration_close ?? null),
    tracks: (initial?.tracks ?? ["Open"]).join(", "),
  });
  // Optional AI (Groq) key: fully opt-in. An empty field on edit = leave
  // unchanged; check "replace" + empty + save clears the stored key.
  const [aiKey, setAiKey] = useState("");
  const [wantAi, setWantAi] = useState(initial?.ai_configured ?? false);
  const [clearAi, setClearAi] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm({ ...form, [k]: e.target.value });

  const submit = (ev: React.FormEvent) => {
    ev.preventDefault();
    setBusy(true);
    setError(null);
    const payload: Record<string, unknown> = {
      name: form.name,
      description: form.description,
      judge_count: Number(form.judge_count),
      tracks: form.tracks.split(",").map((t) => t.trim()).filter(Boolean),
    };
    for (const k of ["submissions_open", "submissions_close", "judging_close",
                     "registration_open", "registration_close"] as const) {
      payload[k] = form[k] ? new Date(form[k]).toISOString() : null;
    }
    if (editing) delete payload.tracks;
    if (wantAi && aiKey.trim()) payload.ai_api_key = aiKey.trim();
    if (editing && initial?.ai_configured && clearAi) payload.ai_api_key = "";
    const call = editing
      ? api.editEvent(initial!.id, payload)
      : api.createEvent(payload);
    call.then((saved) => onSaved(saved as EventRow, !editing))
      .catch((err) => setError(String(err.message ?? err)))
      .finally(() => setBusy(false));
  };

  return (
    <form onSubmit={submit} className="login-form">
      <label>
        Event name
        <input value={form.name} onChange={set("name")} required minLength={3} />
      </label>
      <label>
        Description
        <textarea value={form.description} onChange={set("description")} rows={2} />
      </label>
      <label>
        Evaluators per project
        <input type="number" min={1} max={50} value={form.judge_count} onChange={set("judge_count")} />
      </label>
      <label>
        Submissions open (your local time, optional)
        <input type="datetime-local" value={form.submissions_open} onChange={set("submissions_open")} />
      </label>
      <label>
        Submissions close (your local time)
        <input type="datetime-local" value={form.submissions_close} onChange={set("submissions_close")} required />
      </label>
      <label>
        Judging close (your local time, optional)
        <input type="datetime-local" value={form.judging_close} onChange={set("judging_close")} />
      </label>
      <label>
        Registration open (your local time, optional)
        <input type="datetime-local" value={form.registration_open} onChange={set("registration_open")} />
      </label>
      <label>
        Registration close (your local time, optional)
        <input type="datetime-local" value={form.registration_close} onChange={set("registration_close")} />
      </label>
      {!editing && (
        <label>
          Tracks (comma-separated)
          <input value={form.tracks} onChange={set("tracks")} />
        </label>
      )}

      <label style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
        <input
          type="checkbox"
          checked={wantAi}
          onChange={(e) => setWantAi(e.target.checked)}
          style={{ width: "auto" }}
        />
        Enable AI-assisted judgment for evaluators (optional)
      </label>
      {wantAi && (
        <>
          <label>
            Groq API key (stored server-side, never shown again)
            <input
              type="password"
              value={aiKey}
              onChange={(e) => setAiKey(e.target.value)}
              placeholder={initial?.ai_configured && !clearAi ? "•••••••• (configured — enter a new key to replace)" : "gsk_…"}
              maxLength={255}
            />
          </label>
          <p className="meta">
            With a key, evaluators get a detailed LLM code review (strengths, risks,
            suggestions) alongside the offline scan. Without one — or if Groq is
            unreachable — review falls back to the offline static analysis. The AI
            never assigns marks; humans score. Get a free key at console.groq.com.
          </p>
          {editing && initial?.ai_configured && (
            <label style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
              <input
                type="checkbox"
                checked={clearAi}
                onChange={(e) => setClearAi(e.target.checked)}
                style={{ width: "auto" }}
              />
              Remove the stored key (disable AI judgment)
            </label>
          )}
        </>
      )}
      {error && <p className="error">{error}</p>}
      <button type="submit" disabled={busy}>{busy ? "Saving…" : editing ? "Save changes" : "Host event"}</button>{" "}
      <button type="button" className="ghost" onClick={onCancel}>Cancel</button>
    </form>
  );
}

export default function MyEvents() {
  const [events, setEvents] = useState<EventRow[] | null>(null);
  const [mode, setMode] = useState<"list" | "create" | "edit">("list");
  const [editing, setEditing] = useState<EventRow | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () =>
    api.myEvents().then(setEvents).catch((e) => setError(String(e.message ?? e)));

  useEffect(() => {
    load();
  }, []);

  const onSaved = (saved: EventRow, created: boolean) => {
    setMode("list");
    setEditing(null);
    if (created) {
      setFlash(`Event "${saved.name}" created — share code ${saved.code} · link ${saved.share_link}`);
    } else {
      setFlash(`Saved changes to "${saved.name}".`);
    }
    load();
  };

  if (error) return <p className="error">{error}</p>;

  return (
    <section>
      <h1>My Events</h1>
      {flash && <p className="summary"><strong>{flash}</strong></p>}
      {mode === "list" && !editing && (
        <>
          <button onClick={() => setMode("create")}>Host a new event</button>
          {(events ?? []).map((e) => {
            const now = new Date();
            const openAt = e.submissions_open ? new Date(e.submissions_open) : null;
            const closesAt = new Date(e.submissions_close);
            const state =
              openAt && now < openAt ? "upcoming" : now <= closesAt ? "open" : "closed";
            return (
            <article key={e.id} className="card" style={{ marginTop: "1rem" }}>
              <h3>
                {e.name} <span className="tag">{state}</span>
              </h3>
              <p className="summary">{e.description || "No description"}</p>
              <p className="meta">
                Code <code>{e.code}</code> · share link <code>{e.share_link ?? `/events/${e.code}`}</code>
                {" "}· {e.project_count ?? 0} projects · {e.judge_count} evaluator(s) per project
              </p>
              <p className="meta">
                Submissions: {e.submissions_open ? e.submissions_open.slice(0, 16).replace("T", " ") : "now"} →{" "}
                {e.submissions_close.slice(0, 16).replace("T", " ")}
                {e.judging_close && ` · judging until ${e.judging_close.slice(0, 16).replace("T", " ")}`}
              </p>
              <p className="meta">Tracks: {e.tracks.join(", ")}</p>
              <p className="meta">
                AI judgment: {e.ai_configured
                  ? <span style={{ color: "var(--emerald)" }}>enabled (Groq key configured)</span>
                  : "offline static analysis only"}
              </p>
              <button onClick={() => { setEditing(e); setMode("edit"); }}>Edit details</button>
            </article>
            );
          })}
          {events !== null && events.length === 0 && (
            <p className="meta">You are not hosting any events yet.</p>
          )}
        </>
      )}
      {(mode === "create" || editing) && (
        <EventForm
          initial={editing}
          onSaved={onSaved}
          onCancel={() => { setMode("list"); setEditing(null); }}
        />
      )}
    </section>
  );
}
