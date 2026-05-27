import { Treemap, ResponsiveContainer, Tooltip } from "recharts";

interface SectorDatum {
  name: string;
  size: number;
  over?: boolean;
}

interface Props {
  data: SectorDatum[];
  height?: number;
}

/**
 * Sector exposure treemap. Boxes scale by allocation %; sectors over the
 * policy cap render in the accent color, others in muted neutral.
 */
export function SectorTreemap({ data, height = 320 }: Props) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <Treemap
        data={data}
        dataKey="size"
        stroke="rgb(var(--surface-1))"
        isAnimationActive={false}
        content={<TreemapCell />}
      >
        <Tooltip
          contentStyle={{
            background: "rgb(var(--surface-1))",
            border: "1px solid rgb(var(--line) / 0.16)",
            borderRadius: 10,
            color: "rgb(var(--ink))",
            fontSize: 12,
          }}
          formatter={(v: number) => [`${v}%`, "Sector"]}
        />
      </Treemap>
    </ResponsiveContainer>
  );
}

function TreemapCell(props: any) {
  const { x, y, width, height, name, size, over } = props;
  if (width < 2 || height < 2) return null;
  const fill = over ? "rgb(var(--accent))" : "#7A8298";
  const opacity = over ? 0.9 : 0.55;
  return (
    <g>
      <rect x={x} y={y} width={width} height={height} fill={fill} fillOpacity={opacity} stroke="rgb(var(--surface-1))" strokeWidth={3} />
      {width > 80 && height > 50 && (
        <>
          <text x={x + 12} y={y + 22} fontFamily="var(--font-sans)" fontWeight={500} fontSize={13} fill="#FFFFFF">
            {name}
          </text>
          <text x={x + 12} y={y + 42} fontFamily="var(--font-display)" fontSize={22} letterSpacing="-0.02em" fill="#FFFFFF">
            {size}%
          </text>
        </>
      )}
    </g>
  );
}
