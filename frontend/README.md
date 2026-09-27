# Drive frontend POC (DRIVE-12)

A responsive, business-style frontend for the existing FastAPI API. All frontend code, tooling, tests, and configuration live here; the backend does not need changes.

## Run

Start the backend, migrate, and seed users using the repository's quick start. Then, with Node.js 22 or newer:

```sh
cd frontend
npm ci
npm start
```

Open http://localhost:3000. Sign in with an existing account (for the local demo seed: `alice@example.com` / `alice123`, or `bob@example.com` / `bob123`). No build step is needed.

The Node server serves the frontend and streams `/api/v1/` requests to the backend, including multipart uploads and binary downloads. This same-origin setup needs no backend CORS changes. Set `API_ORIGIN` to a backend origin (default `http://127.0.0.1:8000`), `PORT` (default `3000`), or `HOST` (default `127.0.0.1`) in the process environment. For a hosted demo, expose this server behind an HTTPS reverse proxy; public links use the frontend's origin, which must be reachable by recipients.

## Demo workflow

1. Sign in, create a root folder, and upload a file. Create subfolders and use the breadcrumb to navigate.
2. Download files or delete files/folders after confirmation.
3. Choose Share to view, grant/update, or remove viewer/editor access using a recipient's user ID (the seed assigns Bob ID 2). The API enforces access rights and its errors appear in the UI.
4. Create a public download link for a file. Copy the displayed URL, open it without signing in, or paste it into Revoke link to revoke it as owner.
5. Sign in as the recipient and open a shared folder by ID or download an individually shared file by ID.

The current API has no root-folder listing, resource search, user directory, or public-link listing. The frontend therefore remembers created/opened folders per sign-in email in this browser and accepts folder/file/user IDs where needed. Saved folders are bookmarks, not an authoritative listing: access and existence are checked when opening them. Public links are displayed on creation and can later be revoked by pasting the URL. Permissions are direct permissions as returned by the API. Accounts are provisioned through the backend. Folder deletion uses the backend's existing deletion semantics; there is no restore endpoint.

Authentication tokens stay in memory. Reloading or signing out requires signing in again; credentials and tokens are not persisted. Only folder bookmarks are kept in local storage.

## Tests

```sh
cd frontend
npm ci
npx playwright install --with-deps chromium
npm test
```

Tests exercise the real browser UI with API fixtures for login, failed/expired sessions, folder creation/navigation/bookmarks, upload/download, sharing and permission removal, public-link creation/revocation, deletion confirmation, safe text rendering, and mobile layout. A local HTTP integration test verifies proxy byte preservation and status forwarding. UI fixtures do not replace backend tests (`python -m pytest` from the repository root).
