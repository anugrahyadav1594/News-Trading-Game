import http from "node:http";
import net from "node:net";
import { URL } from "node:url";
import next from "next";

const dev = process.env.NODE_ENV !== "production";
const hostname = process.env.HOST || "0.0.0.0";
const port = parseInt(process.env.PORT || "3006", 10);
const backendUrl = new URL(process.env.BACKEND_INTERNAL_URL || "http://127.0.0.1:8000");

const app = next({ dev, hostname, port });
const handle = app.getRequestHandler();

await app.prepare();
const nextUpgradeHandler = app.getUpgradeHandler();

const server = http.createServer((req, res) => {
  const reqUrl = req.url || "";
  if (reqUrl.startsWith("/api/") || reqUrl.startsWith("/health/")) {
    const targetPort = Number(backendUrl.port || (backendUrl.protocol === "https:" ? 443 : 80));
    const proxyReq = http.request(
      {
        hostname: backendUrl.hostname,
        port: targetPort,
        path: reqUrl,
        method: req.method,
        headers: {
          ...req.headers,
          host: `${backendUrl.hostname}:${targetPort}`,
        },
      },
      (proxyRes) => {
        res.writeHead(proxyRes.statusCode || 502, proxyRes.headers);
        proxyRes.pipe(res, { end: true });
      }
    );
    proxyReq.on("error", (err) => {
      if (!res.headersSent) {
        res.writeHead(502, { "Content-Type": "application/json" });
      }
      res.end(
        JSON.stringify({
          error: { code: "BAD_GATEWAY", message: `Backend unreachable: ${err.message}` },
        })
      );
    });
    req.pipe(proxyReq, { end: true });
    return;
  }

  handle(req, res);
});

server.on("upgrade", (req, socket, head) => {
  const reqUrl = req.url || "";
  if (reqUrl.startsWith("/ws/")) {
    const targetPort = Number(backendUrl.port || (backendUrl.protocol === "https:" ? 443 : 80));
    const targetHost = backendUrl.hostname;

    const backendSocket = net.connect(targetPort, targetHost, () => {
      const headers = [`GET ${reqUrl} HTTP/1.1`];
      for (let i = 0; i < req.rawHeaders.length; i += 2) {
        const key = req.rawHeaders[i];
        const val = req.rawHeaders[i + 1];
        if (key.toLowerCase() === "host") {
          headers.push(`Host: ${targetHost}:${targetPort}`);
        } else {
          headers.push(`${key}: ${val}`);
        }
      }
      headers.push("\r\n");
      backendSocket.write(headers.join("\r\n"));
      if (head && head.length > 0) {
        backendSocket.write(head);
      }
      socket.pipe(backendSocket).pipe(socket);
    });

    backendSocket.on("error", () => {
      socket.destroy();
    });
    socket.on("error", () => {
      backendSocket.destroy();
    });
    return;
  }

  nextUpgradeHandler(req, socket, head);
});

server.listen(port, hostname, () => {
  console.log(`[MTT-FRONTEND] Ready on http://${hostname}:${port} (proxying API & WS -> ${backendUrl.origin})`);
});
