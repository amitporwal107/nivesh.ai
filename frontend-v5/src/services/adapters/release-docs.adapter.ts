/**
 * release-docs.adapter — Release Process Management API (Settings → Release Management).
 *
 * Talks to backend routes/release_docs.py (all admin-only):
 *   GET    /api/release-docs                      → list head summaries
 *   GET    /api/release-docs/templates            → generic template skeletons
 *   POST   /api/release-docs                      → create (head + revision 1)
 *   GET    /api/release-docs/{id}                 → full current content
 *   PUT    /api/release-docs/{id}                 → save edit → new revision
 *   GET    /api/release-docs/{id}/revisions       → revision history (metadata)
 *   GET    /api/release-docs/{id}/revisions/{n}   → one revision snapshot
 */
import { http } from "@/services/api/http";

export type DocType = "release_notes" | "release_process";
export type DocStatus = "draft" | "in_review" | "approved" | "final";
export type DocFormat = "structured" | "markdown";

export interface ReleaseDocSection {
  key: string;
  title: string;
  body: string;
}
export type ReleaseDocContent =
  | { sections: ReleaseDocSection[] }
  | { markdown: string };

export interface ReleaseDocSummary {
  id: string;
  doc_type: DocType;
  release_version: string;
  title: string;
  status: DocStatus;
  environment: string | null;
  format: DocFormat;
  current_revision: number;
  created_at: string;
  created_by: string;
  updated_at: string;
  updated_by: string;
}
export interface ReleaseDoc extends ReleaseDocSummary {
  content: ReleaseDocContent;
}

export interface ReleaseTemplate {
  doc_type: DocType;
  label: string;
  title_hint: string;
  sections: ReleaseDocSection[];
}

export interface RevisionMeta {
  revision: number;
  status: DocStatus;
  format: DocFormat;
  change_note: string | null;
  saved_at: string;
  saved_by: string;
}
export interface RevisionSnapshot extends RevisionMeta {
  document_id: string;
  doc_type: DocType;
  release_version: string;
  content: ReleaseDocContent;
}

export interface CreateReleaseDocInput {
  doc_type: DocType;
  release_version: string;
  title: string;
  content: ReleaseDocContent;
  format?: DocFormat;
  status?: DocStatus;
  environment?: string | null;
}
export interface UpdateReleaseDocInput {
  content: ReleaseDocContent;
  status?: DocStatus;
  change_note?: string;
}

export interface ReleaseDocsAdapter {
  list(params?: { doc_type?: DocType; status?: DocStatus }): Promise<ReleaseDocSummary[]>;
  get(id: string): Promise<ReleaseDoc>;
  templates(): Promise<ReleaseTemplate[]>;
  create(input: CreateReleaseDocInput): Promise<ReleaseDoc>;
  update(id: string, input: UpdateReleaseDocInput): Promise<ReleaseDoc>;
  revisions(id: string): Promise<RevisionMeta[]>;
  revision(id: string, n: number): Promise<RevisionSnapshot>;
}

export const realReleaseDocsAdapter: ReleaseDocsAdapter = {
  async list(params) {
    const res = await http<{ documents: ReleaseDocSummary[] }>({
      path: "/api/release-docs",
      query: { doc_type: params?.doc_type, status: params?.status },
    });
    return res.data?.documents ?? [];
  },

  async get(id) {
    const res = await http<ReleaseDoc>({ path: `/api/release-docs/${id}` });
    return res.data;
  },

  async templates() {
    const res = await http<{ templates: ReleaseTemplate[] }>({
      path: "/api/release-docs/templates",
    });
    return res.data?.templates ?? [];
  },

  async create(input) {
    const res = await http<ReleaseDoc>({
      method: "POST",
      path: "/api/release-docs",
      body: input,
      noRetry: true,
    });
    return res.data;
  },

  async update(id, input) {
    const res = await http<ReleaseDoc>({
      method: "PUT",
      path: `/api/release-docs/${id}`,
      body: input,
      noRetry: true,
    });
    return res.data;
  },

  async revisions(id) {
    const res = await http<{ revisions: RevisionMeta[] }>({
      path: `/api/release-docs/${id}/revisions`,
    });
    return res.data?.revisions ?? [];
  },

  async revision(id, n) {
    const res = await http<RevisionSnapshot>({
      path: `/api/release-docs/${id}/revisions/${n}`,
    });
    return res.data;
  },
};
