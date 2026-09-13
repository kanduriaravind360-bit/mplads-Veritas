import { useMemo, useState } from "react";
import { Area, AreaChart, Bar, CartesianGrid, Cell, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useLang } from "@/lib/i18n";
import { useApi } from "@/lib/query";
import { count, inr, monthLabel, pct } from "@/lib/format";
import type { MonthRow } from "@/lib/types";
import { axis, categorical, ChartTooltip, colors, grid } from "@/components/charts";
import { Caveat } from "@/components/Caveat";
import { EmptyState, PageHeader, PanelSkeleton, QueryState } from "@/components/common";
import { Card, CardBody, CardHeader, Select } from "@/components/ui/primitives";

interface CategoryMix {
  categories: string[];
  months: ({ month: string } & Record<string, number | string>)[];
}
interface CostDistribution {
  work_type: string;
  states: { state: string; n: number; p10: number; p25: number; median: number; p75: number; p90: number }[];
  note: string;
}
interface Facets {
  work_types: { value: string; count: number }[];
}

export default function Trends() {
  const { t, lang } = useLang();
  const monthly = useApi<MonthRow[]>("/analytics/monthly");
  const mix = useApi<CategoryMix>("/analytics/category-mix", { top: 8 });
  const facets = useApi<Facets>("/works/facets", undefined, { staleTime: Infinity });
  const [workType, setWorkType] = useState<string>("");
  const types = [...(facets.data?.work_types ?? [])].sort((a, b) => b.count - a.count).slice(0, 25);
  const selectedType = workType || types[0]?.value || "";
  const cost = useApi<CostDistribution>(selectedType ? "/analytics/cost-distribution" : null, { work_type: selectedType, top_states: 16 });

  const marchShare = useMemo(() => {
    if (!monthly.data?.length) return null;
    const total = monthly.data.reduce((s, m) => s + m.amount, 0);
    const march = monthly.data.filter((m) => m.is_march).reduce((s, m) => s + m.amount, 0);
    const marchMonths = monthly.data.filter((m) => m.is_march).length;
    return { share: total ? march / total : 0, months: marchMonths, of: monthly.data.length };
  }, [monthly.data]);

  return (
    <div className="space-y-6">
      <PageHeader title={t("nav.trends")} subtitle={t("trends.subtitle")} />
      <Caveat />
      <Card>
        <CardHeader
          title={t("command.monthly")}
          hint={t("command.monthlyHint")}
          action={marchShare ? <span className="text-xs text-muted">{t("trends.marchShare", { share: pct(marchShare.share), months: marchShare.months, of: marchShare.of })}</span> : null}
        />
        <CardBody className="h-[320px]">
          <QueryState query={monthly} skeleton={<PanelSkeleton rows={6} />} isEmpty={(d) => !d.length}>
            {(d) => (
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={d} margin={{ left: 8, right: 8, top: 8 }}>
                  <CartesianGrid {...grid} />
                  <XAxis dataKey="month" {...axis} tickFormatter={(m: string) => monthLabel(m, lang)} interval={1} />
                  <YAxis yAxisId="amount" {...axis} tickFormatter={(v: number) => inr(v, lang)} width={72} />
                  <YAxis yAxisId="works" orientation="right" {...axis} tickFormatter={(v: number) => count(v)} width={56} />
                  <Tooltip content={<ChartTooltip money={["amount"]} labelFormat="month" />} cursor={{ fill: "rgb(var(--raised))" }} />
                  <Legend wrapperStyle={{ fontSize: 12, color: "rgb(var(--muted))" }} />
                  <Bar yAxisId="amount" dataKey="amount" name={t("common.sanctioned")} radius={[3, 3, 0, 0]} isAnimationActive={false}>
                    {d.map((m) => (
                      <Cell key={m.month} fill={m.is_march ? colors.saffron : colors.info} fillOpacity={m.is_march ? 1 : 0.7} />
                    ))}
                  </Bar>
                  <Line yAxisId="works" dataKey="works" name={t("common.worksCap")} stroke="rgb(var(--ink))" strokeOpacity={0.7} strokeWidth={1.5} dot={false} isAnimationActive={false} />
                </ComposedChart>
              </ResponsiveContainer>
            )}
          </QueryState>
        </CardBody>
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader title={t("trends.mix")} hint={t("trends.mixHint")} />
          <CardBody className="h-[420px]">
            <QueryState query={mix} skeleton={<PanelSkeleton rows={8} />} isEmpty={(d) => !d.months.length}>
              {(d) => (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={d.months} margin={{ left: 8, right: 8, top: 8 }}>
                    <CartesianGrid {...grid} />
                    <XAxis dataKey="month" {...axis} tickFormatter={(m: string) => monthLabel(m, lang)} interval={3} />
                    <YAxis {...axis} tickFormatter={(v: number) => inr(v, lang)} width={72} />
                    <Tooltip content={<ChartTooltip money={d.categories} labelFormat="month" />} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    {d.categories.map((c, i) => (
                      <Area key={c} type="monotone" dataKey={c} name={c} stackId="1" stroke={categorical[i % categorical.length]} fill={categorical[i % categorical.length]} fillOpacity={0.55} isAnimationActive={false} connectNulls />
                    ))}
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </QueryState>
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title={t("trends.cost")}
            hint={cost.data?.note}
            action={
              <Select value={selectedType} onChange={(e) => setWorkType(e.target.value)} aria-label={t("common.type")} className="w-[320px]">
                {types.map((w) => (
                  <option key={w.value} value={w.value}>{w.value} ({count(w.count)})</option>
                ))}
              </Select>
            }
          />
          <CardBody>
            {facets.data && !types.length ? <EmptyState /> : null}
            <QueryState query={cost} skeleton={facets.data && !types.length ? null : <PanelSkeleton rows={8} />} isEmpty={(d) => !d.states.length}>
              {(d) => {
                const max = Math.max(...d.states.map((s) => s.p90));
                const x = (v: number) => `${(v / max) * 100}%`;
                return (
                  <div className="space-y-1.5" data-testid="cost-distribution">
                    {d.states.map((s) => (
                      <div key={s.state} className="grid grid-cols-[10rem_1fr_5rem] items-center gap-3 text-sm">
                        <span className="truncate text-muted" title={s.state}>{s.state} <span className="num text-2xs text-faint">n={count(s.n)}</span></span>
                        <div className="relative h-5">
                          <div className="absolute inset-y-2 rounded-full bg-info/25" style={{ left: x(s.p10), width: `calc(${x(s.p90)} - ${x(s.p10)})` }} />
                          <div className="absolute inset-y-1 rounded-sm bg-info/60" style={{ left: x(s.p25), width: `calc(${x(s.p75)} - ${x(s.p25)})` }} />
                          <div className="absolute inset-y-0 w-0.5 bg-saffron" style={{ left: x(s.median) }} />
                        </div>
                        <span className="num text-right text-xs">{inr(s.median, lang)}</span>
                      </div>
                    ))}
                    <p className="pt-2 text-2xs text-faint">{t("trends.costLegend")}</p>
                  </div>
                );
              }}
            </QueryState>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
