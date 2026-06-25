import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { http } from "@/services/api/http";

export interface GmailStatus {
  connected: boolean;
  connected_at?: string;
  auto_import_enabled: boolean;
  auto_import_ready: boolean;
  last_auto_import_at?: string;
  last_import?: {
    filename: string;
    imported_at: string;
    count: number;
  } | null;
}

export function useGmailStatus() {
  return useQuery<GmailStatus>({
    queryKey: ["gmail", "status"],
    queryFn: async () => {
      const res = await http<GmailStatus>({ path: "/api/gmail/status" });
      return res.data;
    },
    staleTime: 30_000,
  });
}

export function useGmailAutoImportToggle() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (enabled: boolean) => {
      const res = await http<{ auto_import_enabled: boolean }>({
        method: "POST",
        path: "/api/gmail/auto-import/toggle",
        body: { enabled },
      });
      return res.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["gmail", "status"] });
    },
  });
}

export function useGmailConnect() {
  return useMutation({
    mutationFn: async () => {
      const res = await http<{ auth_url: string }>({
        path: "/api/gmail/connect",
        query: { return_to: "/settings" },
      });
      window.location.href = res.data.auth_url;
    },
  });
}

export function useGmailDisconnect() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      await http({ method: "POST", path: "/api/gmail/disconnect" });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["gmail", "status"] });
    },
  });
}
