import { useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Building2, CheckCircle2, Hourglass, Landmark, Scale, Wallet } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { useLang } from "@/lib/i18n";
import { useApi } from "@/lib/query";
import { count, inr, monthLabel, ofTotal, pct } from "@/lib/format";
import type { BandRow, GroupRow, Kpis, MonthRow, WorkSummary } from "@/lib/types";
import { BAND_ORDER, bandColor } from "@/lib/utils";
import { axis, ChartTooltip, colors, grid } from "@/components/charts";
import { BandBadge, EmptyState, EstimateTag, KpiCard, LowVolume, Money, PageHeader, PanelSkeleton, QueryState } from "@/components/common";
import { Badge, Card, CardBody, CardHeader, Select } from "@/components/ui/primitives";

interface Constituencies {
  items: { mp_code: string; constituency: string | null; member: string | null; chamber: string | null; state: string; works: number }[];
  note: string;
}
interface PortfolioData {
  mp_code: string;
  constituency: string | null;
  member: string | null;
  chamber: string | null;
  state: string;
  framing: string;
  kpis: Kpis;
  entitlement_estimate: { amount: number; per_year: number; years: string[]; estimate: boolean; note: string };
  bands: BandRow[];
  status_mix: { status: string; works: number; amount: number }[];
  work_types: { work_type: string; works: number; amount: number }[];
  agencies: GroupRow[];
  monthly: MonthRow[];
  open_works: number;
  open_high_delay_risk: number;
  high_delay_risk_threshold: number;
  attention: WorkSummary[];
}

export default function Portfolio() {
  const { t, lang } = useLang();
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const isMp = user?.role === "MP";
  const state = params.get("state") ?? "";
  const mpCode = isMp ? (user?.mp_code ?? "") : (params.get("mp") ?? "");
  const list = useApi<Constituencies>(isMp ? null : "/portfolio/constituencies");
  const portfolio = useApi<PortfolioData>(mpCode ? "/portfolio" : null, isMp ? undefined : { mp_code: mpCode }, { placeholderData: undefined });

  const states = useMemo(() => [...new Set(list.data?.items.map((i) => i.state))].sort(), [list.data]);
  const options = useMemo(() => list.data?.items.filter((i) => !state || i.state === state) ?? [], [list.data, state]);

  return (
    <div className="space-y-6">
      <PageHeader title={t("nav.mp")} subtitle={t("portfolio.subtitle")} />
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-saffron/30 bg-saffron/[0.06] px-4 py-3 text-sm" data-testid="portfolio-framing">
        <Scale className="size-4 text-saffron-text" />
        <span className="font-medium">{portfolio.data?.framing ?? t("portfolio.framing")}</span>
      </div>

      {!isMp ? (
        <Card className="flex flex-wrap items-end gap-4 p-4">
          <Select label={t("common.state")} value={state} onChange={(e) => setParams({ state: e.target.value }, { replace: true })} className="min-w-[220px]">
            <option value="">{t("common.all")}</option>
            {states.map((s) => <option key={s} value={s}>{s}</option>)}
          </Select>
          <Select
            label={t("portfolio.constituency")}
            value={mpCode}
            onChange={(e) => setParams({ ...(state ? { state } : {}), mp: e.target.value }, { replace: true })}
            className="min-w-[360px]"
            data-testid="constituency-select"
          >
            <option value="">{t("portfolio.choose")}</option>
            {options.map((c) => (
              <option key={c.mp_code} value={c.mp_code}>
                {c.constituency ?? c.mp_code} · {c.state} ({c.chamber}) · {count(c.works)} {t("common.works")}
              </option>
            ))}
          </Select>
          <p className="text-xs text-muted">{list.data?.note}</p>
        </Card>
      ) : null}

      {!mpCode ? (
        <Card>
          <EmptyState icon={<Landmark className="size-5" />} title={t("portfolio.choose")} body={t("portfolio.chooseBody")} />
        </Card>
      ) : (
        <QueryState query={portfolio} skeleton={<Card><PanelSkeleton rows={10} /></Card>}>
          {(p) => (
            <>
              <Card className="flex flex-wrap items-center justify-between gap-4 p-5">
                <div>
                  <div className="eyebrow">{p.state} · {p.chamber === "RS" ? "Rajya Sabha" : "Lok Sabha"} · MP code {p.mp_code}</div>
                  <h2 className="mt-1 font-display text-2xl font-semibold" data-testid="portfolio-title">{p.constituency}</h2>
                  {p.member && !(p.constituency ?? "").includes(p.member) ? <div className="text-sm text-muted">{t("portfolio.member")}: {p.member}</div> : null}
                </div>
                <div className="rounded-lg border border-line bg-bg/40 px-4 py-3 text-right">
                  <div className="flex items-center justify-end gap-2 text-xs text-muted">{t("portfolio.entitlement")} <EstimateTag /></div>
                  <div className="num font-display text-2xl font-semibold"><Money value={p.entitlement_estimate.amount} /></div>
                  <div className="text-2xs text-faint">{inr(p.entitlement_estimate.per_year, lang)} × {p.entitlement_estimate.years.length} · {p.entitlement_estimate.note}</div>
                </div>
              </Card>

              <div className="grid grid-cols-2 gap-4 xl:grid-cols-5">
                <KpiCard label={t("common.worksCap")} value={p.kpis.works} icon={<Building2 className="size-4" />} />
                <KpiCard label={t("common.sanctioned")} value={p.kpis.sanctioned} kind="money" sub={`${pct(p.kpis.sanctioned / Math.max(p.entitlement_estimate.amount, 1))} ${t("portfolio.ofEstimate")}`} />
                <KpiCard label={t("common.disbursed")} value={p.kpis.disbursed} kind="money" icon={<Wallet className="size-4" />} sub={`${pct(p.kpis.utilisation)} ${t("common.utilisation").toLowerCase()}`} />
                <KpiCard label={t("command.kpiCompletion")} value={p.kpis.completion_rate} kind="percent" icon={<CheckCircle2 className="size-4" />} sub={ofTotal(p.kpis.completed, p.kpis.works, lang)} />
                <KpiCard label={t("portfolio.openDelay")} value={p.open_high_delay_risk} icon={<Hourglass className="size-4" />} accent={bandColor("High")} sub={ofTotal(p.open_high_delay_risk, p.open_works, lang)} hint={t("portfolio.delayHint", { threshold: pct(p.high_delay_risk_threshold, 0) })} />
              </div>

              <div className="grid gap-4 xl:grid-cols-12">
                <Card className="xl:col-span-4">
                  <CardHeader title={t("portfolio.bands")} hint={t("command.bandsHint")} />
                  <CardBody className="space-y-3">
                    {[...p.bands].sort((a, b) => BAND_ORDER.indexOf(a.band) - BAND_ORDER.indexOf(b.band)).map((b) => (
                      <div key={b.band}>
                        <div className="mb-1 flex justify-between text-sm">
                          <span className="flex items-center gap-2"><span className="size-2 rounded-full" style={{ background: bandColor(b.band) }} />{t(`bands.${b.band}`)}</span>
                          <span className="num">{ofTotal(b.works, p.kpis.works, lang)}</span>
                        </div>
                        <div className="h-2 rounded-full bg-raised"><div className="h-full rounded-full" style={{ width: pct(b.works / Math.max(p.kpis.works, 1)), background: bandColor(b.band) }} /></div>
                      </div>
                    ))}
                  </CardBody>
                </Card>
                <Card className="xl:col-span-4">
                  <CardHeader title={t("portfolio.status")} />
                  <CardBody className="space-y-2">
                    {p.status_mix.map((s) => (
                      <div key={s.status} className="flex items-center justify-between rounded-md border border-line/60 px-3 py-2 text-sm">
                        <span>{s.status}</span>
                        <span className="text-right"><span className="num">{count(s.works)}</span> <span className="num text-2xs text-muted">{inr(s.amount, lang)}</span></span>
                      </div>
                    ))}
                  </CardBody>
                </Card>
                <Card className="xl:col-span-4">
                  <CardHeader title={t("portfolio.types")} />
                  <CardBody className="space-y-2">
                    {p.work_types.map((w) => (
                      <div key={w.work_type} className="grid grid-cols-[1fr_auto] gap-2 text-sm">
                        <span className="truncate">{w.work_type}</span>
                        <span className="num text-right text-muted">{count(w.works)} · {inr(w.amount, lang)}</span>
                        <div className="col-span-2 h-1.5 rounded-full bg-raised"><div className="h-full rounded-full bg-info/70" style={{ width: pct(w.amount / Math.max(p.kpis.sanctioned, 1)) }} /></div>
                      </div>
                    ))}
                  </CardBody>
                </Card>
              </div>

              <div className="grid gap-4 xl:grid-cols-12">
                <Card className="xl:col-span-7">
                  <CardHeader title={t("portfolio.agencies")} hint={t("portfolio.agenciesHint")} />
                  <CardBody className="px-0 pb-2">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-line text-left text-2xs uppercase tracking-wider text-muted">
                          <th className="px-5 pb-2 font-medium">{t("work.agency")}</th>
                          <th className="px-3 pb-2 text-right font-medium">{t("common.worksCap")}</th>
                          <th className="px-3 pb-2 text-right font-medium">{t("common.completion")}</th>
                          <th className="px-5 pb-2 text-right font-medium">{t("common.highOrCritical")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {p.agencies.map((a) => (
                          <tr key={a.key} className="border-b border-line/50 last:border-0">
                            <td className="max-w-[320px] px-5 py-2"><span className="line-clamp-1" title={a.key}>{a.key}</span></td>
                            <td className="num px-3 py-2 text-right">{count(a.works)} {a.low_volume ? <LowVolume /> : null}</td>
                            <td className="num px-3 py-2 text-right">{pct(a.completion_rate)}</td>
                            <td className="num px-5 py-2 text-right">{ofTotal(a.high_or_critical, a.works, lang)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </CardBody>
                </Card>
                <Card className="xl:col-span-5">
                  <CardHeader title={t("command.monthly")} />
                  <CardBody className="h-[260px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={p.monthly} margin={{ left: 0, right: 8, top: 8 }}>
                        <CartesianGrid {...grid} />
                        <XAxis dataKey="month" {...axis} tickFormatter={(m: string) => monthLabel(m, lang)} interval={3} />
                        <YAxis {...axis} tickFormatter={(v: number) => inr(v, lang)} width={64} />
                        <Tooltip content={<ChartTooltip money={["amount"]} labelFormat="month" />} cursor={{ fill: "rgb(var(--raised))" }} />
                        <Bar dataKey="amount" name={t("common.sanctioned")} fill={colors.info} radius={[3, 3, 0, 0]} isAnimationActive={false} />
                      </BarChart>
                    </ResponsiveContainer>
                  </CardBody>
                </Card>
              </div>

              <Card>
                <CardHeader title={t("portfolio.attention")} hint={t("portfolio.attentionHint")} />
                <CardBody className="space-y-2">
                  {p.attention.length ? (
                    p.attention.map((w) => (
                      <Link key={w.work_id} to={`/works/${w.work_id}`} className="grid grid-cols-[1fr_auto] items-center gap-4 rounded-md border border-line px-4 py-3 hover:border-saffron/40">
                        <span className="min-w-0">
                          <span className="block truncate font-medium">{w.work_description}</span>
                          <span className="block truncate text-xs text-muted">{lang === "hi" ? (w.top_reason_hi ?? w.top_reason_en) : w.top_reason_en}</span>
                          <span className="block text-2xs text-faint">{t("work.agency")}: {w.ida} · <span className="font-mono">{w.work_id}</span></span>
                        </span>
                        <span className="flex flex-col items-end gap-1">
                          <Money value={w.sanction_amount} className="font-semibold" />
                          <BandBadge band={w.band} score={w.risk_score} />
                        </span>
                      </Link>
                    ))
                  ) : (
                    <EmptyState title={t("portfolio.noAttention")} body={<Badge tone="ok">{t("portfolio.noAttentionBody")}</Badge>} />
                  )}
                </CardBody>
              </Card>
            </>
          )}
        </QueryState>
      )}
    </div>
  );
}
