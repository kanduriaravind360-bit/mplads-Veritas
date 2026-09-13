import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ArrowUpRight, Banknote, CheckCircle2, FileStack, Flame, IndianRupee, Wallet } from "lucide-react";
import { useLang } from "@/lib/i18n";
import { useApi } from "@/lib/query";
import { count, date, dateTime, inr, monthLabel, ofTotal, pct } from "@/lib/format";
import type { AlertsSummary, Overview, MonthRow } from "@/lib/types";
import { alertTypeLabel, BAND_ORDER, bandColor } from "@/lib/utils";
import { axis, ChartTooltip, colors, grid } from "@/components/charts";
import { Caveat } from "@/components/Caveat";
import { EstimateTag, KpiCard, LowVolume, Money, PageHeader, PanelSkeleton, QueryState } from "@/components/common";
import { Badge, Card, CardBody, CardHeader, Skeleton } from "@/components/ui/primitives";
import { Button } from "@/components/ui/button";

export default function CommandCentre() {
  const { t, lang } = useLang();
  const overview = useApi<Overview>("/overview");
  const monthly = useApi<MonthRow[]>("/overview/monthly");
  const alertSummary = useApi<AlertsSummary>("/alerts/summary");
  const data = overview.data;

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("command.title")}
        subtitle={data ? t("command.subtitle", { scope: data.scope }) : <Skeleton className="h-4 w-64" />}
        actions={
          data ? (
            <Badge tone="outline" className="px-3 py-1 text-xs">
              {t("common.dataCutoff")} {date(data.what_changed.data_cutoff, lang)}
            </Badge>
          ) : null
        }
      />
      <Caveat framing={data?.framing} />

      <QueryState
        query={overview}
        skeleton={
          <div className="grid grid-cols-2 gap-4 xl:grid-cols-6">
            {Array.from({ length: 6 }, (_, i) => (
              <Card key={i} className="h-[132px] p-5">
                <Skeleton className="h-3 w-24" />
                <Skeleton className="mt-4 h-8 w-32" />
              </Card>
            ))}
          </div>
        }
      >
        {(d) => (
          <>
            <div className="grid grid-cols-2 gap-4 xl:grid-cols-6" data-testid="kpis">
              <KpiCard label={t("command.kpiWorks")} value={d.kpis.works} icon={<FileStack className="size-4" />} sub={t("command.worksSub", { districts: count(d.kpis.districts), mps: count(d.kpis.mps) })} />
              <KpiCard label={t("command.kpiSanctioned")} value={d.kpis.sanctioned} kind="money" icon={<IndianRupee className="size-4" />} />
              <KpiCard label={t("command.kpiDisbursed")} value={d.kpis.disbursed} kind="money" icon={<Wallet className="size-4" />} sub={`${pct(d.kpis.utilisation)} ${t("common.utilisation").toLowerCase()}`} />
              <KpiCard label={t("command.kpiCompletion")} value={d.kpis.completion_rate} kind="percent" icon={<CheckCircle2 className="size-4" />} sub={ofTotal(d.kpis.completed, d.kpis.works, lang)} />
              <KpiCard label={t("command.kpiHigh")} value={d.kpis.high_or_critical} icon={<Flame className="size-4" />} accent={bandColor("High")} sub={ofTotal(d.kpis.high_or_critical, d.kpis.works, lang)} />
              <KpiCard label={t("command.kpiMoney")} value={d.kpis.money_at_risk} kind="money" icon={<Banknote className="size-4" />} accent={bandColor("Critical")} sub={t("command.ofSanctioned", { share: pct(d.kpis.money_at_risk_share) })} hint={t("command.moneyHint")} />
            </div>

            <div className="grid gap-4 xl:grid-cols-12">
              <Card className="xl:col-span-5">
                <CardHeader title={t("command.fundFlow")} hint={t("command.fundFlowHint")} />
                <CardBody className="space-y-4">
                  {d.fund_flow.map((stage) => {
                    const max = Math.max(...d.fund_flow.map((s) => s.amount));
                    return (
                      <div key={stage.stage}>
                        <div className="mb-1.5 flex items-center justify-between text-sm">
                          <span className="flex items-center gap-2 text-muted">
                            {({ Sanctioned: t("common.sanctioned"), Disbursed: t("common.disbursed") } as Record<string, string>)[stage.stage] ?? (stage.estimate ? t("command.entitlement") : stage.stage)}{" "}
                            {stage.estimate ? <EstimateTag /> : null}
                          </span>
                          <Money value={stage.amount} className="font-semibold text-ink" />
                        </div>
                        <div className="h-3 overflow-hidden rounded-full bg-raised">
                          <div
                            className="h-full rounded-full"
                            style={{
                              width: `${(stage.amount / max) * 100}%`,
                              background: stage.estimate
                                ? "repeating-linear-gradient(135deg, rgb(var(--faint) / .55) 0 6px, rgb(var(--faint) / .25) 6px 12px)"
                                : stage.stage === "Sanctioned"
                                  ? colors.info
                                  : colors.saffron,
                            }}
                          />
                        </div>
                        {stage.note ? <p className="mt-1 text-2xs text-faint">{stage.note}</p> : null}
                      </div>
                    );
                  })}
                </CardBody>
              </Card>

              <Card className="xl:col-span-4">
                <CardHeader title={t("command.bands")} hint={t("command.bandsHint")} />
                <CardBody>
                  <BandStack bands={d.bands} total={d.kpis.works} />
                </CardBody>
              </Card>

              <Card className="xl:col-span-3">
                <CardHeader
                  title={t("command.alerts")}
                  action={
                    <Button asChild variant="link" size="sm">
                      <Link to="/alerts">
                        {t("common.viewAll")} <ArrowUpRight />
                      </Link>
                    </Button>
                  }
                />
                <CardBody className="space-y-3">
                  {alertSummary.data ? (
                    <>
                      {BAND_ORDER.filter((b) => alertSummary.data.by_severity[b]).map((band) => (
                        <Link key={band} to={`/alerts?severity=${band}`} className="flex items-center justify-between rounded-md border border-line px-3 py-2.5 transition-colors hover:border-saffron/40">
                          <span className="flex items-center gap-2 text-sm">
                            <span className="size-2 rounded-full" style={{ background: bandColor(band) }} />
                            {t(`bands.${band}`)}
                          </span>
                          <span className="text-right">
                            <span className="num block font-semibold">{count(alertSummary.data.by_severity[band])}</span>
                            <span className="num block text-2xs text-muted">{inr(alertSummary.data.amount_by_severity[band], lang)}</span>
                          </span>
                        </Link>
                      ))}
                      <div className="flex flex-wrap gap-1.5 pt-1">
                        {Object.entries(alertSummary.data.by_type).map(([type, n]) => (
                          <Link key={type} to={`/alerts?type=${type}`}>
                            <Badge tone="outline" className="hover:border-saffron/40">
                              {alertTypeLabel(type)} · {count(n)}
                            </Badge>
                          </Link>
                        ))}
                      </div>
                    </>
                  ) : (
                    <PanelSkeleton rows={3} className="p-0" />
                  )}
                </CardBody>
              </Card>
            </div>

            <div className="grid gap-4 xl:grid-cols-12">
              <Card className="xl:col-span-8">
                <CardHeader title={t("command.monthly")} hint={t("command.monthlyHint")} />
                <CardBody className="h-[260px]">
                  {monthly.data ? (
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={monthly.data} margin={{ left: 8, right: 8, top: 8 }}>
                        <CartesianGrid {...grid} />
                        <XAxis dataKey="month" {...axis} tickFormatter={(m: string) => monthLabel(m, lang)} interval={2} />
                        <YAxis {...axis} tickFormatter={(v: number) => inr(v, lang)} width={72} />
                        <Tooltip cursor={{ fill: "rgb(var(--raised))" }} content={<ChartTooltip money={["amount"]} labelFormat="month" />} />
                        <Bar dataKey="amount" name={t("common.sanctioned")} radius={[3, 3, 0, 0]} isAnimationActive={false}>
                          {monthly.data.map((m) => (
                            <Cell key={m.month} fill={m.is_march ? colors.saffron : colors.info} fillOpacity={m.is_march ? 1 : 0.75} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  ) : (
                    <Skeleton className="h-full w-full" />
                  )}
                </CardBody>
              </Card>

              <Card className="xl:col-span-4">
                <CardHeader title={t("command.changed")} hint={d.what_changed.note} eyebrow={d.what_changed.window} />
                <CardBody className="space-y-3">
                  <div className="grid grid-cols-3 gap-3">
                    <Stat value={count(d.what_changed.works_sanctioned)} label={t("command.sanctionedWindow")} sub={inr(d.what_changed.amount_sanctioned, lang)} />
                    <Stat value={count(d.what_changed.works_completed)} label={t("command.completedWindow")} />
                    <Stat value={count(d.what_changed.new_high_or_critical)} label={t("command.newHigh")} tone={bandColor("High")} />
                  </div>
                  {d.what_changed.last_scoring_run ? (
                    <div className="rounded-md border border-line bg-bg/40 p-3 text-xs">
                      <div className="eyebrow mb-1">{t("command.lastRun")}</div>
                      <div className="text-ink">{d.what_changed.last_scoring_run.message}</div>
                      <div className="mt-1 text-muted">{dateTime(d.what_changed.last_scoring_run.finished_at, lang)}</div>
                    </div>
                  ) : null}
                </CardBody>
              </Card>
            </div>

            <div className="grid gap-4 xl:grid-cols-2">
              <Card>
                <CardHeader title={t("command.districts")} />
                <CardBody className="px-0 pb-2">
                  <GroupTable rows={d.top_districts} linkTo={(key) => `/alerts?district=${encodeURIComponent(key)}`} />
                </CardBody>
              </Card>
              <Card>
                <CardHeader title={t("command.vendors")} hint={t("command.vendorsHint")} />
                <CardBody className="px-0 pb-2">
                  <GroupTable rows={d.top_vendors} />
                </CardBody>
              </Card>
            </div>
          </>
        )}
      </QueryState>
    </div>
  );
}

function Stat({ value, label, sub, tone }: { value: string; label: string; sub?: string; tone?: string }) {
  return (
    <div className="rounded-md border border-line bg-bg/40 p-3">
      <div className="num font-display text-xl font-semibold" style={tone ? { color: tone } : undefined}>
        {value}
      </div>
      <div className="text-2xs text-muted">{label}</div>
      {sub ? <div className="num text-2xs text-faint">{sub}</div> : null}
    </div>
  );
}

function BandStack({ bands, total }: { bands: Overview["bands"]; total: number }) {
  const { t, lang } = useLang();
  const ordered = [...bands].sort((a, b) => BAND_ORDER.indexOf(a.band) - BAND_ORDER.indexOf(b.band));
  return (
    <div>
      <div className="flex h-4 overflow-hidden rounded-full bg-raised" role="img" aria-label="Works by risk band">
        {[...ordered].reverse().map((b) => (
          <div key={b.band} style={{ width: `${(b.works / Math.max(total, 1)) * 100}%`, background: bandColor(b.band) }} title={`${b.band}: ${count(b.works)}`} />
        ))}
      </div>
      <table className="mt-4 w-full text-sm">
        <thead>
          <tr className="text-left text-2xs uppercase tracking-wider text-muted">
            <th className="pb-2 font-medium">{t("common.band")}</th>
            <th className="pb-2 text-right font-medium">{t("common.worksCap")}</th>
            <th className="pb-2 text-right font-medium">{t("common.sanctioned")}</th>
          </tr>
        </thead>
        <tbody>
          {ordered.map((b) => (
            <tr key={b.band} className="border-t border-line/60">
              <td className="py-2">
                <span className="flex items-center gap-2">
                  <span className="size-2 rounded-full" style={{ background: bandColor(b.band) }} />
                  {t(`bands.${b.band}`)}
                </span>
              </td>
              <td className="py-2 text-right">
                <span className="num">{count(b.works)}</span> <span className="num text-2xs text-muted">{pct(b.works / Math.max(total, 1))}</span>
              </td>
              <td className="py-2 text-right">
                <Money value={b.amount} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-2xs text-faint">{t("command.acrossWorks", { amount: inr(ordered.reduce((s, b) => s + b.amount, 0), lang), works: count(total) })}</p>
    </div>
  );
}

function GroupTable({ rows, linkTo }: { rows: Overview["top_districts"]; linkTo?: (key: string) => string }) {
  const { t, lang } = useLang();
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-line text-left text-2xs uppercase tracking-wider text-muted">
            <th className="px-5 pb-2 font-medium">{t("command.name")}</th>
            <th className="px-3 pb-2 text-right font-medium">{t("common.moneyAtRisk")}</th>
            <th className="px-3 pb-2 text-right font-medium">{t("common.highOrCritical")}</th>
            <th className="px-5 pb-2 text-right font-medium">{t("common.utilisation")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.key}-${r.state}`} className="border-b border-line/50 last:border-0 hover:bg-raised/40">
              <td className="px-5 py-2.5">
                <div className="flex items-center gap-2">
                  {linkTo ? (
                    <Link to={linkTo(r.key)} className="font-medium hover:text-saffron-text">
                      {r.key}
                    </Link>
                  ) : (
                    <span className="font-medium">{r.key}</span>
                  )}
                  {r.low_volume ? <LowVolume /> : null}
                </div>
                <div className="text-2xs text-muted">{r.state}</div>
              </td>
              <td className="px-3 py-2.5 text-right">
                <Money value={r.money_at_risk} className="font-medium" />
                <div className="num text-2xs text-muted">{t("command.ofAmount", { amount: inr(r.sanctioned, lang) })}</div>
              </td>
              <td className="num px-3 py-2.5 text-right">{ofTotal(r.high_or_critical, r.works, lang)}</td>
              <td className="num px-5 py-2.5 text-right">{pct(r.utilisation)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
