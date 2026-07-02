/**
 * Settings → Release Management → one document (admin-only).
 *
 * View/edit the current content (saving appends an immutable revision and
 * advances the head), change status, and browse the revision history. Selecting
 * a past revision shows its snapshot read-only.
 */
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Card, CardLabel } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ArrowLeft, History, Loader2, Check } from "lucide-react";
import {
  useReleaseDoc,
  useReleaseDocRevisions,
  useUpdateReleaseDoc,
} from "@/hooks/use-release-docs";
import { releaseDocsService } from "@/services";
import { DocContentEditor } from "./DocContentEditor";
import type { DocStatus, ReleaseDocContent, RevisionSnapshot } from "@/services";

const DOC_TYPE_LABEL: Record<string, string> = {
  release_notes: "Release Notes",
  release_process: "Release Process",
};
const INPUT_CLS =
  "rounded-md border border-hairline bg-surface-2 px-3 py-2 text-[13px] focus:outline-none focus:border-accent transition-colors";

function fmtDate(iso?: string) {
  if (!iso) return "";
  return new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export default function ReleaseDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: doc, isPending, isError } = useReleaseDoc(id);
  const { data: revisions } = useReleaseDocRevisions(id);
  const update = useUpdateReleaseDoc(id ?? "");

  const [content, setContent] = useState<ReleaseDocContent>({ sections: [] });
  const [status, setStatus] = useState<DocStatus>("draft");
  const [changeNote, setChangeNote] = useState("");
  const [saved, setSaved] = useState(false);
  const [viewing, setViewing] = useState<RevisionSnapshot | null>(null);

  // Sync editor state when the document loads / changes.
  useEffect(() => {
    if (doc) {
      setContent(doc.content);
      setStatus(doc.status);
    }
  }, [doc?.id, doc?.current_revision]); // eslint-disable-line react-hooks/exhaustive-deps

  async function save() {
    if (!id) return;
    await update.mutateAsync({ content, status, change_note: changeNote.trim() || undefined });
    setChangeNote("");
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  }

  async function viewRevision(n: number) {
    if (!id) return;
    const snap = await releaseDocsService.revision(id, n);
    setViewing(snap);
  }

  if (isPending) {
    return (
      <div className="px-6 py-10 max-w-[900px] mx-auto text-[13px] text-ink-3 flex items-center gap-2">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading…
      </div>
    );
  }
  if (isError || !doc) {
    return (
      <div className="px-6 py-10 max-w-[900px] mx-auto">
        <Link to="/settings/releases" className="inline-flex items-center gap-1.5 text-[12px] text-ink-3 hover:text-ink-2">
          <ArrowLeft className="h-3.5 w-3.5" /> Releases
        </Link>
        <div className="mt-4 text-[13px] text-neg">Release document not found.</div>
      </div>
    );
  }

  return (
    <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[900px] mx-auto w-full" data-testid="rd-detail">
      <Link to="/settings/releases" className="inline-flex items-center gap-1.5 text-[12px] text-ink-3 hover:text-ink-2 transition-colors">
        <ArrowLeft className="h-3.5 w-3.5" /> Releases
      </Link>
      <div className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3 mt-4">
        {DOC_TYPE_LABEL[doc.doc_type]} · v{doc.release_version}
      </div>
      <h1 data-testid="rd-title-display" className="font-display text-3xl tracking-tightish leading-[1.05] mt-1.5">{doc.title}</h1>
      <div className="text-[12px] text-ink-3 mt-2">
        <span data-testid="rd-current-revision">revision {doc.current_revision}</span> · updated {fmtDate(doc.updated_at)} by {doc.updated_by}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_260px] gap-6 mt-6">
        {/* Editor / revision viewer */}
        <div>
          {viewing ? (
            <Card className="p-6">
              <div className="flex items-center justify-between">
                <CardLabel>Revision {viewing.revision} · read-only</CardLabel>
                <Button variant="outline" size="sm" onClick={() => setViewing(null)}>Back to current</Button>
              </div>
              <div className="text-[12px] text-ink-3 mt-1 mb-4">
                saved {fmtDate(viewing.saved_at)} by {viewing.saved_by}
                {viewing.change_note ? ` · ${viewing.change_note}` : ""}
              </div>
              <DocContentEditor format={viewing.format} content={viewing.content} readOnly />
            </Card>
          ) : (
            <Card className="p-6">
              <div className="flex items-center gap-3 flex-wrap">
                <label className="inline-flex flex-col">
                  <span className="font-mono text-[11px] uppercase tracking-wider text-ink-4">Status</span>
                  <select
                    data-testid="rd-status-edit"
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
                <label className="inline-flex flex-col flex-1 min-w-[180px]">
                  <span className="font-mono text-[11px] uppercase tracking-wider text-ink-4">Change note (optional)</span>
                  <input
                    data-testid="rd-change-note"
                    value={changeNote}
                    onChange={(e) => setChangeNote(e.target.value)}
                    placeholder="What changed in this revision?"
                    className={INPUT_CLS + " mt-1"}
                  />
                </label>
              </div>

              <div className="mt-5">
                <DocContentEditor format={doc.format} content={content} onChange={setContent} />
              </div>

              <div className="mt-5 flex items-center gap-2">
                <Button data-testid="rd-save" onClick={save} disabled={update.isPending}>
                  {update.isPending ? <><Loader2 className="h-4 w-4 mr-1 animate-spin" /> Saving…</> : "Save revision"}
                </Button>
                {saved && (
                  <span data-testid="rd-save-ok" className="text-[12px] text-pos inline-flex items-center gap-1">
                    <Check className="h-3.5 w-3.5" /> Saved as revision {doc.current_revision}
                  </span>
                )}
                {update.isError && (
                  <span className="text-[12px] text-neg">{(update.error as { message?: string })?.message ?? "Save failed."}</span>
                )}
              </div>
            </Card>
          )}
        </div>

        {/* Revision history */}
        <div>
          <div className="font-mono text-[11px] uppercase tracking-wider text-ink-4 flex items-center gap-1.5 mb-2">
            <History className="h-3.5 w-3.5" /> Revision history
          </div>
          <div data-testid="rd-revisions" className="space-y-1.5">
            {(revisions ?? []).slice().reverse().map((r) => (
              <button
                key={r.revision}
                data-testid={`rd-rev-${r.revision}`}
                onClick={() => viewRevision(r.revision)}
                className={cn(
                  "w-full text-left rounded-md border border-hairline bg-surface-1 px-3 py-2 hover:bg-surface-2 transition-colors",
                  viewing?.revision === r.revision && "border-accent",
                )}
              >
                <div className="text-[12.5px] font-medium">rev {r.revision} · {r.status}</div>
                <div className="text-[11px] text-ink-3 mt-0.5">{fmtDate(r.saved_at)}</div>
                {r.change_note && <div className="text-[11px] text-ink-3 mt-0.5 truncate">{r.change_note}</div>}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
