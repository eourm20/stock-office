import type { MetadataRoute } from "next";

/** Installable web app: home-screen icon, opens full screen without browser bars. */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Stock Office",
    short_name: "Stock Office",
    description: "AI 투자 위원회 분석 결과 (모의투자 전용, 주문 없음)",
    lang: "ko",
    start_url: "/",
    scope: "/",
    display: "standalone",
    background_color: "#0b1020",
    theme_color: "#0b1020",
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
      { src: "/icons/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
