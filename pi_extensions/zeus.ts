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

interface BusInboxPayload {
  id: string;
  message: string;
  deliver_as?: string;
  source_name?: string;
  source_agent_id?: string;
  source_role?: string;
}

const DEFAULT_MAP_DIR = path.join(process.env.HOME || "~", ".zeus", "session-map");
const TMP_FALLBACK_STATE_DIR = "/tmp/zeus";
const CAPABILITY_HEARTBEAT_MS = 5000;

let inboxWatcher: fs.FSWatcher | null = null;
let watchedInboxDir = "";
let inboxPumpRunning = false;
let inboxPumpScheduled = false;
let capabilityTimer: NodeJS.Timeout | null = null;
let latestCtx: any = null;
let processedIdsLoaded = false;
let processedIds = new Set<string>();

function sanitizeAgentId(value: string): string {
  return value.trim().replace(/[^A-Za-z0-9_-]/g, "");
}

function getAgentId(): string {
  return sanitizeAgentId(process.env.ZEUS_AGENT_ID ?? "");
}

function getAgentRole(): string {
  return (process.env.ZEUS_ROLE ?? "").trim().toLowerCase() || "hippeus";
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

function getBusDir(): string {
  return path.join(getStateDir(), "zeus-agent-bus");
}

function getAgentInboxRoot(agentId: string): string {
  return path.join(getBusDir(), "inbox", agentId);
}

function getAgentInboxNewDir(agentId: string): string {
  return path.join(getAgentInboxRoot(agentId), "new");
}

function getAgentInboxProcessingDir(agentId: string): string {
  return path.join(getAgentInboxRoot(agentId), "processing");
}

function getReceiptFile(agentId: string, messageId: string): string {
  return path.join(getBusDir(), "receipts", agentId, `${messageId}.json`);
}

function getCapabilityFile(agentId: string): string {
  return path.join(getBusDir(), "caps", `${agentId}.json`);
}

function getProcessedFile(agentId: string): string {
  return path.join(getBusDir(), "processed", `${agentId}.json`);
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

function writeJsonAtomic(filePath: string, payload: unknown): void {
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

function removeFile(filePath: string): void {
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
    removeFile(mapFile);
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

function writeCapability(ctx: any): void {
  const agentId = getAgentId();
  if (!agentId) return;

  const payload = {
    agent_id: agentId,
    role: getAgentRole(),
    session_id: getSessionId(ctx),
    session_path: getSessionFile(ctx),
    cwd: getCwd(ctx),
    updated_at: Date.now() / 1000,
    supports: {
      queue_bus: true,
      receipt_v1: true,
    },
    extension: {
      name: "zeus",
      version: "1",
    },
  };

  writeJsonAtomic(getCapabilityFile(agentId), payload);
}

function ensureCapabilityHeartbeat(): void {
  if (capabilityTimer) return;
  capabilityTimer = setInterval(() => {
    try {
      writeCapability(latestCtx);
    } catch {
      // Capability heartbeat is best effort.
    }
  }, CAPABILITY_HEARTBEAT_MS);
}

function parseInboxPayload(raw: string): BusInboxPayload | null {
  try {
    const parsed = JSON.parse(raw) as Partial<BusInboxPayload>;
    if (!parsed || typeof parsed !== "object") return null;
    const id = typeof parsed.id === "string" ? parsed.id.trim() : "";
    const message = typeof parsed.message === "string" ? parsed.message : "";
    if (!id || !message.trim()) return null;
    return {
      id,
      message,
      deliver_as:
        typeof parsed.deliver_as === "string" && parsed.deliver_as.trim()
          ? parsed.deliver_as.trim()
          : "followUp",
      source_name:
        typeof parsed.source_name === "string" ? parsed.source_name : undefined,
      source_agent_id:
        typeof parsed.source_agent_id === "string"
          ? parsed.source_agent_id
          : undefined,
      source_role:
        typeof parsed.source_role === "string" ? parsed.source_role : undefined,
    };
  } catch {
    return null;
  }
}

function loadProcessedIds(agentId: string): void {
  if (processedIdsLoaded) return;
  processedIdsLoaded = true;
  processedIds = new Set<string>();

  const filePath = getProcessedFile(agentId);
  try {
    const raw = JSON.parse(fs.readFileSync(filePath, "utf-8")) as any;
    const ids = Array.isArray(raw?.ids) ? raw.ids : [];
    for (const value of ids) {
      if (typeof value === "string" && value.trim()) {
        processedIds.add(value.trim());
      }
    }
  } catch {
    // Missing or invalid files are treated as empty.
  }
}

function saveProcessedIds(agentId: string): void {
  const filePath = getProcessedFile(agentId);
  const payload = {
    updated_at: Date.now() / 1000,
    ids: [...processedIds].sort((a, b) => a.localeCompare(b)),
  };
  writeJsonAtomic(filePath, payload);
}

function ensureAcceptedReceipt(agentId: string, messageId: string): void {
  const filePath = getReceiptFile(agentId, messageId);
  const payload = {
    id: messageId,
    status: "accepted",
    accepted_at: Date.now() / 1000,
    agent_id: agentId,
    session_id: latestCtx ? getSessionId(latestCtx) : "",
    session_path: latestCtx ? getSessionFile(latestCtx) : "",
  };
  writeJsonAtomic(filePath, payload);
}

function scheduleInboxPump(pi: ExtensionAPI): void {
  if (inboxPumpScheduled) return;
  inboxPumpScheduled = true;
  setTimeout(() => {
    inboxPumpScheduled = false;
    processAgentInbox(pi);
  }, 50);
}

function moveBackToNew(processingFile: string, newFile: string): void {
  try {
    fs.renameSync(processingFile, newFile);
  } catch {
    // Leave the file in processing for retry on next pass.
  }
}

function processClaimedFile(
  pi: ExtensionAPI,
  agentId: string,
  filePath: string,
  fileNameForRetry: string,
): void {
  let payload: BusInboxPayload | null = null;
  try {
    payload = parseInboxPayload(fs.readFileSync(filePath, "utf-8"));
  } catch {
    payload = null;
  }

  if (!payload) {
    removeFile(filePath);
    return;
  }

  loadProcessedIds(agentId);
  if (processedIds.has(payload.id)) {
    try {
      ensureAcceptedReceipt(agentId, payload.id);
    } catch {
      // Best effort.
    }
    removeFile(filePath);
    return;
  }

  try {
    pi.sendUserMessage(payload.message, {
      deliverAs: payload.deliver_as === "followUp" ? "followUp" : "followUp",
    });
  } catch {
    const retryPath = path.join(getAgentInboxNewDir(agentId), fileNameForRetry);
    moveBackToNew(filePath, retryPath);
    return;
  }

  processedIds.add(payload.id);
  try {
    saveProcessedIds(agentId);
  } catch {
    // Keep running; worst case is duplicate prevention loss after restart.
  }

  try {
    ensureAcceptedReceipt(agentId, payload.id);
  } catch {
    // Receipt is best effort; retries will restore it using processed ledger.
  }

  removeFile(filePath);
}

function processAgentInbox(pi: ExtensionAPI): void {
  const agentId = getAgentId();
  if (!agentId) return;

  if (inboxPumpRunning) {
    scheduleInboxPump(pi);
    return;
  }

  inboxPumpRunning = true;
  try {
    const inboxNew = getAgentInboxNewDir(agentId);
    const inboxProcessing = getAgentInboxProcessingDir(agentId);
    fs.mkdirSync(inboxNew, { recursive: true });
    fs.mkdirSync(inboxProcessing, { recursive: true });

    const processingFiles = fs
      .readdirSync(inboxProcessing)
      .filter((name) => name.endsWith(".json"))
      .sort((a, b) => a.localeCompare(b));

    for (const fileName of processingFiles) {
      const claimedPath = path.join(inboxProcessing, fileName);
      processClaimedFile(pi, agentId, claimedPath, fileName);
    }

    const newFiles = fs
      .readdirSync(inboxNew)
      .filter((name) => name.endsWith(".json"))
      .sort((a, b) => a.localeCompare(b));

    for (const fileName of newFiles) {
      const sourcePath = path.join(inboxNew, fileName);
      const claimedPath = path.join(inboxProcessing, fileName);
      try {
        fs.renameSync(sourcePath, claimedPath);
      } catch {
        continue;
      }
      processClaimedFile(pi, agentId, claimedPath, fileName);
    }
  } catch {
    // Inbox processing is best-effort.
  } finally {
    inboxPumpRunning = false;
  }
}

function ensureInboxWatcher(pi: ExtensionAPI): void {
  const agentId = getAgentId();
  if (!agentId) return;

  const watchDir = getAgentInboxRoot(agentId);
  try {
    fs.mkdirSync(getAgentInboxNewDir(agentId), { recursive: true });
    fs.mkdirSync(getAgentInboxProcessingDir(agentId), { recursive: true });
  } catch {
    return;
  }

  if (inboxWatcher && watchedInboxDir === watchDir) {
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
    inboxWatcher = fs.watch(watchDir, () => {
      scheduleInboxPump(pi);
    });
    watchedInboxDir = watchDir;
  } catch {
    // fs.watch can fail on some filesystems; turn_end hook remains fallback.
  }

  scheduleInboxPump(pi);
}

export default function (pi: ExtensionAPI) {
  const subscribe = (eventName: string): void => {
    pi.on(eventName as any, async (_event, ctx) => {
      latestCtx = ctx;

      try {
        syncSession(eventName, ctx);
      } catch {
        // Best-effort telemetry sync; never break pi runtime.
      }

      try {
        writeCapability(ctx);
      } catch {
        // Capability heartbeat writes are best effort.
      }
      ensureCapabilityHeartbeat();

      if (
        eventName === "session_start" ||
        eventName === "session_switch" ||
        eventName === "session_fork" ||
        eventName === "session_tree"
      ) {
        ensureInboxWatcher(pi);
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
