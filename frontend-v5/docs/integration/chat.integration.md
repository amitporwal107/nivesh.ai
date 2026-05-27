# Chat — API integration

## Endpoints

| Hook | Endpoint |
|---|---|
| `useSuggestedPrompts()` | `GET /api/copilot/suggested-prompts` |
| `useChatSessions()` | `GET /api/chat/sessions` |
| `useCreateChatSession()` | `POST /api/chat/sessions` |
| `useChatSession(id)` | `GET /api/chat/sessions/{id}` |
| `useSendChat()` | `POST /api/chat { message, session_id? }` |

## Behaviour

Session is **lazily created** on the user's first send. Sequence:

1. User types question, hits Enter / Send.
2. If no `sessionId` in component state → `createSession()` returns one.
3. `send({ message, sessionId })` → assistant reply.
4. Both `["chat","sessions"]` and `["chat","sessions",id]` query keys invalidate → UI repaints with full thread.

## Empty / loading / streaming states

- Empty thread (post-session-creation, before first reply): centered intro card with `Badge tone="accent"` "Ready".
- Pending send: animated three-dot "typing" indicator (Tailwind pulse).
- Prompt chips load via `useSuggestedPrompts()`; fallback to a hardcoded list if backend returns empty.

## Not yet wired

- **Streaming.** Backend supports `text/event-stream` per the chat tag description; current implementation is single-round JSON. To switch, replace `chatService.send()` with an `EventSource` reader and stream tokens into the assistant bubble.
- **Session list sidebar.** `useChatSessions()` is wired but unused in the current single-thread UI.
