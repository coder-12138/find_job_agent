import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "/task-assets/",
  build: {
    outDir: "../src/job_application_agent_langchain/web/task_static",
    emptyOutDir: true,
    sourcemap: true,
  },
});
