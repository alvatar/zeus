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

interface HopliteInboxPayload {
  id: string;
  message: string;
  source_name?: string;
  source_agent_id?: string;
}

const DEFAULT_MAP_DIR = path.join(process.env.HOME || "~", ".zeus", "session-map");
const TMP_FALLBACK_STATE_DIR = "/tmp/zeus";

let inboxWatcher: fs.FSWatcher | null = null;
let watchedInboxDir = "";
let inboxPumpRunning = false;
let inboxPumpScheduled = false;

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

function getStateDir(): string {
  const explicit = (process.env.ZEUS_STATE_DIR ?? "").trim();
  if (explicit) return explicit;

  const zeusHome = (process.env.ZEUS_HOME ?? "").trim();
  if (zeusHome) return zeusHome;

  const home = process.env.HOME || "";
  if (home) {
    const homeState = path.join(home, ".zeus");
    if (fs.existsSync(homeState)) return homeState;
  }

  if (fs.existsSync(TMP_FALLBACK_STATE_DIR)) {
    return TMP_FALLBACK_STATE_DIR;
  }

  return path.join(home || "~", ".zeus");
}

function getHopliteInboxDir(): string {
  const agentId = getAgentId();
  return path.join(getStateDir(), "zeus-hoplite-inbox", agentId);
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

function isHopliteProcess(): boolean {
  return (process.env.ZEUS_ROLE ?? "").trim().toLowerCase() === "hoplite";
}

function scheduleInboxPump(pi: ExtensionAPI): void {
  if (inboxPumpScheduled) return;
  inboxPumpScheduled = true;
  setTimeout(() => {
    inboxPumpScheduled = false;
    processHopliteInbox(pi);
  }, 50);
}

function parseInboxPayload(raw: string): HopliteInboxPayload | null {
  try {
    const parsed = JSON.parse(raw) as Partial<HopliteInboxPayload>;
    if (!parsed || typeof parsed !== "object") return null;
    const id = typeof parsed.id === "string" ? parsed.id.trim() : "";
    const message = typeof parsed.message === "string" ? parsed.message : "";
    if (!id || !message.trim()) return null;
    return {
      id,
      message,
      source_name:
        typeof parsed.source_name === "string"
          ? parsed.source_name
          : undefined,
      source_agent_id:
        typeof parsed.source_agent_id === "string"
          ? parsed.source_agent_id
          : undefined,
    };
  } catch {
    return null;
  }
}

function processHopliteInbox(pi: ExtensionAPI): void {
  if (!isHopliteProcess()) return;
  const agentId = getAgentId();
  if (!agentId) return;

  if (inboxPumpRunning) {
    scheduleInboxPump(pi);
    return;
  }

  inboxPumpRunning = true;
  try {
    const inboxDir = getHopliteInboxDir();
    fs.mkdirSync(inboxDir, { recursive: true });

    const files = fs
      .readdirSync(inboxDir)
      .filter((name) => name.endsWith(".json"))
      .sort((a, b) => a.localeCompare(b));

    for (const fileName of files) {
      const filePath = path.join(inboxDir, fileName);
      let payload: HopliteInboxPayload | null = null;

      try {
        const raw = fs.readFileSync(filePath, "utf-8");
        payload = parseInboxPayload(raw);
      } catch {
        payload = null;
      }

      if (!payload) {
        try {
          fs.unlinkSync(filePath);
        } catch {
          // Leave unreadable files alone if deletion fails.
        }
        continue;
      }

      try {
        pi.sendUserMessage(payload.message, { deliverAs: "followUp" });
      } catch {
        // Retry later if dispatch fails.
        continue;
      }

      try {
        fs.unlinkSync(filePath);
      } catch {
        // Best effort; duplicates are harmless and should be idempotent.
      }
    }
  } catch {
    // Inbox processing is best-effort.
  } finally {
    inboxPumpRunning = false;
  }
}

function ensureHopliteInboxWatcher(pi: ExtensionAPI): void {
  if (!isHopliteProcess()) return;
  const agentId = getAgentId();
  if (!agentId) return;

  const inboxDir = getHopliteInboxDir();

  try {
    fs.mkdirSync(inboxDir, { recursive: true });
  } catch {
    return;
  }

  if (inboxWatcher && watchedInboxDir === inboxDir) {
    scheduleInboxPump(pi);
    return;
  }

  if (inboxWatcher) {
    try {
      inboxWatcher.close();
    } catch {
      // Ignore watcher close failures.
    }
    inboxWatcher = null;
    watchedInboxDir = "";
  }

  try {
    inboxWatcher = fs.watch(inboxDir, () => {
      scheduleInboxPump(pi);
    });
    watchedInboxDir = inboxDir;
  } catch {
    // fs.watch can fail on some filesystems; rely on event-driven fallback.
  }

  scheduleInboxPump(pi);
}

export default function (pi: ExtensionAPI) {
  const subscribe = (eventName: string): void => {
    pi.on(eventName as any, async (_event, ctx) => {
      try {
        syncSession(eventName, ctx);
      } catch {
        // Best-effort telemetry sync; never break pi runtime.
      }

      if (
        eventName === "session_start" ||
        eventName === "session_switch" ||
        eventName === "session_fork" ||
        eventName === "session_tree"
      ) {
        ensureHopliteInboxWatcher(pi);
      }

      if (eventName === "turn_end") {
        scheduleInboxPump(pi);
      }
    });
  };

  subscribe("session_start");
  subscribe("session_switch");
  subscribe("session_fork");
  subscribe("session_tree");
  subscribe("turn_end");
}
