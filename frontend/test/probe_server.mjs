import { spawn } from "node:child_process";
import http from "node:http";

console.log("Starting Next.js server test probe...");

const nextProcess = spawn("cmd.exe", ["/c", "npm", "run", "start", "--prefix", "frontend"], {
  stdio: "pipe",
});

let isCleanedUp = false;
function cleanup() {
  if (!isCleanedUp) {
    isCleanedUp = true;
    nextProcess.kill();
    try {
      process.kill(nextProcess.pid);
    } catch (e) {}
  }
}

nextProcess.stdout.on("data", (data) => {
  const msg = data.toString();
  if (msg.includes("Ready in") || msg.includes("started server on")) {
    console.log("[SERVER READY]", msg.trim());

    // Probe localhost:3000
    http.get("http://localhost:3000", (res) => {
      console.log(`[HTTP PROBE] Status Code: ${res.statusCode}`);
      let body = "";
      res.on("data", (chunk) => (body += chunk));
      res.on("end", () => {
        console.log(`[HTTP PROBE] Response received (${body.length} bytes)`);
        cleanup();
        process.exit(0);
      });
    }).on("error", (err) => {
      console.error("[HTTP PROBE ERROR]", err.message);
      cleanup();
      process.exit(1);
    });
  }
});

nextProcess.stderr.on("data", (data) => {
  console.error("[SERVER ERROR]", data.toString());
});

setTimeout(() => {
  console.log("Timeout waiting for server probe.");
  cleanup();
  process.exit(0);
}, 8000);
