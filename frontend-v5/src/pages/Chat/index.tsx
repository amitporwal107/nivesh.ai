import { useState, useEffect } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ArrowRight, Plus, Send } from "lucide-react";
import { cn } from "@/lib/utils";
import { useSendChat, useSuggestedPrompts, useChatSession, useCreateChatSession } from "@/hooks/use-chat";
import { Skeleton } from "@/components/ui/skeleton";
import { ChatWidget } from "@/components/chat/ChatWidget";

const WIDGET_TYPES = new Set(["fund_consolidation", "fund_overlap"]);

const FALLBACK_PROMPTS = [
  "Why is my score 74?",
  "Which funds overlap most?",
  "How risky is my portfolio?",
  "What should I reduce first?",
];

export default function ChatPage() {
  const [composer, setComposer] = useState("");
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);

  const prompts = useSuggestedPrompts();
  const send = useSendChat();
  const createSession = useCreateChatSession();
  const session = useChatSession(sessionId ?? "");

  // Lazily create a session on first send.
  useEffect(() => {
    if (sessionId || !send.isPending) return;
  }, [sessionId, send.isPending]);

  const messages = session.data?.messages ?? [];

  const handleSend = async () => {
    const text = composer.trim();
    if (!text || send.isPending) return;
    setComposer("");
    let sid = sessionId;
    if (!sid) {
      const created = await createSession.mutateAsync(undefined);
      sid = created.id;
      setSessionId(sid);
    }
    await send.mutateAsync({ message: text, sessionId: sid });
  };

  const promptList = prompts.data && prompts.data.length > 0 ? prompts.data : FALLBACK_PROMPTS;

  return (
    <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[880px] mx-auto w-full min-h-[calc(100vh-4rem)] flex flex-col">
      <div className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3">Chat</div>
      <h1 className="font-display text-3xl sm:text-4xl tracking-tightish leading-[1.05] mt-1.5">
        Ask anything about your portfolio.
      </h1>

      <div className="flex flex-wrap gap-2 mt-6">
        {prompts.isPending && Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-9 w-40 rounded-full" />
        ))}
        {!prompts.isPending && promptList.map((q) => (
          <button
            key={q}
            onClick={() => setComposer(q)}
            className="px-3.5 py-2 rounded-full bg-surface-2 border border-hairline text-[12.5px] text-ink-2 hover:bg-surface-3 transition-colors"
          >
            {q}
          </button>
        ))}
      </div>

      <div className="mt-7 flex-1 flex flex-col gap-5">
        {messages.length === 0 && !send.isPending && (
          <div className="flex flex-col items-center text-center mt-6">
            <Badge tone="accent" className="mb-3">Ready</Badge>
            <p className="text-ink-2 text-[14px] max-w-md leading-relaxed">
              Pick a question above or type your own. I'll read your portfolio first, then answer in plain English.
            </p>
          </div>
        )}

        {messages.map((m, i) => {
          const isUser = m.role === "user";
          const widget = !isUser ? (m as { widget?: { widget_type?: string; data?: unknown } }).widget : undefined;
          const hasWidget = !!widget?.widget_type && WIDGET_TYPES.has(widget.widget_type);
          return (
            <div key={m.id ?? i} className={cn(isUser ? "self-end max-w-[520px] px-4 py-3 rounded-2xl rounded-br-md bg-surface-2 border border-hairline" : "flex gap-3.5")}>
              {!isUser && (
                <span className="grid place-items-center h-9 w-9 rounded-md bg-ink text-on-accent font-display text-base leading-none shrink-0">न</span>
              )}
              <div className={isUser ? "" : "flex-1 min-w-0"}>
                {hasWidget ? (
                  <ChatWidget widget={widget} />
                ) : (
                  <p className={isUser ? "text-[14px]" : "text-[15.5px] leading-relaxed whitespace-pre-wrap"}>{m.content}</p>
                )}
              </div>
            </div>
          );
        })}

        {send.isPending && (
          <div className="flex gap-3.5">
            <span className="grid place-items-center h-9 w-9 rounded-md bg-ink text-on-accent font-display text-base leading-none shrink-0">न</span>
            <div className="flex-1 flex items-center gap-1.5 text-ink-3">
              <Dot delay={0} /><Dot delay={150} /><Dot delay={300} />
            </div>
          </div>
        )}
      </div>

      {/* composer */}
      <div className="mt-7 sticky bottom-0 bg-bg/95 backdrop-blur">
        <div
          className={cn(
            "flex items-center gap-3 px-4 py-3 rounded-md bg-surface-1 border border-hairline-2",
            "focus-within:border-accent",
          )}
        >
          <Plus className="h-4 w-4 text-ink-3" />
          <input
            type="text"
            placeholder="Ask anything…"
            value={composer}
            onChange={(e) => setComposer(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") handleSend(); }}
            className="flex-1 bg-transparent outline-none text-[14.5px]"
            disabled={send.isPending}
          />
          <Button variant="accent" size="sm" disabled={!composer.trim() || send.isPending} onClick={handleSend}>
            <Send className="h-3.5 w-3.5" /> Send
          </Button>
        </div>
        {send.isError && (
          <div className="text-[12px] text-neg mt-2 font-mono">
            {(send.error as Error).message}
          </div>
        )}
      </div>
    </div>
  );
}

function Dot({ delay }: { delay: number }) {
  return (
    <span
      className="h-1.5 w-1.5 rounded-full bg-ink-3"
      style={{ animation: `pulse 1.2s ${delay}ms infinite ease-in-out` }}
    />
  );
}
