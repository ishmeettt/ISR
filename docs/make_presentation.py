"""Generate docs/ISR-Presentation.pptx — the ISR pitch/how-it-works deck.

Run (no host Python needed):
  docker run --rm -v "<repo>/docs:/docs" python:3.12-slim \
    sh -c "pip install -q python-pptx && python /docs/make_presentation.py"

The output imports 1:1 into Google Slides (drive.google.com -> New -> Google
Slides -> File -> Import slides). Edit THIS file to change the deck, rerun.
"""
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

# --- ISR dark theme ---------------------------------------------------------
BG = RGBColor(0x08, 0x0D, 0x12)      # near-black blue
PANEL = RGBColor(0x11, 0x1A, 0x20)   # card panel
PANEL2 = RGBColor(0x0C, 0x14, 0x1A)  # deeper panel
TEXT = RGBColor(0xE8, 0xF0, 0xF2)    # near-white
MUTED = RGBColor(0x9A, 0xAE, 0xB4)   # muted grey-green
GREEN = RGBColor(0x1C, 0xC7, 0x7D)   # ISR accent
AMBER = RGBColor(0xFF, 0xB0, 0x20)
CRIMSON = RGBColor(0xEF, 0x47, 0x6F)
BLUE = RGBColor(0x4C, 0x9E, 0xD9)
DARKTXT = RGBColor(0x06, 0x0A, 0x0D)

W, H = 13.333, 7.5
prs = Presentation()
prs.slide_width = Inches(W)
prs.slide_height = Inches(H)
BLANK = prs.slide_layouts[6]

cp = prs.core_properties
cp.title = "ISR — Intelligent Submission & Review"
cp.author = "ISR"
cp.subject = "How ISR works: offline-first hackathon portal"


def slide():
    s = prs.slides.add_slide(BLANK)
    bar = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, Inches(0.09))
    bar.fill.solid(); bar.fill.fore_color.rgb = GREEN; bar.line.fill.background()
    bar.shadow.inherit = False
    bg = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, Inches(0.09), prs.slide_width,
                            prs.slide_height - Inches(0.09))
    bg.fill.solid(); bg.fill.fore_color.rgb = BG; bg.line.fill.background()
    bg.shadow.inherit = False
    # footer (added last on each slide via footer())
    return s


def footer(s, n):
    tb = s.shapes.add_textbox(Inches(0.6), Inches(7.08), Inches(9), Inches(0.35))
    p = tb.text_frame.paragraphs[0]
    r = p.add_run(); r.text = "ISR — Intelligent Submission & Review · offline-first hackathon portal"
    r.font.size = Pt(10); r.font.color.rgb = MUTED
    tb2 = s.shapes.add_textbox(Inches(12.3), Inches(7.08), Inches(0.7), Inches(0.35))
    p2 = tb2.text_frame.paragraphs[0]; p2.alignment = PP_ALIGN.RIGHT
    r2 = p2.add_run(); r2.text = str(n)
    r2.font.size = Pt(10); r2.font.color.rgb = MUTED


def kicker(s, text, y=0.42):
    tb = s.shapes.add_textbox(Inches(0.6), Inches(y), Inches(12), Inches(0.4))
    p = tb.text_frame.paragraphs[0]
    r = p.add_run(); r.text = text.upper()
    r.font.size = Pt(12); r.font.bold = True; r.font.color.rgb = GREEN


def title(s, text, y=0.78, size=33):
    tb = s.shapes.add_textbox(Inches(0.6), Inches(y), Inches(12.2), Inches(1.0))
    p = tb.text_frame.paragraphs[0]
    r = p.add_run(); r.text = text
    r.font.size = Pt(size); r.font.bold = True; r.font.color.rgb = TEXT


def bullets(s, x, y, w, h, items):
    """items: list of (text, level) or (text, level, color) or (text, level, color, bold)."""
    tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame; tf.word_wrap = True
    first = True
    for item in items:
        text, level = item[0], item[1]
        color = item[2] if len(item) > 2 else TEXT
        bold = item[3] if len(item) > 3 else False
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.level = level
        p.space_after = Pt(7)
        r = p.add_run()
        r.text = ("• " if level == 0 else "– ") + text if text else ""
        r.font.size = Pt(15 if level == 0 else 13)
        r.font.color.rgb = color
        r.font.bold = bold
    return tb


def card(s, x, y, w, h, heading, lines, accent=GREEN, fill=PANEL,
         head_size=15, line_size=12.5, head_color=None):
    box = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y),
                             Inches(w), Inches(h))
    box.adjustments[0] = 0.06
    box.fill.solid(); box.fill.fore_color.rgb = fill
    box.line.color.rgb = accent; box.line.width = Pt(1.1)
    box.shadow.inherit = False
    edge = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y),
                              Inches(0.07), Inches(h))
    edge.adjustments[0] = 0.5
    edge.fill.solid(); edge.fill.fore_color.rgb = accent
    edge.line.fill.background(); edge.shadow.inherit = False
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.TOP
    tf.margin_left = Inches(0.22); tf.margin_right = Inches(0.18)
    tf.margin_top = Inches(0.16); tf.margin_bottom = Inches(0.12)
    p = tf.paragraphs[0]; p.space_after = Pt(5)
    r = p.add_run(); r.text = heading
    r.font.size = Pt(head_size); r.font.bold = True
    r.font.color.rgb = head_color or accent
    for line in lines:
        p = tf.add_paragraph(); p.space_after = Pt(4)
        r = p.add_run(); r.text = line
        r.font.size = Pt(line_size); r.font.color.rgb = TEXT
    return box


def chip(s, x, y, w, h, text, fill=GREEN, color=DARKTXT, size=13, bold=True):
    box = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y),
                             Inches(w), Inches(h))
    box.adjustments[0] = 0.5
    box.fill.solid(); box.fill.fore_color.rgb = fill
    box.line.fill.background(); box.shadow.inherit = False
    tf = box.text_frame; tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = text
    r.font.size = Pt(size); r.font.bold = bold; r.font.color.rgb = color


def set_cell(cell, text, size=12, bold=False, color=TEXT, fill=PANEL,
             align=PP_ALIGN.LEFT):
    cell.fill.solid(); cell.fill.fore_color.rgb = fill
    cell.margin_left = Inches(0.1); cell.margin_right = Inches(0.08)
    cell.margin_top = Inches(0.04); cell.margin_bottom = Inches(0.04)
    cell.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf = cell.text_frame; tf.word_wrap = True
    p = tf.paragraphs[0]; p.alignment = align
    r = p.add_run(); r.text = text
    r.font.size = Pt(size); r.font.bold = bold; r.font.color.rgb = color


def notes(s, text):
    s.notes_slide.notes_text_frame.text = text


# --- 1. Title -----------------------------------------------------------------
s = slide()
kicker(s, "hackathon infrastructure · offline-first · self-hosted", y=1.5)
tb = s.shapes.add_textbox(Inches(0.6), Inches(2.0), Inches(12.2), Inches(1.6))
p = tb.text_frame.paragraphs[0]
r = p.add_run(); r.text = "ISR — Intelligent Submission & Review"
r.font.size = Pt(44); r.font.bold = True; r.font.color.rgb = TEXT
tb = s.shapes.add_textbox(Inches(0.6), Inches(3.35), Inches(12.2), Inches(0.8))
p = tb.text_frame.paragraphs[0]
r = p.add_run(); r.text = "RUN  →  JUDGE  →  VERIFY  →  EXPLAIN"
r.font.size = Pt(24); r.font.bold = True; r.font.color.rgb = GREEN
tb = s.shapes.add_textbox(Inches(0.6), Inches(4.35), Inches(12.2), Inches(1.2))
for i, line in enumerate([
    "One container. Zero internet. Deterministic results.",
    "Submissions, AI-assisted judging, explainable rankings, and a full audit trail —",
    "on one machine, in one native desktop window.",
]):
    p = tb.text_frame.paragraphs[0] if i == 0 else tb.text_frame.add_paragraph()
    r = p.add_run(); r.text = line
    r.font.size = Pt(16 if i == 0 else 13)
    r.font.color.rgb = TEXT if i == 0 else MUTED
    p.space_after = Pt(4)
notes(s, "ISR is a self-hosted hackathon competition portal. Everything — API, UI, "
         "database — ships as one Docker container that runs fully offline, plus a "
         "Windows desktop launcher. This deck walks through how it works and how to demo it.")

# --- 2. The problem -----------------------------------------------------------
s = slide(); footer_later = s
kicker(s, "the problem"); title(s, "Hackathon ops is a spreadsheet swamp")
bullets(s, 0.6, 2.1, 12.2, 3.6, [
    ("Project links scattered across chat, forms, and email — no single gallery.", 0),
    ("Judge scores land in spreadsheets; nobody can explain how the winner was computed.", 0),
    ("Cloud judging tools need reliable venue wifi and send teams' code to third parties.", 0),
    ("No trace of who scored what, when, or what changed — disputes go unresolved.", 0),
    ("Deadline enforcement is a checkbox in a form, not a server-side guarantee.", 0),
])
card(s, 0.6, 5.6, 12.2, 1.1,
     "ISR's answer",
     ["One machine runs the whole competition. Results are reproducible and explainable, "
      "every action is audited, and nothing ever leaves the room."],
     accent=GREEN)
footer(s, 2)
notes(s, "Frame the pain: ops chaos, opaque scoring, cloud dependence, zero auditability. "
         "ISR replaces all of it with one offline container.")

# --- 3. What is ISR -----------------------------------------------------------
s = slide(); kicker(s, "what it is"); title(s, "A complete competition stack in one container")
bullets(s, 0.6, 2.0, 6.6, 4.6, [
    ("API + UI + database in a single Docker image — one command to run.", 0),
    ("Deterministic FairScore rankings with per-project “Why this rank?”.", 0),
    ("Judge isolation enforced server-side; append-only audit trail.", 0),
    ("AI code review: offline static analyzer, optional Groq LLM — advisory only.", 0),
    ("Trust Center anomaly detectors + Mission Control dashboard.", 0),
    ("CSV export of every evaluation.", 0),
    ("Windows desktop app: double-click → native window, own taskbar icon.", 0),
])
card(s, 7.5, 2.0, 5.3, 1.35, "Stack",
     ["FastAPI + SQLAlchemy 2 · React + TypeScript + Vite", "SQLite (Postgres optional) · PBKDF2 + cookie sessions"],
     accent=BLUE)
card(s, 7.5, 3.55, 5.3, 1.35, "Runs on",
     ["Any Docker host · Windows 10/11 via WSL2", "Health check: /api/health · API docs at /docs"],
     accent=BLUE)
card(s, 7.5, 5.1, 5.3, 1.5, "Data stays put",
     ["isr_data volume → SQLite DB", "isr_repos volume → judge-added repo clones"],
     accent=BLUE)
footer(s, 3)
notes(s, "One image = backend + built frontend + SQLite. Volumes persist data across "
         "redeploys. The Windows launcher makes it feel like a normal app.")

# --- 4. The flow --------------------------------------------------------------
s = slide(); kicker(s, "how it works"); title(s, "RUN → JUDGE → VERIFY → EXPLAIN")
steps = [
    ("RUN", GREEN, ["Organizer creates the event,", "gets a share code;", "deadline enforced server-side"]),
    ("JUDGE", BLUE, ["Judges enter the code at login;", "AI static review + rubric", "scores 0–5, weighted"]),
    ("VERIFY", AMBER, ["FairScore normalizes per judge;", "Trust Center flags", "suspicious patterns"]),
    ("EXPLAIN", CRIMSON, ["“Why this rank?” re-derives", "every number; full audit", "trail backs every action"]),
]
x = 0.6
for i, (name, color, lines) in enumerate(steps):
    card(s, x, 2.3, 2.85, 2.9, name, lines, accent=color, head_size=19)
    if i < 3:
        tb = s.shapes.add_textbox(Inches(x + 2.82), Inches(3.35), Inches(0.45), Inches(0.6))
        p = tb.text_frame.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
        r = p.add_run(); r.text = "→"; r.font.size = Pt(26); r.font.bold = True
        r.font.color.rgb = MUTED
    x += 3.24
card(s, 0.6, 5.7, 12.2, 0.95, "Every step writes to the audit trail",
     ["logins · signups · submissions · evaluations & revisions · AI reviews · exports · dispositions"],
     accent=MUTED, head_size=13)
footer(s, 4)
notes(s, "The four-stage flow is the product. Emphasize that RUN and JUDGE are "
         "role-separated, VERIFY is automatic, and EXPLAIN is what makes results defensible.")

# --- 5. Architecture ----------------------------------------------------------
s = slide(); kicker(s, "architecture"); title(s, "One process serves everything")
bullets(s, 0.6, 2.0, 6.4, 4.4, [
    ("FastAPI serves the REST API and the built React bundle from one process (ISR_SERVE_UI=1).", 0),
    ("No nginx, no separate frontend container, no node at runtime.", 0),
    ("SQLite at /data/isr.db inside the isr_data volume; repo clones in isr_repos.", 0),
    ("Auth: PBKDF2 password hashes, HttpOnly session cookies (7-day TTL).", 0),
    ("--restart unless-stopped: the engine comes back with the machine.", 0),
])
card(s, 7.3, 2.0, 5.5, 4.4, "Request path",
     ["ISR window (Edge app mode)", "        ↓  http://127.0.0.1:8080",
      "Docker inside WSL2 Ubuntu", "        ↓",
      "FastAPI (uvicorn, :8000)", "        ↓",
      "SQLite (isr_data) + /repos (isr_repos)", "",
      "Same image everywhere: laptop, lab, venue."],
     accent=BLUE, line_size=13)
footer(s, 5)
notes(s, "The single-process design is why it is fully offline and trivial to deploy. "
         "Compose mode with Postgres still exists for classic deployments.")

# --- 6. AI review ---------------------------------------------------------------
s = slide(); kicker(s, "ai review"); title(s, "Advisory intelligence — the machine never scores")
card(s, 0.6, 2.0, 6.1, 2.5, "Static analyzer — always on, fully offline",
     ["Scans repo checkouts for security loopholes, real errors, improvements, run hints",
      "Deterministic: same repo, same findings, no network",
      "Finds: hardcoded secrets, SQL string building, eval/exec, shell injection, bare excepts…"],
     accent=GREEN)
card(s, 6.95, 2.0, 5.85, 2.5, "Groq LLM judgment — optional, per-event key",
     ["Structured review: strengths, risks, suggestions",
      "Advisory suggested scores per rubric criterion",
      "Falls back to static automatically when offline or unkeyed"],
     accent=AMBER)
box = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.6), Inches(4.9),
                         Inches(12.2), Inches(1.6))
box.adjustments[0] = 0.08
box.fill.solid(); box.fill.fore_color.rgb = PANEL2
box.line.color.rgb = CRIMSON; box.line.width = Pt(1.4); box.shadow.inherit = False
tf = box.text_frame; tf.word_wrap = True; tf.vertical_anchor = MSO_ANCHOR.MIDDLE
p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
r = p.add_run(); r.text = "Policy: the machine NEVER assigns marks."
r.font.size = Pt(20); r.font.bold = True; r.font.color.rgb = CRIMSON
p2 = tf.add_paragraph(); p2.alignment = PP_ALIGN.CENTER
r2 = p2.add_run(); r2.text = "AI output is advisory context for the human judge — final scores always come from a person."
r2.font.size = Pt(13); r2.font.color.rgb = TEXT
footer(s, 6)
notes(s, "The AI policy is a feature, not a caveat: judges get speed and coverage; "
         "humans keep authority. Offline fallback means judging never blocks.")

# --- 7. FairScore ----------------------------------------------------------------
s = slide(); kicker(s, "results"); title(s, "FairScore — rankings you can defend")
bullets(s, 0.6, 2.0, 6.6, 4.4, [
    ("Per-judge z-score normalization: harsh and generous judges are put on one scale.", 0),
    ("Immutable runs: every POST /api/results/run snapshots its inputs and intermediates.", 0),
    ("Same data + same code = same ranking. Reproduce any historical run byte-for-byte.", 0),
    ("Judge-blind: rankings are computed without knowing which judge said what.", 0),
])
card(s, 7.4, 2.0, 5.4, 2.0, "Rubric",
     ["functionality — 40%", "quality — 35%", "innovation — 25%", "each criterion 0–5"],
     accent=BLUE)
card(s, 7.4, 4.2, 5.4, 2.2, "Why this rank?",
     ["GET /api/results/why/{run}/{project}",
      "Re-derives the project's normalized scores, weighting, and rank",
      "from stored intermediates — the answer is the data, not a claim."],
     accent=CRIMSON)
footer(s, 7)
notes(s, "Normalization removes judge-to-judge scale bias. Immutability plus the "
         "explanation endpoint is what lets you show a team exactly why they ranked where they did.")

# --- 8. Trust Center & Mission Control ---------------------------------------------
s = slide(); kicker(s, "integrity & oversight"); title(s, "Trust Center + Mission Control")
card(s, 0.6, 2.0, 6.1, 3.0, "Trust Center — anomaly detectors",
     ["Uniform-score judges (same marks every row)",
      "Low review coverage per judge or project",
      "Out-of-track reviews and duplicate submissions",
      "Flags never alter scores — the organizer resolves or dismisses, and every disposition is audited"],
     accent=AMBER)
card(s, 6.95, 2.0, 5.85, 3.0, "Mission Control — one organizer dashboard",
     ["Event health & submission windows",
      "Judging progress and completion percent",
      "Judge workload and coverage gaps",
      "Trust summary and FairScore run history"],
     accent=BLUE)
card(s, 0.6, 5.35, 12.2, 1.25, "Exports",
     ["One click CSV of all evaluations — judges stay anonymous by design; review counts are shown to teams without identities."],
     accent=GREEN, head_size=13)
footer(s, 8)
notes(s, "Trust flags are advisory too: they surface patterns for humans to judge. "
         "Mission Control answers 'how is the event doing' in one screen.")

# --- 9. Demo accounts ----------------------------------------------------------------
s = slide(); kicker(s, "try it now"); title(s, "Demo accounts — password: isr-dev-password")
rows = [
    ("Role", "Email", "What you'll see"),
    ("Organizer", "organizer@isr.local", "My Events · Mission Control · Results · Trust Center"),
    ("Evaluator (judge A)", "diego.herrera@example.org", "Evaluator dashboard"),
    ("Evaluator (judge B)", "jonas.vogel@example.org", "Evaluator dashboard"),
    ("Participant", "priya1@example.org", "Public gallery"),
    ("Admin", "admin@isr.local", "Same powers as organizer"),
]
tbl = s.shapes.add_table(len(rows), 3, Inches(0.6), Inches(2.1),
                         Inches(12.2), Inches(3.4)).table
tbl.columns[0].width = Inches(2.9)
tbl.columns[1].width = Inches(4.4)
tbl.columns[2].width = Inches(4.9)
for r_i, row in enumerate(rows):
    for c_i, val in enumerate(row):
        if r_i == 0:
            set_cell(tbl.cell(r_i, c_i), val, size=13, bold=True, color=DARKTXT, fill=GREEN)
        else:
            mono = c_i == 1
            set_cell(tbl.cell(r_i, c_i), val, size=12.5,
                     bold=(c_i == 0),
                     color=TEXT if not mono else RGBColor(0x8E, 0xD9, 0xC0),
                     fill=PANEL if r_i % 2 else PANEL2)
card(s, 0.6, 5.85, 12.2, 0.9, "Sign-up flow",
     ["Create account → lands back on the login page → sign in with the credentials you chose. New accounts join as participants."],
     accent=MUTED, head_size=12.5)
footer(s, 9)
notes(s, "All seeded accounts share the dev password. Judge A and Judge B are the two "
         "fixture judges with seeded evaluation history.")

# --- 10. Two demo events -----------------------------------------------------------
s = slide(); kicker(s, "demo events"); title(s, "Two codes, two kinds of demo")
card(s, 0.6, 2.1, 6.1, 3.3, "SAMPLE26 — Sample Hack 2026",
     ["HAS PROJECTS: 41 projects, 126 seeded evaluations",
      "Submissions closed (server-enforced)",
      "Best for: browsing the gallery, judging history,",
      "FairScore runs, Trust Center, CSV exports"],
     accent=GREEN, head_size=16)
card(s, 6.95, 2.1, 5.85, 3.3, "KYF5ES5P — DogFood",
     ["EMPTY: a brand-new event for a live walkthrough",
      "Best for: the full flow from zero —",
      "add repo by GitHub link → AI evaluate →",
      "score → run FairScore → inspect Trust flags"],
     accent=AMBER, head_size=16)
card(s, 0.6, 5.7, 12.2, 1.0, "Switching events",
     ["Enter the code on the Evaluator card at login. The workspace follows the LAST code you entered — log in again with the other code to switch."],
     accent=MUTED, head_size=13)
footer(s, 10)
notes(s, "SAMPLE26 is the populated demo; KYF5ES5P (DogFood) is deliberately empty so "
         "you can demo the whole flow live. Judges can hop between events by re-entering codes.")

# --- 11. Offline guarantee -----------------------------------------------------------
s = slide(); kicker(s, "offline by design"); title(s, "Proven with a network-none container")
bullets(s, 0.6, 2.0, 6.6, 4.4, [
    ("A throwaway container boots with --network none — no NIC, no DNS, nothing.", 0),
    ("Every API route is then walked in-process: signup, login, submission, judging, AI static review, results, export.", 0),
    ("31/31 checks pass. That is the offline guarantee, not an aspiration.", 0),
    ("bash scripts/verify_offline.sh re-proves it after any change.", 0),
])
card(s, 7.4, 2.0, 5.4, 2.6, "The only optional network features",
     ["Groq LLM judging → falls back to the offline static analyzer",
      "Judge repo cloning by GitHub link → degrades to a clear error; baked-in probe repos still work"],
     accent=AMBER)
card(s, 7.4, 4.8, 5.4, 1.8, "Built for",
     ["venues without wifi · privacy-sensitive code · air-gapped labs", "and events that must simply not go down"],
     accent=GREEN)
footer(s, 11)
notes(s, "This is the strongest differentiator: the offline property is machine-checked "
         "in CI-style, not claimed in docs.")

# --- 12. Running it -------------------------------------------------------------------
s = slide(); kicker(s, "running it"); title(s, "Three ways to start")
card(s, 0.6, 2.1, 4.0, 3.4, "Windows desktop",
     ["Double-click the ISR shortcut", "(or desktop\\Start ISR.bat)",
      "", "starts Docker in WSL, boots the",
      "container, pins WSL open, opens",
      "the app window. Stop ISR.bat stops."],
     accent=GREEN)
card(s, 4.85, 2.1, 4.0, 3.4, "Docker anywhere",
     ["docker run -d --name isr \\",
      "  -p 8080:8000 \\",
      "  -v isr_data:/data \\",
      "  -v isr_repos:/repos \\",
      "  --restart unless-stopped \\",
      "  isr-offline:latest"],
     accent=BLUE, line_size=12)
card(s, 9.1, 2.1, 3.7, 3.4, "From source",
     ["cd frontend && npm run build",
      "",
      "docker build -f backend/Dockerfile",
      "  -t isr-backend .",
      "docker build -f Dockerfile.offline",
      "  -t isr-offline ."],
     accent=AMBER, line_size=12)
card(s, 0.6, 5.8, 12.2, 0.9, "Then",
     ["Open http://localhost:8080 · health at /api/health → {\"status\":\"ok\"} · interactive API docs at /docs"],
     accent=MUTED, head_size=12.5)
footer(s, 12)
notes(s, "On this machine the desktop shortcut is the intended path. The raw docker "
         "command is the portable story; building from source needs node once.")

# --- 13. Guarantees --------------------------------------------------------------------
s = slide(); kicker(s, "security & fairness"); title(s, "Guarantees, not settings")
bullets(s, 0.6, 2.0, 12.2, 4.4, [
    ("Deadline enforcement is server-side: late submissions get HTTP 403, they are not merely hidden in the UI.", 0, TEXT, True),
    ("Judge isolation: /api/judge/scores returns only the caller's evaluations; cross-judge probes get 403.", 0),
    ("Workspace follows the judge's last-entered event code — new empty events no longer get shadowed by old ones.", 0),
    ("Append-only audit trail: logins, signups, submissions, evaluation revisions (upserts), AI reviews, exports, dispositions.", 0),
    ("Tampered session tokens are rejected; passwords are PBKDF2-hashed; cookies are HttpOnly.", 0),
    ("AI never assigns marks; Trust flags never alter scores; results runs are immutable.", 0, TEXT, True),
])
footer(s, 13)
notes(s, "Each line maps to a backend guard or a test in backend/tests — these are "
         "enforced properties, not configuration options.")

# --- 14. Closing -------------------------------------------------------------------------
s = slide(); kicker(s, "wrap-up"); title(s, "Run your next hackathon on one machine")
bullets(s, 0.6, 2.0, 6.6, 3.6, [
    ("Shipped: core submission & judging, FairScore, Trust Center, Mission Control, offline guarantee, Windows desktop app, multi-event workspaces.", 0),
    ("Next: event switcher inside the evaluator dashboard, Groq key field in the organizer UI, richer gallery profiles.", 0),
])
card(s, 7.4, 2.0, 5.4, 2.6, "Where things live",
     ["README.md — quick start + demo accounts", "scripts/verify_offline.sh — offline proof",
      "backend/tests — the guarantee suite", "docs/ — spec & judging plan"],
     accent=BLUE)
tb = s.shapes.add_textbox(Inches(0.6), Inches(5.3), Inches(12.2), Inches(1.2))
p = tb.text_frame.paragraphs[0]
r = p.add_run(); r.text = "ISR — RUN → JUDGE → VERIFY → EXPLAIN."
r.font.size = Pt(26); r.font.bold = True; r.font.color.rgb = GREEN
p2 = tb.text_frame.add_paragraph()
r2 = p2.add_run(); r2.text = "With receipts for every score."
r2.font.size = Pt(16); r2.font.color.rgb = MUTED
footer(s, 14)
notes(s, "Close on the differentiators: one container, offline-proof, explainable, "
         "audited. Offer the live demo: organizer creates an event, judge adds a repo, "
         "AI review, score, FairScore, Trust scan — five minutes end to end.")

prs.save("/docs/ISR-Presentation.pptx")
print("saved /docs/ISR-Presentation.pptx with", len(prs.slides.slides if hasattr(prs.slides, 'slides') else prs.slides._sldIdLst), "slides")
