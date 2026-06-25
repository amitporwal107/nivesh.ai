/**
 * use-chat — AI Copilot chat session + suggested prompts.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { chatService } from "@/services";
import { useImpersonationStore } from "@/stores/impersonation.store";

export function useSuggestedPrompts() {
  // Scope the cache by the active impersonation context so an advisor's
  // cross-client tiles and a client's personal tiles never bleed across a
  // context switch. Keyed off the store (which drives the X-Active-Profile
  // header) rather than me.activeProfileId, which can race the persisted-store
  // rehydration. Non-advisor users have no active profile → stable "self".
  const activeProfileId = useImpersonationStore((s) => s.profileId);
  const ctxKey = activeProfileId ?? "self";
  return useQuery({
    queryKey: ["chat", "suggestedPrompts", ctxKey],
    queryFn: () => chatService.suggestedPrompts(),
    staleTime: 5 * 60_000,                  // 5min — prompts change slowly
  });
}

export function useChatSessions() {
  return useQuery({
    queryKey: ["chat", "sessions"],
    queryFn: () => chatService.listSessions(),
  });
}

export function useChatSession(id: string) {
  return useQuery({
    queryKey: ["chat", "sessions", id],
    queryFn: () => chatService.getSession(id),
    enabled: !!id,
  });
}

export function useSendChat() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { message: string; sessionId?: string; page?: string }) =>
      chatService.send(args.message, args.sessionId, args.page),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["chat", "sessions"] });
      if (vars.sessionId) qc.invalidateQueries({ queryKey: ["chat", "sessions", vars.sessionId] });
    },
  });
}

export function useCreateChatSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (title?: string) => chatService.createSession(title),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["chat", "sessions"] }); },
  });
}

export function useDeleteChatSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => chatService.deleteSession(id),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ["chat", "sessions"] });
      qc.removeQueries({ queryKey: ["chat", "sessions", id] });
    },
  });
}
