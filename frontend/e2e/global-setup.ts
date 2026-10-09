import { execFileSync } from "node:child_process";
import path from "node:path";

// Reseed and prepare the four demo decisions through the real API (replay client, approvals as the BA persona with the note
// "demo preparation"). AI Coach ends at `decided` in the specs, so every run needs a fresh demo state.
export default async function globalSetup() {
  if (process.env.E2E_SKIP_RESET === "1") {
    console.log("E2E_SKIP_RESET=1: using the database as it is (it must be freshly prepared).");
    return;
  }
  const root = path.resolve(__dirname, "..", "..");
  const python = process.platform === "win32" ? path.join(root, "backend", ".venv", "Scripts", "python.exe") : path.join(root, "backend", ".venv", "bin", "python");
  console.log("Resetting the demo state: scripts/demo_prepare.py --reset (this reseeds the database and takes several minutes) ...");
  execFileSync(python, ["scripts/demo_prepare.py", "--reset"], {
    cwd: root,
    stdio: "inherit",
    env: { ...process.env, PYTHONPATH: `${path.join(root, "backend")}${path.delimiter}${root}`, DDR_AS_OF_DATE: "2026-10-01" },
  });
}
