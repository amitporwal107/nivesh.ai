/**
 * BlogArticlePage — /blog/:slug. Public long-form reader inside the marketing
 * shell (nav + footer). Renders the post header + its Body component. Unknown
 * slugs fall back to the blog index.
 */
import { useParams, useNavigate, Navigate } from "react-router-dom";
import MarketingShell from "@/components/marketing/MarketingShell";
import { useIsMobile } from "@/hooks/use-is-mobile";
import { getPost } from "./posts";

export default function BlogArticlePage() {
  const { slug } = useParams();
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const post = getPost(slug);

  if (!post) return <Navigate to="/blog" replace />;

  const Body = post.Body;

  return (
    <MarketingShell>
      <article data-testid="blog-article" style={{ maxWidth: 760, margin: "0 auto", padding: isMobile ? "36px 20px 24px" : "72px 56px 32px" }}>
        <span
          onClick={() => navigate("/blog")}
          className="nv-mono"
          style={{ fontSize: 12, color: "var(--ink-3)", cursor: "pointer", letterSpacing: ".04em" }}
        >
          ← All writing
        </span>
        <div className="nv-mono" style={{ fontSize: 11, letterSpacing: ".16em", color: "var(--mint)", textTransform: "uppercase", marginTop: 22 }}>
          {post.category}
        </div>
        <h1 className="nv-serif" style={{ fontSize: isMobile ? 34 : 52, lineHeight: 1.04, letterSpacing: "-0.03em", margin: "12px 0 0" }}>
          {post.title}
        </h1>
        <p style={{ fontSize: isMobile ? 17 : 19, lineHeight: 1.6, color: "var(--ink-2)", margin: "18px 0 0" }}>
          {post.excerpt}
        </p>
        <div className="nv-mono" style={{ fontSize: 11, color: "var(--ink-4)", letterSpacing: ".06em", margin: "18px 0 8px", display: "flex", gap: 14, flexWrap: "wrap" }}>
          <span>{post.dateLabel}</span>
          <span>·</span>
          <span>{post.readMins} min read</span>
        </div>
        <div style={{ borderTop: "1px solid var(--line-2)", margin: "20px 0 32px" }} />
        <Body />
      </article>
    </MarketingShell>
  );
}
