import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev proxy to the FastAPI backend (uvicorn on :8000).
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://localhost:8000", "/health": "http://localhost:8000" } },
});
