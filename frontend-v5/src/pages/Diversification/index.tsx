import { useConcentration } from "@/hooks/use-analytics";
import { useCorrelation, useOverlap } from "@/hooks/use-analytics";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ErrorState } from "@/components/shared/ErrorState";
import { Diversification } from "./Diversification";

export default function DiversificationPage() {
  const corr = useCorrelation();
  const overlap = useOverlap();
  const conc = useConcentration();

  if (corr.isPending || overlap.isPending || conc.isPending) {
    return (
      <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full">
        <LoadingSkeleton variant="dashboard" />
      </div>
    );
  }
  if (corr.isError || overlap.isError || conc.isError) {
    return <ErrorState onRetry={() => { corr.refetch(); overlap.refetch(); conc.refetch(); }} />;
  }
  return <Diversification correlation={corr.data!} overlap={overlap.data!} />;
}
