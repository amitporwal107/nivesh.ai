/**
 * Settings → Release Management (admin-only).
 *
 * Lists every release document to date (grouped by release semver, newest
 * first) and lets an admin author a new one from a generic template. Route is
 * guarded by <RequireAdmin> in routes.tsx.
 */
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Card, CardLabel } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ArrowLeft, FileText, Plus, ChevronRight, Loader2 } from "lucide-react";
import {
  useReleaseDocs,
  useReleaseTemplates,
  useCreateReleaseDoc,
} from "@/hooks/use-release-docs";
import { sectionsToMarkdown } from "./DocContentEditor";
import { DocContentEditor } from "./DocContentEditor";
import type {
  DocType,
  DocFormat,
  DocStatus,
  ReleaseDocContent,
  ReleaseDocSummary,
} from "@/services";

const DOC_TYPE_LABEL: Record<DocType, string> = {
  release_notes: "Release Notes",
  release_process: "Release Process",
};

const STATUS_CLS: Record<DocStatus, string> = {
  draft: "bg-surface-3 text-ink-2",
  in_review: "bg-amber-500/15 text-amber-500",
  approved: "bg-accent-soft text-accent",
  final: "bg-pos/15 text-pos",
};

const INPUT_CLS =
  "w-full rounded-md border border-hairline bg-surface-2 px-3 py-2 text-[13px] focus:outline-none focus:border-accent transition-colors";

function semverKey(v: string): number[] {
  return v.split(/[.\-+]/).map((p) => (/^\d+$/.test(p) ? parseInt(p, 10) : -1));
}
function compareVersionsDesc(a: string, b: string): number {
  const ka = semverKey(a), kb = semverKey(b);
  for (let i = 0; i < Math.max(ka.length, kb.length); i++) {
    const d = (kb[i] ?? 0) - (ka[i] ?? 0);
    if (d !== 0) return d;
  }
  return 0;
}
function fmtDate(iso?: string) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export default function ReleasesPage() {
  const navigate = useNavigate();
  const { data: docs, isPending, isError } = useReleaseDocs();
  const { data: templates } = useReleaseTemplates();
  const create = useCreateReleaseDoc();

  const [open, setOpen] = useState(false);
  const [docType, setDocType] = useState<DocType>("release_notes");
  const [version, setVersion] = useState("");
  const [title, setTitle] = useState("");
  const [format, setFormat] = useState<DocFormat>("structured");
  const [status, setStatus] = useState<DocStatus>("draft");
  const [content, setContent] = useState<ReleaseDocContent>({ sections: [] });

  const template = useMemo(
    () => templates?.find((t) => t.doc_type === docType),
    [templates, docType],
  );

  // Load the picked template's sections into the editor.
  function applyTemplate(type: DocType, fmt: DocFormat) {
    const t = templates?.find((x) => x.doc_type === type);
    if (!t) return;
    if (fmt === "markdown") {
      setContent({ markdown: sectionsToMarkdown({ sections: t.sections }) });
    } else {
      setContent({ sections: t.sections.map((s) => ({ ...s })) });
    }
    if (!title) setTitle(t.title_hint);
  }

  function openForm() {
    setOpen(true);
    setDocType("release_notes");
    setFormat("structured");
    setStatus("draft");
    setVersion("");
    setTitle("");
    // seed content from the release_notes template
    const t = templates?.find((x) => x.doc_type === "release_notes");
    setContent(t ? { sections: t.sections.map((s) => ({ ...s })) } : { sections: [] });
    if (t) setTitle(t.title_hint);
  }

  function onDocTypeChange(type: DocType) {
    setDocType(type);
    const t = templates?.find((x) => x.doc_type === type);
    if (t) setTitle(t.title_hint);
    applyTemplate(type, format);
  }

  function onFormatChange(fmt: DocFormat) {
    setFormat(fmt);
    // convert current content to the new representation
    if (fmt === "markdown") {
      setContent({ markdown: sectionsToMarkdown(content) });
    } else {
      applyTemplate(docType, "structured");
    }
  }

  async function submit() {
    const titled = title.trim() || `${DOC_TYPE_LABEL[docType]} — v${version}`;
    try {
      const doc = await create.mutateAsync({
        doc_type: docType,
        release_version: version.trim(),
        title: titled,
        content,
        format,
        status,
      });
      setOpen(false);
      navigate(`/settings/releases/${doc.id}`);
    } catch {
      /* error surfaced via create.error below */
    }
  }

  const grouped = useMemo(() => {
    const byVersion = new Map<string, ReleaseDocSummary[]>();
    for (const d of docs ?? []) {
      const arr = byVersion.get(d.release_version) ?? [];
      arr.push(d);
      byVersion.set(d.release_version, arr);
    }
    return [...byVersion.entries()].sort((a, b) => compareVersionsDesc(a[0], b[0]));
  }, [docs]);

  const createErr = create.isError ? ((create.error as { message?: string })?.message ?? "Could not create document.") : null;

  return (
    <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[900px] mx-auto w-full">
      <Link to="/settings" className="inline-flex items-center gap-1.5 text-[12px] text-ink-3 hover:text-ink-2 transition-colors">
        <ArrowLeft className="h-3.5 w-3.5" /> Settings
      </Link>
      <div className="mt-4 flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3">Release Management</div>
          <h1 className="font-display text-3xl sm:text-4xl tracking-tightish leading-[1.05] mt-1.5">Releases</h1>
          <p className="text-[14px] text-ink-2 mt-3 max-w-[560px] leading-relaxed">
            Author and version release documents — Release Notes and Release Process — from generic
            templates. Every save keeps an immutable revision. All documents to date are listed below.
          </p>
        </div>
        <Button data-testid="new-release-doc" onClick={openForm} disabled={open}>
          <Plus className="h-4 w-4 mr-1" /> New document
        </Button>
      </div>

      {/* Create form */}
      {open && (
        <Card className="mt-6 p-6" data-testid="rd-create-form">
          <CardLabel>New release document</CardLabel>
          <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-4">
            <label className="block">
              <span className="font-mono text-[11px] uppercase tracking-wider text-ink-4">Document type</span>
              <select
                data-testid="rd-doc-type"
                value={docType}
                onChange={(e) => onDocTypeChange(e.target.value as DocType)}
                className={INPUT_CLS + " mt-1"}
              >
                <option value="release_notes">Release Notes</option>
                <option value="release_process">Release Process</option>
              </select>
            </label>
            <label className="block">
              <span className="font-mono text-[11px] uppercase tracking-wider text-ink-4">Release version (semver)</span>
              <input
                data-testid="rd-version"
                value={version}
                onChange={(e) => setVersion(e.target.value)}
                placeholder="4.2.0"
                className={INPUT_CLS + " mt-1"}
              />
            </label>
            <label className="block sm:col-span-2">
              <span className="font-mono text-[11px] uppercase tracking-wider text-ink-4">Title</span>
              <input
                data-testid="rd-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                className={INPUT_CLS + " mt-1"}
              />
            </label>
            <label className="block">
              <span className="font-mono text-[11px] uppercase tracking-wider text-ink-4">Format</span>
              <select
                data-testid="rd-format"
                value={format}
                onChange={(e) => onFormatChange(e.target.value as DocFormat)}
                className={INPUT_CLS + " mt-1"}
              >
                <option value="structured">Structured (template sections)</option>
                <option value="markdown">Markdown (paste / import)</option>
              </select>
            </label>
            <label className="block">
              <span className="font-mono text-[11px] uppercase tracking-wider text-ink-4">Status</span>
              <select
                data-testid="rd-status"
                value={status}
                onChange={(e) => setStatus(e.target.value as DocStatus)}
                className={INPUT_CLS + " mt-1"}
              >
                <option value="draft">Draft</option>
                <option value="in_review">In review</option>
                <option value="approved">Approved</option>
                <option value="final">Final</option>
              </select>
            </label>
          </div>

          <div className="mt-5">
            <DocContentEditor format={format} content={content} onChange={setContent} />
          </div>

          {createErr && (
            <div data-testid="rd-create-error" className="mt-3 text-[12px] text-neg">{createErr}</div>
          )}

          <div className="mt-5 flex items-center gap-2">
            <Button data-testid="rd-create-submit" onClick={submit} disabled={create.isPending || !version.trim()}>
              {create.isPending ? <><Loader2 className="h-4 w-4 mr-1 animate-spin" /> Saving…</> : "Create document"}
            </Button>
            <Button variant="ghost" onClick={() => setOpen(false)} disabled={create.isPending}>Cancel</Button>
          </div>
        </Card>
      )}

      {/* List */}
      <div className="mt-6">
        {isPending ? (
          <div className="text-[13px] text-ink-3 flex items-center gap-2"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</div>
        ) : isError ? (
          <div className="text-[13px] text-neg">Could not load release documents.</div>
        ) : grouped.length === 0 ? (
          <div data-testid="rd-empty" className="text-[13px] text-ink-3 border border-dashed border-hairline rounded-md px-4 py-8 text-center">
            No release documents yet. Click “New document” to author the first one.
          </div>
        ) : (
          <div className="space-y-6">
            {grouped.map(([ver, items]) => (
              <div key={ver} data-testid={`rd-group-${ver}`}>
                <div className="font-mono text-[12px] text-ink-3 mb-2">v{ver}</div>
                <div className="space-y-2">
                  {items.map((d) => (
                    <Link
                      key={d.id}
                      to={`/settings/releases/${d.id}`}
                      data-testid={`rd-item-${d.id}`}
                      className="flex items-center gap-3 rounded-md border border-hairline bg-surface-1 px-4 py-3 hover:bg-surface-2 transition-colors"
                    >
                      <FileText className="h-4 w-4 text-accent shrink-0" />
                      <div className="flex-1 min-w-0">
                        <div className="text-[13.5px] font-medium truncate">{d.title}</div>
                        <div className="text-[12px] text-ink-3 mt-0.5">
                          {DOC_TYPE_LABEL[d.doc_type]} · rev {d.current_revision} · updated {fmtDate(d.updated_at)}
                        </div>
                      </div>
                      <span className={cn("shrink-0 rounded-full px-2 py-0.5 text-[11px] font-mono", STATUS_CLS[d.status])}>
                        {d.status}
                      </span>
                      <ChevronRight className="h-4 w-4 text-ink-4 shrink-0" />
                    </Link>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
