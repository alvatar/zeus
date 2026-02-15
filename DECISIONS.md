# Decisions

## 2026-02-15 — Celebration overlays require minimum active fleet size

- **Decision:** Trigger Dopamine / Steady Lad overlays only when (a) efficiency threshold is met, (b) warm-up is complete, and (c) at least 4 non-paused agents exist.
- **Reasoning:** High efficiency with too few agents produces noisy/low-signal celebrations; requiring a minimum active fleet size better reflects meaningful throughput.
- **Alternatives considered:**
  - Keep threshold-only trigger (rejected: too chatty with small fleets).
  - Count only WORKING/WAITING agents (rejected for now: excludes active non-paused fleet members that still contribute to overall context).

## 2026-02-15 — Interact stream links open via explicit Textual click actions

- **Decision:** Linkify stream text with Rich `Style(link=..., meta={"@click": "app.open_url(...)"})` and handle browser opening in `action_open_url`.
- **Reasoning:** Visual `link` styling alone is not reliably actionable in this Textual/RichLog path; explicit `@click` actions make link opening deterministic.
- **Alternatives considered:**
  - Keep plain Rich link styles only (rejected: looked linked but did not open reliably).
  - Parse clicks manually at coordinate level (rejected: more complex and brittle than leveraging Textual action broker).
