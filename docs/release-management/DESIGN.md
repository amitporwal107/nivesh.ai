# Release Process Management — Design / Spec

**Status:** Design (pre-implementation) · **Date:** 2026-07-02 · **Branch:** feat/copilot-backtest
**Decisions (confirmed with requester):** in-app authoring · release semver + immutable revision history · admin-only.

## 1. Problem / Goal
Provide an internal, admin-only place to author, version, and browse release documents
(two types: **Release Notes** and **Release Process**), stored in MongoDB, viewable in Settings.
Templates are the generic skeletons in `TEMPLATE_release_notes.md` / `TEMPLATE_release_process.md`.

## 2. Data Model (MongoDB)

Reuses the shared handle `from deps import db` (same client as the rest of the backend).

### Collection `release_documents` (current head — fast reads)
```
{
  _id: ObjectId,
  doc_type: "release_notes" | "release_process",
  release_version: "4.2.0",              // semver; unique per doc_type
  title: string,
  status: "draft" | "in_review" | "approved" | "final",
  environment: "staging" | "production" | null,
  format: "structured" | "markdown",     // structured = section model from template; markdown = pasted/imported
  content: object | { markdown: string }, // current content
  current_revision: number,               // points at latest revision
  created_at, created_by (email),
  updated_at, updated_by (email)
}
```
Index: unique `(doc_type, release_version)`; secondary `(updated_at desc)` for the list.

### Collection `release_document_revisions` (immutable history)
```
{
  _id, document_id (ref), doc_type, release_version,
  revision: number,                       // 1,2,3… monotonic per document
  status, format, content,                // full snapshot at save time
  change_note: string | null,
  saved_at, saved_by (email)
}
```
Revisions are **append-only**: never updated or deleted → satisfies "immutable revision history".
Save flow: bump head `current_revision`, overwrite head `content/status/updated_*`, and **insert** a new revision snapshot.

## 3. API (backend/routes/release_docs.py, prefix `/api`, ALL admin-gated via `require_admin`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/release-docs` | List all release docs (head summaries, no full content), newest first. `?doc_type=&status=` filters. |
| GET | `/api/release-docs/{id}` | Full head doc (current content). |
| POST | `/api/release-docs` | Create from template. Body: `doc_type, release_version, title, format, content, status?`. 409 on duplicate `(doc_type, release_version)`. Creates head + revision 1. |
| PUT | `/api/release-docs/{id}` | Save edit → new revision (bump + snapshot). Body: `content, status?, change_note?`. |
| GET | `/api/release-docs/{id}/revisions` | Revision history (metadata only). |
| GET | `/api/release-docs/{id}/revisions/{n}` | One revision's full content (read-only). |
| GET | `/api/release-docs/templates` | The two generic template skeletons (section model) for the authoring form. |

Validation: `doc_type` ∈ enum; `release_version` matches semver regex; `format` ∈ enum; `content` required.
Store lives in `backend/services/release_docs_store.py` (Mongo CRUD + revision bump). Registered in `server.py`.

## 4. Frontend (frontend-v5)
- **Route:** `/settings/releases` (list) and `/settings/releases/:id` (view/edit + revision history). Wired in `routes.tsx`.
- **Page:** `src/pages/Settings/Releases/` — list grouped by `release_version` (newest first) with doc_type, status, last-updated, revision count; a create button (choose type → template form); an editor (structured form driven by `/templates`, **plus** a "paste/import markdown" mode); a viewer with a revision-history drawer.
- **Hook:** `src/hooks/use-release-docs.ts` (react-query: list/get/create/update/revisions).
- **Service:** `src/services/adapters/release-docs.adapter.ts`, registered in `src/services/index.ts`.
- **Settings entry:** a "Release Management" card in `src/pages/Settings/index.tsx` with a `Link` to `/settings/releases`, shown **only for admins** (same `me.role`/`getAdminNav` gating already used). Route guarded so non-admins are redirected.

## 5. Versioning semantics
- `release_version` (semver) groups the document set for a release — the Settings list is organized by it, newest first ("all release documents till today").
- Every save appends an immutable revision; the head always reflects the latest. History is viewable per document and never mutated.

## 6. Out of scope (v1)
- Rich diff between revisions (show snapshots, not a diff view).
- PDF export / approvals workflow automation (status is a manual field).
- Deleting documents (append-only; add archive later if needed).

## 7. Verification plan
See `test_reports/release-management_functionality.md` (authored up front). Backend endpoints verified on
**staging** with real curl output; frontend verified with **Playwright**. Requires a staging admin session token
(to be requested from the user) and the new routes deployed to staging.
