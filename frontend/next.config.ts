import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  // Self-contained server bundle (server.js + traced deps) for the small deploy server.
  output: "standalone",
  // The dev badge sits on top of the office canvas controls.
  devIndicators: false,
};

export default config;
