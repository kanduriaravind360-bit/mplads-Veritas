import { useMemo, useState } from "react";
import { ResponsiveContainer, Tooltip, Treemap } from "recharts";
import { ArrowLeft, Banknote, Flame, Percent } from "lucide-react";
import { useLang } from "@/lib/i18n";
import { useApi } from "@/lib/query";
import { count, inr, ofTotal, pct } from "@/lib/format";
import type { GroupRow, Overview } from "@/lib/types";
import { Caveat } from "@/components/Caveat";
import { KpiCard, LowVolume, Money, PageHeader, PanelSkeleton, QueryState } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, Segmented } from "@/components/ui/primitives";

type By = "state" | "work_type";
interface MoneyResponse {
  by: string;
  total_money_at_risk: number;
  total_sanctioned: number;
  rows: GroupRow[];
  note: string;
}

// Sequential saffron-to-red scale on the share of a group's value that is at risk.
function shareColour(share: number): string {
  const stops = ["#27466B", "#6D6A5E", "#B8732F", "#D9622B", "#D63C3C"];
  const i = Math.min(stops.length - 1, Math.floor(Math.min(share, 0.6) / 0.15));
  return stops[i] ?? stops[0]!;
}

interface Cell {
  name: string;
  value: number;
  share: number;
  works: number;
  sanctioned: number;
  high: number;
  lowVolume: boolean;
}

function TreeCell(props: { x?: number; y?: number; width?: number; height?: number; name?: string; share?: number; value?: number; depth?: number }) {
  const { x = 0, y = 0, width = 0, height = 0, name = "", share = 0, value = 0, depth = 1 } = props;
  const { lang } = useLang();
  if (depth === 0) return null;
  return (
    <g>
      <rect x={x} y={y} width={width} height={height} rx={4} fill={shareColour(share)} stroke="rgb(var(--surface))" strokeWidth={2} />
      {width > 70 && height > 34 ? (
        <>
          <text x={x + 8} y={y + 18} className="fill-white text-[12px] font-medium">{name.length > width / 7 ? `${name.slice(0, Math.floor(width / 7) - 1)}…` : name}</text>
          <text x={x + 8} y={y + 34} className="fill-white/80 text-[11px]">{inr(value, lang)} · {pct(share, 0)}</text>
        </>
      ) : null}
    </g>
  );
}

export default function MoneyAtRisk() {
  const { t, lang } = useLang();
  const [by, setBy] = useState<By>("state");
  const [state, setState] = useState<string | null>(null);
  const top = useApi<MoneyResponse>("/analytics/money-at-risk", { by, limit: 40 });
  const districts = useApi<MoneyResponse>(state ? "/analytics/money-at-risk" : null, { by: "district", limit: 500 });
  const overview = useApi<Overview>("/overview");

  const source = state ? districts : top;
  const rows = useMemo(() => {
    const all = source.data?.rows ?? [];
    return (state ? all.filter((r) => r.state === state) : all).filter((r) => r.money_at_risk > 0);
  }, [source.data, state]);
  const cells: Cell[] = rows.map((r) => ({
    name: r.key,
    value: r.money_at_risk,
    share: r.sanctioned ? r.money_at_risk / r.sanctioned : 0,
    works: r.works,
    sanctioned: r.sanctioned,
    high: r.high_or_critical,
    lowVolume: r.low_volume,
  }));
  const totals = top.data;

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("money.title")}
        subtitle={top.data?.note ?? t("money.subtitle")}
        actions={
          state ? (
            <Button variant="outline" size="sm" onClick={() => setState(null)}><ArrowLeft /> {t("money.back")}</Button>
          ) : (
            <Segmented size="sm" label={t("money.by")} value={by} onChange={setBy} options={[{ value: "state", label: t("common.state") }, { value: "work_type", label: t("common.type") }]} />
          )
        }
      />
      <Caveat />
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {totals ? (
          <>
            <KpiCard label={t("common.moneyAtRisk")} value={totals.total_money_at_risk} kind="money" icon={<Banknote className="size-4" />} />
            <KpiCard label={t("money.share")} value={totals.total_sanctioned ? totals.total_money_at_risk / totals.total_sanctioned : 0} kind="percent" icon={<Percent className="size-4" />} sub={`${inr(totals.total_money_at_risk, lang)} ${t("common.of")} ${inr(totals.total_sanctioned, lang)}`} />
            {overview.data ? (
              <KpiCard label={t("common.highOrCritical")} value={overview.data.kpis.high_or_critical} icon={<Flame className="size-4" />} sub={ofTotal(overview.data.kpis.high_or_critical, overview.data.kpis.works, lang)} />
            ) : (
              <Card className="h-[132px]"><PanelSkeleton rows={2} /></Card>
            )}
          </>
        ) : (
          [0, 1, 2].map((i) => <Card key={i} className="h-[132px]"><PanelSkeleton rows={2} /></Card>)
        )}
      </div>

      <div className="grid gap-4 xl:grid-cols-12">
        <Card className="xl:col-span-8">
          <CardHeader title={state ? t("money.districtsOf", { state }) : by === "state" ? t("money.byState") : t("money.byType")} hint={t("money.treemapHint")} />
          <CardBody>
            <QueryState query={source} skeleton={<PanelSkeleton rows={10} />} isEmpty={() => !cells.length}>
              {() => (
                <div className="h-[560px]" data-testid="money-treemap">
                  <ResponsiveContainer width="100%" height="100%">
                    <Treemap
                      data={cells}
                      dataKey="value"
                      nameKey="name"
                      isAnimationActive={false}
                      content={<TreeCell />}
                      onClick={(node: { name?: string }) => {
                        if (!state && by === "state" && node?.name) setState(node.name);
                      }}
                    >
                      <Tooltip
                        content={({ payload }) => {
                          const cell = payload?.[0]?.payload as Cell | undefined;
                          if (!cell) return null;
                          return (
                            <div className="rounded-md border border-line bg-raised px-3 py-2 text-xs shadow-pop">
                              <div className="font-semibold">{cell.name}</div>
                              <div className="num mt-1">{t("common.moneyAtRisk")}: {inr(cell.value, lang)} ({pct(cell.share)} {t("common.of")} {inr(cell.sanctioned, lang)})</div>
                              <div className="num">{t("common.highOrCritical")}: {ofTotal(cell.high, cell.works, lang)}</div>
                              {!state && by === "state" ? <div className="mt-1 text-muted">{t("money.clickHint")}</div> : null}
                            </div>
                          );
                        }}
                      />
                    </Treemap>
                  </ResponsiveContainer>
                </div>
              )}
            </QueryState>
            <div className="mt-3 flex items-center gap-2 text-2xs text-muted">
              <span>{t("money.legendLow")}</span>
              {[0, 0.15, 0.3, 0.45, 0.6].map((s) => <span key={s} className="h-3 w-8 rounded-sm" style={{ background: shareColour(s) }} />)}
              <span>{t("money.legendHigh")}</span>
            </div>
          </CardBody>
        </Card>
        <Card className="xl:col-span-4">
          <CardHeader title={t("money.table")} />
          <CardBody className="max-h-[640px] overflow-y-auto px-0 pb-2">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-surface">
                <tr className="border-b border-line text-left text-2xs uppercase tracking-wider text-muted">
                  <th className="px-5 pb-2 font-medium">{by === "work_type" && !state ? t("common.type") : state ? t("common.district") : t("common.state")}</th>
                  <th className="px-3 pb-2 text-right font-medium">{t("common.moneyAtRisk")}</th>
                  <th className="px-5 pb-2 text-right font-medium">{t("common.highOrCritical")}</th>
                </tr>
              </thead>
              <tbody>
                {[...rows].sort((a, b) => b.money_at_risk - a.money_at_risk).map((r) => (
                  <tr key={`${r.key}-${r.state}`} className="border-b border-line/50 last:border-0">
                    <td className="px-5 py-2">
                      <button type="button" className="text-left font-medium hover:text-saffron-text disabled:hover:text-ink" disabled={!!state || by !== "state"} onClick={() => setState(r.key)}>
                        {r.key}
                      </button>
                      {r.low_volume ? <span className="ml-2"><LowVolume /></span> : null}
                    </td>
                    <td className="px-3 py-2 text-right"><Money value={r.money_at_risk} /><div className="num text-2xs text-muted">{pct(r.sanctioned ? r.money_at_risk / r.sanctioned : 0)}</div></td>
                    <td className="num px-5 py-2 text-right text-xs">{count(r.high_or_critical)} / {count(r.works)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
