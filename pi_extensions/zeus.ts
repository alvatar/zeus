import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { Box, Text } from "@mariozechner/pi-tui";
import { Type } from "@sinclair/typebox";
import * as crypto from "node:crypto";
import * as fs from "node:fs";
import * as path from "node:path";

interface SessionSyncPayload {
  agentId: string;
  sessionPath: string;
  sessionId: string;
  cwd: string;
  updatedAt: string;
  event: string;
  sessionKey: string;
  identitySource: "env" | "adopted" | "anonymous";
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
let adoptionWatcher: fs.FSWatcher | null = null;
let watchedInboxDir = "";
let watchedAdoptionsDir = "";
let inboxPumpRunning = false;
let inboxPumpScheduled = false;
let capabilityTimer: NodeJS.Timeout | null = null;
let latestCtx: any = null;
let processedIdsLoadedForAgentId = "";
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

function getSessionRecordDir(): string {
  return path.join(getMapDir(), "sessions");
}

function getSessionAdoptionsDir(): string {
  return path.join(getMapDir(), "adoptions");
}

function normalizeSessionPath(value: string): string {
  const clean = value.trim();
  if (!clean) return "";
  const resolved = path.resolve(clean);
  if (!path.isAbsolute(resolved)) return "";
  try {
    if (!fs.existsSync(resolved)) return "";
    if (!fs.statSync(resolved).isFile()) return "";
  } catch {
    return "";
  }
  return resolved;
}

function getSessionKey(sessionPath: string): string {
  const normalized = normalizeSessionPath(sessionPath);
  if (!normalized) return "";
  return crypto.createHash("sha256").update(normalized).digest("hex");
}

function getSessionRecordFile(sessionPath: string): string {
  const key = getSessionKey(sessionPath);
  if (!key) return "";
  return path.join(getSessionRecordDir(), `${key}.json`);
}

function getSessionAdoptionFile(sessionPath: string): string {
  const key = getSessionKey(sessionPath);
  if (!key) return "";
  return path.join(getSessionAdoptionsDir(), `${key}.json`);
}

function readAdoptedAgentId(ctx: any): string {
  const sessionPath = normalizeSessionPath(getSessionFile(ctx));
  if (!sessionPath) return "";

  const filePath = getSessionAdoptionFile(sessionPath);
  if (!filePath) return "";

  try {
    const raw = JSON.parse(fs.readFileSync(filePath, "utf-8")) as any;
    if (!raw || typeof raw !== "object") return "";
    const adoptedPath = normalizeSessionPath(
      typeof raw.sessionPath === "string" ? raw.sessionPath : "",
    );
    if (!adoptedPath || adoptedPath !== sessionPath) return "";
    return sanitizeAgentId(typeof raw.agentId === "string" ? raw.agentId : "");
  } catch {
    return "";
  }
}

function getEffectiveAgentId(ctx: any): string {
  return getAgentId() || readAdoptedAgentId(ctx);
}

function getEffectiveIdentitySource(ctx: any): "env" | "adopted" | "anonymous" {
  if (getAgentId()) return "env";
  if (readAdoptedAgentId(ctx)) return "adopted";
  return "anonymous";
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
  const sessionPath = normalizeSessionPath(getSessionFile(ctx));
  const effectiveAgentId = getEffectiveAgentId(ctx);

  if (!sessionPath) {
    if (effectiveAgentId) {
      removeFile(path.join(getMapDir(), `${effectiveAgentId}.json`));
    }
    return;
  }

  const payload: SessionSyncPayload = {
    agentId: effectiveAgentId,
    sessionPath,
    sessionId: getSessionId(ctx),
    cwd: getCwd(ctx),
    updatedAt: new Date().toISOString(),
    event: eventName,
    sessionKey: getSessionKey(sessionPath),
    identitySource: getEffectiveIdentitySource(ctx),
  };

  const sessionRecordFile = getSessionRecordFile(sessionPath);
  if (sessionRecordFile) {
    writeJsonAtomic(sessionRecordFile, payload);
  }

  if (effectiveAgentId) {
    const mapFile = path.join(getMapDir(), `${effectiveAgentId}.json`);
    writeJsonAtomic(mapFile, payload);
  }
}

function writeCapability(ctx: any): void {
  const agentId = getEffectiveAgentId(ctx);
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

function ensureCapabilityHeartbeat(pi: ExtensionAPI): void {
  if (capabilityTimer) return;
  capabilityTimer = setInterval(() => {
    if (!latestCtx) return;

    try {
      syncSession("heartbeat", latestCtx);
    } catch {
      // Runtime sync is best effort.
    }

    try {
      writeCapability(latestCtx);
    } catch {
      // Capability heartbeat is best effort.
    }

    try {
      ensureInboxWatcher(pi);
      scheduleInboxPump(pi);
    } catch {
      // Inbox refresh is best effort.
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
  if (processedIdsLoadedForAgentId === agentId) return;
  processedIdsLoadedForAgentId = agentId;
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
    const deliverAs = payload.deliver_as === "steer" ? "steer" : "followUp";
    pi.sendUserMessage(payload.message, { deliverAs });
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
  const agentId = getEffectiveAgentId(latestCtx);
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
  const agentId = getEffectiveAgentId(latestCtx);
  if (!agentId) return;

  const watchDir = getAgentInboxNewDir(agentId);
  try {
    fs.mkdirSync(watchDir, { recursive: true });
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

function ensureAdoptionWatcher(pi: ExtensionAPI): void {
  const watchDir = getSessionAdoptionsDir();
  try {
    fs.mkdirSync(watchDir, { recursive: true });
  } catch {
    return;
  }

  if (adoptionWatcher && watchedAdoptionsDir === watchDir) {
    return;
  }

  if (adoptionWatcher) {
    try {
      adoptionWatcher.close();
    } catch {
      // Ignore watcher close failures.
    }
    adoptionWatcher = null;
    watchedAdoptionsDir = "";
  }

  try {
    adoptionWatcher = fs.watch(watchDir, () => {
      if (!latestCtx) return;
      try {
        syncSession("adoption_refresh", latestCtx);
      } catch {
        // Best effort.
      }
      try {
        writeCapability(latestCtx);
      } catch {
        // Best effort.
      }
      ensureInboxWatcher(pi);
      scheduleInboxPump(pi);
    });
    watchedAdoptionsDir = watchDir;
  } catch {
    // fs.watch can fail on some filesystems; heartbeat remains fallback.
  }
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
      ensureCapabilityHeartbeat(pi);
      ensureAdoptionWatcher(pi);

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

  // ── Memory config ─────────────────────────────────────────────────────
  const MEMORY_CONFIG_PATH = path.join(getStateDir(), "memory-config.json");

  interface MemoryConfig {
    verbose: boolean;
  }

  function loadMemoryConfig(): MemoryConfig {
    try {
      const raw = JSON.parse(fs.readFileSync(MEMORY_CONFIG_PATH, "utf-8"));
      return { verbose: raw.verbose !== false }; // default true
    } catch {
      return { verbose: true }; // default on
    }
  }

  function saveMemoryConfig(cfg: MemoryConfig): void {
    try {
      fs.mkdirSync(path.dirname(MEMORY_CONFIG_PATH), { recursive: true });
      fs.writeFileSync(MEMORY_CONFIG_PATH, JSON.stringify(cfg, null, 2));
    } catch { /* best effort */ }
  }

  let memoryConfig = loadMemoryConfig();
  let memoryInjectionEnabled = true;

  // ── Memory message renderer ───────────────────────────────────────────
  pi.registerMessageRenderer("zeus_memory_log", (message, _options, theme) => {
    const content = typeof message.content === "string"
      ? message.content
      : message.content.map((c) => ("text" in c ? c.text : "")).join("");
    const box = new Box(1, 1, (t) => theme.bg("customMessageBg", t));
    box.addChild(new Text(theme.fg("dim", content), 0, 0));
    return box;
  });

  /** Log a memory event as a visible custom message (when verbose). */
  function memoryLog(label: string, detail: string): void {
    if (!memoryConfig.verbose) return;
    try {
      pi.sendMessage({
        customType: "zeus_memory_log",
        content: `🧠 [memory:${label}] ${detail}`,
        display: true,
      });
    } catch { /* best effort */ }
  }

  // ── /memory command ───────────────────────────────────────────────────

  /** Helper: run a raw sqlite3 query (plain text mode) against memory.db and return stdout. */
  async function memoryQueryRaw(sql: string): Promise<string> {
    const dbPath = path.join(getStateDir(), "memory.db");
    if (!fs.existsSync(dbPath)) return "";
    const r = await pi.exec("sqlite3", [dbPath, sql], { timeout: 5000 });
    return r.code === 0 ? (r.stdout || "").trim() : "";
  }

  /** Helper: run a sqlite3 query in JSON mode and parse the result. */
  async function memoryQueryJson(sql: string): Promise<Record<string, string>[]> {
    const dbPath = path.join(getStateDir(), "memory.db");
    if (!fs.existsSync(dbPath)) return [];
    const r = await pi.exec("sqlite3", [dbPath, ".mode json", ".headers on", sql], { timeout: 5000 });
    if (r.code !== 0 || !(r.stdout || "").trim()) return [];
    try { return JSON.parse(r.stdout!); } catch { return []; }
  }

  /** Format a memory row for display. */
  function fmtMemory(ns: string, key: string, content: string, tags: string): string {
    const tagStr = tags ? ` [${tags}]` : "";
    const preview = content.length > 120 ? content.slice(0, 120) + "…" : content;
    return `  ${ns}/${key}${tagStr}\n    ${preview.replace(/\n/g, "\n    ")}`;
  }

  pi.registerCommand("memory", {
    description: "Memory system — /memory help for all subcommands",
    async handler(args: string, _ctx) {
      // Preserve case for namespace/key args, lowercase only the subcommand
      const rawParts = args.trim().split(/\s+/);
      const sub = (rawParts[0] || "help").toLowerCase();

      // ── verbose ──────────────────────────────────────────────────
      if (sub === "verbose") {
        const val = (rawParts[1] || "").toLowerCase();
        if (val === "on" || val === "true" || val === "1") {
          memoryConfig.verbose = true;
          saveMemoryConfig(memoryConfig);
          pi.sendMessage({ customType: "zeus_memory_log", content: "🧠 Memory verbose logging: ON", display: true });
        } else if (val === "off" || val === "false" || val === "0") {
          memoryConfig.verbose = false;
          saveMemoryConfig(memoryConfig);
          pi.sendMessage({ customType: "zeus_memory_log", content: "🧠 Memory verbose logging: OFF", display: true });
        } else {
          pi.sendMessage({
            customType: "zeus_memory_log",
            content: `🧠 Verbose logging: ${memoryConfig.verbose ? "ON" : "OFF"}\nUsage: /memory verbose on|off`,
            display: true,
          });
        }
        return;
      }

      // ── injection toggle (current agent only) ────────────────────
      if (sub === "enable") {
        memoryInjectionEnabled = true;
        pi.sendMessage({
          customType: "zeus_memory_log",
          content: "🧠 Memory injection: ON (current agent)",
          display: true,
        });
        return;
      }

      if (sub === "disable") {
        memoryInjectionEnabled = false;
        pi.sendMessage({
          customType: "zeus_memory_log",
          content: "🧠 Memory injection: OFF (current agent)",
          display: true,
        });
        return;
      }

      // ── status ───────────────────────────────────────────────────
      if (sub === "status") {
        const dbPath = path.join(getStateDir(), "memory.db");
        const exists = fs.existsSync(dbPath);
        let count = "?";
        let namespaces = "";
        if (exists) {
          count = await memoryQueryRaw("SELECT COUNT(*) FROM memories WHERE archived = 0;") || "0";
          namespaces = await memoryQueryRaw(
            "SELECT namespace || ' (' || COUNT(*) || ')' FROM memories WHERE archived = 0 GROUP BY namespace ORDER BY namespace;"
          );
        }
        pi.sendMessage({
          customType: "zeus_memory_log",
          content: [
            `🧠 Memory status:`,
            `  DB: ${dbPath} (${exists ? "exists" : "not created"})`,
            `  Total: ${count} active memories`,
            `  Verbose: ${memoryConfig.verbose ? "ON" : "OFF"}`,
            `  Injection (this agent): ${memoryInjectionEnabled ? "ON" : "OFF"}`,
            namespaces ? `  Namespaces:\n    ${namespaces.split("\n").join("\n    ")}` : "",
          ].filter(Boolean).join("\n"),
          display: true,
        });
        return;
      }

      // ── list [namespace] ─────────────────────────────────────────
      if (sub === "list" || sub === "ls") {
        const ns = rawParts[1] || "";
        let sql: string;
        if (ns) {
          sql = `SELECT namespace, key, content, tags FROM memories WHERE archived = 0 AND namespace = '${ns.replace(/'/g, "''")}' ORDER BY key;`;
        } else {
          sql = `SELECT namespace, key, content, tags FROM memories WHERE archived = 0 ORDER BY namespace, key;`;
        }
        const rows = await memoryQueryJson(sql);
        if (!rows.length) {
          pi.sendMessage({ customType: "zeus_memory_log", content: ns ? `🧠 No memories in namespace '${ns}'.` : "🧠 No memories found.", display: true });
          return;
        }
        const entries = rows.map(r => fmtMemory(r.namespace, r.key, r.content, r.tags));
        pi.sendMessage({
          customType: "zeus_memory_log",
          content: `🧠 Memories${ns ? ` in ${ns}` : ""} (${rows.length}):\n${entries.join("\n\n")}`,
          display: true,
        });
        return;
      }

      // ── get <namespace> <key> ────────────────────────────────────
      if (sub === "get" || sub === "recall") {
        const ns = rawParts[1];
        const key = rawParts[2];
        if (!ns || !key) {
          pi.sendMessage({ customType: "zeus_memory_log", content: "Usage: /memory get <namespace> <key>", display: true });
          return;
        }
        const rows = await memoryQueryJson(
          `SELECT content, tags, updated_at FROM memories WHERE archived = 0 AND namespace = '${ns.replace(/'/g, "''")}' AND key = '${key.replace(/'/g, "''")}';`
        );
        if (!rows.length) {
          pi.sendMessage({ customType: "zeus_memory_log", content: `🧠 Not found: ${ns}/${key}`, display: true });
          return;
        }
        const r = rows[0];
        pi.sendMessage({
          customType: "zeus_memory_log",
          content: `🧠 ${ns}/${key}${r.tags ? ` [${r.tags}]` : ""}${r.updated_at ? ` (updated: ${r.updated_at})` : ""}\n\n${r.content}`,
          display: true,
        });
        return;
      }

      // ── search <query> ───────────────────────────────────────────
      if (sub === "search" || sub === "find") {
        const query = rawParts.slice(1).join(" ");
        if (!query) {
          pi.sendMessage({ customType: "zeus_memory_log", content: "Usage: /memory search <query>", display: true });
          return;
        }
        const escaped = query.replace(/'/g, "''");
        const rows = await memoryQueryJson(
          `SELECT m.namespace, m.key, m.content, m.tags FROM memories m JOIN memories_fts f ON m.id = f.rowid WHERE m.archived = 0 AND f.memories_fts MATCH '${escaped}' ORDER BY rank LIMIT 20;`
        );
        if (!rows.length) {
          pi.sendMessage({ customType: "zeus_memory_log", content: `🧠 No results for '${query}'.`, display: true });
          return;
        }
        const entries = rows.map(r => fmtMemory(r.namespace, r.key, r.content, r.tags));
        pi.sendMessage({
          customType: "zeus_memory_log",
          content: `🧠 Search '${query}' (${entries.length} results):\n${entries.join("\n\n")}`,
          display: true,
        });
        return;
      }

      // ── delete <namespace> <key> ─────────────────────────────────
      if (sub === "delete" || sub === "rm") {
        const ns = rawParts[1];
        const key = rawParts[2];
        if (!ns || !key) {
          pi.sendMessage({ customType: "zeus_memory_log", content: "Usage: /memory delete <namespace> <key>", display: true });
          return;
        }
        const rows = await memoryQueryJson(
          `SELECT id FROM memories WHERE archived = 0 AND namespace = '${ns.replace(/'/g, "''")}' AND key = '${key.replace(/'/g, "''")}';`
        );
        if (!rows.length) {
          pi.sendMessage({ customType: "zeus_memory_log", content: `🧠 Not found: ${ns}/${key}`, display: true });
          return;
        }
        await memoryQueryRaw(
          `DELETE FROM memories WHERE namespace = '${ns.replace(/'/g, "''")}' AND key = '${key.replace(/'/g, "''")}';`
        );
        pi.sendMessage({ customType: "zeus_memory_log", content: `🧠 Deleted: ${ns}/${key}`, display: true });
        return;
      }

      // ── topics ───────────────────────────────────────────────────
      if (sub === "topics") {
        const topics = await memoryQueryRaw(
          "SELECT REPLACE(namespace, 'topic:', '') || ' (' || COUNT(*) || ' memories)' FROM memories WHERE archived = 0 AND namespace LIKE 'topic:%' GROUP BY namespace ORDER BY namespace;"
        );
        const pending = await memoryQueryRaw(
          "SELECT REPLACE(namespace, 'new:', '') || ' (' || COUNT(*) || ' pending)' FROM memories WHERE archived = 0 AND namespace LIKE 'new:%' GROUP BY namespace ORDER BY namespace;"
        );
        const lines: string[] = ["🧠 Topics:"];
        if (topics) lines.push("  Promoted:\n    " + topics.split("\n").join("\n    "));
        else lines.push("  (no promoted topics)");
        if (pending) lines.push("  Staging (new:*):\n    " + pending.split("\n").join("\n    "));
        pi.sendMessage({ customType: "zeus_memory_log", content: lines.join("\n"), display: true });
        return;
      }

      // ── save <namespace> <key> <content...> ────────────────────
      if (sub === "save" || sub === "set") {
        const ns = rawParts[1];
        const key = rawParts[2];
        const content = rawParts.slice(3).join(" ");
        if (!ns || !key || !content) {
          pi.sendMessage({ customType: "zeus_memory_log", content: "Usage: /memory save <namespace> <key> <content...>", display: true });
          return;
        }
        try {
          await ensureMemorySchema();
          await sqliteExec(
            `INSERT INTO memories (namespace, key, content, tags, source_agent, source_project)
             VALUES ('${sqlEscape(ns)}', '${sqlEscape(key)}', '${sqlEscape(content)}', '', '${sqlEscape(getAgentId())}', '${sqlEscape(await resolveProjectName())}')
             ON CONFLICT(namespace, key) DO UPDATE SET content = excluded.content, updated_at = datetime('now');`
          );
          pi.sendMessage({ customType: "zeus_memory_log", content: `🧠 Saved: ${ns}/${key}`, display: true });
        } catch (e: any) {
          pi.sendMessage({ customType: "zeus_memory_log", content: `🧠 Error saving: ${e.message || e}`, display: true });
        }
        return;
      }

      // ── rename <old_ns> <new_ns> ─────────────────────────────────
      if (sub === "rename" || sub === "mv") {
        const oldNs = rawParts[1];
        const newNs = rawParts[2];
        if (!oldNs || !newNs) {
          pi.sendMessage({ customType: "zeus_memory_log", content: "Usage: /memory rename <old_namespace> <new_namespace>\nExample: /memory rename project:old-name project:new-name", display: true });
          return;
        }
        try {
          await ensureMemorySchema();
          const count = await memoryQueryRaw(
            `SELECT COUNT(*) FROM memories WHERE namespace = '${sqlEscape(oldNs)}';`
          );
          if (!count || count === "0") {
            pi.sendMessage({ customType: "zeus_memory_log", content: `🧠 No memories found in namespace '${oldNs}'.`, display: true });
            return;
          }
          await sqliteExec(`
            UPDATE memories SET namespace = '${sqlEscape(newNs)}' WHERE namespace = '${sqlEscape(oldNs)}';
            UPDATE memories SET source_project = '${sqlEscape(newNs.replace("project:", ""))}' WHERE source_project = '${sqlEscape(oldNs.replace("project:", ""))}';
            UPDATE topic_links SET project = '${sqlEscape(newNs.replace("project:", ""))}' WHERE project = '${sqlEscape(oldNs.replace("project:", ""))}';
          `);
          pi.sendMessage({ customType: "zeus_memory_log", content: `🧠 Renamed: ${oldNs} → ${newNs} (${count} memories)`, display: true });
        } catch (e: any) {
          pi.sendMessage({ customType: "zeus_memory_log", content: `🧠 Error: ${e.message || e}`, display: true });
        }
        return;
      }

      // ── namespaces ───────────────────────────────────────────────
      if (sub === "namespaces" || sub === "ns") {
        const raw = await memoryQueryRaw(
          "SELECT namespace || ': ' || COUNT(*) || ' memories' FROM memories WHERE archived = 0 GROUP BY namespace ORDER BY namespace;"
        );
        pi.sendMessage({
          customType: "zeus_memory_log",
          content: raw ? `🧠 Namespaces:\n  ${raw.split("\n").join("\n  ")}` : "🧠 No memories.",
          display: true,
        });
        return;
      }

      // ── help ─────────────────────────────────────────────────────
      pi.sendMessage({
        customType: "zeus_memory_log",
        content: [
          "🧠 /memory commands:",
          "",
          "  /memory status                       — DB stats, namespace counts, verbose state",
          "  /memory list [namespace]             — list all memories (or filter by namespace)",
          "  /memory get <ns> <key>               — show full content of a memory",
          "  /memory save <ns> <key> <content...> — save or update a memory",
          "  /memory search <query>               — full-text search across all memories",
          "  /memory delete <ns> <key>            — permanently remove a memory",
          "  /memory rename <old_ns> <new_ns>     — rename a namespace (e.g. after moving a project folder)",
          "  /memory namespaces                   — list all namespaces with counts",
          "  /memory topics                       — list topics and pending staging entries",
          "  /memory enable                       — enable memory injection for this agent",
          "  /memory disable                      — disable memory injection for this agent",
          "  /memory verbose on|off               — toggle verbose memory logging",
          "",
          "  Aliases: ls=list, find=search, rm=delete, ns=namespaces, recall=get, set=save, mv=rename",
        ].join("\n"),
        display: true,
      });
    },
  });

  // ── Memory injection (before_agent_start) ─────────────────────────────
  // Appends relevant memories to the system prompt each turn.
  // Budget: 10K tokens (~40K chars) total.
  const MEMORY_BUDGET_CHARS = 40000;
  const GLOBAL_BUDGET = 8000;    // ~2K tokens
  const PROJECT_BUDGET = 12000;  // ~3K tokens
  const TOPIC_BUDGET = 16000;    // ~4K tokens
  // Remainder for FTS if needed (not used in auto-injection yet).

  pi.on("before_agent_start", async (event, _ctx) => {
    try {
      if (!memoryInjectionEnabled) return;

      const dbPath = path.join(getStateDir(), "memory.db");
      if (!fs.existsSync(dbPath)) return;

      const project = await resolveProjectName();
      if (!project) return;

      // Load linked topics
      let linkedTopics: string[] = [];
      try {
        const linkResult = await pi.exec("sqlite3", [
          dbPath, ".mode json",
          `SELECT topic FROM topic_links WHERE project = '${sqlEscape(project)}' ORDER BY topic;`,
        ], { timeout: 5000 });
        if (linkResult.code === 0 && linkResult.stdout) {
          const parsed = JSON.parse(linkResult.stdout.trim() || "[]");
          linkedTopics = parsed.map((r: any) => r.topic).filter(Boolean);
        }
      } catch {}

      // Build namespace list
      const namespaces = ["global", `project:${project}`];
      for (const t of linkedTopics) namespaces.push(`topic:${t}`);

      // Load all memories in relevant namespaces
      const inClause = namespaces.map((n) => `'${sqlEscape(n)}'`).join(",");
      const memResult = await pi.exec("sqlite3", [
        dbPath, ".mode json",
        `SELECT namespace, key, content FROM memories WHERE namespace IN (${inClause}) AND archived = 0 ORDER BY access_count DESC, updated_at DESC;`,
      ], { timeout: 5000 });

      if (memResult.code !== 0 || !memResult.stdout?.trim()) return;

      let rows: Array<{ namespace: string; key: string; content: string }>;
      try {
        rows = JSON.parse(memResult.stdout.trim());
      } catch {
        return;
      }
      if (!rows.length) return;

      // Partition by type
      const globalMems: typeof rows = [];
      const projectMems: typeof rows = [];
      const topicMems: Record<string, typeof rows> = {};

      for (const r of rows) {
        if (r.namespace === "global") {
          globalMems.push(r);
        } else if (r.namespace === `project:${project}`) {
          projectMems.push(r);
        } else if (r.namespace.startsWith("topic:")) {
          const tName = r.namespace.slice(6);
          if (!topicMems[tName]) topicMems[tName] = [];
          topicMems[tName].push(r);
        }
      }

      // Format sections with budget enforcement
      const sections: string[] = [];
      let totalChars = 0;

      const addSection = (title: string, mems: typeof rows, budget: number) => {
        if (!mems.length) return;
        let used = 0;
        const lines: string[] = [`## ${title}`];
        for (const m of mems) {
          const line = `- **${m.key}**: ${m.content}`;
          if (used + line.length > budget) break;
          lines.push(line);
          used += line.length;
        }
        if (lines.length > 1) {
          const block = lines.join("\n");
          totalChars += block.length;
          sections.push(block);
        }
      };

      addSection("Global Memories", globalMems, GLOBAL_BUDGET);
      addSection(`Project: ${project}`, projectMems, PROJECT_BUDGET);

      // Distribute topic budget across linked topics
      const topicNames = Object.keys(topicMems);
      if (topicNames.length > 0) {
        const perTopic = Math.floor(TOPIC_BUDGET / topicNames.length);
        for (const tName of topicNames) {
          addSection(`Topic: ${tName}`, topicMems[tName], perTopic);
        }
      }

      if (!sections.length) return;
      if (totalChars > MEMORY_BUDGET_CHARS) {
        // Truncate: drop last sections if over budget
        while (sections.length > 1 && totalChars > MEMORY_BUDGET_CHARS) {
          const removed = sections.pop()!;
          totalChars -= removed.length;
        }
      }

      const memoryBlock = [
        "",
        "# Agent Memory",
        "The following are your persistent memories across sessions. Use them as context.",
        "",
        ...sections,
      ].join("\n");

      memoryLog("inject", `${rows.length} memories injected (${totalChars} chars) — global:${globalMems.length} project:${projectMems.length} topics:${topicNames.length}`);

      return { systemPrompt: event.systemPrompt + memoryBlock };
    } catch {
      // Memory injection is best-effort; never break the agent loop.
      return;
    }
  });

  // ── Memory helpers ────────────────────────────────────────────────────
  const MEMORY_DB = path.join(getStateDir(), "memory.db");

  /** Run a sqlite3 command and return stdout. Lazily initialises the DB. */
  async function sqliteExec(sql: string, signal?: AbortSignal): Promise<string> {
    // Ensure parent dir exists
    const dir = path.dirname(MEMORY_DB);
    try { fs.mkdirSync(dir, { recursive: true }); } catch {}

    const result = await pi.exec(
      "sqlite3",
      [MEMORY_DB, ".mode json", ".headers on", sql],
      { signal, timeout: 10000 },
    );
    if (result.code !== 0) {
      throw new Error(`sqlite3 error: ${result.stderr || result.stdout}`);
    }
    return (result.stdout || "").trim();
  }

  /** Initialise memory DB schema if needed. */
  async function ensureMemorySchema(signal?: AbortSignal): Promise<void> {
    await sqliteExec(`
      CREATE TABLE IF NOT EXISTS memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        namespace TEXT NOT NULL,
        key TEXT NOT NULL,
        content TEXT NOT NULL,
        metadata TEXT DEFAULT '{}',
        tags TEXT DEFAULT '',
        source_agent TEXT DEFAULT '',
        source_project TEXT DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        accessed_at TEXT,
        access_count INTEGER DEFAULT 0,
        archived INTEGER DEFAULT 0,
        UNIQUE(namespace, key)
      );
      CREATE TABLE IF NOT EXISTS topic_links (
        project TEXT NOT NULL,
        topic TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(project, topic)
      );
      CREATE INDEX IF NOT EXISTS idx_memories_ns ON memories(namespace);
      CREATE INDEX IF NOT EXISTS idx_memories_ns_archived ON memories(namespace, archived);
      CREATE INDEX IF NOT EXISTS idx_memories_source_project ON memories(source_project);
      CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
        namespace, key, content, tags,
        content=memories, content_rowid=id
      );
      CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
        INSERT INTO memories_fts(rowid, namespace, key, content, tags)
        VALUES (new.id, new.namespace, new.key, new.content, new.tags);
      END;
      CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
        INSERT INTO memories_fts(memories_fts, rowid, namespace, key, content, tags)
        VALUES ('delete', old.id, old.namespace, old.key, old.content, old.tags);
      END;
      CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
        INSERT INTO memories_fts(memories_fts, rowid, namespace, key, content, tags)
        VALUES ('delete', old.id, old.namespace, old.key, old.content, old.tags);
        INSERT INTO memories_fts(rowid, namespace, key, content, tags)
        VALUES (new.id, new.namespace, new.key, new.content, new.tags);
      END;
    `, signal);
  }

  let schemaEnsured = false;
  async function withSchema(signal?: AbortSignal): Promise<void> {
    if (!schemaEnsured) {
      await ensureMemorySchema(signal);
      schemaEnsured = true;
    }
  }

  /** Escape a string for safe use in SQL single-quoted literals. */
  function sqlEscape(s: string): string {
    return s.replace(/'/g, "''");
  }

  /** Resolve the current project name from the canonical git repo root. */
  async function resolveProjectName(signal?: AbortSignal): Promise<string> {
    try {
      const commonResult = await pi.exec("git", ["rev-parse", "--git-common-dir"], { signal, timeout: 5000 });
      if (commonResult.code !== 0) return "";

      const commonRaw = (commonResult.stdout || "").trim();
      const cwd = getCwd(latestCtx) || process.cwd();
      const commonDir = path.resolve(cwd, commonRaw);

      let root = "";
      if (path.basename(commonDir) === ".git") {
        root = path.dirname(commonDir);
      } else {
        const topResult = await pi.exec("git", ["rev-parse", "--show-toplevel"], { signal, timeout: 5000 });
        if (topResult.code !== 0) return "";
        root = (topResult.stdout || "").trim();
      }
      if (!root) return "";

      const home = process.env.HOME || "";
      const codePrefix = path.join(home, "code") + path.sep;
      let name: string;
      if (root.startsWith(codePrefix)) {
        name = root.slice(codePrefix.length);
      } else {
        name = path.basename(root);
      }
      return name.replace(/\//g, "-");
    } catch {
      return "";
    }
  }

  /** Validate namespace for agent writes. */
  function validateNamespace(ns: string): string | null {
    const trimmed = ns.trim();
    if (/^(global|project:[a-zA-Z0-9_-]+|new:[a-zA-Z0-9_-]+)$/.test(trimmed)) {
      return trimmed;
    }
    if (/^topic:[a-zA-Z0-9_-]+$/.test(trimmed)) {
      return null; // topic: is read-only for regular agents
    }
    return null;
  }

  // ── zeus_tmux tool ──────────────────────────────────────────────────
  // Creates a tmux session with automatic Zeus ownership stamping.
  // Agents should use this instead of raw `tmux new-session` commands.
  pi.registerTool({
    name: "zeus_tmux",
    label: "Zeus tmux",
    description:
      "Create a tmux session tracked by Zeus. Automatically stamps ownership so the session appears under this agent in the dashboard. Use this instead of raw tmux commands.",
    parameters: Type.Object({
      session_name: Type.String({ description: "tmux session name (e.g. 'my-build-1234')" }),
      command: Type.String({
        description: "Shell command to run inside the session (e.g. 'cargo test 2>&1 | tee /tmp/test.log')",
      }),
      cwd: Type.Optional(
        Type.String({ description: "Working directory for the session (default: current directory)" }),
      ),
    }),
    async execute(_toolCallId, params, signal) {
      const agentId = getAgentId();
      const sessionName = params.session_name.trim();
      if (!sessionName) {
        return {
          content: [{ type: "text", text: "Error: session_name is required" }],
          details: { error: "empty session_name" },
        };
      }

      // Build tmux new-session command
      const tmuxArgs: string[] = ["new-session", "-d", "-s", sessionName];

      // Pass ZEUS_AGENT_ID into the tmux session environment
      if (agentId) {
        tmuxArgs.push("-e", `ZEUS_AGENT_ID=${agentId}`);
      }

      // Set working directory if provided
      if (params.cwd) {
        tmuxArgs.push("-c", params.cwd);
      }

      // The shell command to run
      tmuxArgs.push(params.command);

      try {
        const createResult = await pi.exec("tmux", tmuxArgs, { signal, timeout: 10000 });
        if (createResult.code !== 0) {
          const errMsg = (createResult.stderr || createResult.stdout || "").trim();
          return {
            content: [{ type: "text", text: `tmux new-session failed (exit ${createResult.code}): ${errMsg}` }],
            details: { exit_code: createResult.code, stderr: errMsg },
          };
        }

        // Stamp @zeus_owner for deterministic dashboard matching
        if (agentId) {
          try {
            await pi.exec("tmux", ["set-option", "-t", sessionName, "@zeus_owner", agentId], {
              signal,
              timeout: 5000,
            });
          } catch {
            // Best-effort: session is created, ownership stamp failed.
          }
        }

        return {
          content: [{ type: "text", text: `tmux session '${sessionName}' created.` }],
          details: { session_name: sessionName, agent_id: agentId || null },
        };
      } catch (err: any) {
        return {
          content: [{ type: "text", text: `Error creating tmux session: ${err?.message || String(err)}` }],
          details: { error: String(err) },
        };
      }
    },
  });

  // ── zeus_memory_save ────────────────────────────────────────────────
  pi.registerTool({
    name: "zeus_memory_save",
    label: "Save memory",
    description:
      "Store a persistent memory. Namespace must be 'global', 'project:<name>', or 'new:<name>'. Use 'new:<name>' for specialized knowledge beyond the current project.",
    parameters: Type.Object({
      namespace: Type.String({ description: "Namespace: 'global', 'project:<name>', or 'new:<name>'" }),
      key: Type.String({ description: "Descriptive key (e.g. 'error-handling-convention')" }),
      content: Type.String({ description: "Memory content — concise, actionable" }),
      tags: Type.Optional(Type.String({ description: "Comma-separated tags" })),
    }),
    async execute(_toolCallId, params, signal) {
      const ns = validateNamespace(params.namespace);
      if (!ns) {
        const trimmed = params.namespace.trim();
        if (/^topic:/.test(trimmed)) {
          return {
            content: [{ type: "text", text: `Cannot write directly to '${trimmed}'. Write to 'new:${trimmed.slice(6)}' instead.` }],
          };
        }
        return {
          content: [{ type: "text", text: `Invalid namespace '${params.namespace}'. Must be global, project:<name>, or new:<name>.` }],
        };
      }

      await withSchema(signal);
      const agentId = getAgentId();
      const project = await resolveProjectName(signal);
      const key = sqlEscape(params.key.trim());
      const content = sqlEscape(params.content);
      const tags = sqlEscape((params.tags || "").trim());

      await sqliteExec(`
        INSERT INTO memories (namespace, key, content, tags, source_agent, source_project)
        VALUES ('${sqlEscape(ns)}', '${key}', '${content}', '${tags}', '${sqlEscape(agentId)}', '${sqlEscape(project)}')
        ON CONFLICT(namespace, key) DO UPDATE SET
          content = excluded.content,
          tags = excluded.tags,
          source_agent = excluded.source_agent,
          source_project = excluded.source_project,
          updated_at = datetime('now');
      `, signal);

      // Auto-create topic_links for new:* saves
      if (ns.startsWith("new:") && project) {
        const topicName = sqlEscape(ns.slice(4));
        try {
          await sqliteExec(`
            INSERT OR IGNORE INTO topic_links (project, topic) VALUES ('${sqlEscape(project)}', '${topicName}');
          `, signal);
        } catch { /* best effort */ }
      }

      return {
        content: [{ type: "text", text: `Saved memory '${params.key.trim()}' in ${ns}.` }],
        details: { namespace: ns, key: params.key.trim() },
      };
    },
  });

  // ── zeus_memory_recall ──────────────────────────────────────────────
  pi.registerTool({
    name: "zeus_memory_recall",
    label: "Recall memory",
    description: "Retrieve a specific memory by exact namespace and key.",
    parameters: Type.Object({
      namespace: Type.String({ description: "Namespace to look up" }),
      key: Type.String({ description: "Exact key" }),
    }),
    async execute(_toolCallId, params, signal) {
      await withSchema(signal);
      const ns = sqlEscape(params.namespace.trim());
      const key = sqlEscape(params.key.trim());
      const raw = await sqliteExec(`
        UPDATE memories SET access_count = access_count + 1, accessed_at = datetime('now')
        WHERE namespace = '${ns}' AND key = '${key}' AND archived = 0;
        SELECT namespace, key, content, tags, source_agent, source_project, created_at, updated_at, access_count
        FROM memories WHERE namespace = '${ns}' AND key = '${key}' AND archived = 0;
      `, signal);

      if (!raw || raw === "[]") {
        return { content: [{ type: "text", text: `No memory found for '${params.key.trim()}' in ${params.namespace.trim()}.` }] };
      }

      try {
        const rows = JSON.parse(raw);
        if (!Array.isArray(rows) || rows.length === 0) {
          return { content: [{ type: "text", text: `No memory found for '${params.key.trim()}' in ${params.namespace.trim()}.` }] };
        }
        const m = rows[0];
        return {
          content: [{ type: "text", text: `[${m.namespace}] ${m.key}\n${m.content}\nTags: ${m.tags || "(none)"}\nCreated: ${m.created_at} | Updated: ${m.updated_at}` }],
          details: m,
        };
      } catch {
        return { content: [{ type: "text", text: raw }] };
      }
    },
  });

  // ── zeus_memory_search ──────────────────────────────────────────────
  pi.registerTool({
    name: "zeus_memory_search",
    label: "Search memories",
    description:
      "Full-text search across memories. If namespace is omitted, searches global + current project + linked topics.",
    parameters: Type.Object({
      query: Type.String({ description: "Search query" }),
      namespace: Type.Optional(Type.String({ description: "Restrict to a specific namespace" })),
      limit: Type.Optional(Type.Number({ description: "Max results (default 10)" })),
    }),
    async execute(_toolCallId, params, signal) {
      await withSchema(signal);
      const limit = params.limit || 10;
      const query = sqlEscape(params.query.trim());

      if (!query) {
        return { content: [{ type: "text", text: "Empty search query." }] };
      }

      let nsFilter = "";
      if (params.namespace) {
        nsFilter = `AND m.namespace = '${sqlEscape(params.namespace.trim())}'`;
      } else {
        // Search global + project + linked topics
        const project = await resolveProjectName(signal);
        const namespaces = ["'global'"];
        if (project) {
          namespaces.push(`'project:${sqlEscape(project)}'`);
          // Get linked topics
          try {
            const linkRaw = await sqliteExec(
              `SELECT topic FROM topic_links WHERE project = '${sqlEscape(project)}';`,
              signal,
            );
            if (linkRaw && linkRaw !== "[]") {
              const links = JSON.parse(linkRaw);
              for (const link of links) {
                if (link.topic) namespaces.push(`'topic:${sqlEscape(link.topic)}'`);
              }
            }
          } catch { /* best effort */ }
        }
        nsFilter = `AND m.namespace IN (${namespaces.join(",")})`;
      }

      try {
        const raw = await sqliteExec(`
          SELECT m.namespace, m.key, SUBSTR(m.content, 1, 300) AS content, m.tags
          FROM memories_fts f
          JOIN memories m ON m.id = f.rowid
          WHERE memories_fts MATCH '${query}'
            ${nsFilter}
            AND m.archived = 0
          ORDER BY bm25(memories_fts)
          LIMIT ${limit};
        `, signal);

        if (!raw || raw === "[]") {
          return { content: [{ type: "text", text: `No results for '${params.query.trim()}'.` }] };
        }

        const rows = JSON.parse(raw);
        const lines = rows.map((r: any) => `- [${r.namespace}] ${r.key}: ${r.content}`);
        return {
          content: [{ type: "text", text: `Found ${rows.length} result(s):\n${lines.join("\n")}` }],
          details: { results: rows },
        };
      } catch (err: any) {
        return { content: [{ type: "text", text: `Search error: ${err?.message || String(err)}` }] };
      }
    },
  });

  // ── zeus_memory_list ────────────────────────────────────────────────
  pi.registerTool({
    name: "zeus_memory_list",
    label: "List memories",
    description:
      "Browse memories in a namespace. If namespace is omitted, lists the current project.",
    parameters: Type.Object({
      namespace: Type.Optional(Type.String({ description: "Namespace to list (default: current project)" })),
      limit: Type.Optional(Type.Number({ description: "Max results (default 50)" })),
    }),
    async execute(_toolCallId, params, signal) {
      await withSchema(signal);
      const limit = params.limit || 50;
      let ns: string;
      if (params.namespace) {
        ns = params.namespace.trim();
      } else {
        const project = await resolveProjectName(signal);
        ns = project ? `project:${project}` : "global";
      }

      const raw = await sqliteExec(`
        SELECT namespace, key, SUBSTR(content, 1, 200) AS content_preview, tags,
               source_project, created_at, updated_at, access_count
        FROM memories
        WHERE namespace = '${sqlEscape(ns)}' AND archived = 0
        ORDER BY updated_at DESC
        LIMIT ${limit};
      `, signal);

      if (!raw || raw === "[]") {
        return { content: [{ type: "text", text: `No memories in '${ns}'.` }] };
      }

      const rows = JSON.parse(raw);
      const lines = rows.map((r: any) => `- ${r.key}: ${r.content_preview}${r.tags ? ` [${r.tags}]` : ""}`);
      return {
        content: [{ type: "text", text: `${rows.length} memor${rows.length === 1 ? "y" : "ies"} in '${ns}':\n${lines.join("\n")}` }],
        details: { namespace: ns, count: rows.length, results: rows },
      };
    },
  });

  // ── zeus_memory_delete ──────────────────────────────────────────────
  pi.registerTool({
    name: "zeus_memory_delete",
    label: "Delete memory",
    description: "Permanently remove a memory by namespace and key.",
    parameters: Type.Object({
      namespace: Type.String({ description: "Namespace" }),
      key: Type.String({ description: "Key to delete" }),
    }),
    async execute(_toolCallId, params, signal) {
      await withSchema(signal);
      const ns = sqlEscape(params.namespace.trim());
      const key = sqlEscape(params.key.trim());
      const raw = await sqliteExec(`
        DELETE FROM memories WHERE namespace = '${ns}' AND key = '${key}';
        SELECT changes() AS deleted;
      `, signal);

      let deleted = 0;
      try {
        const rows = JSON.parse(raw);
        deleted = rows?.[0]?.deleted || 0;
      } catch {}

      if (deleted > 0) {
        return { content: [{ type: "text", text: `Deleted '${params.key.trim()}' from ${params.namespace.trim()}.` }] };
      }
      return { content: [{ type: "text", text: `No memory '${params.key.trim()}' found in ${params.namespace.trim()}.` }] };
    },
  });

  // ── zeus_memory_list_topics ─────────────────────────────────────────
  pi.registerTool({
    name: "zeus_memory_list_topics",
    label: "List topics",
    description:
      "Show topics linked to the current project and count of pending new:* memories.",
    parameters: Type.Object({}),
    async execute(_toolCallId, _params, signal) {
      await withSchema(signal);
      const project = await resolveProjectName(signal);
      if (!project) {
        return { content: [{ type: "text", text: "Not in a git repository — cannot determine project." }] };
      }

      const linkRaw = await sqliteExec(
        `SELECT topic FROM topic_links WHERE project = '${sqlEscape(project)}' ORDER BY topic;`,
        signal,
      );
      const pendingRaw = await sqliteExec(
        `SELECT COUNT(*) AS cnt FROM memories WHERE namespace LIKE 'new:%' AND source_project = '${sqlEscape(project)}' AND archived = 0;`,
        signal,
      );

      let topics: string[] = [];
      let pending = 0;
      try {
        const links = JSON.parse(linkRaw || "[]");
        topics = links.map((r: any) => r.topic);
      } catch {}
      try {
        const p = JSON.parse(pendingRaw || "[]");
        pending = p?.[0]?.cnt || 0;
      } catch {}

      const topicList = topics.length > 0 ? topics.join(", ") : "(none)";
      return {
        content: [{ type: "text", text: `Project: ${project}\nLinked topics: ${topicList}\nPending new topics: ${pending}` }],
        details: { project, linked_topics: topics, pending_new_count: pending },
      };
    },
  });

  // ── zeus_memory_rename_project ──────────────────────────────────────
  pi.registerTool({
    name: "zeus_memory_rename_project",
    label: "Rename project",
    description: "Rename a project namespace and update all references (memories, topic_links, source_project).",
    parameters: Type.Object({
      old_name: Type.String({ description: "Current project name (without 'project:' prefix)" }),
      new_name: Type.String({ description: "New project name (without 'project:' prefix)" }),
    }),
    async execute(_toolCallId, params, signal) {
      await withSchema(signal);
      const oldName = sqlEscape(params.old_name.trim());
      const newName = sqlEscape(params.new_name.trim());

      if (!oldName || !newName) {
        return { content: [{ type: "text", text: "Both old_name and new_name are required." }] };
      }

      await sqliteExec(`
        UPDATE memories SET namespace = 'project:${newName}' WHERE namespace = 'project:${oldName}';
        UPDATE memories SET source_project = '${newName}' WHERE source_project = '${oldName}';
        UPDATE topic_links SET project = '${newName}' WHERE project = '${oldName}';
      `, signal);

      return {
        content: [{ type: "text", text: `Renamed project '${params.old_name.trim()}' to '${params.new_name.trim()}'.` }],
        details: { old_name: params.old_name.trim(), new_name: params.new_name.trim() },
      };
    },
  });

  // ── zeus_consolidation_done ─────────────────────────────────────────
  pi.registerTool({
    name: "zeus_consolidation_done",
    label: "Consolidation done",
    description:
      "Signal that memory consolidation is complete. Only used by ephemeral consolidation agents.",
    parameters: Type.Object({}),
    async execute(_toolCallId, _params, signal) {
      const agentId = getAgentId();
      if (!agentId) {
        return { content: [{ type: "text", text: "No ZEUS_AGENT_ID — cannot signal completion." }] };
      }

      // Send consolidation_done message through agent bus
      const busInboxDir = path.join(getBusDir(), "inbox", "zeus", "new");
      try {
        fs.mkdirSync(busInboxDir, { recursive: true });
      } catch {}

      const msgId = `consolidation-done-${agentId}-${Date.now()}`;
      const payload = {
        id: msgId,
        type: "consolidation_done",
        agent_id: agentId,
        timestamp: new Date().toISOString(),
      };

      writeJsonAtomic(path.join(busInboxDir, `${msgId}.json`), payload);

      return {
        content: [{ type: "text", text: "Consolidation complete. Signaled Zeus for cleanup." }],
        details: { agent_id: agentId, message_id: msgId },
      };
    },
  });

  // ── Worktree merge helpers ──────────────────────────────────────────

  /** Shared merge logic for both sync and finalize. */
  async function doWorktreeMerge(signal: AbortSignal | undefined, finalize: boolean): Promise<{
    content: { type: string; text: string }[];
    details?: Record<string, string>;
  }> {
    // Detect worktree: git rev-parse --git-common-dir differs from --git-dir
    const gitDirResult = await pi.exec("git", ["rev-parse", "--git-dir"], { signal, timeout: 5000 });
    const gitCommonResult = await pi.exec("git", ["rev-parse", "--git-common-dir"], { signal, timeout: 5000 });

    if (gitDirResult.code !== 0 || gitCommonResult.code !== 0) {
      return { content: [{ type: "text", text: "Not in a git repository." }] };
    }

    const gitDir = (gitDirResult.stdout || "").trim();
    const gitCommon = (gitCommonResult.stdout || "").trim();

    if (gitDir === gitCommon || gitDir === ".git") {
      return { content: [{ type: "text", text: "Not in a git worktree. This tool only works from a Zeus workdir agent." }] };
    }

    // Get current branch
    const branchResult = await pi.exec("git", ["rev-parse", "--abbrev-ref", "HEAD"], { signal, timeout: 5000 });
    if (branchResult.code !== 0) {
      return { content: [{ type: "text", text: "Cannot determine current branch." }] };
    }
    const currentBranch = (branchResult.stdout || "").trim();

    if (!currentBranch.startsWith("zeus/")) {
      return { content: [{ type: "text", text: `Current branch '${currentBranch}' is not a Zeus worktree branch (expected zeus/* prefix).` }] };
    }

    // Find the main repo root (parent of .git/worktrees)
    const commonDir = path.resolve(gitCommon);
    const repoRoot = path.dirname(commonDir);

    // Determine parent branch
    let parentBranch = process.env.ZEUS_PARENT_BRANCH || "";
    if (!parentBranch) {
      for (const candidate of ["main", "master"]) {
        const check = await pi.exec("git", ["rev-parse", "--verify", candidate], { signal, timeout: 5000, cwd: repoRoot });
        if (check.code === 0) {
          parentBranch = candidate;
          break;
        }
      }
    }
    if (!parentBranch) {
      return { content: [{ type: "text", text: "Cannot determine parent branch. Set ZEUS_PARENT_BRANCH env var." }] };
    }

    // Check for uncommitted changes
    const statusResult = await pi.exec("git", ["status", "--porcelain"], { signal, timeout: 5000 });
    const uncommitted = (statusResult.stdout || "").trim();
    if (uncommitted) {
      return { content: [{ type: "text", text: `Uncommitted changes in worktree. Commit or stash before merging:\n${uncommitted}` }] };
    }

    // Perform merge from the main repo directory
    const mergeResult = await pi.exec("git", [
      "-C", repoRoot,
      "merge", "--no-ff", currentBranch,
      "-m", `Merge ${currentBranch} into ${parentBranch}`,
    ], { signal, timeout: 60000 });

    if (mergeResult.code === 0) {
      const output = (mergeResult.stdout || "").trim();

      if (finalize) {
        // Signal Zeus dashboard for cleanup
        const agentId = process.env.ZEUS_AGENT_ID || "";
        const agentName = process.env.ZEUS_AGENT_NAME || "";
        if (agentId) {
          const busDir = path.join(getBusDir(), "inbox", "zeus", "new");
          try {
            fs.mkdirSync(busDir, { recursive: true });
            const signalPayload = JSON.stringify({
              type: "worktree_merge_done",
              agent_id: agentId,
              agent_name: agentName,
              branch: currentBranch,
              target: parentBranch,
              repo_root: repoRoot,
            });
            const sigFile = path.join(busDir, `worktree-done-${agentId.slice(0, 8)}-${Date.now()}.json`);
            fs.writeFileSync(sigFile, signalPayload);
          } catch {
            // Best-effort signal; merge already succeeded
          }
        }
        return {
          content: [{ type: "text", text: `Merge & finalize: ${currentBranch} → ${parentBranch}\n${output}\n\nZeus will clean up the worktree and terminate this agent.` }],
          details: { branch: currentBranch, target: parentBranch, status: "finalized" },
        };
      }

      // Continue mode: push succeeded, now pull parent → worktree
      const pullResult = await pi.exec("git", [
        "merge", parentBranch,
        "-m", `Merge ${parentBranch} into ${currentBranch}`,
      ], { signal, timeout: 60000 });

      if (pullResult.code !== 0) {
        // Pull had conflicts — abort and report
        const pullConflicts = await pi.exec("git", ["diff", "--name-only", "--diff-filter=U"], { signal, timeout: 10000 });
        await pi.exec("git", ["merge", "--abort"], { signal, timeout: 10000 });
        const conflictFiles = (pullConflicts.stdout || "").trim();
        let pullMsg = `Pushed ${currentBranch} → ${parentBranch} OK, but pulling ${parentBranch} → ${currentBranch} has conflicts.`;
        if (conflictFiles) pullMsg += `\n\nConflicted files:\n${conflictFiles}`;
        pullMsg += "\n\nResolve conflicts, commit, then try again.";
        return {
          content: [{ type: "text", text: pullMsg }],
          details: { branch: currentBranch, target: parentBranch, status: "pull_conflicts", files: conflictFiles },
        };
      }

      const pullOutput = (pullResult.stdout || "").trim();
      return {
        content: [{ type: "text", text: `Merge & continue:\n  ${currentBranch} → ${parentBranch}: OK\n  ${parentBranch} → ${currentBranch}: OK\n${output}\n${pullOutput}\n\nWorktree is in sync. Continue working.` }],
        details: { branch: currentBranch, target: parentBranch, status: "synced" },
      };
    }

    // Merge failed — get conflict info
    const conflictResult = await pi.exec("git", [
      "-C", repoRoot,
      "diff", "--name-only", "--diff-filter=U",
    ], { signal, timeout: 10000 });
    const conflicts = (conflictResult.stdout || "").trim();

    // Abort the failed merge to leave repo clean
    await pi.exec("git", ["-C", repoRoot, "merge", "--abort"], { signal, timeout: 10000 });

    const errOutput = ((mergeResult.stdout || "") + "\n" + (mergeResult.stderr || "")).trim();
    let msg = `Merge conflicts detected when merging ${currentBranch} into ${parentBranch}.\n\n${errOutput}`;
    if (conflicts) {
      msg += `\n\nConflicted files:\n${conflicts}`;
    }
    msg += "\n\nResolve conflicts in the conflicted files, git add them, commit, then try again.";

    return {
      content: [{ type: "text", text: msg }],
      details: { branch: currentBranch, target: parentBranch, status: "conflicts", files: conflicts },
    };
  }

  /** Discard worktree branch and request Zeus cleanup (no merge). */
  async function doWorktreeDiscard(signal: AbortSignal | undefined): Promise<{
    content: { type: string; text: string }[];
    details?: Record<string, string>;
  }> {
    const gitDirResult = await pi.exec("git", ["rev-parse", "--git-dir"], { signal, timeout: 5000 });
    const gitCommonResult = await pi.exec("git", ["rev-parse", "--git-common-dir"], { signal, timeout: 5000 });

    if (gitDirResult.code !== 0 || gitCommonResult.code !== 0) {
      return { content: [{ type: "text", text: "Not in a git repository." }] };
    }

    const gitDir = (gitDirResult.stdout || "").trim();
    const gitCommon = (gitCommonResult.stdout || "").trim();

    if (gitDir === gitCommon || gitDir === ".git") {
      return { content: [{ type: "text", text: "Not in a git worktree. This tool only works from a Zeus workdir agent." }] };
    }

    const branchResult = await pi.exec("git", ["rev-parse", "--abbrev-ref", "HEAD"], { signal, timeout: 5000 });
    if (branchResult.code !== 0) {
      return { content: [{ type: "text", text: "Cannot determine current branch." }] };
    }
    const currentBranch = (branchResult.stdout || "").trim();

    if (!currentBranch.startsWith("zeus/")) {
      return { content: [{ type: "text", text: `Current branch '${currentBranch}' is not a Zeus worktree branch (expected zeus/* prefix).` }] };
    }

    const commonDir = path.resolve(gitCommon);
    const repoRoot = path.dirname(commonDir);

    const agentId = process.env.ZEUS_AGENT_ID || "";
    const agentName = process.env.ZEUS_AGENT_NAME || "";
    if (!agentId) {
      return { content: [{ type: "text", text: "No ZEUS_AGENT_ID — cannot request discard cleanup." }] };
    }

    try {
      const busDir = path.join(getBusDir(), "inbox", "zeus", "new");
      fs.mkdirSync(busDir, { recursive: true });
      const signalPayload = JSON.stringify({
        type: "worktree_discard_done",
        agent_id: agentId,
        agent_name: agentName,
        branch: currentBranch,
        repo_root: repoRoot,
      });
      const sigFile = path.join(busDir, `worktree-discard-${agentId.slice(0, 8)}-${Date.now()}.json`);
      fs.writeFileSync(sigFile, signalPayload);
    } catch (err) {
      const reason = err instanceof Error ? err.message : String(err);
      return {
        content: [{ type: "text", text: `Failed to signal discard cleanup: ${reason}` }],
        details: { branch: currentBranch, status: "discard_signal_failed" },
      };
    }

    return {
      content: [{ type: "text", text: `Discard requested for ${currentBranch}. Zeus will remove this worktree branch and terminate this agent (no merge).` }],
      details: { branch: currentBranch, status: "discard_requested" },
    };
  }

  // ── zeus_worktree_merge_and_finalize (finalize) ────────────────────────────────────
  pi.registerTool({
    name: "zeus_worktree_merge_and_finalize",
    label: "Merge & finalize",
    description:
      "Merge the current worktree branch back into the parent branch and finalize. " +
      "After a successful merge, Zeus kills this agent and removes the worktree. " +
      "Use this when your work is DONE. Only works from a Zeus workdir agent.",
    parameters: Type.Object({}),
    async execute(_toolCallId, _params, signal) {
      return doWorktreeMerge(signal, true);
    },
  });

  // ── zeus_worktree_merge_and_continue (continue) ─────────────────────────────────────
  pi.registerTool({
    name: "zeus_worktree_merge_and_continue",
    label: "Merge & continue",
    description:
      "Merge the current worktree branch into the parent branch but keep working. " +
      "The worktree and agent stay alive after the merge. " +
      "Use this to push intermediate progress without finishing. Only works from a Zeus workdir agent.",
    parameters: Type.Object({}),
    async execute(_toolCallId, _params, signal) {
      return doWorktreeMerge(signal, false);
    },
  });

  // ── zeus_worktree_discard (discard without merge) ───────────────────────────────────
  pi.registerTool({
    name: "zeus_worktree_discard",
    label: "Discard worktree",
    description:
      "Discard the current Zeus worktree branch without merging. " +
      "Zeus removes the worktree and branch and terminates this agent. " +
      "Use this when Oracle requests abandoning this workdir branch.",
    parameters: Type.Object({}),
    async execute(_toolCallId, _params, signal) {
      return doWorktreeDiscard(signal);
    },
  });
}
