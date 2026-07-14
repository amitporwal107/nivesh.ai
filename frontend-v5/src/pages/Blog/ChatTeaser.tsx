/**
 * ChatTeaser — a small chat exchange (you → Nivesh) shown at the top of the
 * conversational blog articles, reinforcing the "just text and find out" theme
 * that mirrors the Nivesh Copilot chat product. Pure presentational, design-token styled.
 */
export default function ChatTeaser({ q, a }: { q: string; a: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10, margin: "6px 0 26px" }} data-testid="chat-teaser">
      <div
        style={{
          alignSelf: "flex-end", maxWidth: "82%", background: "var(--bg-2)",
          border: "1px solid var(--line-2)", borderRadius: "16px 16px 4px 16px",
          padding: "11px 15px", fontSize: 14.5, lineHeight: 1.5,
        }}
      >
        {q}
      </div>
      <div style={{ alignSelf: "flex-start", maxWidth: "88%", display: "flex", gap: 10, alignItems: "flex-end" }}>
        <span
          aria-hidden="true"
          style={{
            flexShrink: 0, width: 28, height: 28, borderRadius: "50%", background: "var(--mint)",
            color: "#08110d", display: "grid", placeItems: "center", fontWeight: 700, fontSize: 14,
          }}
        >
          न
        </span>
        <div className="nv-card" style={{ borderRadius: "16px 16px 16px 4px", padding: "11px 15px", fontSize: 14.5, lineHeight: 1.55 }}>
          {a}
        </div>
      </div>
    </div>
  );
}
