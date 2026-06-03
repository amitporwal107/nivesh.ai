import { useRisk } from "@/hooks/use-analytics";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ErrorState } from "@/components/shared/ErrorState";
import { Risk } from "./Risk";

export default function RiskPage() {
  const q = useRisk();
  if (q.isPending) {
    return (
      <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full">
        <LoadingSkeleton variant="dashboard" />
      </div>
    );
  }
  if (q.isError) {
    return <ErrorState onRetry={() => q.refetch()} error={q.error} />;
  }
  return <Risk data={q.data!} />;
}
