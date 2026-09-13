import { useState } from "react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AlarmClock, Hourglass, PiggyBank, Timer } from "lucide-react";
import { useLang } from "@/lib/i18n";
import { useApi } from "@/lib/query";
import { count, date, inr, ofTotal, pct } from "@/lib/format";
import type { Page, WorkSummary } from "@/lib/types";
import { bandColor } from "@/lib/utils";
import { axis, ChartTooltip, colors, grid } from "@/components/charts";
import { Caveat } from "@/components/Caveat";
import { EstimateTag, KpiCard, LowVolume, Money, PageHeader, PanelSkeleton, QueryState } from "@/components/common";
import { featureLabel } from "@/components/evidence";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardBody, CardHeader, Segmented } from "@/components/ui/primitives";

interface DelayRow extends WorkSummary {
  delay_drivers: [string, number][];
  delay_reason_en: string | null;
}
interface DelayPage extends Page<DelayRow> {
  summary: { open_works: number; high_delay_risk_works: number; high_delay_risk_value: number; threshold: number };
  note: string;
}
interface Lapse {
  rows: { district: string; state: string; open_works: number; undisbursed: number; expected_unspent: number; high_delay_risk_works: number; low_volume: boolean }[];
  total_expected_unspent: number;
  estimate: boolean;
  note: string;
}

const PAGE = 25;

export default function Delays() {
  const { t, lang } = useLang();
  const [minProbability, setMinProbability] = useState("0");
  const [offset, setOffset] = useState(0);
  const delays = useApi<DelayPage>("/predictions/delay", { min_probability: minProbability, limit: PAGE, offset });
  const lapse = useApi<Lapse>("/predictions/fund-lapse", { limit: 15 });
  const s = delays.data?.summary;

  return (
    <div className="space-y-6">
      <PageHeader title={t("nav.delays")} subtitle={delays.data?.note ?? t("delays.subtitle")} />
      <Caveat />
      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        {s ? (
          <>
            <KpiCard label={t("delays.open")} value={s.open_works} icon={<Hourglass className="size-4" />} />
            <KpiCard label={t("delays.high", { threshold: pct(s.threshold, 0) })} value={s.high_delay_risk_works} accent={bandColor("High")} icon={<AlarmClock className="size-4" />} sub={ofTotal(s.high_delay_risk_works, s.open_works, lang)} />
            <KpiCard label={t("delays.highValue")} value={s.high_delay_risk_value} kind="money" icon={<Timer className="size-4" />} />
          </>
        ) : (
          [0, 1, 2].map((i) => <Card key={i} className="h-[132px]"><PanelSkeleton rows={2} /></Card>)
        )}
        {lapse.data ? (
          <KpiCard label={t("delays.lapse")} value={lapse.data.total_expected_unspent} kind="money" icon={<PiggyBank className="size-4" />} sub={<EstimateTag />} hint={t("delays.lapseHint")} />
        ) : (
          <Card className="h-[132px]"><PanelSkeleton rows={2} /></Card>
        )}
      </div>

      <div className="grid gap-4 xl:grid-cols-12">
        <Card className="min-w-0 xl:col-span-7">
          <CardHeader
            title={t("delays.queue")}
            hint={t("delays.queueHint")}
            action={<Segmented size="sm" label={t("delays.queue")} value={minProbability} onChange={(v) => { setMinProbability(v); setOffset(0); }} options={[{ value: "0", label: t("common.all") }, { value: "0.7", label: "≥ 70%" }, { value: "0.9", label: "≥ 90%" }]} />}
          />
          <CardBody className="px-0 pb-0">
            <QueryState query={delays} skeleton={<PanelSkeleton rows={10} />} isEmpty={(d) => !d.items.length}>
              {(d) => (
                <>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm" data-testid="delay-table">
                      <thead>
                        <tr className="border-b border-line text-left text-2xs uppercase tracking-wider text-muted">
                          <th className="px-5 pb-2 font-medium">Work</th>
                          <th className="px-3 pb-2 font-medium">{t("delays.stage")}</th>
                          <th className="px-3 pb-2 text-right font-medium">{t("common.sanctioned")}</th>
                          <th className="w-44 px-5 pb-2 font-medium">{t("common.delayRisk")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {d.items.map((w) => (
                          <tr key={w.work_id} className="border-b border-line/50 align-top hover:bg-raised/30">
                            <td className="max-w-[360px] px-5 py-2.5">
                              <Link to={`/works/${w.work_id}`} className="line-clamp-1 font-medium hover:text-saffron-text">{w.work_description}</Link>
                              <div className="text-2xs text-muted">{w.district}, {w.state} · <span className="font-mono">{w.work_id}</span></div>
                              <div className="mt-1 flex flex-wrap gap-1">
                                {w.delay_drivers.slice(0, 3).map(([feature, v]) => (
                                  <Badge key={feature} tone={v > 0 ? "warn" : "outline"}>{featureLabel(feature)} {v > 0 ? "↑" : "↓"}</Badge>
                                ))}
                              </div>
                            </td>
                            <td className="px-3 py-2.5 text-xs text-muted">
                              {w.work_status}
                              <div className="text-2xs text-faint">{t("work.sanctionedOn")} {date(w.sanction_date, lang)}</div>
                            </td>
                            <td className="px-3 py-2.5 text-right"><Money value={w.sanction_amount} /></td>
                            <td className="px-5 py-2.5">
                              <div className="flex items-center gap-2">
                                <div className="h-2 flex-1 overflow-hidden rounded-full bg-raised">
                                  <div className="h-full rounded-full" style={{ width: pct(w.delay_risk, 0), background: w.delay_risk >= d.summary.threshold ? bandColor("High") : colors.info }} />
                                </div>
                                <span className="num w-10 text-right text-xs">{pct(w.delay_risk, 0)}</span>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div className="flex items-center justify-between px-5 py-2 text-xs text-muted">
                    <span className="num">{t("common.showing", { from: count(d.total ? offset + 1 : 0), to: count(Math.min(offset + PAGE, d.total)), total: count(d.total) })}</span>
                    <span>
                      <Button variant="ghost" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>{t("common.previous")}</Button>
                      <Button variant="ghost" size="sm" disabled={offset + PAGE >= d.total} onClick={() => setOffset(offset + PAGE)}>{t("common.next")}</Button>
                    </span>
                  </div>
                </>
              )}
            </QueryState>
          </CardBody>
        </Card>

        <Card className="min-w-0 xl:col-span-5">
          <CardHeader title={<span className="flex items-center gap-2">{t("delays.lapseChart")} <EstimateTag /></span>} hint={lapse.data?.note} />
          <CardBody>
            <QueryState query={lapse} isEmpty={(d) => !d.rows.length}>
              {(d) => (
                <>
                  <div className="h-[520px]" data-testid="lapse-chart">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart layout="vertical" data={d.rows} margin={{ left: 8, right: 16 }} barGap={2}>
                        <CartesianGrid {...grid} horizontal={false} vertical />
                        <XAxis type="number" {...axis} tickFormatter={(v: number) => inr(v, lang)} />
                        <YAxis type="category" dataKey="district" {...axis} width={128} tick={{ ...axis.tick, fontSize: 10 }} />
                        <Tooltip content={<ChartTooltip money={["undisbursed", "expected_unspent"]} />} cursor={{ fill: "rgb(var(--raised))" }} />
                        <Bar dataKey="undisbursed" name={t("delays.undisbursed")} fill={colors.info} fillOpacity={0.35} radius={[0, 3, 3, 0]} isAnimationActive={false} />
                        <Bar dataKey="expected_unspent" name={t("delays.expectedUnspent")} fill={colors.saffron} radius={[0, 3, 3, 0]} isAnimationActive={false} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                  <ul className="mt-2 flex flex-wrap gap-2 text-2xs text-muted">
                    {d.rows.filter((r) => r.low_volume).map((r) => (
                      <li key={r.district} className="flex items-center gap-1">{r.district} <LowVolume /></li>
                    ))}
                  </ul>
                </>
              )}
            </QueryState>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
