import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import { chromium } from "@playwright/test";
import { createServer } from "../server.js";
let server, origin, browser;
before(async () => {
  server = createServer();
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  origin = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ headless: true });
});
after(async () => {
  await browser?.close();
  await new Promise((resolve) => server.close(resolve));
});
async function setup() {
  const page = await browser.newPage();
  page.setDefaultTimeout(8000);
  let files = [],
    permissions = [],
    calls = [];
  await page.route("**/api/v1/**", async (route) => {
    const req = route.request(),
      path = new URL(req.url()).pathname,
      method = req.method();
    calls.push({ path, method, body: req.postData(), headers: req.headers() });
    let data = {},
      status = 200;
    if (path.endsWith("/auth/token")) {
      if (req.postData().includes("wrong")) {
        status = 401;
        data = { detail: "Invalid credentials" };
      } else data = { access_token: "test-token", token_type: "bearer" };
    } else if (path.endsWith("/folders") && method === "POST")
      data = { id: 1, name: JSON.parse(req.postData()).name, parent_id: null };
    else if (path.includes("/folders/99/")) {
      status = 403;
      data = { detail: "No access to folder" };
    } else if (path.endsWith("/contents")) data = { folders: [], files };
    else if (path.endsWith("/files") && method === "POST") {
      files = [{ id: 3, name: "<report>.txt", size_bytes: 12, folder_id: 1 }];
      data = files[0];
    } else if (path.endsWith("/files/3") && method === "DELETE") {
      files = [];
      status = 204;
    } else if (path.endsWith("/permissions")) data = permissions;
    else if (path.endsWith("/share")) {
      permissions = [
        { id: 4, user_id: 2, role: JSON.parse(req.postData()).role },
      ];
      data = permissions[0];
    } else if (path.endsWith("/permissions/4")) {
      permissions = [];
      status = 204;
    } else if (path.endsWith("/shared-links") && method === "POST")
      data = { download_url: "/api/v1/drive/shared-links/secret/download" };
    else if (method === "DELETE") status = 204;
    else if (path.endsWith("/download")) {
      await route.fulfill({ body: "hello", contentType: "text/plain" });
      return;
    }
    await route.fulfill({
      status,
      contentType: "application/json",
      body: status === 204 ? "" : JSON.stringify(data),
    });
  });
  await page.goto(origin);
  return { page, calls };
}
async function login(page, password = "alice123") {
  await page.getByLabel("Email", { exact: true }).fill("alice@example.com");
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
}
async function ready(page, text) {
  await page.getByRole("heading", { name: text, exact: true }).waitFor();
}

test("customer workflow: login, create, upload, download, sharing, public links, deletion", async () => {
  const { page, calls } = await setup();
  try {
    await login(page);
    await ready(page, "Your workspace");
    await page.getByLabel("Folder name", { exact: true }).fill("Documents");
    await page
      .getByRole("button", { name: "Create folder", exact: true })
      .click();
    await ready(page, "Documents");
    assert.deepEqual(
      JSON.parse(calls.find((c) => c.path.endsWith("/folders")).body),
      { name: "Documents", parent_id: null },
    );
    await page
      .getByLabel("Upload a file")
      .setInputFiles({
        name: "<report>.txt",
        mimeType: "text/plain",
        buffer: Buffer.from("hello"),
      });
    await page.getByRole("button", { name: "Upload", exact: true }).click();
    await page.getByText("<report>.txt", { exact: true }).waitFor();
    const upload = calls.find((c) => c.path.endsWith("/folders/1/files"));
    assert.match(
      upload.headers["content-type"],
      /multipart\/form-data; boundary=/,
    );
    assert.match(upload.body, /name="upload"/);
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download", exact: true }).click();
    await download;
    await page.getByRole("button", { name: "Share", exact: true }).click();
    await ready(page, "Sharing · file #3");
    await page.getByLabel("User ID", { exact: true }).fill("2");
    await page.getByLabel("Access", { exact: true }).selectOption("editor");
    await page.getByRole("button", { name: "Save access" }).click();
    await page.getByText("User #2 · editor", { exact: false }).waitFor();
    assert.deepEqual(
      JSON.parse(calls.find((c) => c.path.endsWith("/share")).body),
      { user_id: 2, role: "editor" },
    );
    await page.getByRole("button", { name: "Remove access" }).click();
    await page.getByText("No direct permissions.").waitFor();
    await page.getByRole("button", { name: "Create public link" }).click();
    await page
      .getByRole("link", { name: "Download via public link" })
      .waitFor();
    await page
      .locator('form[data-form="revoke"] input')
      .fill(`${origin}/api/v1/drive/shared-links/secret/download`);
    await page
      .getByRole("button", { name: "Revoke link", exact: true })
      .click();
    await page.getByText("Public link revoked.", { exact: true }).waitFor();
    page.on("dialog", (dialog) => dialog.accept());
    await page.getByRole("button", { name: "Delete", exact: true }).click();
    await page.getByText("File deleted.", { exact: true }).waitFor();
    assert.equal(
      await page.getByText("<report>.txt", { exact: true }).count(),
      0,
    );
    await page
      .getByRole("button", { name: "Delete folder", exact: true })
      .click();
    await ready(page, "Your workspace");
    assert.ok(
      calls
        .filter((c) => !c.path.endsWith("/auth/token"))
        .every((c) => c.headers.authorization === "Bearer test-token"),
    );
    await page.getByRole("button", { name: "Sign out" }).click();
    await ready(page, "Welcome to Drive");
    assert.equal(
      await page.evaluate(() =>
        Object.values(localStorage).some((v) => v.includes("test-token")),
      ),
      false,
    );
  } finally {
    await page.close();
  }
});

test("invalid credentials, inaccessible folders and expired sessions are recoverable", async () => {
  const { page } = await setup();
  try {
    await login(page, "wrong");
    await page
      .getByRole("alert")
      .filter({ hasText: "Invalid credentials" })
      .waitFor();
    await login(page);
    await ready(page, "Your workspace");
    await page.getByLabel("Folder ID", { exact: true }).fill("99");
    await page
      .getByRole("button", { name: "Open folder", exact: true })
      .click();
    await page
      .getByRole("alert")
      .filter({ hasText: "No access to folder" })
      .waitFor();
    await page.route("**/api/v1/drive/folders/1/contents", (route) =>
      route.fulfill({ status: 401, json: { detail: "Invalid token" } }),
    );
    await page.getByLabel("Folder ID", { exact: true }).fill("1");
    await page
      .getByRole("button", { name: "Open folder", exact: true })
      .click();
    await ready(page, "Welcome to Drive");
    await page
      .getByRole("alert")
      .filter({ hasText: "Your session expired" })
      .waitFor();
  } finally {
    await page.close();
  }
});

test("folder bookmarks, navigation, cancellation and narrow screens", async () => {
  const { page, calls } = await setup();
  try {
    await page.setViewportSize({ width: 390, height: 844 });
    await login(page);
    await ready(page, "Your workspace");
    await page.getByLabel("Folder name", { exact: true }).fill("<Business>");
    await page
      .getByRole("button", { name: "Create folder", exact: true })
      .click();
    await ready(page, "<Business>");
    await page.getByRole("button", { name: "Workspace", exact: true }).click();
    await ready(page, "Your workspace");
    await page
      .getByRole("button", { name: "▱ <Business>", exact: true })
      .click();
    await ready(page, "<Business>");
    page.on("dialog", (dialog) => dialog.dismiss());
    await page
      .getByRole("button", { name: "Delete folder", exact: true })
      .click();
    assert.equal(calls.filter((c) => c.method === "DELETE").length, 0);
    assert.ok(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    );
    await page.reload();
    await login(page);
    await ready(page, "Your workspace");
    await page
      .getByRole("button", { name: "▱ <Business>", exact: true })
      .waitFor();
  } finally {
    await page.close();
  }
});

test("frontend server proxies authentication, multipart uploads and binary downloads", async () => {
  const received = [];
  const backend = http.createServer((req, res) => {
    received.push({ path: req.url, headers: req.headers });
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => {
      res.writeHead(201, { "content-type": "application/octet-stream" });
      res.end(Buffer.concat(chunks));
    });
  });
  await new Promise((resolve) => backend.listen(0, "127.0.0.1", resolve));
  const proxy = createServer(`http://127.0.0.1:${backend.address().port}`);
  await new Promise((resolve) => proxy.listen(0, "127.0.0.1", resolve));
  try {
    const base = `http://127.0.0.1:${proxy.address().port}`;
    const body = Buffer.from([0, 255, 32, 1]);
    const reply = await fetch(`${base}/api/v1/drive/folders/1/files`, {
      method: "POST",
      body,
      headers: { Authorization: "Bearer test" },
    });
    assert.equal(reply.status, 201);
    assert.deepEqual(Buffer.from(await reply.arrayBuffer()), body);
    assert.equal(received[0].headers.authorization, "Bearer test");
    assert.equal(received[0].path, "/api/v1/drive/folders/1/files");
    const form = new FormData();
    form.set("upload", new Blob(["document"]), "report.txt");
    const upload = await fetch(`${base}/api/v1/drive/folders/1/files`, {
      method: "POST",
      body: form,
    });
    assert.match(await upload.text(), /name="upload"; filename="report.txt"/);
    assert.match(
      received[1].headers["content-type"],
      /multipart\/form-data; boundary=/,
    );
    const login = await fetch(`${base}/api/v1/auth/token`, {
      method: "POST",
      body: new URLSearchParams({
        username: "alice@example.com",
        password: "demo",
      }),
    });
    assert.equal(
      await login.text(),
      "username=alice%40example.com&password=demo",
    );
    assert.equal((await fetch(`${base}/server.js`)).status, 404);
    assert.equal((await fetch(`${base}/src/app.js`)).status, 200);
  } finally {
    await Promise.all([
      new Promise((r) => proxy.close(r)),
      new Promise((r) => backend.close(r)),
    ]);
  }
});
