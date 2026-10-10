import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The backend allows this origin (backend/config.py FRONTEND_ORIGINS), so the port is fixed.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true, open: false },
});
