// Parses a Copilot response string into a sequence of renderable
// segments: plain markdown vs. structured chart specs.
//
// The backend emits chart specs as fenced code blocks tagged `chart`:
//   ```chart
//   { "type": "bar", "title": "...", "data": [...] }
//   ```
// We split on those blocks so the caller can render each markdown
// segment with ReactMarkdown and each chart spec with ChartBlock.
//
// Bad/malformed JSON does not throw — the offending block falls back
// to a plain markdown segment so the user still sees the LLM's intent.

const CHART_FENCE_RE = /```chart\s*\n([\s\S]*?)```/g;

export function parseCopilotChartBlocks(text) {
  if (!text || typeof text !== "string") {
    return [{ kind: "markdown", text: text || "" }];
  }
  const segments = [];
  let lastIndex = 0;
  let match;
  CHART_FENCE_RE.lastIndex = 0;
  while ((match = CHART_FENCE_RE.exec(text)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ kind: "markdown", text: text.slice(lastIndex, match.index) });
    }
    const body = match[1].trim();
    try {
      const spec = JSON.parse(body);
      segments.push({ kind: "chart", spec });
    } catch {
      segments.push({ kind: "markdown", text: "```\n" + body + "\n```" });
    }
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) {
    segments.push({ kind: "markdown", text: text.slice(lastIndex) });
  }
  return segments.length ? segments : [{ kind: "markdown", text }];
}
