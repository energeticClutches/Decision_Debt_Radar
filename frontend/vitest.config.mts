import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// Vitest tests pure logic and renders presentational components to static markup (react-dom/server) in a node environment.
// No DOM library is installed on purpose: the only dev dependencies are vitest and @playwright/test.
export default defineConfig({
  resolve: {
    alias: {
      "next/link": fileURLToPath(new URL("./tests/stubs/link.tsx", import.meta.url)),
    },
  },
  test: {
    environment: "node",
    include: ["tests/**/*.test.{ts,tsx}"],
    globals: false,
  },
});
