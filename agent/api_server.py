#!/usr/bin/env python3
"""Vibe-Trading API Server - RESTful API for finance research and backtesting.

Thin assembler: creates the FastAPI app, mounts middleware, registers route
modules, and re-exports symbols for test compatibility.  All shared
infrastructure lives in ``src.api.{security,models,helpers,state}``.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request, status  # noqa: F401
from fastapi.responses import FileResponse  # noqa: F401
from fastapi.middleware.cors import CORSMiddleware
from rich.console import Console

from cli._version import __version__ as APP_VERSION
from src.ui_services import build_run_analysis, load_run_context  # noqa: F401

# UTF-8 on Windows
import sys as _sys
for _s in ("stdout", "stderr"):
    _r = getattr(getattr(_sys, _s, None), "reconfigure", None)
    if callable(_r):
        _r(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Extracted infrastructure — re-exported for route-module and test access
# ---------------------------------------------------------------------------

from src.api.security import (  # noqa: F401, E402
    _API_KEY,
    _CORS_ORIGINS,
    _DEFAULT_CORS_ORIGINS,
    _DEFAULT_LOOPBACK_HOSTS,
    _EXTRA_LOOPBACK_HOSTS,
    _SAFE_BROWSER_METHODS,
    _apply_security_headers,
    _auth_credential_from_header_or_query,
    _configured_api_key,
    _consume_sse_ticket,
    _default_gateway_ips,
    _env_shell_tools_enabled,
    _host_without_port,
    _is_allowed_loopback_host,
    _is_local_client,
    _is_loopback_bind_host,
    _is_loopback_origin,
    _mint_sse_ticket,
    _origin_matches_request_host,
    _parse_cors_origins,
    _parse_extra_cors_origins,
    _parse_extra_loopback_hosts,
    _redact_query_secrets,
    _reject_cross_site_browser_request,
    _reject_untrusted_loopback_host,
    _require_shutdown_authorization,
    _security,
    _shell_tools_enabled_for_request,
    _trusted_docker_loopback_ip,
    _validate_api_auth,
    install_access_log_redaction_filter,
    require_auth,
    require_event_stream_auth,
    require_local_or_auth,
    require_settings_write_auth,
)

from src.api.models import (  # noqa: F401, E402
    Artifact,
    BacktestMetrics,
    RAGSelection,
    RunInfo,
    RunResponse,
)

from src.api.helpers import (  # noqa: F401, E402
    AGENT_DIR,
    ENV_EXAMPLE_PATH,
    ENV_PATH,
    LEGACY_ENV_PATH,
    RUNS_DIR,
    SESSIONS_DIR,
    UPLOADS_DIR,
    _coerce_float,
    _coerce_int,
    _ensure_agent_env_file,
    _format_env_value,
    _FRONTEND_DIST,
    _is_configured_secret,
    _is_spa_html_route,
    _project_relative_path,
    _read_env_values,
    _SAFE_PATH_PARAM_RE,
    _spa_html_deep_link_fallback,
    _strip_env_value,
    _validate_path_param,
    _write_env_values,
)

from src.api.state import (  # noqa: F401, E402
    _channel_bus,
    _channel_manager,
    _channel_runtime,
    _get_channel_runtime,
    _get_session_service,
    _session_service,
)

console = Console()
logger = logging.getLogger(__name__)

from src.api.channels_routes import (  # noqa: E402
    _start_channel_runtime,
    _stop_channel_runtime,
)
from src.api.scheduled_routes import (  # noqa: E402
    _start_scheduled_research_executor,
    _stop_scheduled_research_executor,
)


async def _run_startup_preflight() -> None:
    """Run preflight checks on server startup."""
    from src.preflight import run_preflight

    from src.config import migrate as _migrate

    try:
        _migrate.migrate_legacy_state()  # one-time pre-#904 state move; must never block startup
    except Exception:  # pragma: no cover — best-effort
        logging.getLogger(__name__).warning("Legacy state migration failed", exc_info=True)
    run_preflight(console)
    _start_scheduled_research_executor()
    from src.config.accessor import get_env_config

    if get_env_config().agent_tuning.vibe_trading_channels_auto_start:
        await _start_channel_runtime()


async def _stop_scheduled_research_on_shutdown() -> None:
    """Stop the scheduled research executor on server shutdown."""
    try:
        await _stop_channel_runtime()
    finally:
        await _stop_scheduled_research_executor()


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Run API startup and guaranteed reverse-order shutdown."""
    try:
        await _run_startup_preflight()
        yield
    finally:
        await _stop_scheduled_research_on_shutdown()


app = FastAPI(
    title="Vibe-Trading API",
    description="Vibe-Trading API: natural-language finance research, backtesting, and swarm workflows",
    version=APP_VERSION,
    docs_url=None,  # docs/redoc/openapi re-registered behind require_auth
    redoc_url=None,  # in register_system_routes -- see the rationale there
    openapi_url=None,
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.middleware("http")(_reject_untrusted_loopback_host)
app.middleware("http")(_spa_html_deep_link_fallback)
app.middleware("http")(_apply_security_headers)


# Route registration + re-exports

# --- Runs ---
from src.api.runs_routes import register_runs_routes  # noqa: E402
register_runs_routes(app)

from src.api.runs_routes import (  # noqa: F401, E402
    _load_json_file,
    _load_csv_to_dict,
    _build_response_from_run_dir,
)
from src.api.attribution_routes import register_attribution_routes  # noqa: E402
register_attribution_routes(app)

# --- Sessions ---
from src.api.sessions_routes import register_sessions_routes  # noqa: E402
register_sessions_routes(app)

from src.api.sessions_routes import (  # noqa: F401, E402
    _goal_store,
    _live_action_frame_from_tool_result,
    _mandate_proposal_frame_from_tool_result,
)

# --- System ---
from src.api.system_routes import register_system_routes  # noqa: E402
register_system_routes(app)

from src.api.system_routes import _terminate_current_process  # noqa: F401, E402

# --- Settings ---
from src.api.settings_routes import register_settings_routes  # noqa: E402
register_settings_routes(app)

from src.api.settings_routes import (  # noqa: F401, E402
    _baostock_supported,
    _baostock_installed,
    _load_llm_providers,
)

# --- Uploads ---
from src.api.uploads_routes import register_uploads_routes  # noqa: E402
register_uploads_routes(app)

from src.api.uploads_routes import (  # noqa: F401, E402
    MAX_UPLOAD_SIZE,
    _BLOCKED_UPLOAD_EXT,
    _BLOCKED_UPLOAD_NAMES,
    _SHADOW_ID_RE,
    _UPLOAD_CHUNK_SIZE,
)

# --- Channels ---
from src.api.channels_routes import register_channels_routes  # noqa: E402
register_channels_routes(app)
from src.api.qveris_routes import qveris_router  # noqa: E402  # QVERIS-INTEGRATION
app.include_router(qveris_router)  # QVERIS-INTEGRATION

from src.api.channels_routes import (  # noqa: F401, E402
    ChannelPairingCommandRequest,
)

# --- Swarm ---
from src.api.swarm_routes import register_swarm_routes  # noqa: E402
register_swarm_routes(app)

from src.api.swarm_routes import _get_swarm_runtime  # noqa: F401, E402

# --- Live trading ---
from src.api.live_routes import register_live_routes  # noqa: E402
register_live_routes(app)

# --- Read-only portfolio dashboard ---
from src.api.portfolio_routes import register_portfolio_routes  # noqa: E402
register_portfolio_routes(app)

from src.api.connection_routes import register_connection_routes  # noqa: E402
register_connection_routes(app)

from src.api.live_routes import (  # noqa: F401, E402
    CommitMandateRequest,
    LiveHaltRequest,
    LiveAuthorizeRequest,
    LiveRunnerControlRequest,
    BrokerAuthState,
    MandateLimits,
    ActiveMandateState,
    RunnerLivenessState,
    LiveBrokerStatus,
    LiveStatusResponse,
    LiveRunnerUnavailable,
    _runner_tasks,
    _runner_factory,
    _emit_live_event,
    _fetch_broker_ceilings,
    _known_live_brokers,
    _oauth_token_present,
    _active_mandate_state,
    _runner_liveness_state,
    _live_broker_adapter,
    _build_live_runner,
    _drive_runner,
    _connector_verify_cache,
    _check_connector_status,
)

# --- Alpha Zoo ---
from src.api.alpha_routes import register_alpha_routes  # noqa: E402
register_alpha_routes(app)

# --- Options analysis ---
from src.api.options_routes import register_options_routes  # noqa: E402
register_options_routes(app)

# --- Auth helpers (SSE tickets) ---
from src.api.auth_routes import register_auth_routes  # noqa: E402
register_auth_routes(app)

# --- OpenBB Workspace agent bridge (GET /agents.json, POST /v1/query) ---
# No-op unless the optional `openbb` extra is installed; self-reports either way.
from src.openbb_bridge import try_register_openbb_routes  # noqa: E402  # OPENBB-WORKSPACE-INTEGRATION
try_register_openbb_routes(app)

# --- Scheduled research ---
from src.api.scheduled_routes import register_scheduled_routes  # noqa: E402
register_scheduled_routes(app)

from src.api.scheduled_routes import (  # noqa: E402, F401
    CreateRunFromPlaybookRequest,
    CreateScheduledRunRequest,
    PlaybookResponse,
    ScheduledRunResponse,
    _dispatch_scheduled_research_job,
    _get_scheduled_research_executor,
    _get_scheduled_research_store,
    _scheduled_research_scheduler_enabled,
)


@app.post("/swarm/runs/{run_id}/retry", dependencies=[Depends(require_auth)])
async def retry_swarm_run(run_id: str, http_request: Request):
    """Retry a failed, stale, or cancelled swarm run.

    Creates a new run with the same preset and user_vars as the original.
    """
    _validate_path_param(run_id, "run_id")
    runtime = _get_swarm_runtime()
    loaded = runtime._store.load_run(run_id)
    if not loaded:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    # Reconcile first so a stale "running" run whose host died gets demoted
    # before we gate on status; only a genuinely active run blocks retry.
    from src.swarm.models import RunStatus

    reconciled = runtime._store.reconcile_run(loaded, write=True)
    if reconciled.status == RunStatus.running:
        raise HTTPException(status_code=409, detail="Cannot retry a running run. Cancel it first.")

    try:
        new_run = runtime.start_run(
            reconciled.preset_name,
            reconciled.user_vars or {},
            include_shell_tools=_shell_tools_enabled_for_request(http_request),
        )
        return {"id": new_run.id, "status": new_run.status.value, "preset_name": new_run.preset_name}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============================================================================
# Live trading channel — consent commit + kill switch
# ============================================================================
#
# These are the privileged SURFACE actions of the live-trading channel
# (live-trading SPEC, Consent §1/§3/§4). None is an agent tool:
#   - POST /mandate/commit  -> the single mandate writer (commit_mandate)
#   - POST /live/halt       -> trip the kill switch (P5 trip_halt)
#   - POST /live/resume     -> clear the kill switch (P5 clear_halt)
# Each best-effort relays a mandate.committed / live.halted / live.action event
# through the EXISTING session EventBus, so the frontend's already-wired
# /sessions/{id}/events SSE stream reflects the state change. No new bus.


def _emit_live_event(session_id: Optional[str], event_type: str, data: Dict[str, Any]) -> None:
    """Best-effort relay of a live-channel event through the existing bus.

    The event flows out the existing ``/sessions/{session_id}/events`` SSE
    stream. Notifications never gate autonomy (SPEC Consent §5): a relay failure
    or a missing session is swallowed — the state change already happened on disk.

    Args:
        session_id: Target session, or ``None`` to skip relay.
        event_type: SSE event name (``mandate.committed`` / ``live.halted`` /
            ``live.resumed`` / ``live.action``).
        data: JSON-serializable event payload.
    """
    if not session_id:
        return
    try:
        svc = _get_session_service()
        if svc and svc.get_session(session_id):
            svc.event_bus.emit(session_id, event_type, data)
    except Exception:  # pragma: no cover - relay is non-blocking by contract
        logger.debug("live event relay failed for %s/%s", session_id, event_type, exc_info=True)


# ---- C1: propose_mandate_profiles tool_result -> mandate.proposal SSE frame ----
#
# The agent surfaces a proposal by calling the read-only ``propose_mandate_profiles``
# tool whose tool_result JSON body is ``{"type":"mandate.proposal", ...}`` (SPEC
# Consent §1). The CLI / frontend listen for a TOP-LEVEL ``mandate.proposal`` SSE
# event. ``src/agent/loop.py`` only emits a truncated ``tool_result`` event
# (``preview = result[:200]``) and is PROTECTED — we do NOT edit it. Instead this
# open-file SSE seam (TASKS "Remaining integration items" #1, the recommended
# wiring) detects the propose tool's tool_result on the stream, recovers the
# ``proposal_id`` from the preview, reloads the FULL persisted proposal from the
# proposal store (written by the tool before it returned), and emits the
# ``mandate.proposal`` frame. No protected touch.

_PROPOSAL_TOOL_NAME = "propose_mandate_profiles"
_PROPOSAL_ID_RE = re.compile(r'"proposal_id"\s*:\s*"(mp_[0-9a-f]{32})"')


def _load_full_proposal(proposal_id: str) -> Optional[Dict[str, Any]]:
    """Reload a persisted ``mandate.proposal`` payload by id, broker-agnostic.

    The propose tool persists the full proposal under
    ``<runtime_root>/live/<broker>/proposals/<proposal_id>.json`` before
    returning. The SSE ``tool_result`` preview is too short to carry the full
    body, so the relay reloads it from disk. The broker segment is unknown from
    the preview alone, so every broker's proposals directory is searched.

    Args:
        proposal_id: The ``mp_...`` id parsed from the tool_result preview.

    Returns:
        The full proposal dict, or ``None`` when not found / unreadable.
    """
    try:
        from src.live.paths import live_root

        for proposal_path in live_root().glob(f"*/proposals/{proposal_id}.json"):
            try:
                data = json.loads(proposal_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and data.get("type") == "mandate.proposal":
                return data
    except Exception:  # pragma: no cover - relay must never break the stream
        logger.debug("mandate.proposal reload failed for %s", proposal_id, exc_info=True)
    return None


def _mandate_proposal_frame_from_tool_result(event: Any) -> Optional[str]:
    """Build a ``mandate.proposal`` SSE frame from a propose-tool tool_result.

    Args:
        event: An ``SSEEvent`` flowing through the session stream.

    Returns:
        A ready-to-yield SSE text frame for the ``mandate.proposal`` event, or
        ``None`` when ``event`` is not a successful propose-tool result or the
        proposal cannot be recovered.
    """
    data = getattr(event, "data", None)
    if getattr(event, "event_type", None) != "tool_result" or not isinstance(data, dict):
        return None
    if data.get("tool") != _PROPOSAL_TOOL_NAME or data.get("status") != "ok":
        return None
    match = _PROPOSAL_ID_RE.search(str(data.get("preview") or ""))
    if not match:
        return None
    proposal = _load_full_proposal(match.group(1))
    if proposal is None:
        return None

    from src.session.events import SSEEvent

    frame = SSEEvent(
        event_type="mandate.proposal",
        data=proposal,
        session_id=getattr(event, "session_id", "") or "",
    )
    return frame.to_sse()


_LIVE_ACTION_ID_RE = re.compile(r'"audit_id"\s*:\s*"(la_[0-9a-zA-Z]+)"')


def _load_live_action_record(audit_id: str) -> Optional[Dict[str, Any]]:
    """Reload a redacted live-action record from the ledger by ``audit_id``.

    The order guard embeds its (already-redacted) audit record under the
    ``live_action`` key of its tool_result, but the SSE ``tool_result`` preview
    is truncated to ~200 chars, so the full record is reloaded from the
    append-only ledger at ``<runtime_root>/live/audit.jsonl``.

    Args:
        audit_id: The ``la_...`` id parsed from the tool_result preview.

    Returns:
        The full redacted live-action record, or ``None`` when not found.
    """
    try:
        from src.live.paths import live_root

        ledger = live_root() / "audit.jsonl"
        if not ledger.exists():
            return None
        for line in reversed(ledger.read_text(encoding="utf-8").splitlines()):
            if audit_id not in line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and record.get("audit_id") == audit_id:
                return record
    except Exception:  # pragma: no cover - relay must never break the stream
        logger.debug("live.action reload failed for %s", audit_id, exc_info=True)
    return None


def _live_action_frame_from_tool_result(event: Any) -> Optional[str]:
    """Build a ``live.action`` SSE frame from an order-guard tool_result.

    The order guard stamps a ``live_action`` audit record onto its tool_result
    (and the ledger) for every live order placed/rejected. The interactive agent
    loop only emits a truncated ``tool_result`` event and is PROTECTED, so this
    open-file relay surfaces the live action as a top-level ``live.action`` event
    for the timeline — without touching ``src/agent/loop.py``. (Autonomous-runner
    actions already emit ``live.action`` natively via the runner's event bus.)

    Args:
        event: An ``SSEEvent`` flowing through the session stream.

    Returns:
        A ready-to-yield ``live.action`` SSE frame, or ``None`` when the event is
        not an order-guard result carrying a recoverable live-action record.
    """
    data = getattr(event, "data", None)
    if getattr(event, "event_type", None) != "tool_result" or not isinstance(data, dict):
        return None
    preview = str(data.get("preview") or "")
    if '"live_action"' not in preview:
        return None
    match = _LIVE_ACTION_ID_RE.search(preview)
    if not match:
        return None
    record = _load_live_action_record(match.group(1))
    if record is None:
        return None

    from src.session.events import SSEEvent

    frame = SSEEvent(
        event_type="live.action",
        data=record,
        session_id=getattr(event, "session_id", "") or "",
    )
    return frame.to_sse()


def _fetch_broker_ceilings(broker: str) -> Optional[Dict[str, Any]]:
    """Best-effort fetch of broker-side account ceilings for the commit re-check.

    Reads the broker's mapped account/portfolio tool and derives an authoritative
    ceiling snapshot (buying power / funding) so the commit-time fit check binds
    to the venue's real limits rather than an agent-proposed number. Returns
    ``None`` on any failure (channel not configured, tool error, fields not
    recognized) so the caller falls back to the proposal's own snapshot — a
    commit is never blocked on a broker read.

    Args:
        broker: The live-broker key.

    Returns:
        A ceilings dict (canonical keys) or ``None`` to fall back.
    """
    try:
        adapter = _live_broker_adapter(broker)
    except LiveRunnerUnavailable:
        return None
    try:
        from src.trading.service import runner_tool_name

        account_tool = runner_tool_name(broker, "account") or "get_account"
        result = adapter.call_tool(account_tool, {})
    except Exception:  # pragma: no cover - status/commit must never raise here
        logger.debug("broker ceiling fetch failed for %s", broker, exc_info=True)
        return None
    if not isinstance(result, dict) or result.get("status") == "error":
        return None
    payload = result.get("result") if isinstance(result.get("result"), dict) else result
    funding: Optional[float] = None
    for key in ("account_funding_usd", "buying_power", "cash", "portfolio_value", "equity"):
        raw = payload.get(key) if isinstance(payload, dict) else None
        try:
            if raw is not None:
                funding = float(raw)
                break
        except (TypeError, ValueError):
            continue
    if funding is None or funding <= 0:
        return None
    # A single order can never exceed available funding; total exposure is capped
    # at funding for a cash account. Leverage stays at 1.0 unless the broker
    # reports margin (L6). These canonical keys are normalized by commit_mandate.
    return {
        "account_funding_usd": funding,
        "max_order_notional_usd": funding,
        "max_total_exposure_usd": funding,
    }


@app.post("/mandate/commit", dependencies=[Depends(require_auth)])
async def commit_mandate_endpoint(payload: CommitMandateRequest):
    """Commit a user-selected mandate profile — the only mandate write path.

    Calls :func:`src.live.mandate.commit.commit_mandate`, which re-validates the
    proposal is live and the resolved profile still fits the ceilings the user
    saw. Requires ``consent_ack=true`` (rejected otherwise). On success emits a
    ``mandate.committed`` + ``live.action`` event so all surfaces reflect the
    newly active mandate.
    """
    if payload.consent_ack is not True:
        raise HTTPException(status_code=400, detail="consent_ack must be true to commit a mandate")

    from src.live.mandate.commit import CommitError, commit_mandate

    # Prefer broker-DERIVED ceilings over the agent-supplied proposal snapshot:
    # the commit re-check should bind to the venue's real account limits, not a
    # number the model proposed. Best-effort — falls back to the proposal's own
    # ceilings (commit_mandate handles ceilings_ref=None) when the broker channel
    # is unavailable or the read fails (we never block a commit on a broker read).
    broker_ceilings = _fetch_broker_ceilings(payload.broker)

    try:
        result = commit_mandate(
            proposal_id=payload.proposal_id,
            ordinal=payload.selected_ordinal,
            adjustments=payload.adjustments,
            consent_ack=payload.consent_ack,
            broker=payload.broker,
            account_ref=payload.account_ref,
            session_id=payload.session_id,
            ceilings_ref=broker_ceilings,
            lifetime_days=payload.lifetime_days,
        )
    except CommitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _emit_live_event(payload.session_id, "mandate.committed", result)
    _emit_live_event(
        payload.session_id,
        "live.action",
        {"kind": "mandate_committed", "broker": result["broker"], "mandate_id": result["mandate_id"]},
    )
    return result


@app.post("/live/halt", dependencies=[Depends(require_auth)])
async def halt_live_endpoint(payload: LiveHaltRequest):
    """Trip the live kill switch (privileged surface action, Consent §4).

    Writes the HALT sentinel via :func:`src.live.halt.trip_halt`; the
    enforcement gate then rejects every order attempt until resumed. Emits a
    ``live.halted`` event so all surfaces reflect the halted state.
    """
    from src.live.halt import trip_halt

    try:
        path = trip_halt(by="frontend", reason=payload.reason, broker=payload.broker)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = {"halted": True, "broker": payload.broker, "reason": payload.reason, "sentinel": str(path)}
    _emit_live_event(payload.session_id, "live.halted", result)
    _emit_live_event(
        payload.session_id,
        "live.action",
        {"kind": "halt_tripped", "broker": payload.broker, "reason": payload.reason},
    )
    return result


@app.post("/live/resume", dependencies=[Depends(require_auth)])
async def resume_live_endpoint(payload: LiveHaltRequest):
    """Clear the live kill switch (privileged surface action, Consent §4).

    Deletes the HALT sentinel via :func:`src.live.halt.clear_halt` (an explicit
    re-enable; never an agent tool). Emits a ``live.resumed`` event.
    """
    from src.live.halt import clear_halt

    try:
        cleared = clear_halt(broker=payload.broker)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = {"halted": False, "broker": payload.broker, "cleared": cleared}
    _emit_live_event(payload.session_id, "live.resumed", result)
    _emit_live_event(
        payload.session_id,
        "live.action",
        {"kind": "halt_cleared", "broker": payload.broker, "cleared": cleared},
    )
    return result


# ============================================================================
# Live trading channel — status, authorize on-ramp, runner control (C2 + §7.5)
# ============================================================================
#
# C2 surfaces the dormant-by-default channel state so a user can SEE what is and
# is not authorized before trusting it: per-broker OAuth presence, the active
# mandate with its expiry countdown, runner liveness, and the kill-switch state.
# The runner-control endpoints start/stop the persistent §7.5 runner that trades
# autonomously inside a committed mandate. None of these is an agent tool; they
# are privileged surface actions like /mandate/commit and /live/halt.


def _known_live_brokers() -> List[str]:
    """Return the recognized live-broker keys (SPEC §7.2)."""
    from src.config.schema import LIVE_BROKER_SERVER_KEYS

    return sorted(LIVE_BROKER_SERVER_KEYS)


def _oauth_token_present(broker: str) -> bool:
    """Return whether an OAuth token cache exists for a broker (C2 auth state).

    The token cache lives at ``<runtime_root>/live/<broker>/oauth/`` (0700) and
    is created only when the user OAuth-authorizes the channel. A missing or
    empty directory means the channel is dormant (read-only, no live path).
    """
    try:
        from src.live.paths import broker_dir

        oauth_dir = broker_dir(broker) / "oauth"
        return oauth_dir.is_dir() and any(oauth_dir.iterdir())
    except Exception:  # pragma: no cover - status must never raise
        logger.debug("oauth presence check failed for %s", broker, exc_info=True)
        return False


def _active_mandate_state(broker: str) -> Optional[ActiveMandateState]:
    """Build the active-mandate snapshot for a broker, or ``None`` when absent.

    Reads the committed mandate via the frozen store contract and computes the
    ``expires_at`` countdown (SPEC §9 dec. 2). A mandate whose ``expires_at`` has
    passed is still surfaced, flagged ``expired`` so the UI can prompt re-consent.
    """
    from src.live.mandate.store import load_mandate

    mandate = load_mandate(broker)
    if mandate is None:
        return None

    consent = mandate.consent
    caps = mandate.hard_caps
    expires_in: Optional[int] = None
    expired = False
    try:
        expires_dt = datetime.fromisoformat(consent.expires_at.replace("Z", "+00:00"))
        from datetime import timezone

        now = datetime.now(timezone.utc)
        if expires_dt.tzinfo is None:
            expires_dt = expires_dt.replace(tzinfo=timezone.utc)
        delta = expires_dt - now
        expires_in = int(delta.total_seconds())
        expired = expires_in <= 0
    except (ValueError, AttributeError):
        logger.debug("could not parse expires_at for %s mandate", broker, exc_info=True)

    return ActiveMandateState(
        broker=broker,
        account_ref=consent.account_ref,
        created_at=consent.created_at,
        expires_at=consent.expires_at,
        expires_in_seconds=expires_in,
        expired=expired,
        limits=MandateLimits(
            max_order_notional_usd=caps.max_order_notional_usd,
            max_total_exposure_usd=caps.max_total_exposure_usd,
            max_leverage=caps.max_leverage,
            max_trades_per_day=caps.max_trades_per_day,
            allowed_instruments=[str(getattr(i, "value", i)) for i in caps.allowed_instruments],
            account_funding_usd=caps.account_funding_usd,
        ),
    )


def _runner_liveness_state(broker: str) -> RunnerLivenessState:
    """Build the runner-liveness snapshot for a broker (SPEC §7.5 contract).

    Uses the §7.5 ``liveness`` module (``is_runner_alive`` / ``last_tick``),
    keyed by broker as the runner id. The module is built concurrently (R1); a
    missing module or any error is treated as "not alive" (fail-safe display).
    """
    alive = False
    tick: Optional[float] = None
    age: Optional[float] = None
    try:
        from src.live.runtime import liveness

        alive = bool(liveness.is_runner_alive(broker))
        raw_tick = liveness.last_tick(broker)
        if raw_tick is not None:
            tick = float(raw_tick)
            age = max(0.0, time.time() - tick)
    except Exception:  # pragma: no cover - liveness module is built concurrently
        logger.debug("runner liveness lookup failed for %s", broker, exc_info=True)

    return RunnerLivenessState(broker=broker, alive=alive, last_tick=tick, last_tick_age_seconds=age)


@app.get("/live/status", response_model=LiveStatusResponse, dependencies=[Depends(require_auth)])
async def live_status_endpoint(broker: Optional[str] = Query(None, max_length=64)):
    """Return live-channel status: auth, active mandate, runner liveness, halt (C2).

    Args:
        broker: Optional single-broker filter. When omitted, every recognized
            live broker is reported.

    Returns:
        A :class:`LiveStatusResponse` with the global kill-switch state and a
        per-broker breakdown so the UI can show exactly what is authorized.
    """
    from src.live.halt import halt_flag_set

    if broker is not None:
        target = broker.strip().lower()
        if not target:
            raise HTTPException(status_code=400, detail="broker must not be blank")
        brokers = [target]
    else:
        brokers = _known_live_brokers()

    known = set(_known_live_brokers())
    statuses: List[LiveBrokerStatus] = []
    for key in brokers:
        statuses.append(
            LiveBrokerStatus(
                auth=BrokerAuthState(
                    broker=key,
                    oauth_token_present=_oauth_token_present(key),
                    is_live_broker=key in known,
                ),
                mandate=_active_mandate_state(key),
                runner=_runner_liveness_state(key),
                halted=halt_flag_set(broker=key),
            )
        )

    return LiveStatusResponse(global_halted=halt_flag_set(broker=None), brokers=statuses)


@app.post("/live/authorize", dependencies=[Depends(require_auth)])
async def live_authorize_endpoint(payload: LiveAuthorizeRequest):
    """Describe the OAuth bootstrap on-ramp for a live broker (C2 web on-ramp).

    Vibe-Trading holds no funds and runs no venue: the OAuth flow happens on the
    broker's own user-authorized device channel (CLI / desktop MCP), never a
    server-side redirect. A Web UI user reaches this endpoint to DISCOVER how to
    start the flow. It performs no authorization itself and never returns a token.
    """
    broker = payload.broker.strip().lower()
    if not broker:
        raise HTTPException(status_code=400, detail="broker must not be blank")
    if broker not in set(_known_live_brokers()):
        raise HTTPException(status_code=400, detail=f"unknown live broker: {broker}")

    from src.trading.service import connector_profile_id_for_broker

    connector_profile = connector_profile_id_for_broker(broker)
    return {
        "broker": broker,
        "connector_profile": connector_profile,
        "oauth_token_present": _oauth_token_present(broker),
        "instruction": (
            f"Run `vibe-trading connector authorize {connector_profile}` "
            "from the device that will hold the broker session. This opens the "
            "broker's own OAuth consent flow; Vibe-Trading never holds funds and "
            "only relays intent once you authorize."
        ),
        "note": (
            "The live channel stays read-only until the OAuth token is present AND a "
            "mandate is committed AND order tools are explicitly enabled."
        ),
    }


# ---- Runner control (SPEC §7.5): start / stop the persistent live runner ----
#
# A LiveRunner (R2 contract: ``LiveRunner(broker)`` with ``run_loop()`` /
# ``run_once()``) is driven in a background task per broker. The factory is
# injectable (``_runner_factory``) so tests stub it with no real agent/broker.
# ``run_loop`` may be sync (long-blocking) or async; both are supported.

_runner_tasks: Dict[str, "asyncio.Task[Any]"] = {}
_runner_factory: Optional[Any] = None


class LiveRunnerUnavailable(RuntimeError):
    """Raised when a live runner cannot be wired (broker not configured/authorized).

    Distinct from a programming error so the start endpoint can map it to a 503
    rather than a 500: the runtime is fine, the broker channel just isn't ready.
    """


def _live_broker_adapter(broker: str) -> Any:
    """Build an ``MCPServerAdapter`` for a live broker from the user-side config.

    Resolves the broker's MCP server entry by config key OR by a live-broker URL
    host (so an aliased key still resolves), mirroring the registry's detection.

    Args:
        broker: The live-broker key, e.g. ``"robinhood"``.

    Returns:
        A constructed :class:`MCPServerAdapter` for the broker's read/write tools.

    Raises:
        LiveRunnerUnavailable: When no MCP server is configured for the broker.
    """
    from src.config.loader import load_agent_config
    from src.tools.mcp import MCPServerAdapter

    try:
        from src.config.schema import is_live_broker_entry
    except Exception:  # pragma: no cover - older schema without URL detection
        is_live_broker_entry = None  # type: ignore[assignment]

    cfg = load_agent_config()
    servers = getattr(cfg, "mcp_servers", {}) or {}
    for name, server_cfg in servers.items():
        is_match = name == broker
        if not is_match and is_live_broker_entry is not None and broker == "robinhood":
            try:
                is_match = is_live_broker_entry(name, server_cfg)
            except Exception:  # pragma: no cover
                is_match = False
        if is_match:
            return MCPServerAdapter(name, server_cfg)
    raise LiveRunnerUnavailable(f"no MCP server configured for live broker {broker!r}")


def _build_live_runner(broker: str) -> Any:
    """Construct a fully-wired ``LiveRunner`` for a broker (SPEC §7.5 R-INT).

    Wires the runner to the real surfaces — the public ``SessionService`` agent
    caller (never the protected loop internals), the broker's READ/WRITE MCP
    tools, the R4 reconciler, the R1 scheduler, and R3 market-hours triggers —
    and injects an audit ``event_callback`` so every autonomous live action is
    broadcast as a ``live.action`` SSE event on the runner's session bus.

    Args:
        broker: The live-broker key.

    Returns:
        A runner object exposing ``run_loop`` / ``run_once`` (R2 contract).

    Raises:
        LiveRunnerUnavailable: When the broker channel is not configured.
    """
    if _runner_factory is not None:
        return _runner_factory(broker)

    from src.live.audit import write_live_action
    from src.live.runtime.reconcile import reconcile
    from src.live.runtime.runner import LiveRunner
    from src.live.runtime.scheduler import Scheduler
    from src.live.runtime.triggers import Trigger
    from src.trading.service import runner_tool_name

    def _tool(operation: str) -> str:
        remote_tool = runner_tool_name(broker, operation)
        if remote_tool is None:
            raise LiveRunnerUnavailable(
                f"live runner for {broker!r} does not define remote tool {operation!r}"
            )
        return remote_tool

    positions_tool = _tool("positions")
    balance_tool = _tool("account")
    open_orders_tool = _tool("orders")
    submit_order_tool = _tool("submit_order")
    cancel_order_tool = _tool("cancel_order")
    adapter = _live_broker_adapter(broker)  # raises LiveRunnerUnavailable if absent

    def _read(remote_tool: str):
        """A zero-arg broker READ callable bound to one remote tool."""
        return lambda: adapter.call_tool(remote_tool, {})

    def _submit(order: Dict[str, Any]) -> Dict[str, Any]:
        # Route the flatten sweep's normalized order to the broker's write tools.
        # Field mapping against the real Robinhood schema is finalized post-access
        # (L6); the action discriminator is broker-agnostic.
        if order.get("action") == "cancel":
            return adapter.call_tool(cancel_order_tool, order)
        return adapter.call_tool(submit_order_tool, order)

    svc = _get_session_service()
    session = svc.create_session(title=f"live-runner:{broker}")
    session_id = session.session_id

    async def _agent_caller(sid: str, prompt: str) -> Dict[str, Any]:
        # Dispatch one autonomous turn through the PUBLIC SessionService entry.
        # The agent then trades within the mandate via the gated order tools.
        return await svc.send_message(sid, prompt)

    def _audit_with_bus(event: Any) -> Dict[str, Any]:
        # Broadcast each live action as a live.action SSE event on the runner's
        # session bus (no protected-loop touch — the runner owns its session).
        return write_live_action(
            event,
            event_callback=lambda etype, record: svc.event_bus.emit(session_id, etype, record),
        )

    # Wire the scheduler's fire callback to the runner's tick. The scheduler is
    # constructed before the runner (it needs on_fire), and the runner needs the
    # scheduler, so late-bind via a holder to break the cycle.
    runner_holder: Dict[str, Any] = {}

    async def _on_fire(_job: Any) -> None:
        runner = runner_holder.get("runner")
        if runner is not None:
            await runner.run_once()

    scheduler = Scheduler(_on_fire)

    runner = LiveRunner(
        broker,
        agent_caller=_agent_caller,
        reconcile_fn=reconcile,
        read_positions=_read(positions_tool),
        read_balance=_read(balance_tool),
        read_open_orders=_read(open_orders_tool),
        submit_fn=_submit,
        write_audit_fn=_audit_with_bus,
        scheduler=scheduler,
        triggers=[Trigger.market("us_equity")],
        session_id=session_id,
    )
    runner_holder["runner"] = runner
    return runner


async def _drive_runner(runner: Any) -> None:
    """Run a runner's ``run_loop`` to completion, sync or async.

    A synchronous ``run_loop`` is offloaded to a worker thread so it does not
    block the event loop; an async ``run_loop`` is awaited directly.
    """
    result = runner.run_loop()
    if asyncio.iscoroutine(result):
        await result
    else:
        await asyncio.get_running_loop().run_in_executor(None, lambda: result)


@app.post("/live/runner/start", dependencies=[Depends(require_auth)])
async def start_runner_endpoint(payload: LiveRunnerControlRequest):
    """Start the persistent live runner for a broker (SPEC §7.5).

    Refuses to start unless a committed, unexpired mandate exists and the kill
    switch is clear — the runner trades autonomously, so it must not start into a
    dead/halted channel. Idempotent: a request for an already-running broker
    returns ``already_running`` without spawning a second task.
    """
    from src.live.halt import halt_flag_set

    broker = payload.broker.strip().lower()
    if not broker:
        raise HTTPException(status_code=400, detail="broker must not be blank")
    from src.trading.service import broker_supports_live_runner

    if not broker_supports_live_runner(broker):
        raise HTTPException(
            status_code=400,
            detail=f"live runner is not supported for {broker}",
        )

    existing = _runner_tasks.get(broker)
    if existing is not None and not existing.done():
        return {"broker": broker, "started": False, "already_running": True}

    mandate = _active_mandate_state(broker)
    if mandate is None:
        raise HTTPException(status_code=409, detail=f"no committed mandate for {broker}")
    if mandate.expired:
        raise HTTPException(status_code=409, detail=f"mandate for {broker} has expired; re-authorize first")
    if halt_flag_set(broker=broker) or halt_flag_set(broker=None):
        raise HTTPException(status_code=409, detail="kill switch is tripped; resume before starting the runner")

    try:
        runner = _build_live_runner(broker)
    except LiveRunnerUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"could not construct runner: {exc}") from exc

    task = asyncio.ensure_future(_drive_runner(runner))
    _runner_tasks[broker] = task
    task.add_done_callback(
        lambda t, b=broker: _runner_tasks.pop(b, None) if _runner_tasks.get(b) is t else None
    )

    _emit_live_event(
        payload.session_id,
        "live.action",
        {"kind": "runner_started", "broker": broker},
    )
    return {"broker": broker, "started": True, "already_running": False}


@app.post("/live/runner/stop", dependencies=[Depends(require_auth)])
async def stop_runner_endpoint(payload: LiveRunnerControlRequest):
    """Stop the persistent live runner for a broker (SPEC §7.5).

    Cancels the background task. This does NOT flatten positions — that is the
    preemptive kill switch's job (``/live/halt`` -> flatten); stopping the runner
    simply ceases new autonomous turns. Idempotent for an already-stopped broker.
    """
    broker = payload.broker.strip().lower()
    if not broker:
        raise HTTPException(status_code=400, detail="broker must not be blank")
    from src.trading.service import broker_supports_live_runner

    if not broker_supports_live_runner(broker):
        raise HTTPException(
            status_code=400,
            detail=f"live runner is not supported for {broker}",
        )

    task = _runner_tasks.pop(broker, None)
    if task is None or task.done():
        return {"broker": broker, "stopped": False, "was_running": False}

    task.cancel()
    _emit_live_event(
        payload.session_id,
        "live.action",
        {"kind": "runner_stopped", "broker": broker},
    )
    return {"broker": broker, "stopped": True, "was_running": True}


# ============================================================================
# Ranking routes — top stocks by 20-day volume / amount
# ============================================================================

from pydantic import BaseModel as PydanticBaseModel2


class RankingItem(PydanticBaseModel2):
    rank: int
    code: str
    name: str
    total_volume: float
    total_amount: float
    float_market_cap: float = 0.0


def _connect_ranking_db():
    """Open the market database read-only for ranking views."""
    from src.analytics.connection import connect_market_db

    return connect_market_db()


@app.get(
    "/analytics/recipes",
    dependencies=[Depends(require_auth)],
)
async def analytics_recipes():
    """List registered local analytics recipes."""
    from src.analytics import list_recipes

    return list_recipes()


@app.get(
    "/analytics/{recipe_id}",
    dependencies=[Depends(require_auth)],
)
async def analytics_run(recipe_id: str, request: Request):
    """Run a registered local analytics recipe."""
    from src.analytics import AnalyticsError, run_analysis

    try:
        return run_analysis(recipe_id, dict(request.query_params))
    except AnalyticsError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("analytics_run failed for recipe %s", recipe_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Analytics data unavailable: {exc}",
        ) from exc


@app.get(
    "/ranking/top-volume",
    response_model=list[RankingItem],
    dependencies=[Depends(require_auth)],
)
async def ranking_top_volume(
    days: int = Query(20, ge=1, le=120, description="Number of trading days to aggregate"),
    limit: int = Query(100, ge=1, le=200, description="Max results"),
):
    """Top stocks by total volume over the last N trading days.

    Reads from the DuckDB database populated by ``python -m src.data download``.
    Returns an empty list when no data is available.
    """
    limit = min(max(1, limit), 200)
    try:
        conn = _connect_ranking_db()
        try:
            from src.analytics import run_analysis

            analysis = run_analysis("top-volume", {"days": days, "limit": limit}, conn=conn)
        finally:
            conn.close()

        results: list[RankingItem] = []
        for row in analysis["rows"]:
            results.append(RankingItem(
                rank=int(row["rank"]),
                code=str(row["code"]),
                name=str(row["name"]),
                total_volume=float(row["total_volume"] or 0),
                total_amount=float(row["total_amount"] or 0),
                float_market_cap=float(row["float_market_cap"] or 0),
            ))
        return results
    except Exception as exc:
        logger.exception("ranking_top_volume failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Ranking data unavailable: {exc}",
        ) from exc


# ============================================================================
# Alpha Zoo routes (Web UI) — defined in src/api/alpha_routes.py
# ============================================================================

from src.api.alpha_routes import register_alpha_routes  # noqa: E402
register_alpha_routes(app)


# ============================================================================
# Scheduled Research Routes
# ============================================================================
#
# Lightweight CRUD endpoints backed by ScheduledResearchJobStore. The endpoint
# handlers only record and expose jobs; the optional executor lifecycle is
# guarded separately by VIBE_TRADING_ENABLE_SCHEDULER.


_SCHEDULED_RESEARCH_SCHEDULER_ENV = "VIBE_TRADING_ENABLE_SCHEDULER"
_SCHEDULED_RESEARCH_TRUE_VALUES = {"1", "true", "yes", "on"}

_scheduled_research_store: Optional["ScheduledResearchJobStore"] = None
_scheduled_research_executor: Optional["ScheduledResearchExecutor"] = None


def _get_scheduled_research_store() -> "ScheduledResearchJobStore":
    """Return the singleton ScheduledResearchJobStore, creating it on first call."""
    global _scheduled_research_store
    if _scheduled_research_store is None:
        from src.scheduled_research.store import ScheduledResearchJobStore

        _scheduled_research_store = ScheduledResearchJobStore()
    return _scheduled_research_store


def _scheduled_research_scheduler_enabled() -> bool:
    """Return whether scheduled research execution is enabled."""
    return os.getenv(_SCHEDULED_RESEARCH_SCHEDULER_ENV, "").strip().lower() in _SCHEDULED_RESEARCH_TRUE_VALUES


async def _dispatch_scheduled_research_job(job: "ScheduledResearchJob") -> None:
    """Enqueue one scheduled research job through the session runtime.

    ``send_message`` queues the agent attempt and returns once accepted; it
    does not wait for that agent run to reach a terminal status. The executor's
    ``COMPLETED`` state for this dispatch path means "successfully enqueued."
    """
    svc = _get_session_service()
    if not svc:
        raise RuntimeError("Session runtime not enabled")
    # Pass a copy so the session runtime's internal config writes (e.g.
    # include_shell_tools) do not mutate the persisted scheduled-run config.
    session = svc.create_session(title=f"scheduled-research:{job.id}", config=dict(job.config))
    logger.info("dispatching scheduled research job %s via session %s", job.id, session.session_id)
    await svc.send_message(session.session_id, job.prompt)


def _get_scheduled_research_executor() -> "ScheduledResearchExecutor":
    """Return the singleton scheduled research executor."""
    global _scheduled_research_executor
    if _scheduled_research_executor is None:
        from src.scheduled_research.executor import ScheduledResearchExecutor

        _scheduled_research_executor = ScheduledResearchExecutor(
            _get_scheduled_research_store(),
            _dispatch_scheduled_research_job,
            enabled=_scheduled_research_scheduler_enabled(),
        )
    return _scheduled_research_executor


def _start_scheduled_research_executor() -> None:
    """Start scheduled research execution when explicitly enabled."""
    if not _scheduled_research_scheduler_enabled():
        return
    _get_scheduled_research_executor().start()


async def _stop_scheduled_research_executor() -> None:
    """Stop scheduled research execution if it was started."""
    executor = _scheduled_research_executor
    if executor is not None:
        await executor.stop()


class CreateScheduledRunRequest(BaseModel):
    """Request body for POST /scheduled-runs."""

    id: Optional[str] = Field(None, description="Job id; auto-generated UUID when omitted")
    prompt: str = Field(..., min_length=1, description="Research prompt or backtest description")
    schedule: str = Field(..., min_length=1, description="Interval-ms or 5-field cron expression")
    next_run_at: Optional[int] = Field(None, description="Epoch-ms for next run; defaults to now")
    config: Dict[str, Any] = Field(default_factory=dict, description="Optional backtest parameters")


class ScheduledRunResponse(BaseModel):
    """API response for a single scheduled job."""

    id: str
    prompt: str
    schedule: str
    next_run_at: int
    status: str
    created_at: int
    config: Dict[str, Any] = Field(default_factory=dict)


@app.post(
    "/scheduled-runs",
    response_model=ScheduledRunResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_auth)],
)
async def create_scheduled_run(request: CreateScheduledRunRequest) -> ScheduledRunResponse:
    """Create (or replace) a scheduled research job.

    The job is persisted immediately. No execution is triggered.
    """
    import time

    from src.scheduled_research.models import JobStatus, ScheduledResearchJob
    from src.scheduled_research.models import validate_schedule

    try:
        validate_schedule(request.schedule)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    now_ms = int(time.time() * 1000)
    job = ScheduledResearchJob(
        id=request.id or str(uuid.uuid4()),
        prompt=request.prompt,
        schedule=request.schedule,
        next_run_at=request.next_run_at if request.next_run_at is not None else now_ms,
        status=JobStatus.PENDING,
        created_at=now_ms,
        config=request.config,
    )
    _get_scheduled_research_store().upsert(job)
    return ScheduledRunResponse(**job.to_dict())


@app.get(
    "/scheduled-runs",
    response_model=List[ScheduledRunResponse],
    dependencies=[Depends(require_auth)],
)
async def list_scheduled_runs(
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
) -> List[ScheduledRunResponse]:
    """List scheduled research jobs, optionally filtered by status."""
    jobs = _get_scheduled_research_store().list_jobs(status=status_filter, limit=limit)
    return [ScheduledRunResponse(**j.to_dict()) for j in jobs]


@app.delete(
    "/scheduled-runs/{job_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_auth)],
)
async def delete_scheduled_run(job_id: str) -> None:
    """Cancel (delete) a scheduled research job by id."""
    _validate_path_param(job_id, "job_id")
    removed = _get_scheduled_research_store().delete(job_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"scheduled run {job_id} not found")


# ============================================================================
# Main Entry Point
# ============================================================================

def serve_main(argv: list[str] | None = None) -> int:
    """Start the API server from CLI-style arguments."""
    import argparse
    import subprocess
    import uvicorn
    from src.api.spa import SPAStaticFiles

    parser = argparse.ArgumentParser(description="Vibe-Trading Server")
    parser.add_argument("--port", type=int, default=8000, help="Listen port (default 8000)")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address")
    parser.add_argument("--dev", action="store_true", help="Dev mode: spawn Vite on :5173")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2

    if not _is_loopback_bind_host(args.host) and not _configured_api_key():
        print(
            f"[warn] Binding to {args.host} without API_AUTH_KEY set. "
            f"Remote requests are rejected by the loopback peer-IP check, "
            f"but consider using --host 127.0.0.1 for local-only access."
        )

    frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    frontend_root = Path(__file__).resolve().parent.parent / "frontend"

    vite_proc = None
    if args.dev and frontend_root.exists():
        print("[dev] Starting Vite dev server on :5173 ...")
        vite_proc = subprocess.Popen(
            ["npx", "vite", "--host", "0.0.0.0"],
            cwd=str(frontend_root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"[dev] Vite PID={vite_proc.pid}")
        print("[dev] Frontend: http://localhost:5173")
        print(f"[dev] API: http://localhost:{args.port}")
    elif frontend_dist.exists():
        if not any(getattr(route, "path", None) == "/" for route in app.routes):
            app.mount("/", SPAStaticFiles(directory=str(frontend_dist), html=True), name="frontend")
        print(f"[prod] Frontend served from {frontend_dist}")
    else:
        print(f"[warn] No frontend build found at {frontend_dist}")
        print("[warn] Run: cd frontend && npm run build")

    print("=" * 50)
    print("  Vibe-Trading Server")
    print(f"  http://127.0.0.1:{args.port}")
    print("=" * 50)

    # Redact api_key=/ticket= values from Uvicorn's access log (it logs the full
    # request line including the query string). Installed before run() so the
    # filter is attached when Uvicorn configures its loggers.
    install_access_log_redaction_filter()

    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    finally:
        if vite_proc:
            vite_proc.terminate()
            print("[dev] Vite stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(serve_main())
