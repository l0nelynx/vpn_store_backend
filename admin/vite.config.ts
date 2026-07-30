import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "/store/admin/",
  server: {
    port: 5174,
    proxy: {
      "/store/api": "http://127.0.0.1:5001",
      "/store/internal": "http://127.0.0.1:5001",
    },
  },
});
