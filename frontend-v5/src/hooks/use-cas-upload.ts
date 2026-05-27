/**
 * use-cas-upload — multipart CAS upload + async polling for parse status.
 *
 * Returns a unified handle: kick off upload, then poll status; surface
 * progress + final result through one shape.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { casUploadService } from "@/services";
import { usePolling } from "@/lib/polling";
import type { UploadTaskStatus } from "@/services/adapters/cas-upload.adapter";

const TERMINAL = new Set<UploadTaskStatus>(["COMPLETED", "FAILED"]);

export function useCasUpload() {
  const qc = useQueryClient();
  const taskKey = ["casUpload", "task"] as const;

  const upload = useMutation({
    mutationFn: (args: { file: File; password?: string; portfolioId?: string }) =>
      casUploadService.upload(args.file, { password: args.password, portfolioId: args.portfolioId }),
    onSuccess: (data) => qc.setQueryData(taskKey, data),
  });

  const taskId = (qc.getQueryData(taskKey) as { task_id?: string } | undefined)?.task_id;

  const polling = usePolling<{ task_id: string; status: UploadTaskStatus; progress?: number; result?: unknown; error?: string }>({
    queryKey: ["casUpload", "poll", taskId ?? ""],
    queryFn: () => casUploadService.status(taskId!),
    isTerminal: (d) => TERMINAL.has(d.status),
    intervalMs: 2_000,
    enabled: !!taskId,
  });

  return {
    upload: upload.mutate,
    isUploading: upload.isPending,
    taskId,
    status: polling.data?.status,
    progress: polling.data?.progress ?? 0,
    result: polling.data?.result,
    error: upload.error ?? polling.error ?? (polling.data?.error ? new Error(polling.data.error) : null),
  };
}

export function useLatestUploadTask() {
  return useQuery({
    queryKey: ["casUpload", "latest"],
    queryFn: () => casUploadService.latestTask(),
  });
}
