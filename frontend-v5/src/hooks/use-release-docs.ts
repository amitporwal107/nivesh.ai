/**
 * Hooks for Settings → Release Management (admin-only).
 *
 * Thin react-query wrappers over releaseDocsService (release-docs.adapter):
 * list / get / templates / revisions (queries) and create / update (mutations).
 * Mutations invalidate the relevant caches so the list + detail + revision
 * history stay in sync after a save.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { releaseDocsService } from "@/services";
import type {
  CreateReleaseDocInput,
  UpdateReleaseDocInput,
  DocType,
  DocStatus,
} from "@/services";

export function useReleaseDocs(params?: { doc_type?: DocType; status?: DocStatus }) {
  return useQuery({
    queryKey: ["release-docs", params ?? {}],
    queryFn: () => releaseDocsService.list(params),
  });
}

export function useReleaseDoc(id: string | undefined) {
  return useQuery({
    queryKey: ["release-doc", id],
    queryFn: () => releaseDocsService.get(id as string),
    enabled: Boolean(id),
  });
}

export function useReleaseTemplates() {
  return useQuery({
    queryKey: ["release-doc-templates"],
    queryFn: () => releaseDocsService.templates(),
    staleTime: 5 * 60 * 1000,
  });
}

export function useReleaseDocRevisions(id: string | undefined) {
  return useQuery({
    queryKey: ["release-doc-revisions", id],
    queryFn: () => releaseDocsService.revisions(id as string),
    enabled: Boolean(id),
  });
}

export function useCreateReleaseDoc() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateReleaseDocInput) => releaseDocsService.create(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["release-docs"] }),
  });
}

export function useUpdateReleaseDoc(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: UpdateReleaseDocInput) => releaseDocsService.update(id, input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["release-docs"] });
      qc.invalidateQueries({ queryKey: ["release-doc", id] });
      qc.invalidateQueries({ queryKey: ["release-doc-revisions", id] });
    },
  });
}
