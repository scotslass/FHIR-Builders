# Web UI — Design & Action Items

> Status: **PLANNING** (no code written yet). Branch: `feat/web-ui`.
> Goal: a very simple, **local** web interface to run the data-quality checker
> against Medplum and read the results in a table.

---

## What we're building

A small local web app with two parts:

1. **A thin web server** that wraps the existing checker. It does not reimplement
   anything — it calls the same `RuleEngine` that `src/run_quality_check.py` uses.
2. **One simple web page**: pick what to run (all rules or a single rule, and
   which resource types), press **Run**, read the results in a table.

```
Browser (Run button) → local server → existing RuleEngine → Medplum → results → table
```

### Requirements (from the user)
- Execute the data-quality checker **all at once** or **one rule at a time**.
- Run against the **Medplum** database (reuse existing client + credentials).
- Display results in an **easy-to-read table**.
- Standalone, but **follow security best practices** (or explicitly flag tradeoffs).

---

## Key design decisions

| Decision | Choice | Why |
|---|---|---|
| Architecture | **FastAPI JSON API (backend) + separate static frontend** | Clean split: the backend has no opinion on the UI, so the frontend can grow or be replaced (tabs, multi-page, even React later) **without backend changes**. This is the future-proofing decision. |
| Frontend (start) | **Plain HTML + htmx/Alpine.js**, no build step | Gives tabs / multiple views / dynamic updates now, with no Node or build tooling. Upgrade path to React/Vue later leaves the API untouched. (Streamlit rejected: it fuses backend+frontend and fights multi-page/tabs.) |
| Run "one rule only" | Reuse the engine's existing `disabled` set — keep one rule on, disable the rest | **Zero engine changes** |
| Slow / huge runs | Start **synchronous with a default resource cap** (e.g. 500); add background-job + polling later if needed | Avoid browser timeouts without building a job queue up front |
| Honest coverage labeling | For each resource type, report **fetched vs total available** and whether the cap was hit; the UI shows "evaluated N of M — more data not evaluated" when truncated | The cap is a spot-check; results must never be mistaken for a full-dataset total |
| Resource types | **Auto-derived from the registry** — the UI offers exactly the types that registered rules cover (Patient / Observation / Encounter today) | Every option returns meaningful results; self-updates when a rule for a new type is added; doubles as the input allowlist. Zero list to maintain. |
| Code reuse | Extract the core "fetch → run engine → result" steps from `run_quality_check.py` into one shared function used by **both** CLI and web | One source of truth, no duplication |
| Results shape | JSON: `rule_id, severity, resource_type, resource_id, message, status` | Mirrors the existing CSV report columns |

### Future growth (multi-page / tabs / richer interactivity)
The backend is a neutral JSON API, so the frontend can evolve independently:
- **Now → near term:** plain HTML + htmx/Alpine → tabs and a few pages, no build step.
- **Later (only if it gets complex):** swap the frontend for a React/Vue SPA. The
  FastAPI API stays exactly the same; nothing on the server changes.

---

## Security best practices (and tradeoffs to accept)

| Concern | Action | Tradeoff if skipped |
|---|---|---|
| Network exposure | Bind to **`127.0.0.1` only**, never `0.0.0.0` | Anyone on the network could query the clinical DB |
| Credentials | Medplum id/secret stay **server-side** from `.env`; never sent to browser | Leaked secrets |
| PHI on screen | Show only `rule_id, severity, resource_type, resource_id, message` (project's "type + id only" rule) | Clinical detail leaks into browser cache/history |
| Auth | **None** — accepted *only because* localhost + single user | If ever exposed (ngrok/deploy/`0.0.0.0`), this is wide open — needs auth + HTTPS first |
| DNS-rebinding / CSRF | Validate `Host` header is localhost; reject others | A malicious website could trigger DB runs via your local server |
| Input safety | Allowlist resource types + rule IDs against the **registry** | Injection risk into FHIR queries |
| Dependencies | Pin web-framework version in `docs/requirements.txt` | Bigger attack surface, surprise breakage |
| Reports on disk | Reuse existing `outputs/` (gitignored) | — |

> ⚠️ **The one conscious tradeoff:** this is an *unauthenticated* tool. That is
> normal and fine for a localhost developer utility — **as long as it stays on
> localhost.** Exposing it externally changes the security model entirely and
> must not be done without adding authentication and TLS first.

---

## Action items

### Phase 0 — Groundwork
- [x] Confirm framework choice (default: **FastAPI**).
- [x] Add pinned web-framework dependency to `docs/requirements.txt`.
- [x] Refactor `src/run_quality_check.py`: extract a reusable
      `run_check(resource_types, disabled, limit, page_size, from_file) -> EngineResult`
      function; have the CLI call it. (Keep CLI behavior identical; tests stay green.)

### Phase 1 — Backend (server)
- [x] New module (e.g. `src/web/app.py`) exposing:
  - [x] `GET /api/rules` — list registered rules (id, description, severity, resource_types) from the registry.
  - [x] `GET /api/resource-types` — allowlisted resource types.
  - [x] `POST /api/run` — body: `{ resource_types[], rule_id? , limit? }`; returns `EngineResult` as JSON.
- [x] "One rule" = run with every other rule in the `disabled` set.
- [x] Validate all inputs against the registry allowlist; reject unknown values.
- [x] Apply a **default resource cap** so runs return promptly.
- [x] **Capture coverage per resource type**: alongside `fetched` (count evaluated),
      get the `total` available from Medplum (FHIR search `Bundle.total`, e.g. via a
      cheap `_summary=count` request) and set `truncated = fetched < total`.
- [x] Include a `coverage` block in the `/api/run` response, e.g.
      `coverage: [{ resource_type, fetched, total, truncated }], cap, complete`
      (`complete = no type truncated`).
- [x] Bind server to `127.0.0.1`; add a `Host`-header check (reject non-localhost).
- [x] Ensure credentials are loaded server-side only and never serialized to the client.

### Phase 2 — Frontend (page)
- [x] Single static HTML page (served by the same server):
  - [x] Mode selector: **Run all** vs **Run one rule** (dropdown of rules).
  - [x] Resource-type selector.
  - [x] **Run** button with a loading state.
  - [x] Results **table**: rule, severity, resource type, resource id, message.
  - [x] Summary line (resources checked, counts by severity, could-not-assess count).
  - [x] **Coverage banner** driven by the `coverage` block:
    - [x] When any type is truncated, show a clear warning, e.g.
          *"⚠️ Partial run — evaluated 500 of 12,340 Patients (cap 500). More data was not evaluated."*
    - [x] When nothing is truncated, show *"✅ Full coverage — all resources evaluated."*
    - [x] Per-type "N of M" shown in/near the table so totals are never mistaken for the whole dataset.
  - [x] Show errors (e.g. Medplum auth failure) clearly instead of a frozen spinner.

### Phase 3 — Verify & document
- [x] Manual run against synthetic Medplum data end-to-end.
- [x] Add a "Web UI" section to `README.md` (how to start it, the localhost-only warning).
- [x] Update `CONTEXT.md` "Current status".
- [x] Optional unit/smoke test for the new API endpoints.

### Later / if needed (not now)
- [ ] Background-job + polling for large runs (replaces the resource cap).
- [ ] Download-results-as-CSV button (reuse existing report writer).
- [ ] Run history / trend view (the `db/` DuckDB stores already exist for this).

---

## Resolved decisions
1. **Architecture**: ✅ FastAPI JSON API + separate static frontend (plain HTML +
   htmx/Alpine to start), chosen specifically to keep multi-page/tabs/React open
   for the future without backend rework.
2. **Slow runs**: ✅ Cap with a default resource limit (background jobs deferred).
3. **Resource types**: ✅ Auto-derived from the registry (rules' declared types) —
   resolves to Patient / Observation / Encounter today, self-updating thereafter.
   Also serves as the input allowlist.

## Still to confirm
- **Default resource cap** value for an interactive run (proposed: **500**).
