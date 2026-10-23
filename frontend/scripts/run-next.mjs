import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(here, "..");
const command = process.argv[2] ?? "dev";
const port = process.env.FRONTEND_PORT || "3030";
const nextBin = path.join(frontendRoot, "node_modules", "next", "dist", "bin", "next");

const child = spawn(process.execPath, [nextBin, command, "-p", port], {
  cwd: frontendRoot,
  stdio: "inherit",
  env: process.env,
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => child.kill(signal));
}
child.on("exit", (code) => process.exit(code ?? 1));
child.on("error", (error) => {
  console.error(error);
  process.exit(1);
});
