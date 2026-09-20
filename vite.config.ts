import { defineConfig } from "vite";
import { resolve } from "node:path";
import { readFileSync } from "node:fs";

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

const pwaFiles = [
  "manifest.webmanifest",
  "icon-192.png",
  "icon-512.png",
  "icon-maskable-512.png",
];

export default defineConfig({
  root: "web",
  base: "./",
  publicDir: publicFiles,
  plugins: [
    {
      name: "social-preview",
      configureServer(server) {
        server.middlewares.use((req, res, next) => {
          const name = (req.url ?? "").split("?")[0].replace(/^\//, "");
          if (!pwaFiles.includes(name)) return next();
          res.setHeader(
            "Content-Type",
            name.endsWith(".png") ? "image/png" : "application/manifest+json",
          );
          res.end(readFileSync(resolve("web/pwa", name)));
        });
      },
      generateBundle() {
        for (const name of pwaFiles)
          this.emitFile({
            type: "asset",
            fileName: name,
            source: readFileSync(resolve("web/pwa", name)),
          });
        // One reviewed public screenshot; never copy the private state directory.
        this.emitFile({
          type: "asset",
          fileName: "preview.png",
          source: readFileSync(resolve("web/preview.png")),
        });
      },
    },
  ],
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
