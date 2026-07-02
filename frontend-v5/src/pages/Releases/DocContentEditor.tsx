/**
 * DocContentEditor — renders the editable body of a release document.
 *
 * Two modes (matching the stored `format`):
 *  - structured: one labelled textarea per template section
 *  - markdown:   a single free-form textarea
 *
 * Fully controlled: the parent owns the ReleaseDocContent and re-renders on change.
 */
import type { DocFormat, ReleaseDocContent } from "@/services";

const TEXTAREA_CLS =
  "w-full rounded-md border border-hairline bg-surface-2 px-3 py-2 text-[13px] font-mono leading-relaxed focus:outline-none focus:border-accent transition-colors";

export function DocContentEditor({
  format,
  content,
  onChange,
  readOnly = false,
}: {
  format: DocFormat;
  content: ReleaseDocContent;
  onChange?: (c: ReleaseDocContent) => void;
  readOnly?: boolean;
}) {
  if (format === "markdown") {
    const md = "markdown" in content ? content.markdown : "";
    return (
      <div>
        <label className="font-mono text-[11px] uppercase tracking-wider text-ink-4">Markdown</label>
        <textarea
          data-testid="release-markdown"
          value={md}
          readOnly={readOnly}
          onChange={(e) => onChange?.({ markdown: e.target.value })}
          rows={22}
          className={TEXTAREA_CLS + " mt-1"}
        />
      </div>
    );
  }

  const sections = "sections" in content ? content.sections : [];
  return (
    <div className="space-y-4">
      {sections.map((s) => (
        <div key={s.key}>
          <label
            htmlFor={`sec-${s.key}`}
            className="font-mono text-[11px] uppercase tracking-wider text-ink-4"
          >
            {s.title}
          </label>
          <textarea
            id={`sec-${s.key}`}
            data-testid={`release-section-${s.key}`}
            value={s.body}
            readOnly={readOnly}
            onChange={(e) =>
              onChange?.({
                sections: sections.map((x) =>
                  x.key === s.key ? { ...x, body: e.target.value } : x,
                ),
              })
            }
            rows={5}
            className={TEXTAREA_CLS + " mt-1"}
          />
        </div>
      ))}
    </div>
  );
}

/** Flatten structured sections into a markdown document (for format switches / export). */
export function sectionsToMarkdown(content: ReleaseDocContent): string {
  if ("markdown" in content) return content.markdown;
  return content.sections.map((s) => `## ${s.title}\n\n${s.body}`).join("\n\n");
}
