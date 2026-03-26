"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { ArrowLeft, Wifi, WifiOff, QrCode, Copy, RefreshCw, Shield, Check, Loader2, AlertTriangle, Download, Play, Square, RotateCw, Eye, EyeOff, ExternalLink, X, Unplug } from "lucide-react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api";
import { API, IS_DESKTOP, getBackendUrl } from "@/lib/constants";
import {
  useChannels,
  useOpenClawStatus,
  useOpenClawStart,
  useOpenClawStop,
  useAddChannel,
  useRemoveChannel,
} from "@/hooks/use-channels";
import { WhatsAppIcon, DiscordIcon, TelegramIcon, SlackIcon, FeishuIcon, SignalIcon, LineIcon, IMessageIcon } from "@/components/icons/platform-icons";
import type { ChannelInfo, PlatformDef } from "@/types/channels";

export default function RemotePage() {
  const { t } = useTranslation("settings");
  const [status, setStatus] = useState<{
    enabled: boolean;
    tunnel_url: string | null;
    token_preview: string | null;
    active_tasks: number;
    tunnel_mode: string;
    permission_mode: string;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [toggling, setToggling] = useState(false);
  const [showQr, setShowQr] = useState(false);
  const [qrBlobUrl, setQrBlobUrl] = useState<string | null>(null);
  const [fullToken, setFullToken] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [permMode, setPermMode] = useState("auto");
  const [tunnelChanged, setTunnelChanged] = useState(false);
  const prevTunnelUrl = useRef<string | null>(null);

  // Fetch QR image as blob URL to bypass Tauri CSP (img-src blocks http://127.0.0.1)
  const fetchQrBlob = async () => {
    try {
      const backendUrl = IS_DESKTOP ? await getBackendUrl() : "";
      const res = await fetch(`${backendUrl}${API.REMOTE.QR}?t=${Date.now()}`);
      if (!res.ok) return;
      const blob = await res.blob();
      // Revoke previous blob URL to avoid memory leaks
      setQrBlobUrl((prev) => { if (prev) URL.revokeObjectURL(prev); return URL.createObjectURL(blob); });
    } catch {}
  };

  const fetchStatus = async () => {
    try {
      const data = await api.get<typeof status>(API.REMOTE.STATUS);
      setStatus(data);
      if (data) {
        setPermMode(data.permission_mode);

        // Detect tunnel URL change — show warning to re-scan QR
        if (prevTunnelUrl.current !== null && data.tunnel_url && data.tunnel_url !== prevTunnelUrl.current) {
          setTunnelChanged(true);
          // Auto-refresh QR code when URL changes
          if (showQr) { fetchQrBlob(); }
        }
        prevTunnelUrl.current = data.tunnel_url ?? null;
      }
    } catch {
      // Remote API not available
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchStatus(); }, []);

  // Poll status every 30s to detect tunnel restarts
  useEffect(() => {
    if (!status?.enabled) return;
    const interval = setInterval(fetchStatus, 30_000);
    return () => clearInterval(interval);
  }, [status?.enabled]);

  const handleToggle = async () => {
    if (!status) return;
    setToggling(true);
    setTunnelChanged(false);
    try {
      if (status.enabled) {
        await api.post(API.REMOTE.DISABLE);
        setShowQr(false); setQrBlobUrl((prev) => { if (prev) URL.revokeObjectURL(prev); return null; }); setFullToken(null);
        prevTunnelUrl.current = null;
      } else {
        const result = await api.post<{ token: string; tunnel_url: string | null }>(API.REMOTE.ENABLE);
        setFullToken(result.token);
        await fetchStatus();
        await fetchQrBlob();
        setShowQr(true);
        return;
      }
      await fetchStatus();
    } catch (err) {
      console.error("Failed to toggle remote access:", err);
    } finally {
      setToggling(false);
    }
  };

  const handleShowQr = async () => {
    if (showQr) { setShowQr(false); return; }
    await fetchQrBlob();
    setShowQr(true);
    setTunnelChanged(false);
  };

  const handleRotateToken = async () => {
    try {
      const result = await api.post<{ token: string }>(API.REMOTE.ROTATE_TOKEN);
      setFullToken(result.token);
      await fetchStatus();
      if (showQr) handleShowQr();
    } catch {}
  };

  const handleCopyUrl = () => {
    if (status?.tunnel_url) {
      navigator.clipboard.writeText(`${status.tunnel_url}/m`);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const handlePermModeChange = async (mode: string) => {
    setPermMode(mode);
    try { await api.patch(API.REMOTE.CONFIG, { permission_mode: mode }); } catch {}
  };

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-2xl px-4 py-8">
        <div className="flex items-center gap-3 mb-8">
          <Button variant="ghost" size="icon" className="h-8 w-8 lg:hidden" asChild>
            <Link href="/c/new"><ArrowLeft className="h-4 w-4" /></Link>
          </Button>
          <h1 className="text-lg font-semibold text-[var(--text-primary)]">{t("remote")}</h1>
        </div>

        {loading ? (
          <div className="h-16 rounded-lg bg-[var(--surface-tertiary)] animate-pulse" />
        ) : (
          <div className="space-y-6">
            <p className="text-xs text-[var(--text-secondary)]">{t("remoteDesc")}</p>

            {/* Tunnel URL changed warning */}
            {tunnelChanged && status?.enabled && (
              <div className="flex items-start gap-3 rounded-lg border border-amber-500/40 bg-amber-500/5 p-3 animate-slide-up">
                <AlertTriangle className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />
                <div className="flex-1">
                  <p className="text-sm font-medium text-[var(--text-primary)]">Tunnel URL changed</p>
                  <p className="text-xs text-[var(--text-secondary)] mt-0.5">
                    The tunnel was restarted with a new URL. Mobile devices need to rescan the QR code to reconnect.
                  </p>
                </div>
                <Button variant="outline" size="sm" className="h-7 text-xs shrink-0" onClick={handleShowQr}>
                  <QrCode className="h-3 w-3 mr-1" />
                  Show QR
                </Button>
              </div>
            )}

            {/* Enable/Disable toggle */}
            <div className="flex items-center justify-between rounded-lg border border-[var(--border-default)] p-3">
              <div className="flex items-center gap-3">
                {toggling ? <Loader2 className="h-4 w-4 animate-spin text-[var(--text-secondary)]" /> : status?.enabled ? <Wifi className="h-4 w-4 text-green-500" /> : <WifiOff className="h-4 w-4 text-[var(--text-tertiary)]" />}
                <div>
                  <p className="text-sm font-medium text-[var(--text-primary)]">{toggling ? t("remoteStarting") : status?.enabled ? t("remoteActive") : t("remoteDisabled")}</p>
                  {status?.enabled && status.tunnel_url && <p className="text-xs text-[var(--text-secondary)] truncate max-w-[280px]">{status.tunnel_url}</p>}
                </div>
              </div>
              <Switch checked={status?.enabled ?? false} onCheckedChange={handleToggle} disabled={toggling} />
            </div>

            {/* When enabled: show controls */}
            {status?.enabled && (
              <div className="space-y-3">
                {status.tunnel_url && (
                  <div className="flex items-center gap-2">
                    <div className="flex-1 px-3 py-2 rounded-lg bg-[var(--surface-tertiary)] text-xs font-mono text-[var(--text-secondary)] truncate">{status.tunnel_url}/m</div>
                    <Button variant="outline" size="sm" className="h-8 shrink-0" onClick={handleCopyUrl}>
                      {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
                      <span className="ml-1 text-xs">{copied ? t("remoteCopied") : t("remoteCopy")}</span>
                    </Button>
                  </div>
                )}

                <div className="flex gap-2">
                  <Button variant="outline" size="sm" className="h-8" onClick={handleShowQr}>
                    <QrCode className="h-3 w-3" /><span className="ml-1 text-xs">{showQr ? t("remoteHideQr") : t("remoteShowQr")}</span>
                  </Button>
                  <Button variant="outline" size="sm" className="h-8" onClick={handleRotateToken}>
                    <RefreshCw className="h-3 w-3" /><span className="ml-1 text-xs">{t("remoteRotateToken")}</span>
                  </Button>
                </div>

                {showQr && qrBlobUrl && (
                  <div className="flex justify-center p-4 rounded-lg bg-white">
                    <img src={qrBlobUrl} alt={t("remoteQrAlt")} className="w-48 h-48" style={{ imageRendering: "pixelated" }} />
                  </div>
                )}

                {fullToken && (
                  <div className="p-3 rounded-lg bg-[var(--surface-tertiary)] border border-[var(--border-default)]">
                    <p className="text-xs text-[var(--text-secondary)] mb-1">{t("remoteTokenLabel")}</p>
                    <code className="text-xs font-mono text-[var(--text-primary)] break-all select-all">{fullToken}</code>
                  </div>
                )}

                {!fullToken && status.token_preview && <p className="text-xs text-[var(--text-tertiary)]">{t("remoteTokenPreview", { preview: status.token_preview })}</p>}

                <div className="flex items-center gap-3 rounded-lg border border-[var(--border-default)] p-3">
                  <Shield className="h-4 w-4 text-[var(--text-secondary)] shrink-0" />
                  <div className="flex-1">
                    <p className="text-sm font-medium text-[var(--text-primary)]">{t("remotePermission")}</p>
                    <p className="text-xs text-[var(--text-secondary)]">{t("remotePermissionDesc")}</p>
                  </div>
                  <select value={permMode} onChange={(e) => handlePermModeChange(e.target.value)} className="px-2 py-1 rounded-md bg-[var(--surface-tertiary)] text-xs border border-[var(--border-default)] text-[var(--text-primary)]">
                    <option value="auto">{t("remotePermAuto")}</option>
                    <option value="ask">{t("remotePermAsk")}</option>
                    <option value="deny">{t("remotePermDeny")}</option>
                  </select>
                </div>

                {status.active_tasks > 0 && <p className="text-xs text-[var(--text-secondary)]">{t("remoteActiveTasks", { n: status.active_tasks })}</p>}
              </div>
            )}

            {!status?.enabled && (
              <div className="p-3 rounded-lg bg-[var(--surface-tertiary)] text-xs text-[var(--text-secondary)] space-y-1.5">
                <p>{t("remoteInstructions")}</p>
                <ol className="list-decimal list-inside space-y-0.5">
                  <li>{t("remoteStep1")}</li>
                  <li>{t("remoteStep2")}</li>
                  <li>{t("remoteStep3")}</li>
                </ol>
              </div>
            )}
          </div>
        )}

        {/* Divider */}
        <div className="my-8 border-t border-[var(--border-default)]" />

        {/* OpenClaw Channels */}
        <OpenClawSection />
      </div>
    </div>
  );
}


/* ------------------------------------------------------------------ */
/* OpenClaw Channels Section                                           */
/* ------------------------------------------------------------------ */

const PLATFORMS: PlatformDef[] = [
  { id: "whatsapp", name: "WhatsApp", icon: <WhatsAppIcon size={18} />, color: "text-[#25D366]", auth: "qr",
    help: "Scan QR code with your phone to link WhatsApp" },
  { id: "discord", name: "Discord", icon: <DiscordIcon size={18} />, color: "text-[#5865F2]", auth: "token",
    help: "Create a bot at Discord Developer Portal",
    helpUrl: "https://discord.com/developers/applications",
    fields: [{ key: "token", label: "Bot Token", placeholder: "Paste Discord bot token", secret: true }] },
  { id: "telegram", name: "Telegram", icon: <TelegramIcon size={18} />, color: "text-[#26A5E4]", auth: "token",
    help: "Get a token from @BotFather on Telegram",
    helpUrl: "https://t.me/BotFather",
    fields: [{ key: "token", label: "Bot Token", placeholder: "123456:ABC-DEF...", secret: true }] },
  { id: "slack", name: "Slack", icon: <SlackIcon size={18} />, color: "text-[#E01E5A]", auth: "token",
    help: "Create an app at api.slack.com/apps",
    helpUrl: "https://api.slack.com/apps",
    fields: [
      { key: "bot_token", label: "Bot Token", placeholder: "xoxb-...", secret: true },
      { key: "app_token", label: "App Token", placeholder: "xapp-...", secret: true },
    ] },
  { id: "feishu", name: "Feishu", icon: <FeishuIcon size={18} />, color: "text-[#3370FF]", auth: "token",
    help: "Create an app at Feishu Open Platform",
    helpUrl: "https://open.feishu.cn/app",
    fields: [
      { key: "app_id", label: "App ID", placeholder: "cli_xxxxx", secret: false },
      { key: "app_secret", label: "App Secret", placeholder: "Enter app secret", secret: true },
    ] },
  { id: "signal", name: "Signal", icon: <SignalIcon size={18} />, color: "text-[#3A76F0]", auth: "token",
    help: "Requires signal-cli installed",
    fields: [
      { key: "signal_number", label: "Phone Number", placeholder: "+1234567890", secret: false },
    ] },
  { id: "line", name: "LINE", icon: <LineIcon size={18} />, color: "text-[#06C755]", auth: "token",
    help: "Get credentials from LINE Developers Console",
    helpUrl: "https://developers.line.biz/console/",
    fields: [
      { key: "token", label: "Channel Access Token", placeholder: "Paste LINE channel access token", secret: true },
    ] },
  { id: "imessage", name: "iMessage", icon: <IMessageIcon size={18} />, color: "text-[#34C759]", auth: "token",
    help: "macOS only \u2014 reads your local iMessage database",
    fields: [
      { key: "db_path", label: "Database Path (optional)", placeholder: "~/Library/Messages/chat.db", secret: false },
    ] },
];

function OpenClawSection() {
  const { data: clawStatus, refetch: refetchClaw } = useOpenClawStatus();
  const { data: channelsData, refetch: refetchChannels } = useChannels();
  const startClaw = useOpenClawStart();
  const stopClaw = useOpenClawStop();
  const [expandedPlatform, setExpandedPlatform] = useState<string | null>(null);

  const installed = clawStatus?.installed ?? false;
  const running = clawStatus?.running ?? false;
  const channels = channelsData?.channels ?? {};

  return (
    <div className="space-y-4">
      <h2 className="text-base font-semibold text-[var(--text-primary)]">Messaging Channels</h2>
      <p className="text-xs text-[var(--text-secondary)]">
        Connect OpenYak to messaging platforms. Messages will be processed by OpenYak&apos;s AI.
      </p>

      {/* OpenClaw runtime card */}
      <div className="rounded-lg border border-[var(--border-default)] p-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className={`h-2 w-2 rounded-full ${running ? "bg-emerald-500" : installed ? "bg-amber-400" : "bg-[var(--text-tertiary)]"}`} />
            <span className="text-xs font-medium text-[var(--text-primary)]">OpenClaw Gateway</span>
            <span className="text-[10px] text-[var(--text-tertiary)]">
              {running ? "Running" : installed ? "Stopped" : "Not installed"}
            </span>
          </div>
          <div className="flex items-center gap-2">
            {!installed && <OpenClawSetupButton onComplete={() => refetchClaw()} />}
            {installed && !running && (
              <Button variant="outline" size="sm" className="h-7 text-[11px]"
                onClick={() => startClaw.mutate()} disabled={startClaw.isPending}>
                {startClaw.isPending ? <><Loader2 className="h-3 w-3 animate-spin" />Starting...</> : <><Play className="h-3 w-3" />Start</>}
              </Button>
            )}
            {running && (
              <Button variant="outline" size="sm" className="h-7 text-[11px]"
                onClick={() => stopClaw.mutate()} disabled={stopClaw.isPending}>
                {stopClaw.isPending ? <><Loader2 className="h-3 w-3 animate-spin" />Stopping...</> : <><Square className="h-3 w-3" />Stop</>}
              </Button>
            )}
          </div>
        </div>
      </div>

      {/* Platform cards grid */}
      <div className="grid grid-cols-2 gap-2">
        {PLATFORMS.map((p) => {
          const connected = !!channels[p.id];
          const isExpanded = expandedPlatform === p.id;
          return (
            <div key={p.id} className={`rounded-lg border p-3 space-y-2 transition-colors ${
              connected ? "border-emerald-500/30 bg-emerald-500/5" : "border-[var(--border-default)]"
            } ${isExpanded ? "col-span-2" : ""}`}>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className={p.color}>{p.icon}</span>
                  <span className="text-xs font-medium text-[var(--text-primary)]">{p.name}</span>
                  {connected && <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />}
                </div>
                {!connected ? (
                  <Button variant="outline" size="sm" className="h-6 text-[10px] px-2"
                    disabled={!running && !isExpanded}
                    onClick={() => setExpandedPlatform(isExpanded ? null : p.id)}>
                    {isExpanded ? "Cancel" : "Connect"}
                  </Button>
                ) : (
                  <RemoveChannelButton channel={p.id} onRemoved={() => refetchChannels()} />
                )}
              </div>

              {/* Expanded: setup form (stays visible during login even if gateway restarts) */}
              {isExpanded && (
                <div className="pt-1">
                  {p.auth === "qr" ? (
                    <QrLoginFlow channel={p.id} onDone={() => {
                      setExpandedPlatform(null);
                      // Auto-start gateway if it was stopped during login
                      if (!running) startClaw.mutate();
                      setTimeout(() => refetchChannels(), 2000);
                    }} />
                  ) : (
                    <TokenForm platform={p} onDone={() => { setExpandedPlatform(null); refetchChannels(); }} />
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {!running && installed && (
        <p className="text-center text-[11px] text-[var(--text-tertiary)]">
          Start the gateway to connect platforms.
        </p>
      )}
    </div>
  );
}

/** Token-based channel setup form (Discord, Telegram, Slack, Feishu). */
function TokenForm({ platform, onDone }: { platform: PlatformDef; onDone: () => void }) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [showSecret, setShowSecret] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const addChannel = useAddChannel();

  const handleSubmit = async () => {
    setError(null);
    const body: Record<string, string> = { channel: platform.id };
    for (const f of platform.fields || []) {
      if (!values[f.key]?.trim()) {
        setError(`${f.label} is required`);
        return;
      }
      body[f.key] = values[f.key].trim();
    }

    addChannel.mutate(body, {
      onSuccess: (result) => {
        if (result.ok) { onDone(); }
        else { setError(result.message); }
      },
      onError: (e) => setError(String(e)),
    });
  };

  return (
    <div className="space-y-2">
      {platform.fields?.map((f) => (
        <div key={f.key} className="relative">
          <label className="text-[10px] text-[var(--text-tertiary)] mb-0.5 block">{f.label}</label>
          <div className="relative">
            <input
              type={f.secret && !showSecret[f.key] ? "password" : "text"}
              value={values[f.key] || ""}
              onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
              placeholder={f.placeholder}
              autoComplete="one-time-code"
              className="w-full h-7 rounded-md border border-[var(--border-default)] bg-transparent px-2.5 pr-7 text-xs font-mono text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:outline-none focus:ring-1 focus:ring-[var(--border-focus)]"
            />
            {f.secret && (
              <button className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)]"
                onClick={() => setShowSecret((s) => ({ ...s, [f.key]: !s[f.key] }))}>
                {showSecret[f.key] ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
              </button>
            )}
          </div>
        </div>
      ))}

      {platform.helpUrl && (
        <a href={platform.helpUrl} target="_blank" rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-[10px] text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]">
          <ExternalLink className="h-2.5 w-2.5" />{platform.help}
        </a>
      )}

      {error && (
        <p className="text-[11px] text-red-400">{error}</p>
      )}

      <Button size="sm" className="h-7 text-[11px] w-full" onClick={handleSubmit}
        disabled={addChannel.isPending}>
        {addChannel.isPending ? <><Loader2 className="h-3 w-3 animate-spin" />Connecting...</> : "Connect"}
      </Button>
    </div>
  );
}

/** WhatsApp QR login flow (SSE streaming). */
function QrLoginFlow({ channel, onDone }: { channel: string; onDone: () => void }) {
  const [qrUrl, setQrUrl] = useState<string | null>(null);
  const [qrText, setQrText] = useState<string | null>(null);
  const [status, setStatus] = useState<string>("Preparing...");
  const [error, setError] = useState<string | null>(null);
  const startedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;

    (async () => {
      try {
        const backendUrl = await getBackendUrl();
        const resp = await fetch(`${backendUrl}${API.CHANNELS.LOGIN}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ channel }),
        });

        if (!resp.ok || !resp.body) {
          setError("Failed to start login");
          return;
        }

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";

          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            try {
              const data = JSON.parse(line.slice(6));
              if (data.status === "qr") {
                setQrUrl(data.qr_data_url);
                setQrText(null);
                setStatus("Scan QR code with your phone");
              } else if (data.status === "qr_text") {
                setQrText(data.qr_text);
                setQrUrl(null);
                setStatus("Scan QR code in WhatsApp \u2192 Linked Devices");
              } else if (data.status === "connected" || data.status === "done") {
                setStatus(data.status === "connected" ? "Connected!" : "Done");
                setTimeout(onDone, 1000);
                return;
              } else if (data.status === "error") {
                setError(data.message);
                return;
              } else if (data.status === "waiting") {
                setStatus(data.message || "Waiting for scan...");
              } else if (data.message) {
                setStatus(data.message);
              }
            } catch { /* ignore */ }
          }
        }
      } catch (e) {
        setError(String(e));
      }
    })();
  }, [channel, onDone]);

  if (error) {
    return <p className="text-[11px] text-red-400 py-2">{error}</p>;
  }

  const hasQr = qrUrl || qrText;

  return (
    <div className="space-y-2 py-1">
      {qrUrl ? (
        <div className="flex justify-center p-3 rounded-lg bg-white">
          <img src={qrUrl} alt="QR Code" className="w-48 h-48" style={{ imageRendering: "pixelated" }} />
        </div>
      ) : qrText ? (
        <div className="flex justify-center p-2 rounded-lg bg-white overflow-x-auto">
          <pre className="text-black text-[6px] leading-[7px] font-mono whitespace-pre select-none">{qrText}</pre>
        </div>
      ) : (
        <div className="flex justify-center py-6">
          <Loader2 className="h-5 w-5 animate-spin text-[var(--text-tertiary)]" />
        </div>
      )}
      <p className="text-center text-[11px] text-[var(--text-secondary)]">{status}</p>
    </div>
  );
}

/** Remove/disconnect channel button. */
function RemoveChannelButton({ channel, onRemoved }: { channel: string; onRemoved: () => void }) {
  const removeChannel = useRemoveChannel();
  const [removed, setRemoved] = useState(false);

  if (removed) {
    return <span className="text-[10px] text-[var(--text-tertiary)]">Removed</span>;
  }

  const handleRemove = async () => {
    try {
      await removeChannel.mutateAsync({ channel });
    } catch { /* ignore */ }
    setRemoved(true);
    // Delay slightly to let backend update
    setTimeout(onRemoved, 500);
  };

  return (
    <Button variant="outline" size="sm" className="h-6 text-[10px] px-2 text-red-400 border-red-400/30 hover:bg-red-400/10"
      disabled={removeChannel.isPending}
      onClick={handleRemove}>
      {removeChannel.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <><Unplug className="h-3 w-3" />Disconnect</>}
    </Button>
  );
}

/** SSE-streaming setup button (install + start OpenClaw). */
function OpenClawSetupButton({ onComplete }: { onComplete: () => void }) {
  const [progress, setProgress] = useState<{ status: string; message?: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const startSetup = useCallback(async () => {
    setError(null);
    setProgress({ status: "starting" });
    try {
      const backendUrl = await getBackendUrl();
      const resp = await fetch(`${backendUrl}${API.CHANNELS.OPENCLAW_SETUP}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
      });
      if (!resp.ok || !resp.body) { setError("Failed to start setup"); setProgress(null); return; }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const data = JSON.parse(line.slice(6));
            setProgress(data);
            if (data.status === "error") { setError(data.message || "Setup failed"); setProgress(null); return; }
            if (data.status === "ready") { setProgress(null); onComplete(); return; }
          } catch { /* ignore */ }
        }
      }
      setProgress(null);
      onComplete();
    } catch (e) { setError(String(e)); setProgress(null); }
  }, [onComplete]);

  if (error) {
    return (
      <div className="flex items-center gap-2">
        <span className="text-[11px] text-red-400 max-w-[200px] truncate">{error}</span>
        <Button variant="outline" size="sm" className="h-7 text-[11px]" onClick={startSetup}>
          <RotateCw className="h-3 w-3" />Retry
        </Button>
      </div>
    );
  }
  if (progress) {
    return (
      <div className="flex items-center gap-2 text-[11px] text-[var(--text-secondary)]">
        <Loader2 className="h-3 w-3 animate-spin" />
        <span className="max-w-[200px] truncate">{progress.message || progress.status}</span>
      </div>
    );
  }
  return (
    <Button variant="outline" size="sm" className="h-7 text-[11px]" onClick={startSetup}>
      <Download className="h-3 w-3" />Set Up
    </Button>
  );
}
