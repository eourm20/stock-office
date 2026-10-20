import { API_BASE } from "./api";

/** Server side of phone notifications (GET /api/v1/notify/status). */
export interface NotifyStatus {
  enabled: boolean;
  public_key: string | null;
  subscriptions: number;
  quiet: string;
  categories: string[];
}

/** Where this browser stands: what the ⚙ card should offer. */
export type PushState =
  | "unsupported"     // no service worker / Push API (e.g. iPhone Safari tab, old iOS)
  | "install-first"   // iPhone: works only from the home-screen app
  | "blocked"         // permission denied in system settings
  | "off"
  | "on";

export async function getNotifyStatus(): Promise<NotifyStatus> {
  const resp = await fetch(`${API_BASE}/api/v1/notify/status`);
  if (!resp.ok) throw new Error(resp.statusText);
  return (await resp.json()) as NotifyStatus;
}

function isIos(): boolean {
  return /iPhone|iPad|iPod/.test(navigator.userAgent);
}

function standalone(): boolean {
  return window.matchMedia("(display-mode: standalone)").matches
    || (navigator as Navigator & { standalone?: boolean }).standalone === true;
}

export async function pushState(): Promise<PushState> {
  if (isIos() && !standalone()) return "install-first";
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
    return "unsupported";
  }
  if (Notification.permission === "denied") return "blocked";
  const reg = await navigator.serviceWorker.getRegistration("/");
  const sub = reg ? await reg.pushManager.getSubscription() : null;
  return sub ? "on" : "off";
}

/** base64url → bytes, for the server's VAPID public key. */
export function urlBase64ToBytes(value: string): Uint8Array {
  const padded = (value + "=".repeat((4 - (value.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(padded);
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

async function post(path: string, body?: unknown): Promise<Response> {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp;
}

/** Must run from a tap (iOS asks for permission only on a user gesture). */
export async function enablePush(publicKey: string): Promise<void> {
  const permission = await Notification.requestPermission();
  if (permission !== "granted") throw new Error("알림 권한이 허용되지 않았습니다");
  const reg = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
  await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription()
    ?? await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToBytes(publicKey) as BufferSource,
    });
  await post("/api/v1/notify/subscribe", sub.toJSON());
}

export async function disablePush(): Promise<void> {
  const reg = await navigator.serviceWorker.getRegistration("/");
  const sub = reg ? await reg.pushManager.getSubscription() : null;
  if (!sub) return;
  await post("/api/v1/notify/unsubscribe", { endpoint: sub.endpoint });
  await sub.unsubscribe();
}

export async function sendTestPush(): Promise<number> {
  return ((await (await post("/api/v1/notify/test")).json()) as { sent: number }).sent;
}
