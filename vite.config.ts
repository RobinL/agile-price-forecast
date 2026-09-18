import { defineConfig } from "vite";
import { resolve } from "node:path";

// Changing charts never starts Python or contacts a provider. Only public JSON
// is served. Local private state is deliberately outside every allowed root.
const mode = process.env.DATA_MODE ?? "demo";
if (!["demo", "local", "demo-local"].includes(mode))
  throw new Error("DATA_MODE must be demo, demo-local or local");
const publicFiles = resolve(
  mode === "local"
    ? "runtime_state/site"
    : mode === "demo-local"
      ? "runtime_state/demo/site"
      : "fixtures/site",
);

export default defineConfig({
  root: "web",
  base: "./",
  publicDir: publicFiles,
  build: {
    outDir: "../dist",
    emptyOutDir: true,
    // Include the actual bundled dependencies' full notices in every deployment.
    license: { fileName: "third-party-licences.txt" },
  },
  server: {
    port: 5173,
    strictPort: true,
    fs: {
      strict: true,
      allow: [resolve("web"), resolve("node_modules"), publicFiles],
      deny: [
        "**/.env*",
        "**/.git/**",
        "**/runtime_state/local/**",
        "**/.transparency_token*",
      ],
    },
  },
});
