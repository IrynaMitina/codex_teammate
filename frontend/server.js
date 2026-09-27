import http from "node:http";
import https from "node:https";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

export function createServer(apiOrigin = "http://127.0.0.1:8000") {
  const upstream = new URL(apiOrigin);
  const assets = {
    "/": ["index.html", "text/html"],
    "/src/app.js": ["src/app.js", "text/javascript"],
    "/src/api.js": ["src/api.js", "text/javascript"],
    "/src/styles.css": ["src/styles.css", "text/css"],
  };
  return http.createServer(async (req, res) => {
    if (req.url.startsWith("/api/v1/")) {
      const headers = { ...req.headers, host: upstream.host };
      delete headers.connection;
      const proxy = (upstream.protocol === "https:" ? https : http).request(
        {
          protocol: upstream.protocol,
          hostname: upstream.hostname,
          port: upstream.port,
          path: req.url,
          method: req.method,
          headers,
        },
        (reply) => {
          res.writeHead(reply.statusCode, reply.headers);
          reply.pipe(res);
        },
      );
      proxy.on("error", () => {
        if (!res.headersSent)
          res.writeHead(502, { "Content-Type": "application/json" });
        res.end(
          JSON.stringify({
            detail: "Cannot reach the API. Please try again later.",
          }),
        );
      });
      req.pipe(proxy);
      return;
    }
    const asset = assets[req.url.split("?")[0]];
    if (!asset || req.method !== "GET") {
      res.writeHead(404);
      res.end();
      return;
    }
    try {
      const body = await readFile(new URL(asset[0], import.meta.url));
      res.writeHead(200, {
        "Content-Type": `${asset[1]}; charset=utf-8`,
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
      });
      res.end(body);
    } catch {
      res.writeHead(500);
      res.end("Unable to load frontend");
    }
  });
}
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const port = Number(process.env.PORT || 3000);
  createServer(process.env.API_ORIGIN).listen(
    port,
    process.env.HOST || "127.0.0.1",
    () => console.log(`Drive frontend: http://localhost:${port}`),
  );
}
