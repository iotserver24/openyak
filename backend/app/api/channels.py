"""Channels API — manage OpenClaw runtime and messaging platform channels."""

from __future__ import annotations

import base64
import io
import json
import logging
import re
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class OpenClawStatusResponse(BaseModel):
    installed: bool
    running: bool
    port: int | None = None
    ws_url: str | None = None


class ChannelAddRequest(BaseModel):
    channel: str  # whatsapp, discord, telegram, slack, feishu, signal
    account: str = "default"
    # Token-based fields (varies by channel)
    token: str | None = None       # discord, telegram
    bot_token: str | None = None   # slack (xoxb-...)
    app_token: str | None = None   # slack (xapp-...)
    app_id: str | None = None      # feishu
    app_secret: str | None = None  # feishu
    signal_number: str | None = None  # signal
    db_path: str | None = None     # imessage


class ChannelLoginRequest(BaseModel):
    channel: str = "whatsapp"
    account: str = "default"


class ChannelRemoveRequest(BaseModel):
    channel: str
    account: str = "default"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_openclaw_manager(request: Request):
    return getattr(request.app.state, "openclaw_manager", None)


def _require_manager(request: Request):
    mgr = _get_openclaw_manager(request)
    if mgr is None:
        raise HTTPException(503, "OpenClaw manager not initialized")
    if not mgr.is_installed:
        raise HTTPException(400, "OpenClaw not installed — run setup first")
    return mgr


# ---------------------------------------------------------------------------
# OpenClaw Runtime (install / start / stop)
# ---------------------------------------------------------------------------

@router.get("/channels/openclaw/status", response_model=OpenClawStatusResponse)
async def openclaw_status(request: Request) -> OpenClawStatusResponse:
    mgr = _get_openclaw_manager(request)
    if mgr is None:
        return OpenClawStatusResponse(installed=False, running=False)
    status = await mgr.status()
    return OpenClawStatusResponse(
        installed=status["installed"],
        running=status["running"],
        port=status["port"],
        ws_url=status.get("ws_url"),
    )


@router.post("/channels/openclaw/setup")
async def openclaw_setup(request: Request):
    mgr = _get_openclaw_manager(request)
    if mgr is None:
        raise HTTPException(503, "OpenClaw manager not initialized")

    async def stream():
        if not mgr.is_installed:
            async for progress in mgr.install():
                yield f"data: {json.dumps(progress)}\n\n"
                if progress.get("status") == "error":
                    return
        else:
            yield f"data: {json.dumps({'status': 'already_installed'})}\n\n"

        yield f"data: {json.dumps({'status': 'starting', 'message': 'Starting OpenClaw gateway...'})}\n\n"
        try:
            openyak_port = request.url.port or 8000
            ws_url = await mgr.start(openyak_port=openyak_port)
            yield f"data: {json.dumps({'status': 'ready', 'ws_url': ws_url})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/channels/openclaw/start")
async def openclaw_start(request: Request) -> dict:
    mgr = _get_openclaw_manager(request)
    if mgr is None:
        raise HTTPException(503, "OpenClaw manager not initialized")
    if not mgr.is_installed:
        raise HTTPException(400, "OpenClaw not installed — run setup first")
    try:
        openyak_port = request.url.port or 8000
        ws_url = await mgr.start(openyak_port=openyak_port)
        return {"status": "running", "ws_url": ws_url}
    except Exception as e:
        raise HTTPException(500, f"Failed to start OpenClaw: {e}")


@router.post("/channels/openclaw/stop")
async def openclaw_stop(request: Request) -> dict:
    mgr = _get_openclaw_manager(request)
    if mgr is None:
        raise HTTPException(503, "OpenClaw manager not initialized")
    await mgr.stop()
    return {"status": "stopped"}


@router.delete("/channels/openclaw/uninstall")
async def openclaw_uninstall(request: Request) -> dict:
    mgr = _get_openclaw_manager(request)
    if mgr is None:
        raise HTTPException(503, "OpenClaw manager not initialized")
    result = await mgr.uninstall()
    return {"status": "uninstalled", **result}


# ---------------------------------------------------------------------------
# Channel Management (add / login / remove)
# ---------------------------------------------------------------------------

@router.post("/channels/add")
async def add_channel(request: Request, body: ChannelAddRequest) -> dict:
    """Add a channel account (token-based: Discord, Telegram, Slack, Feishu)."""
    mgr = _require_manager(request)

    args = ["channels", "add", "--channel", body.channel, "--account", body.account]

    # Build channel-specific args
    if body.channel == "discord":
        if not body.token:
            raise HTTPException(400, "Discord requires a bot token")
        args += ["--token", body.token]

    elif body.channel == "telegram":
        if not body.token:
            raise HTTPException(400, "Telegram requires a bot token")
        args += ["--token", body.token]

    elif body.channel == "slack":
        if not body.bot_token or not body.app_token:
            raise HTTPException(400, "Slack requires both bot token and app token")
        args += ["--bot-token", body.bot_token, "--app-token", body.app_token]

    elif body.channel == "feishu":
        if not body.app_id or not body.app_secret:
            raise HTTPException(400, "Feishu requires app ID and app secret")
        # Feishu uses env vars — pass via environment
        result = await mgr.run_cli(args)
        # TODO: handle feishu env var injection
        return {"ok": result["ok"], "message": result.get("stderr") or result.get("stdout", "")}

    elif body.channel == "signal":
        if not body.signal_number:
            raise HTTPException(400, "Signal requires a phone number")
        args += ["--signal-number", body.signal_number]

    elif body.channel == "line":
        if not body.token:
            raise HTTPException(400, "LINE requires a channel access token")
        args += ["--token", body.token]

    elif body.channel == "imessage":
        if body.db_path:
            args += ["--db-path", body.db_path]

    else:
        raise HTTPException(400, f"Unsupported channel: {body.channel}")

    result = await mgr.run_cli(args)
    if result["ok"]:
        _set_channel_defaults(body.channel)
        return {"ok": True, "message": f"{body.channel} channel added successfully"}
    else:
        msg = result["stderr"].strip() or result["stdout"].strip() or "Unknown error"
        # Strip ANSI escape codes
        msg = re.sub(r"\x1b\[[0-9;]*m", "", msg)
        return {"ok": False, "message": msg}


@router.post("/channels/login")
async def login_channel(request: Request, body: ChannelLoginRequest):
    """Start QR-based channel login (WhatsApp). Returns SSE stream with QR data."""
    mgr = _require_manager(request)

    async def stream():
        # Step 1: Ensure channel is registered (avoids "Install plugin?" interactive prompt)
        yield _sse({"status": "starting", "message": f"Preparing {body.channel}..."})
        add_result = await mgr.run_cli(
            ["channels", "add", "--channel", body.channel, "--account", body.account],
            timeout=30,
        )
        if not add_result["ok"]:
            stderr = add_result["stderr"].strip()
            if "already" not in stderr.lower() and "exists" not in stderr.lower():
                yield _sse({"status": "error", "message": f"Failed to register channel: {stderr}"})
                return

        # Step 2: Stop gateway to avoid WhatsApp session conflict
        was_running = mgr.is_running
        if was_running and body.channel == "whatsapp":
            yield _sse({"status": "progress", "message": "Pausing gateway..."})
            await mgr.stop()

        # Step 3: Run login
        yield _sse({"status": "starting", "message": f"Starting {body.channel} login..."})
        args = ["channels", "login", "--channel", body.channel, "--account", body.account]

        qr_lines: list[str] = []
        collecting_qr = False

        try:
            async for line in mgr.run_cli_stream(args, timeout=180):
                if "[timeout]" in line:
                    yield _sse({"status": "error", "message": "Login timed out"})
                    return
                if line == "[exit:0]":
                    # Set sensible defaults for the channel (open DM, allow all)
                    _set_channel_defaults(body.channel)
                    # Restart gateway to load new credentials before telling frontend
                    if was_running:
                        try:
                            openyak_port = request.url.port or 8000
                            await mgr.start(openyak_port=openyak_port)
                        except Exception as e:
                            logger.warning("Gateway restart after login: %s", e)
                    yield _sse({"status": "connected", "message": "Login successful!"})
                    return
                if "[error]" in line:
                    msg = re.sub(r"\x1b\[[0-9;]*m", "", line.replace("[error] ", ""))
                    # Don't treat as fatal — CLI may recover (e.g., clear old session + show new QR)
                    yield _sse({"status": "progress", "message": msg})
                    continue

                # Strip ANSI codes but keep Unicode block chars (QR)
                clean = re.sub(r"\x1b\[\??\d*[a-zA-Z]", "", line)
                clean = re.sub(r"\x1b\[[0-9;]*m", "", clean)

                # Detect QR code data URL (base64 PNG) — some versions emit this
                if "data:image/" in clean:
                    match = re.search(r"(data:image/[^\"'\s]+)", clean)
                    if match:
                        yield _sse({"status": "qr", "qr_data_url": match.group(1)})
                        continue

                # Detect Unicode block QR (characters like ▀▄█ etc.)
                # QR lines contain many block characters (U+2580-U+259F range)
                block_count = sum(1 for c in clean if "\u2580" <= c <= "\u259f")
                if block_count > 10:
                    collecting_qr = True
                    qr_lines.append(clean)
                    continue

                # End of QR block — convert to PNG and send as data URL
                if collecting_qr and block_count <= 10:
                    collecting_qr = False
                    if qr_lines:
                        qr_text = "\n".join(qr_lines)
                        data_url = _text_qr_to_data_url(qr_text)
                        if data_url:
                            yield _sse({"status": "qr", "qr_data_url": data_url})
                        else:
                            yield _sse({"status": "qr_text", "qr_text": qr_text})
                        qr_lines = []

                stripped = clean.strip()
                if not stripped:
                    continue

                lower = stripped.lower()

                # Detect connection success (avoid false positives like "Waiting for connection")
                if any(phrase in lower for phrase in [
                    "successfully", "logged in", "is now linked",
                    "is ready", "linked!", "pairing complete",
                    "account linked", "connection established",
                ]):
                    yield _sse({"status": "connected", "message": stripped})
                    return

                # Detect scan prompt
                if "scan" in lower or "qr" in lower:
                    yield _sse({"status": "waiting", "message": stripped})
                    continue

                # Generic progress
                yield _sse({"status": "progress", "message": stripped})

            # Flush remaining QR lines
            if qr_lines:
                qr_text = "\n".join(qr_lines)
                data_url = _text_qr_to_data_url(qr_text)
                if data_url:
                    yield _sse({"status": "qr", "qr_data_url": data_url})
                else:
                    yield _sse({"status": "qr_text", "qr_text": qr_text})

            yield _sse({"status": "done", "message": "Login process completed"})

        except Exception as e:
            yield _sse({"status": "error", "message": str(e)})
            # Try to restart gateway on error too
            if was_running and not mgr.is_running:
                try:
                    openyak_port = request.url.port or 8000
                    await mgr.start(openyak_port=openyak_port)
                except Exception:
                    pass

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/channels/remove")
async def remove_channel(request: Request, body: ChannelRemoveRequest) -> dict:
    """Remove a channel account."""
    mgr = _require_manager(request)

    result = await mgr.run_cli(
        ["channels", "remove", "--channel", body.channel, "--account", body.account, "--delete"],
    )
    if result["ok"]:
        return {"ok": True, "message": f"{body.channel} removed"}
    else:
        msg = re.sub(r"\x1b\[[0-9;]*m", "", result["stderr"].strip() or result["stdout"].strip())
        return {"ok": False, "message": msg}


# ---------------------------------------------------------------------------
# Channel listing
# ---------------------------------------------------------------------------

@router.get("/channels")
async def list_channels(request: Request) -> dict:
    """List configured channels via openclaw CLI."""
    mgr = _get_openclaw_manager(request)
    if mgr is None or not mgr.is_installed:
        return {"channels": {}, "gateway_running": False}

    running = mgr.is_running

    # Use CLI to get channel list (works even when gateway is stopped)
    try:
        result = await mgr.run_cli(["channels", "list", "--json"], timeout=15)
        if result["ok"] and result["stdout"].strip():
            data = json.loads(result["stdout"])
            channels: dict[str, Any] = {}

            # Format: { chat: { whatsapp: ["default"], telegram: ["default"] }, ... }
            chat = data.get("chat") or {}
            if isinstance(chat, dict):
                for cid, accounts in chat.items():
                    channels[cid] = {
                        "id": cid,
                        "name": cid.capitalize(),
                        "status": "configured",
                        "type": cid,
                        "account": accounts[0] if isinstance(accounts, list) and accounts else "default",
                    }

            # Also handle array/object formats as fallback
            if not channels:
                items = data if isinstance(data, list) else data.get("channels", data.get("accounts", []))
                if isinstance(items, list):
                    for item in items:
                        cid = item.get("channel") or item.get("id") or "unknown"
                        channels[cid] = {"id": cid, "name": cid.capitalize(), "status": "configured", "type": cid}
                elif isinstance(items, dict):
                    for cid, cdata in items.items():
                        channels[cid] = {"id": cid, "name": cid.capitalize(), "status": "configured", "type": cid}

            return {"channels": channels, "gateway_running": running}
    except Exception as e:
        logger.debug("channels list --json failed: %s", e)

    # Fallback: query gateway health if running
    if running:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{mgr.base_url}/health")
                if resp.status_code < 400:
                    data = resp.json()
                    raw = data.get("channels") or {}
                    channels = {}
                    if isinstance(raw, dict):
                        for cid, cdata in raw.items():
                            if isinstance(cdata, dict):
                                channels[cid] = {
                                    "id": cid,
                                    "name": cdata.get("name", cid),
                                    "status": cdata.get("status", "unknown"),
                                    "type": cid,
                                }
                    return {"channels": channels, "gateway_running": True}
        except Exception:
            pass

    return {"channels": {}, "gateway_running": running}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


def _set_channel_defaults(channel: str) -> None:
    """Set sensible defaults for a newly added channel.

    By default OpenClaw uses dmPolicy=pairing which requires manual approval
    for each new user. For OpenYak's use case (personal AI assistant), we
    default to open access so messages are processed immediately.
    """
    from pathlib import Path

    cfg_path = Path.home() / ".openclaw" / "openclaw.json"
    if not cfg_path.exists():
        return

    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        ch = cfg.get("channels", {}).get(channel)
        if not isinstance(ch, dict):
            return

        ch["dmPolicy"] = "open"
        ch["allowFrom"] = ["*"]
        if channel == "whatsapp":
            ch["selfChatMode"] = True

        cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Set %s defaults: dmPolicy=open, allowFrom=[*]", channel)
    except Exception as e:
        logger.warning("Failed to set %s defaults: %s", channel, e)


def _text_qr_to_data_url(qr_text: str) -> str | None:
    """Convert Unicode block-character QR text to a PNG data URL.

    The CLI renders QR using half-block characters (▀▄█ etc.) where each
    character encodes 2 vertical pixels. We parse the matrix and render
    a proper PNG using PIL.
    """
    try:
        from PIL import Image
    except ImportError:
        return None

    lines = qr_text.split("\n")
    if not lines:
        return None

    # Each Unicode half-block char encodes a top and bottom pixel:
    # █ (U+2588) = black top + black bottom
    # ▀ (U+2580) = black top + white bottom
    # ▄ (U+2584) = white top + black bottom
    # ' ' (space) = white top + white bottom
    # ▐ ▌ etc. are less common but we handle the main ones
    width = max(len(l) for l in lines)
    height = len(lines) * 2  # each text line = 2 pixel rows

    # Build pixel matrix (True = black)
    pixels: list[list[bool]] = []
    for line in lines:
        top_row: list[bool] = []
        bot_row: list[bool] = []
        for ch in line:
            if ch == "\u2588":      # █ full block
                top_row.append(True); bot_row.append(True)
            elif ch == "\u2580":    # ▀ upper half
                top_row.append(True); bot_row.append(False)
            elif ch == "\u2584":    # ▄ lower half
                top_row.append(False); bot_row.append(True)
            elif ch == " ":
                top_row.append(False); bot_row.append(False)
            else:
                # Treat unknown as black (safer for QR)
                top_row.append(True); bot_row.append(True)
        # Pad to uniform width
        while len(top_row) < width:
            top_row.append(False); bot_row.append(False)
        pixels.append(top_row)
        pixels.append(bot_row)

    if not pixels or not pixels[0]:
        return None

    # Scale up for better readability (4x)
    scale = 4
    img_w = len(pixels[0]) * scale
    img_h = len(pixels) * scale
    img = Image.new("1", (img_w, img_h), 1)  # 1-bit, white background

    for y, row in enumerate(pixels):
        for x, is_black in enumerate(row):
            if is_black:
                for dy in range(scale):
                    for dx in range(scale):
                        img.putpixel((x * scale + dx, y * scale + dy), 0)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/png;base64,{b64}"
