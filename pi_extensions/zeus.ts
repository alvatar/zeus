import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import * as fs from "node:fs";
import * as path from "node:path";

interface SessionSyncPayload {
  agentId: string;
  sessionPath: string;
  sessionId: string;
  cwd: string;
  updatedAt: string;
  event: string;
}

const DEFAULT_MAP_DIR = "/tmp/zeus-session-map";

function sanitizeAgentId(value: string): string {
  return value.trim().replace(/[^A-Za-z0-9_-]/g, "");
}

function getAgentId(): string {
  return sanitizeAgentId(process.env.ZEUS_AGENT_ID ?? "");
}

function getMapDir(): string {
  const configured = (process.env.ZEUS_SESSION_MAP_DIR ?? "").trim();
  if (!configured) return DEFAULT_MAP_DIR;
  return configured;
}

function getSessionFile(ctx: any): string {
  try {
    const raw = ctx?.sessionManager?.getSessionFile?.();
    if (typeof raw !== "string") return "";
    return raw.trim();
  } catch {
    return "";
  }
}

function getSessionId(ctx: any): string {
  try {
    const raw = ctx?.sessionManager?.getSessionId?.();
    if (typeof raw !== "string") return "";
    return raw.trim();
  } catch {
    return "";
  }
}

function getCwd(ctx: any): string {
  try {
    const raw = ctx?.sessionManager?.getCwd?.();
    if (typeof raw !== "string") return "";
    return raw.trim();
  } catch {
    return "";
  }
}

function writeJsonAtomic(filePath: string, payload: SessionSyncPayload): void {
  const dir = path.dirname(filePath);
  fs.mkdirSync(dir, { recursive: true });
  const tempPath = `${filePath}.tmp-${process.pid}-${Date.now()}-${Math.random()
    .toString(16)
    .slice(2)}`;
  try {
    fs.writeFileSync(tempPath, JSON.stringify(payload));
    fs.renameSync(tempPath, filePath);
  } finally {
    if (fs.existsSync(tempPath)) {
      try {
        fs.unlinkSync(tempPath);
      } catch {
        // Ignore cleanup failure.
      }
    }
  }
}

function removeMapFile(filePath: string): void {
  try {
    fs.unlinkSync(filePath);
  } catch {
    // Ignore missing files and transient errors.
  }
}

function syncSession(eventName: string, ctx: any): void {
  const agentId = getAgentId();
  if (!agentId) return;

  const mapFile = path.join(getMapDir(), `${agentId}.json`);
  const sessionPath = getSessionFile(ctx);
  if (!sessionPath) {
    removeMapFile(mapFile);
    return;
  }

  const payload: SessionSyncPayload = {
    agentId,
    sessionPath,
    sessionId: getSessionId(ctx),
    cwd: getCwd(ctx),
    updatedAt: new Date().toISOString(),
    event: eventName,
  };

  writeJsonAtomic(mapFile, payload);
}

export default function (pi: ExtensionAPI) {
  const subscribe = (eventName: string): void => {
    pi.on(eventName as any, async (_event, ctx) => {
      try {
        syncSession(eventName, ctx);
      } catch {
        // Best-effort telemetry sync; never break pi runtime.
      }
    });
  };

  subscribe("session_start");
  subscribe("session_switch");
  subscribe("session_fork");
  subscribe("session_tree");
  subscribe("turn_end");
}
