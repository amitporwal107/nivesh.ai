/**
 * The block registry: one component per block type of `visual-answer-v1`. A type missing here renders the
 * "not supported yet" note (VisualAnswer), never a crash.
 */
import type { ComponentType } from "react";
import type { BlockType, KnownBlock } from "../schema";
import { BarsView } from "./Bars";
import { CandlesView } from "./Candles";
import type { BlockProps } from "./common";
import { HeatmapView } from "./Heatmap";
import { KpisView } from "./Kpis";
import { QuadrantView } from "./Quadrant";
import { RankedView } from "./Ranked";
import { ListView, NoticeView, TradePlanView } from "./Simple";

export const BLOCK_VIEWS: Record<BlockType, ComponentType<BlockProps<never>>> = {
  kpis: KpisView,
  candles: CandlesView,
  bars: BarsView,
  heatmap: HeatmapView,
  quadrant: QuadrantView,
  ranked: RankedView,
  trade_plan: TradePlanView,
  list: ListView,
  notice: NoticeView,
} as Record<BlockType, ComponentType<BlockProps<never>>>;

export function BlockView({ block, compact, ask }: { block: KnownBlock; compact: boolean; ask?: (q: string) => void }) {
  const View = BLOCK_VIEWS[block.type] as ComponentType<BlockProps<KnownBlock>>;
  return <View b={block} compact={compact} ask={ask} />;
}
