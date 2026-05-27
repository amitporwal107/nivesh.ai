import { useParams, useNavigate } from "react-router-dom";
import { useHoldings } from "@/hooks/use-portfolio";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ErrorState } from "@/components/shared/ErrorState";
import { EmptyState } from "@/components/shared/EmptyState";
import { FundDetails } from "./FundDetails";

export default function FundDetailsPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const q = useHoldings();

  if (q.isPending) return <div className="px-6 py-8 max-w-[1080px] mx-auto"><LoadingSkeleton variant="card" /></div>;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;

  const holding = q.data?.find((h) => h.fundId === id);
  if (!holding) {
    return (
      <EmptyState
        title="Fund not found"
        description="That fund isn't in your portfolio."
        action={{ label: "Back to portfolio", onClick: () => navigate("/portfolio") }}
      />
    );
  }
  return <FundDetails holding={holding} />;
}
