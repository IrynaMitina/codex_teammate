import { request } from "./api.js";
const app = document.querySelector("#app");
let token = "",
  email = "",
  current = null,
  trail = [],
  contents = { folders: [], files: [] },
  saved = [],
  sharing = null,
  permissions = [],
  link = "",
  busy = false,
  message = "",
  failed = false;
const esc = (value) =>
  String(value).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const api = (path, options = {}) => request(path, { ...options, token });
const button = (label, action, attrs = "") =>
  `<button type="button" data-action="${action}" ${attrs}>${label}</button>`;
function remember(folder) {
  saved = [...saved.filter((f) => f.id !== folder.id), folder];
  try {
    localStorage.setItem(`drive-folders:${email}`, JSON.stringify(saved));
  } catch {
    /* bookmarks are optional */
  }
}
function render() {
  app.innerHTML = `<header><a class="brand" href="/">▦ <span>Drive</span></a><span class="tag">WORKSPACE</span>${token ? `<div class="account">${esc(email)} ${button("Sign out", "logout")}</div>` : ""}</header>
    <main>${
      !token
        ? `<section class="login panel"><p class="eyebrow">YOUR TEAM’S WORK, TOGETHER</p><h1>Welcome to Drive</h1><p class="muted">Sign in to manage and share your files.</p><form data-form="login"><label>Email<input name="email" type="email" autocomplete="username" required></label><label>Password<input name="password" type="password" autocomplete="current-password" required></label><button class="primary">Sign in</button></form></section>`
        : `
    <div class="heading"><div><p class="eyebrow">FILE MANAGEMENT</p><h1>${esc(current?.name || "Your workspace")}</h1><p class="muted">Keep your documents organized and your team connected.</p></div></div>
    <section class="panel tools"><form data-form="open"><label>Open existing folder<input name="id" aria-label="Folder ID" type="number" min="1" step="1" placeholder="Folder ID" required></label><button>Open folder</button></form><form data-form="create"><label>${current ? "New subfolder" : "New root folder"}<input name="name" aria-label="Folder name" maxlength="255" placeholder="Folder name" required></label><button class="primary">Create folder</button></form>${current ? `<form data-form="upload"><label>Upload a file<input type="file" name="upload" required></label><button class="primary">Upload</button></form>` : ""}</section>
    <nav aria-label="Breadcrumb">${button("Workspace", "home")}${trail.map((f, i) => ` / ${button(esc(f.name), "crumb", `data-index="${i}"`)}`).join("")}</nav>
    <section class="panel"><div class="section-heading"><h2>${current ? `Folder contents · #${current.id}` : "Saved folders"}</h2>${current ? `${button("Refresh", "refresh")} ${button("Manage folder sharing", "share", `data-type="folder" data-id="${current.id}"`)} ${button("Delete folder", "delete", `data-type="folder" data-id="${current.id}"`)}` : ""}</div>
    ${!current ? '<p class="muted">Folders opened or created here are saved in this browser. Open another folder using its ID.</p>' : ""}
    <div class="table-wrap"><table><thead><tr><th>Name</th><th>Type / size</th><th>Actions</th></tr></thead><tbody>${(current ? contents.folders : saved).map((f) => row(f, "folder")).join("")}${(current ? contents.files : []).map((f) => row(f, "file")).join("")}</tbody></table></div>
    ${!(current ? contents.folders.length + contents.files.length : saved.length) ? '<div class="empty"><strong>A little room for your next idea</strong><p>Create a folder to get started, or open an existing folder.</p></div>' : ""}</section>
    <section class="panel direct"><h2>Shared resources</h2><p class="muted">Use a file ID to download a file shared with you. Owners can revoke a public link by pasting it below.</p><form data-form="download"><label>File ID<input name="id" type="number" min="1" step="1" required></label><button>Download file</button></form><form data-form="revoke"><label>Public download link<input name="link" type="url" required placeholder="https://…/shared-links/…/download"></label><button>Revoke link</button></form></section>
    ${sharing ? `<section class="panel" aria-label="Sharing"><div class="section-heading"><h2>Sharing · ${sharing.type} #${sharing.id}</h2>${button("Close", "close")}</div><form data-form="share"><label>User ID<input name="user" type="number" min="1" step="1" required></label><label>Access<select name="role" aria-label="Access"><option value="viewer">Viewer</option><option value="editor">Editor</option></select></label><button class="primary">Save access</button></form><ul>${permissions.map((p) => `<li>User #${p.user_id} · ${esc(p.role)} ${button("Remove access", "remove", `data-id="${p.id}"`)}</li>`).join("")}</ul>${!permissions.length ? '<p class="muted">No direct permissions.</p>' : ""}${sharing.type === "file" ? `<p>Anyone with a public link can download this file.</p>${button("Create public link", "link")}` : ""}${link ? `<label>Public download link<input readonly value="${esc(link)}"></label><a href="${esc(link)}">Download via public link</a>` : ""}</section>` : ""}`
    }
    <div class="notice ${failed ? "error" : ""}" role="${failed ? "alert" : "status"}">${esc(busy ? "Working…" : message)}</div></main><footer>Drive · Frontend proof of concept</footer>`;
  app.querySelectorAll("button, input, select").forEach((el) => {
    el.disabled = busy;
  });
}
function row(item, type) {
  return `<tr><td>${type === "folder" ? button(`▱ ${esc(item.name)}`, "open", `data-id="${item.id}"`) : `<span>${esc(item.name)}</span>`}<small>#${item.id}</small></td><td>${type === "folder" ? "Folder" : `${(item.size_bytes / 1024).toFixed(1)} KB`}</td><td class="actions">${type === "file" ? button("Download", "download", `data-id="${item.id}"`) : ""} ${button("Share", "share", `data-type="${type}" data-id="${item.id}"`)} ${button("Delete", "delete", `data-type="${type}" data-id="${item.id}"`)}</td></tr>`;
}
async function openFolder(folder, path = [folder]) {
  const result = await api(`drive/folders/${folder.id}/contents`);
  current = folder;
  contents = result;
  trail = path;
  sharing = null;
  remember(folder);
}
async function refresh() {
  if (current) contents = await api(`drive/folders/${current.id}/contents`);
}
async function loadPermissions() {
  permissions = await api(`drive/${sharing.type}/${sharing.id}/permissions`);
}
async function download(id) {
  const blob = await api(`drive/files/${id}/download`, { blob: true });
  const url = URL.createObjectURL(blob),
    a = document.createElement("a");
  a.href = url;
  a.download = contents.files.find((f) => f.id === id)?.name || `file-${id}`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
async function run(task) {
  if (busy) return;
  busy = true;
  message = "";
  failed = false;
  render();
  try {
    await task();
  } catch (error) {
    message = error.message;
    failed = true;
    if (error.status === 401 && token) {
      token = "";
      current = null;
      sharing = null;
      message = "Your session expired. Please sign in again.";
    }
  } finally {
    busy = false;
    render();
  }
}
app.addEventListener("submit", (event) => {
  event.preventDefault();
  const kind = event.target.dataset.form,
    data = new FormData(event.target);
  run(async () => {
    if (kind === "login") {
      const result = await request("auth/token", {
        method: "POST",
        body: new URLSearchParams({
          username: data.get("email"),
          password: data.get("password"),
        }),
      });
      token = result.access_token;
      email = data.get("email");
      current = null;
      trail = [];
      contents = { folders: [], files: [] };
      sharing = null;
      link = "";
      try {
        saved = JSON.parse(
          localStorage.getItem(`drive-folders:${email}`) || "[]",
        ).filter((f) => Number.isInteger(f.id) && typeof f.name === "string");
      } catch {
        saved = [];
      }
    }
    if (kind === "open") {
      const id = Number(data.get("id"));
      await openFolder(
        saved.find((f) => f.id === id) || { id, name: `Folder ${id}` },
      );
    }
    if (kind === "create") {
      const name = data.get("name").trim();
      if (!name) throw new Error("Enter a folder name.");
      const folder = await api("drive/folders", {
        method: "POST",
        body: { name, parent_id: current?.id || null },
      });
      remember(folder);
      await openFolder(folder, [...trail, folder]);
      message = "Folder created.";
    }
    if (kind === "upload") {
      const body = new FormData();
      body.set("upload", data.get("upload"));
      await api(`drive/folders/${current.id}/files`, { method: "POST", body });
      await refresh();
      message = "File uploaded.";
    }
    if (kind === "share") {
      await api(`drive/${sharing.type}/${sharing.id}/share`, {
        method: "POST",
        body: { user_id: Number(data.get("user")), role: data.get("role") },
      });
      await loadPermissions();
      message = "Access saved.";
    }
    if (kind === "download") await download(Number(data.get("id")));
    if (kind === "revoke") {
      const path = new URL(data.get("link")).pathname;
      const match = path.match(
        /^\/api\/v1\/drive\/shared-links\/([^/]+)\/download$/,
      );
      if (!match) throw new Error("Enter a valid Drive public download link.");
      await api(`drive/shared-links/${match[1]}`, { method: "DELETE" });
      link = "";
      message = "Public link revoked.";
    }
  });
});
app.addEventListener("click", (event) => {
  const el = event.target.closest("[data-action]");
  if (!el) return;
  const { action, type } = el.dataset,
    id = Number(el.dataset.id);
  if (
    action === "delete" &&
    !confirm(
      `Delete this ${type}${type === "folder" ? " and its contents" : ""}?`,
    )
  )
    return;
  run(async () => {
    if (action === "logout") {
      token = "";
      email = "";
      saved = [];
      current = null;
      sharing = null;
      contents = { folders: [], files: [] };
      link = "";
    }
    if (action === "home") {
      current = null;
      trail = [];
      sharing = null;
    }
    if (action === "open") {
      const folder = [...contents.folders, ...saved].find((f) => f.id === id);
      await openFolder(folder, [...trail, folder]);
    }
    if (action === "crumb") {
      const i = Number(el.dataset.index);
      await openFolder(trail[i], trail.slice(0, i + 1));
    }
    if (action === "refresh") await refresh();
    if (action === "download") await download(id);
    if (action === "delete") {
      await api(`drive/${type}s/${id}`, { method: "DELETE" });
      if (type === "folder") {
        saved = saved.filter((f) => f.id !== id && f.parent_id !== id);
        try {
          localStorage.setItem(`drive-folders:${email}`, JSON.stringify(saved));
        } catch {}
        if (current?.id === id) {
          current = null;
          trail = [];
        }
      }
      sharing = null;
      await refresh();
      message = `${type === "file" ? "File" : "Folder"} deleted.`;
    }
    if (action === "share") {
      const result = await api(`drive/${type}/${id}/permissions`);
      sharing = { type, id };
      permissions = result;
      link = "";
    }
    if (action === "close") sharing = null;
    if (action === "remove") {
      await api(`drive/permissions/${id}`, { method: "DELETE" });
      await loadPermissions();
      message = "Access removed.";
    }
    if (action === "link") {
      const result = await api(`drive/files/${sharing.id}/shared-links`, {
        method: "POST",
      });
      link = new URL(result.download_url, location.origin).href;
    }
  });
});
render();
