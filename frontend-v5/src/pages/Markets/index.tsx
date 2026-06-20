import { useMarketsHome } from "@/hooks/use-markets";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ErrorState } from "@/components/shared/ErrorState";
import { EmptyState } from "@/components/shared/EmptyState";
import { Markets } from "./Markets";

export default function MarketsPage() {
  const home = useMarketsHome();

  if (home.isPending) {
    return (
      <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full">
        <LoadingSkeleton variant="dashboard" />
      </div>
    );
  }

  if (home.isError) {
    return (
      <ErrorState
        title="Couldn't load the markets dashboard"
        error={home.error}
        onRetry={() => home.refetch()}
      />
    );
  }

  const d = home.data;
  const hasAnything =
    d.indices.length > 0 ||
    d.gainers.length > 0 ||
    d.losers.length > 0 ||
    d.sectors.length > 0 ||
    d.breadth.advances != null;

  if (!hasAnything) {
    return (
      <EmptyState
        title="Market data is warming up"
        description="Live indices, breadth and movers aren't available right now. This refreshes automatically."
      />
    );
  }

  return <Markets data={d} />;
}
