"""FastAPI backend for the local data-quality web UI.

A thin JSON API over the shared ``quality_service`` — it does no rule evaluation
of its own, it calls the same ``run_check`` path the CLI uses. The frontend is a
single static page served from ``static/``.

SECURITY — this server is for **localhost use only**:
  * It must be bound to 127.0.0.1 (see ``serve()`` / ``run_web.py``).
  * A Host-header allowlist rejects non-localhost hosts, blocking DNS-rebinding
    attacks where a malicious page tries to drive this API from your browser.
  * Medplum credentials are read server-side from ``.env`` and are NEVER sent to
    the client. Result rows carry only resource type + id + message (the
    project's "type + id only" rule), never full FHIR bodies.
  * There is no authentication — acceptable ONLY because it is bound to
    localhost. Do not expose this externally without adding auth + TLS first.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from medplum_client import MedplumError
from quality_rules.registry import all_rule_ids, all_rules, covered_resource_types
from quality_service import CheckResult, run_check_medplum
from web.config import load_web_config

STATIC_DIR = Path(__file__).parent / "static"

# Default per-type resource cap for an interactive run (from config/web.cfg). A
# spot-check, not a full audit — the response always reports coverage so
# truncation is visible.
DEFAULT_CAP = load_web_config().default_cap

# Hostnames allowed in the Host header (DNS-rebinding guard). Ports are stripped
# before the check, so any port on these hosts is fine.
_ALLOWED_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1"}


# ── Request / response models ────────────────────────────────────────────────

class RunRequest(BaseModel):
    """Body for POST /api/run."""

    resource_types: list[str] = Field(default_factory=list)
    rule_id: str | None = None  # run only this rule (others disabled); None = all
    limit: int = Field(default=DEFAULT_CAP, ge=0)


def _serialize(result: CheckResult) -> dict:
    """Shape a CheckResult into the JSON the frontend consumes."""
    engine = result.engine
    max_sev = engine.max_severity()
    return {
        "summary": {
            "resources_checked": engine.resources_checked,
            "violations": len(engine.violations),
            "could_not_assess": len(engine.could_not_assess),
            "severity_counts": engine.severity_counts(),
            "max_severity": str(max_sev) if max_sev is not None else None,
            "by_resource_type": dict(engine.by_resource_type),
        },
        "coverage": [
            {
                "resource_type": c.resource_type,
                "fetched": c.fetched,
                "total": c.total,
                "truncated": c.truncated,
            }
            for c in result.coverage
        ],
        "cap": result.cap,
        "complete": result.complete,
        "violations": [v.as_row() for v in engine.violations],
        "could_not_assess": [c.as_row() for c in engine.could_not_assess],
    }


# ── App factory ──────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(title="my-fhir-app — Data Quality", docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def _localhost_only(request: Request, call_next):
        """Reject any request whose Host header is not a localhost name.

        Mitigates DNS-rebinding: even though we bind to 127.0.0.1, a browser
        tricked into resolving an attacker domain to 127.0.0.1 would still send
        that domain in the Host header — so we check it explicitly.
        """
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip().lower()
        if host not in _ALLOWED_HOSTS:
            return JSONResponse(
                status_code=403,
                content={"error": "forbidden host; this server is localhost-only"},
            )
        return await call_next(request)

    @app.get("/api/rules")
    def list_rules() -> dict:
        """All registered rules, for the 'run one rule' selector."""
        return {
            "rules": [
                {
                    "id": r.id,
                    "description": r.description,
                    "severity": str(r.severity),
                    "resource_types": list(r.resource_types),
                }
                for r in sorted(all_rules(), key=lambda r: r.id)
            ]
        }

    @app.get("/api/resource-types")
    def list_resource_types() -> dict:
        """Resource types covered by at least one rule (also the allowlist)."""
        return {"resource_types": covered_resource_types()}

    @app.post("/api/run")
    def run(req: RunRequest):
        """Run the checker against Medplum and return results + coverage."""
        allowed_types = covered_resource_types()
        types = req.resource_types or allowed_types

        # Validate against the registry allowlist — reject anything unknown.
        unknown = [t for t in types if t not in allowed_types]
        if unknown:
            return JSONResponse(
                status_code=422,
                content={"error": f"unknown resource type(s): {', '.join(unknown)}"},
            )

        disabled: set[str] | None = None
        if req.rule_id is not None:
            if req.rule_id not in all_rule_ids():
                return JSONResponse(
                    status_code=422,
                    content={"error": f"unknown rule id: {req.rule_id}"},
                )
            # "Run one rule" = disable every other rule.
            disabled = all_rule_ids() - {req.rule_id}

        try:
            result = run_check_medplum(
                resource_types=types,
                disabled=disabled,
                limit=req.limit,
            )
        except MedplumError as exc:
            # Surface a clean message (e.g. missing creds / auth failure) instead
            # of a 500 + stack trace. Never echo credentials.
            return JSONResponse(status_code=502, content={"error": str(exc)})

        return _serialize(result)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()
