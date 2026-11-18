import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { existsSync } from "node:fs";
import net from "node:net";
import path from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath } from "node:url";
import test, { after, before } from "node:test";

const frontendDirectory = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const nextCli = path.join(frontendDirectory, "node_modules", "next", "dist", "bin", "next");
let server;
let origin;
let serverError = "";

before(async () => {
  if (!existsSync(path.join(frontendDirectory, ".next", "BUILD_ID"))) {
    throw new Error("Build the frontend with `npm run build` before running `npm run test:legal`.");
  }

  const portProbe = net.createServer();
  await new Promise((resolve, reject) => {
    portProbe.once("error", reject);
    portProbe.listen(0, "127.0.0.1", resolve);
  });
  const address = portProbe.address();
  if (!address || typeof address === "string") {
    throw new Error("Could not allocate a local port for the legal-page test.");
  }
  const { port } = address;
  await new Promise((resolve, reject) => {
    portProbe.close((error) => (error ? reject(error) : resolve()));
  });

  origin = `http://127.0.0.1:${port}`;
  server = spawn(
    process.execPath,
    [nextCli, "start", "--hostname", "127.0.0.1", "--port", String(port)],
    { cwd: frontendDirectory, stdio: ["ignore", "ignore", "pipe"] },
  );
  server.stderr.setEncoding("utf8");
  server.stderr.on("data", (chunk) => {
    serverError += chunk;
  });

  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (server.exitCode !== null) {
      throw new Error(`Next.js exited before becoming ready: ${serverError}`);
    }
    try {
      const response = await fetch(origin);
      if (response.ok) return;
    } catch {
      await delay(250);
    }
  }
  throw new Error(`Next.js did not become ready in time: ${serverError}`);
});

after(async () => {
  if (!server || server.exitCode !== null) return;
  const exited = once(server, "exit");
  server.kill();
  await Promise.race([exited, delay(5_000)]);
});

test("Terms and Privacy pages are publicly accessible without authentication", async () => {
  for (const [route, heading, otherRoute] of [
    ["/terms", "Terms of Use", "/privacy"],
    ["/privacy", "Privacy Policy", "/terms"],
  ]) {
    const response = await fetch(`${origin}${route}`);
    assert.equal(response.status, 200, `${route} should be publicly available`);
    const html = await response.text();
    assert.match(html, new RegExp(heading));
    assert.ok(html.includes(`href="${otherRoute}"`), `${route} should link to ${otherRoute}`);
    assert.ok(html.includes("Owner confirmation required before paid launch"));
  }
});
