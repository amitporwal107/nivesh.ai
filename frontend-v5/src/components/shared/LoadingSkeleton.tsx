import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

interface LoadingSkeletonProps {
  variant?: "dashboard" | "list" | "card";
  className?: string;
}

/** Page-level skeleton shapes. Match the real component dimensions roughly. */
export function LoadingSkeleton({ variant = "card", className }: LoadingSkeletonProps) {
  if (variant === "dashboard") {
    return (
      <div className={cn("space-y-5", className)}>
        <div className="space-y-2">
          <Skeleton className="h-3 w-32" />
          <Skeleton className="h-9 w-2/3 max-w-md" />
        </div>
        <Card className="p-7">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 items-center">
            <div className="space-y-3">
              <Skeleton className="h-3 w-24" />
              <Skeleton className="h-12 w-48" />
              <Skeleton className="h-3 w-32" />
            </div>
            <div className="flex justify-center"><Skeleton className="h-40 w-40 rounded-full" /></div>
            <div className="space-y-3">
              <Skeleton className="h-3 w-20" />
              <Skeleton className="h-8 w-32" />
              <Skeleton className="h-2 w-full" />
            </div>
          </div>
        </Card>
        <div className="grid gap-3">
          {[0, 1, 2].map((i) => (
            <Card key={i} className="p-5">
              <div className="flex gap-4">
                <Skeleton className="h-10 w-10" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-5 w-3/4 max-w-md" />
                  <Skeleton className="h-3 w-full max-w-lg" />
                  <Skeleton className="h-3 w-1/2 max-w-sm" />
                </div>
              </div>
            </Card>
          ))}
        </div>
      </div>
    );
  }
  if (variant === "list") {
    return (
      <div className={cn("space-y-3", className)}>
        {[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-14" />)}
      </div>
    );
  }
  return <Skeleton className={cn("h-32 w-full", className)} />;
}
