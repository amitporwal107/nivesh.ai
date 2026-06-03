/**
 * use-chat — AI Copilot chat session + suggested prompts.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { chatService } from "@/services";

export function useSuggestedPrompts() {
  return useQuery({
    queryKey: ["chat", "suggestedPrompts"],
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
    mutationFn: (args: { message: string; sessionId?: string }) =>
      chatService.send(args.message, args.sessionId),
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
