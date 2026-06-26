"""Minimal Medplum FHIR REST client.

Authenticates with the OAuth2 client-credentials grant and exposes paginated
FHIR search. Credentials are read from the environment (see .env.example):

    MEDPLUM_BASE_URL, MEDPLUM_CLIENT_ID, MEDPLUM_CLIENT_SECRET

This is intentionally small — it returns raw FHIR resource dicts so the rule
engine can stay transport-agnostic.
"""

from __future__ import annotations

import os
import re
import time
from typing import Iterator
from urllib.parse import urljoin, urlsplit

# Medplum throttles by a token-bucket ("points"). On a 429 it reports how long
# until the bucket refills; we honour that rather than guessing a backoff.
_MS_BEFORE_NEXT = re.compile(r"_msBeforeNext\D+(\d+)")

try:
    import httpx
except ImportError:  # pragma: no cover - dependency hint
    raise SystemExit("ERROR: httpx not installed. Run: pip install -r docs/requirements.txt")


class MedplumError(RuntimeError):
    """Raised when Medplum returns an error or credentials are missing."""


class MedplumClient:
    """Thin wrapper over the Medplum FHIR REST API.

    Parameters
    ----------
    base_url, client_id, client_secret:
        Override the values otherwise read from the environment. ``base_url`` is
        the FHIR base (e.g. ``https://api.medplum.com/fhir/R4``).
    token_url:
        OAuth2 token endpoint. Defaults to ``MEDPLUM_TOKEN_URL`` if set,
        otherwise ``{origin}/oauth2/token`` derived from ``base_url`` — Medplum
        serves the token endpoint at the host root, not under ``/fhir/R4``.
    page_size:
        Default ``_count`` used when paginating search results.
    """

    def __init__(
        self,
        base_url: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        token_url: str | None = None,
        page_size: int = 100,
        timeout: float = 30.0,
        max_retries: int = 5,
        max_wait: float = 60.0,
    ) -> None:
        # FHIR base, normalized to a single trailing slash for urljoin().
        self.base_url = (base_url or os.getenv("MEDPLUM_BASE_URL", "")).rstrip("/") + "/"
        self.client_id = client_id or os.getenv("MEDPLUM_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("MEDPLUM_CLIENT_SECRET", "")
        self.token_url = token_url or os.getenv("MEDPLUM_TOKEN_URL", "") or _default_token_url(self.base_url)
        self.page_size = page_size
        # How many times to wait-and-retry on a 429, and the per-wait ceiling.
        self.max_retries = max_retries
        self.max_wait = max_wait
        self._client = httpx.Client(timeout=timeout)
        self._token: str | None = None

    # ── auth ──────────────────────────────────────────────────────────────

    def authenticate(self) -> None:
        """Obtain an access token via the client-credentials grant."""
        if not (self.base_url.strip("/") and self.client_id and self.client_secret):
            raise MedplumError(
                "Missing Medplum credentials. Set MEDPLUM_BASE_URL, "
                "MEDPLUM_CLIENT_ID and MEDPLUM_CLIENT_SECRET (see .env.example)."
            )
        token_url = self.token_url
        resp = self._client.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )
        if resp.status_code != 200:
            raise MedplumError(f"auth failed: {resp.status_code} {resp.text[:200]}")
        self._token = resp.json().get("access_token")
        if not self._token:
            raise MedplumError("auth response did not contain an access_token")

    def _headers(self) -> dict[str, str]:
        if self._token is None:
            self.authenticate()
        return {"Authorization": f"Bearer {self._token}", "Accept": "application/fhir+json"}

    # ── transport (with 429 backoff) ───────────────────────────────────────

    def _send(self, method: str, url: str, **kwargs) -> "httpx.Response":
        """Issue a request, honouring Medplum's 429 throttling.

        On a 429 the response body carries ``_msBeforeNext`` (ms until the rate
        bucket refills). We sleep for that long (capped at :attr:`max_wait`) and
        retry up to :attr:`max_retries` times before returning the last 429 to
        the caller, which raises a :class:`MedplumError`.
        """
        for attempt in range(self.max_retries + 1):
            resp = self._client.request(method, url, **kwargs)
            if resp.status_code != 429 or attempt == self.max_retries:
                return resp
            wait_s = _retry_after_seconds(resp.text)
            time.sleep(min(wait_s, self.max_wait))
        return resp

    # ── search ────────────────────────────────────────────────────────────

    def search(
        self,
        resource_type: str,
        params: dict[str, str] | None = None,
        limit: int = 0,
    ) -> Iterator[dict]:
        """Yield resources of ``resource_type``, following Bundle ``next`` links.

        ``limit`` caps the total number of resources yielded (0 = no cap).
        ``params`` are extra FHIR search parameters (e.g. ``{"status": "final"}``).
        """
        query = {"_count": str(self.page_size)}
        if params:
            query.update(params)
        url: str | None = urljoin(self.base_url, resource_type)
        yielded = 0

        while url:
            resp = self._send("GET", url, params=query, headers=self._headers())
            if resp.status_code != 200:
                raise MedplumError(
                    f"search {resource_type} failed: {resp.status_code} {resp.text[:200]}"
                )
            bundle = resp.json()
            for entry in bundle.get("entry", []):
                resource = entry.get("resource")
                if resource is None:
                    continue
                yield resource
                yielded += 1
                if limit and yielded >= limit:
                    return
            # Follow the Bundle's self-describing `next` link for pagination.
            url = _next_link(bundle)
            query = {}  # the next link already carries its query string

    # ── write ─────────────────────────────────────────────────────────────

    def post_bundle(self, bundle: dict) -> dict:
        """POST a ``transaction``/``batch`` Bundle to the FHIR base root.

        Medplum executes a ``transaction`` Bundle atomically and a ``batch``
        Bundle entry-by-entry, resolving internal ``urn:uuid`` references
        server-side. Returns the response Bundle (each entry carries a
        ``response.status``). Raises :class:`MedplumError` on a non-2xx HTTP
        status — note a 200 can still contain per-entry failures, so callers
        should inspect the returned entries.
        """
        resp = self._send(
            "POST", self.base_url,
            json=bundle,
            headers={**self._headers(), "Content-Type": "application/fhir+json"},
        )
        if resp.status_code >= 300:
            raise MedplumError(f"bundle POST failed: {resp.status_code} {resp.text[:300]}")
        return resp.json()

    def create(self, resource: dict) -> dict:
        """Create a single resource (``POST {base}/{resourceType}``)."""
        resource_type = resource.get("resourceType")
        if not resource_type:
            raise MedplumError("resource has no resourceType")
        url = urljoin(self.base_url, resource_type)
        resp = self._send(
            "POST", url, json=resource,
            headers={**self._headers(), "Content-Type": "application/fhir+json"},
        )
        if resp.status_code >= 300:
            raise MedplumError(
                f"create {resource_type} failed: {resp.status_code} {resp.text[:300]}"
            )
        return resp.json()

    def delete(self, resource_type: str, resource_id: str) -> None:
        """Delete a resource by id (``DELETE {base}/{resourceType}/{id}``).

        A 404 is treated as success (already gone).
        """
        url = urljoin(self.base_url, f"{resource_type}/{resource_id}")
        resp = self._send("DELETE", url, headers=self._headers())
        if resp.status_code >= 300 and resp.status_code != 404:
            raise MedplumError(
                f"delete {resource_type}/{resource_id} failed: "
                f"{resp.status_code} {resp.text[:200]}"
            )

    def count(self, resource_type: str, params: dict[str, str] | None = None) -> int:
        """Return the number of matching resources via ``_summary=count``.

        Cheap — the server returns only ``Bundle.total``, no resources.
        """
        query = {**(params or {}), "_summary": "count"}
        resp = self._send("GET", urljoin(self.base_url, resource_type),
                          params=query, headers=self._headers())
        if resp.status_code != 200:
            raise MedplumError(
                f"count {resource_type} failed: {resp.status_code} {resp.text[:200]}"
            )
        return int(resp.json().get("total", 0))

    # ── async bundles (bypass the FHIR interaction rate limit) ──────────────

    def post_bundle_async(self, bundle: dict) -> str:
        """Submit a Bundle with ``Prefer: respond-async`` and return its job URL.

        Work done inside the async job does not consume the FHIR interaction
        quota, so this is the way to load/delete in bulk on rate-limited hosted
        Medplum. Returns the ``Content-Location`` job-status URL. Raises
        :class:`MedplumError` if the server does not accept it (not ``202``).
        Poll the returned URL with :meth:`async_job_status`.
        """
        headers = {**self._headers(), "Content-Type": "application/fhir+json",
                   "Prefer": "respond-async"}
        resp = self._send("POST", self.base_url, json=bundle, headers=headers)
        if resp.status_code != 202:
            raise MedplumError(
                f"async bundle not accepted: {resp.status_code} {resp.text[:300]}"
            )
        job_url = resp.headers.get("Content-Location")
        if not job_url:
            raise MedplumError("async response missing Content-Location job URL")
        return job_url

    def async_job_status(self, job_url: str) -> tuple[int, str | None]:
        """Poll an async job once. Returns ``(http_status, AsyncJob.status)``.

        ``http_status`` is ``202`` while running and ``200`` when finished; the
        ``AsyncJob.status`` (``accepted``/``completed``/``error``) is only
        populated on ``200``.
        """
        resp = self._send("GET", job_url, headers=self._headers())
        status = resp.json().get("status") if resp.status_code == 200 else None
        return resp.status_code, status

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "MedplumClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _retry_after_seconds(body: str, default: float = 2.0) -> float:
    """Seconds to wait before retrying a 429, parsed from ``_msBeforeNext``.

    Medplum reports the refill delay either at the top level of a 429 body or
    nested in an OperationOutcome ``diagnostics`` string; a regex finds it in
    both. Falls back to ``default`` when absent. Adds a small cushion so the
    bucket has actually refilled by the time we retry.
    """
    match = _MS_BEFORE_NEXT.search(body or "")
    if not match:
        return default
    return int(match.group(1)) / 1000.0 + 0.5


def _next_link(bundle: dict) -> str | None:
    """Return the URL of the Bundle's ``next`` link, if any."""
    for link in bundle.get("link", []):
        if link.get("relation") == "next":
            return link.get("url")
    return None


def _default_token_url(fhir_base_url: str) -> str:
    """Derive Medplum's OAuth2 token endpoint from the FHIR base URL.

    Medplum serves the token endpoint at ``{scheme}://{host}/oauth2/token`` —
    i.e. at the server origin, not under the ``/fhir/R4`` path. Returns "" if
    the base URL has no host yet (credentials not configured).
    """
    parts = urlsplit(fhir_base_url)
    if not parts.scheme or not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}/oauth2/token"
