/**
 * BlogIndexPage — /blog. Public listing of marketing blog posts inside the
 * marketing shell. Reads the static POSTS registry.
 */
import { useNavigate } from "react-router-dom";
import MarketingShell from "@/components/marketing/MarketingShell";
import { useIsMobile } from "@/hooks/use-is-mobile";
import { POSTS } from "./posts";

export default function BlogIndexPage() {
  const navigate = useNavigate();
  const isMobile = useIsMobile();

  return (
    <MarketingShell>
      {/* hero */}
      <div style={{ maxWidth: 900, margin: "0 auto", padding: isMobile ? "44px 20px 12px" : "80px 56px 20px", textAlign: "center" }}>
        <div className="nv-mono" style={{ fontSize: 11, letterSpacing: ".16em", color: "var(--mint)", textTransform: "uppercase" }}>Blog</div>
        <h1 className="nv-serif" style={{ fontSize: isMobile ? 40 : 60, lineHeight: 1.02, letterSpacing: "-0.035em", margin: "14px 0 0" }}>
          Plain-language investing<span style={{ color: "var(--mint)" }}>.</span>
        </h1>
        <p style={{ fontSize: 18, lineHeight: 1.6, color: "var(--ink-2)", margin: "22px auto 0", maxWidth: 560 }}>
          Data-grounded takes on why Indian investors lose money — and how to keep more of what you make.
        </p>
      </div>

      {/* post list */}
      <div style={{ maxWidth: 900, margin: "0 auto", padding: isMobile ? "24px 20px 8px" : "40px 56px 8px", display: "flex", flexDirection: "column", gap: 16 }}>
        {POSTS.map((p) => (
          <div
            key={p.slug}
            data-testid={`blog-card-${p.slug}`}
            role="link"
            tabIndex={0}
            onClick={() => navigate(`/blog/${p.slug}`)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                navigate(`/blog/${p.slug}`);
              }
            }}
            className="nv-card"
            style={{ padding: isMobile ? 22 : 30, cursor: "pointer" }}
          >
            <div className="nv-mono" style={{ fontSize: 10, letterSpacing: ".14em", color: "var(--mint)", textTransform: "uppercase" }}>
              {p.category} · {p.readMins} min read
            </div>
            <div className="nv-serif" style={{ fontSize: isMobile ? 24 : 30, letterSpacing: "-0.02em", marginTop: 12, lineHeight: 1.12 }}>
              {p.title}
            </div>
            <p style={{ fontSize: 15, color: "var(--ink-2)", lineHeight: 1.6, marginTop: 12, maxWidth: 620 }}>{p.excerpt}</p>
            <div style={{ color: "var(--mint)", fontSize: 14, fontWeight: 500, marginTop: 16 }}>Read the article →</div>
          </div>
        ))}
      </div>
    </MarketingShell>
  );
}
