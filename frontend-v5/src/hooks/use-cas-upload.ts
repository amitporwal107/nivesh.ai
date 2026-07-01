/**
 * use-cas-upload — CAS PDF upload against the in-house server-side parser.
 *
 * The parser is synchronous (/api/onboarding/upload-cas returns the imported
 * holdings summary in its response), so there is no task to poll: status,
 * progress and result are derived directly from the upload mutation.
 */
import { useMutation, useQuery } from "@tanstack/react-query";
import { casUploadService } from "@/services";
import type { UploadTaskStatus, CasUploadResult } from "@/services/adapters/cas-upload.adapter";

export function useCasUpload() {
  const upload = useMutation({
    mutationFn: (args: { file: File; password?: string; portfolioId?: string }) =>
      casUploadService.upload(args.file, { password: args.password, portfolioId: args.portfolioId }),
  });

  const status: UploadTaskStatus | undefined =
    upload.isPending ? "PROCESSING"
    : upload.isSuccess ? "COMPLETED"
    : upload.isError ? "FAILED"
    : undefined;

  return {
    upload: upload.mutate,
    isUploading: upload.isPending,
    /** true once an upload has started (replaces the old task-id gate). */
    started: upload.isPending || upload.isSuccess || upload.isError,
    status,
    progress: upload.isPending ? 50 : upload.isSuccess ? 100 : 0,
    result: (upload.data ?? undefined) as CasUploadResult | undefined,
    error: upload.error ?? null,
  };
}

export function useLatestUploadTask() {
  return useQuery({
    queryKey: ["casUpload", "latest"],
    queryFn: () => casUploadService.latestTask(),
  });
}
