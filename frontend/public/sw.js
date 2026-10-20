/* Stock Office service worker: shows phone notifications and opens the app on tap.
   No caching or offline logic; nothing else runs here. */

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let msg = { title: "Stock Office", body: "", url: "/", tag: "stock-office" };
  try {
    msg = { ...msg, ...event.data.json() };
  } catch (_) {
    /* malformed payload: show the generic title */
  }
  // Only same-app paths are opened from a notification.
  const url = typeof msg.url === "string" && msg.url.startsWith("/") ? msg.url : "/";
  event.waitUntil(self.registration.showNotification(String(msg.title), {
    body: String(msg.body || ""),
    tag: String(msg.tag || "stock-office"),
    icon: "/icons/icon-192.png",
    badge: "/icons/icon-192.png",
    data: { url },
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const w of wins) {
      if ("focus" in w) {
        await w.focus();
        if ("navigate" in w) await w.navigate(url);
        return;
      }
    }
    await self.clients.openWindow(url);
  })());
});
