import React from "react";
import { motion } from "framer-motion";

const shimmer = "relative overflow-hidden before:absolute before:inset-0 before:-translate-x-full before:animate-[shimmer_1.5s_infinite] before:bg-gradient-to-r before:from-transparent before:via-white/40 before:to-transparent";

export const SkeletonLine = ({ className = "", width = "w-full" }) => (
  <div className={`${shimmer} h-4 rounded-lg bg-slate-200/70 dark:bg-slate-700/50 ${width} ${className}`} />
);

export const SkeletonCircle = ({ size = "w-10 h-10", className = "" }) => (
  <div className={`${shimmer} rounded-full bg-slate-200/70 dark:bg-slate-700/50 ${size} ${className}`} />
);

export const SkeletonCard = ({ className = "", lines = 3 }) => (
  <div className={`rounded-2xl border border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 ${className}`}>
    <SkeletonLine width="w-1/3" className="h-5 mb-4" />
    {Array.from({ length: lines }).map((_, i) => (
      <SkeletonLine key={`skel-line-${i}`} width={i === lines - 1 ? "w-2/3" : "w-full"} className="mb-2.5" />
    ))}
  </div>
);

export const SkeletonMetricRow = () => (
  <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
    {[1, 2, 3, 4].map((i) => (
      <div key={`skel-metric-${i}`} className="rounded-2xl border border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900 p-5">
        <SkeletonLine width="w-20" className="h-3 mb-3" />
        <SkeletonLine width="w-28" className="h-7 mb-2" />
        <SkeletonLine width="w-16" className="h-3" />
      </div>
    ))}
  </div>
);

export const SkeletonChart = ({ className = "" }) => (
  <div className={`rounded-2xl border border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 ${className}`}>
    <SkeletonLine width="w-32" className="h-5 mb-6" />
    <div className="flex items-end gap-2 h-40">
      {[40, 65, 50, 80, 60, 75, 55, 70, 85, 45, 90, 65].map((h, i) => (
        <div key={`skel-bar-${i}`} className={`${shimmer} flex-1 rounded-t-lg bg-slate-200/70 dark:bg-slate-700/50`} style={{ height: `${h}%` }} />
      ))}
    </div>
  </div>
);

export const DashboardSkeleton = () => (
  <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-6">
    <SkeletonMetricRow />
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <SkeletonChart />
      <SkeletonChart />
    </div>
    <SkeletonCard lines={5} />
  </motion.div>
);

export const ChatMessageSkeleton = () => (
  <div className="flex gap-3 justify-start animate-pulse">
    <SkeletonCircle size="w-8 h-8" />
    <div className="flex-1 max-w-[75%] space-y-2.5 py-3">
      <SkeletonLine width="w-full" />
      <SkeletonLine width="w-5/6" />
      <SkeletonLine width="w-3/4" />
    </div>
  </div>
);

export const InsightsSkeleton = () => (
  <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-4">
    {[1, 2, 3].map((i) => (
      <SkeletonCard key={`skel-insight-${i}`} lines={4} />
    ))}
  </motion.div>
);

export const PortfolioTableSkeleton = () => (
  <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-2">
    <div className="grid grid-cols-5 gap-4 px-4 py-3">
      {[1, 2, 3, 4, 5].map((i) => <SkeletonLine key={`skel-th-${i}`} width="w-20" className="h-3" />)}
    </div>
    {[1, 2, 3, 4, 5, 6].map((row) => (
      <div key={`skel-row-${row}`} className="grid grid-cols-5 gap-4 px-4 py-3 border-t border-slate-100 dark:border-slate-800">
        {[1, 2, 3, 4, 5].map((col) => <SkeletonLine key={`skel-cell-${row}-${col}`} width={col === 1 ? "w-32" : "w-16"} className="h-4" />)}
      </div>
    ))}
  </motion.div>
);
