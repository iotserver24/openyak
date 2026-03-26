/** Channel (messaging platform connection via OpenClaw) types */

export interface ChannelInfo {
  id: string;
  name: string;
  status: string;
  type: string;
  account?: string;
}

export interface ChannelsResponse {
  channels: Record<string, ChannelInfo>;
  gateway_running: boolean;
  error?: string;
}

export interface OpenClawStatus {
  installed: boolean;
  running: boolean;
  port: number | null;
  ws_url: string | null;
}

export interface PlatformDef {
  id: string;
  name: string;
  icon: React.ReactNode;
  color: string;
  auth: "qr" | "token";
  help: string;
  helpUrl?: string;
  fields?: { key: string; label: string; placeholder: string; secret?: boolean }[];
}
