/** Chart styling shared by every Recharts panel, driven by the theme tokens. */
import type { ReactNode } from "react";
import { useLang } from "@/lib/i18n";
import { count, inr, monthLabel } from "@/lib/format";

export const axis = {
  stroke: "rgb(var(--line))",
  tick: { fill: "rgb(var(--muted))", fontSize: 11 },
  tickLine: false,
  axisLine: false,
} as const;

export const grid = { stroke: "rgb(var(--line))", strokeOpacity: 0.6, vertical: false } as const;

export const colors = {
  saffron: "#C55A11",
  saffronText: "rgb(var(--saffron-text))",
  info: "rgb(var(--info))",
  muted: "rgb(var(--muted))",
  faint: "rgb(var(--faint))",
  ok: "rgb(var(--ok))",
  line: "rgb(var(--line))",
};

/** Qualitative palette for categories, readable on both themes. */
export const categorical = ["#4C8DF6", "#C55A11", "#2DAA82", "#D4AF37", "#A78BFA", "#EF6F8E", "#3BC4D8", "#8FA3BF", "#F08030", "#64748B"];

interface TooltipRow {
  name?: ReactNode;
  value?: number | string;
  color?: string;
  dataKey?: string | number;
  payload?: Record<string, unknown>;
}

export function ChartTooltip({
  active,
  payload,
  label,
  money = [],
  labelFormat,
}: {
  active?: boolean;
  payload?: TooltipRow[];
  label?: string | number;
  money?: string[];
  labelFormat?: "month";
}) {
  const { lang } = useLang();
  if (!active || !payload?.length) return null;
  return (
    <div className="min-w-40 rounded-md border border-line bg-raised px-3 py-2 text-xs shadow-pop">
      {label !== undefined ? (
        <div className="mb-1.5 font-medium text-ink">
          {labelFormat === "month" ? monthLabel(String(label), lang) : label}
        </div>
      ) : null}
      {payload.map((row, i) => (
        <div key={i} className="flex items-center justify-between gap-4 py-0.5">
          <span className="flex items-center gap-1.5 text-muted">
            <span className="size-2 rounded-sm" style={{ background: row.color }} />
            {row.name}
          </span>
          <span className="num text-ink">
            {typeof row.value === "number"
              ? money.includes(String(row.dataKey))
                ? inr(row.value, lang)
                : count(row.value)
              : row.value}
          </span>
        </div>
      ))}
    </div>
  );
}
