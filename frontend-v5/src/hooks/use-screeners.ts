// Saved stock-screener CRUD hooks (per user) — backed by /api/screeners.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";
import { http } from "@/services/api/http";

export const ScreenerConditionC = z.object({
  key: z.string(),
  op: z.string().default("over"),
  value: z.string().default(""),
});
export const SavedScreenerC = z.object({
  screener_id: z.string(),
  name: z.string(),
  query: z.string(),
  conditions: z.array(ScreenerConditionC).default([]),
  bucket: z.string().default(""),
  created_at: z.string().optional(),
  updated_at: z.string().optional(),
}).passthrough();
export type SavedScreener = z.infer<typeof SavedScreenerC>;

export type ScreenerInput = {
  name: string;
  query: string;
  conditions?: { key: string; op: string; value: string }[];
  bucket?: string;
};

const KEY = ["screeners"];

export function useScreeners() {
  return useQuery({
    queryKey: KEY,
    queryFn: async () => {
      const res = await http({ path: "/api/screeners" });
      return z.array(SavedScreenerC).parse(res.data);
    },
  });
}

export function useCreateScreener() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: ScreenerInput) => {
      const res = await http({ method: "POST", path: "/api/screeners", body });
      return SavedScreenerC.parse(res.data);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useUpdateScreener() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, body }: { id: string; body: Partial<ScreenerInput> }) => {
      const res = await http({ method: "PUT", path: `/api/screeners/${id}`, body });
      return SavedScreenerC.parse(res.data);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useDeleteScreener() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      await http({ method: "DELETE", path: `/api/screeners/${id}` });
      return id;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}
