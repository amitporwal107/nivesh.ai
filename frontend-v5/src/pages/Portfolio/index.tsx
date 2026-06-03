import { useNavigate } from "react-router-dom";
import { usePortfolioSummary, useHoldings } from "@/hooks/use-portfolio";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ErrorState } from "@/components/shared/ErrorState";
import { EmptyState } from "@/components/shared/EmptyState";
import { Portfolio } from "./Portfolio";

export default function PortfolioPage() {
  const navigate = useNavigate();
  const summary = usePortfolioSummary();
  const holdings = useHoldings();

  if (summary.isPending || holdings.isPending) {
    return (
      <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full">
        <LoadingSkeleton variant="list" />
      </div>
    );
  }

  if (summary.isError || holdings.isError) {
    return (
      <ErrorState
        title="Couldn't load your portfolio"
        error={summary.error ?? holdings.error}
        onRetry={() => { summary.refetch(); holdings.refetch(); }}
      />
    );
  }

  if (!holdings.data?.length) {
    return (
      <EmptyState
        title="No holdings yet"
        description="Upload a CAS PDF, broker statement, or CSV to populate your portfolio."
        action={{ label: "Connect investments", onClick: () => navigate("/onboarding") }}
      />
    );
  }

  return <Portfolio summary={summary.data!} holdings={holdings.data} />;
}
