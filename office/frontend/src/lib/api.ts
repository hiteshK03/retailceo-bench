import type { OfficeEvent, RunConfig } from "../types";

const apiBase = import.meta.env.VITE_OFFICE_API_URL ?? "";

function wsBase(): string {
  if (apiBase) {
    return apiBase.replace(/^http/, "ws");
  }
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}`;
}

export async function createRun(config: RunConfig): Promise<{ run_id: string }> {
  const response = await fetch(`${apiBase}/api/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
  if (!response.ok) {
    throw new Error(`Failed to create run: ${response.status}`);
  }
  return response.json();
}

export function openRunStream(runId: string, onEvent: (event: OfficeEvent) => void): WebSocket {
  const socket = new WebSocket(`${wsBase()}/api/runs/${runId}/stream`);
  socket.addEventListener("message", (message) => {
    onEvent(JSON.parse(message.data) as OfficeEvent);
  });
  return socket;
}

export function openHumanPlay(runId: string, onEvent: (event: OfficeEvent) => void): WebSocket {
  const socket = new WebSocket(`${wsBase()}/api/human/${runId}/play`);
  socket.addEventListener("message", (message) => {
    onEvent(JSON.parse(message.data) as OfficeEvent);
  });
  return socket;
}

export function sendDecisions(
  socket: WebSocket,
  week: number,
  decisions: { proposal_id: string; verdict: string; modified_params?: Record<string, unknown> }[],
): void {
  socket.send(JSON.stringify({ week, decisions }));
}

