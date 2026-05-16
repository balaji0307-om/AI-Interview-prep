import type {
  AuthUser,
  ChatPayload,
  ChatResponse,
  ChatStreamDoneEvent,
  ChatStreamEvent,
  ModeMap,
  QuestionItem,
  StatusResponse,
  SubmitResult,
  TopicMap,
} from "../types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

function apiUrl(path: string): string {
  return `${API_BASE_URL}${path}`;
}

function accessToken(): string {
  try {
    const raw = localStorage.getItem("interview-prep-ai-store");
    if (!raw) return "";
    const parsed = JSON.parse(raw);
    return parsed?.state?.authUser?.access_token ?? "";
  } catch {
    return "";
  }
}

function authHeaders(): Record<string, string> {
  const token = accessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function wsUrl(path: string): string {
  const base = API_BASE_URL || window.location.origin;
  const url = new URL(path, base);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiUrl(path), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(init?.headers ?? {}),
    },
  });

  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data && typeof data === "object" ? (data.detail ?? data.message) : "";
    throw new Error(String(detail || `Request failed with status ${response.status}`));
  }

  return data as T;
}

export async function fetchStatus(): Promise<StatusResponse> {
  return requestJson<StatusResponse>("/api/status");
}

export async function fetchTopics(): Promise<{ topics: TopicMap; modes: ModeMap }> {
  return requestJson<{ topics: TopicMap; modes: ModeMap }>("/api/topics");
}

export async function signup(username: string, password: string): Promise<AuthUser> {
  return requestJson<AuthUser>("/api/auth/signup", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export async function login(username: string, password: string): Promise<AuthUser> {
  return requestJson<AuthUser>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export async function fetchQuestion(topic: string, mode: string, position: number): Promise<QuestionItem> {
  const query = new URLSearchParams({ topic, mode, position: String(position) });
  return requestJson<QuestionItem>(`/api/questions/random?${query.toString()}`);
}

export async function submitAttempt(payload: {
  user_id: string;
  topic: string;
  mode: string;
  question_id: string;
  answer: string;
  provider: string;
}): Promise<SubmitResult> {
  return requestJson<SubmitResult>("/api/attempts/submit", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function fetchChatHistory(userId: string): Promise<{ history: import("../types").ChatEntry[] }> {
  return requestJson<{ history: import("../types").ChatEntry[] }>(`/api/chat/history?user_id=${encodeURIComponent(userId)}`);
}

export async function clearChatHistory(user_id: string): Promise<{ ok: boolean }> {
  return requestJson<{ ok: boolean }>("/api/chat/clear", {
    method: "POST",
    body: JSON.stringify({ user_id }),
  });
}

export async function sendChat(payload: ChatPayload): Promise<ChatResponse> {
  return requestJson<ChatResponse>("/api/chat", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function streamChatResponse(
  payload: ChatPayload,
  callbacks: {
    onToken?: (value: string) => void;
    onDone?: (event: ChatStreamDoneEvent) => void;
  },
): Promise<void> {
  const response = await fetch(apiUrl("/api/chat/stream"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok || !response.body) {
    const detail = await response.json().catch(() => null);
    const message = detail && typeof detail === "object" ? String(detail.detail ?? detail.message ?? "Chat stream failed.") : "Chat stream failed.";
    throw new Error(message);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const processLine = (line: string) => {
    if (!line.trim()) {
      return;
    }
    const event = JSON.parse(line) as ChatStreamEvent;
    if (event.type === "token") {
      callbacks.onToken?.(event.value);
      return;
    }
    if (event.type === "done") {
      callbacks.onDone?.(event);
      return;
    }
    throw new Error(event.message);
  };

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });

    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    lines.forEach(processLine);

    if (done) {
      break;
    }
  }

  if (buffer.trim()) {
    processLine(buffer);
  }
}

export function openChatWebSocket(callbacks: {
  onToken?: (value: string) => void;
  onDone?: (event: ChatStreamDoneEvent) => void;
  onError?: (message: string) => void;
}): WebSocket {
  const token = accessToken();
  const url = new URL(wsUrl("/ws/chat"));
  if (token) {
    url.searchParams.set("token", token);
  }
  const socket = new WebSocket(url);
  socket.addEventListener("message", (event) => {
    const data = JSON.parse(event.data) as ChatStreamEvent;
    if (data.type === "token") {
      callbacks.onToken?.(data.value);
      return;
    }
    if (data.type === "done") {
      callbacks.onDone?.(data);
      return;
    }
    callbacks.onError?.(data.message);
  });
  return socket;
}
