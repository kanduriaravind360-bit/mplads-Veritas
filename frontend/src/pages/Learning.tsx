import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Cell, LabelList, ResponsiveContainer, XAxis, YAxis } from "recharts";
import { FlaskConical, SlidersHorizontal } from "lucide-react";
import { useLang } from "@/lib/i18n";
import { useApi } from "@/lib/query";
import { count, pct } from "@/lib/format";
import { axis, colors, grid } from "@/components/charts";
import { EmptyState, KpiCard, PageHeader, PanelSkeleton, QueryState } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardBody, CardHeader } from "@/components/ui/primitives";

interface LearningData {
  status: "ok" | "insufficient";
  message?: string;
  counts: {
    total: number;
    by_origin: Record<"planted" | "seed_rule" | "reviewer", { positive: number; negative: number }>;
    learn: number;
    evaluate: number;
  };
  configured_weights: Record<string, number>;
  prior_confirmed_rate?: number;
  channels?: {
    channel: string;
    active_verdicts: number;
    confirmed: number;
    posterior_precision: number;
    interval_90: [number, number];
    multiplier: number;
    configured_weight: number;
    learned_weight: number;
  }[];
  learned_weights?: Record<string, number>;
  reranker?: { trained: boolean; min_labels: number; n_learn?: number; coefficients?: Record<string, number> };
  precision?: { k: number; evaluate_rows: number; base_rate: number | null; configured_fusion: number | null; reweighted_fusion: number | null; reranker: number | null };
  caveats?: string[];
}

const CHANNELS: Record<string, string> = {
  rule: "Rule layer",
  supervised: "Proxy model",
  unsupervised: "Unsupervised anomaly",
  cost: "Cost",
  duplicate: "Duplicate",
  delay: "Delay model",
};

function precisionBars(d: LearningData, t: (key: string) => string) {
  const p = d.precision;
  const bars = [
    { name: t("learn.baseRate"), value: (p?.base_rate ?? 0) * 100, fill: colors.faint },
    { name: t("learn.configured"), value: (p?.configured_fusion ?? 0) * 100, fill: colors.info },
    { name: t("learn.reweighted"), value: (p?.reweighted_fusion ?? 0) * 100, fill: colors.saffron },
  ];
  if (p?.reranker !== null && p?.reranker !== undefined) bars.push({ name: t("learn.reranker"), value: p.reranker * 100, fill: "#2DAA82" });
  return bars;
}

export default function Learning() {
  const { t } = useLang();
  const learning = useApi<LearningData>("/learning");

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("learn.title")}
        subtitle={t("learn.subtitle")}
        actions={
          learning.data?.learned_weights ? (
            <Button asChild variant="primary" size="sm">
              <Link to="/simulator?from=learning"><SlidersHorizontal /> {t("learn.trySimulator")}</Link>
            </Button>
          ) : null
        }
      />
      <QueryState query={learning} skeleton={<Card><PanelSkeleton rows={10} /></Card>}>
        {(d) => (
          <>
            {d.caveats?.length ? (
              <div className="flex gap-3 rounded-lg border border-warn/35 bg-warn/[0.07] p-4" data-testid="learning-caveat">
                <FlaskConical className="mt-0.5 size-5 shrink-0 text-warn" />
                <ul className="space-y-1 text-sm">
                  {d.caveats.map((c, i) => <li key={i} className={i ? "text-muted" : "font-medium"}>{c}</li>)}
                </ul>
              </div>
            ) : null}

            <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
              <KpiCard label={t("learn.planted")} value={d.counts.by_origin.planted.positive} sub={t("learn.plantedSub")} />
              <KpiCard label={t("learn.seeded")} value={d.counts.by_origin.seed_rule.negative} sub={t("learn.seededSub")} />
              <KpiCard label={t("learn.reviewer")} value={d.counts.by_origin.reviewer.positive + d.counts.by_origin.reviewer.negative} sub={t("learn.reviewerSub", { pos: count(d.counts.by_origin.reviewer.positive), neg: count(d.counts.by_origin.reviewer.negative) })} />
              <KpiCard label={t("learn.split")} value={d.counts.total} sub={t("learn.splitSub", { learn: count(d.counts.learn), evaluate: count(d.counts.evaluate) })} />
            </div>

            {d.status !== "ok" ? (
              <Card><EmptyState title={t("learn.insufficient")} body={d.message} /></Card>
            ) : (
              <>
                <div className="grid gap-4 xl:grid-cols-12">
                  <Card className="xl:col-span-5">
                    <CardHeader title={t("learn.precision", { k: d.precision?.k ?? 0 })} hint={t("learn.precisionHint", { n: count(d.precision?.evaluate_rows ?? 0) })} />
                    <CardBody className="h-[300px]" data-testid="learning-precision">
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={precisionBars(d, t)} margin={{ left: -8, right: 8, top: 24 }}>
                          <CartesianGrid {...grid} />
                          <XAxis dataKey="name" {...axis} interval={0} />
                          <YAxis {...axis} domain={[0, 100]} tickFormatter={(v: number) => `${v}%`} />
                          <Bar dataKey="value" radius={[4, 4, 0, 0]} isAnimationActive={false}>
                            {precisionBars(d, t).map((bar) => <Cell key={bar.name} fill={bar.fill} />)}
                            <LabelList dataKey="value" position="top" formatter={(v: number) => `${v.toFixed(0)}%`} className="fill-[rgb(var(--ink))] text-xs" />
                          </Bar>
                        </BarChart>
                      </ResponsiveContainer>
                    </CardBody>
                  </Card>

                  <Card className="xl:col-span-7">
                    <CardHeader title={t("learn.channels")} hint={t("learn.channelsHint", { prior: pct(d.prior_confirmed_rate ?? 0) })} />
                    <CardBody className="overflow-x-auto px-0">
                      <table className="w-full text-sm" data-testid="learning-channels">
                        <thead>
                          <tr className="border-b border-line text-left text-2xs uppercase tracking-wider text-muted">
                            <th className="px-5 pb-2 font-medium">{t("learn.channel")}</th>
                            <th className="px-3 pb-2 text-right font-medium">{t("learn.active")}</th>
                            <th className="w-56 px-3 pb-2 font-medium">{t("learn.posterior")}</th>
                            <th className="px-5 pb-2 text-right font-medium">{t("learn.weight")}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {d.channels?.map((c) => (
                            <tr key={c.channel} className="border-b border-line/50 last:border-0">
                              <td className="px-5 py-2.5 font-medium">{CHANNELS[c.channel] ?? c.channel}</td>
                              <td className="num px-3 py-2.5 text-right text-xs">{count(c.confirmed)} / {count(c.active_verdicts)}</td>
                              <td className="px-3 py-2.5">
                                <div className="relative h-3 rounded-full bg-raised">
                                  <div className="absolute inset-y-0 rounded-full bg-info/40" style={{ left: pct(c.interval_90[0]), width: `calc(${pct(c.interval_90[1])} - ${pct(c.interval_90[0])})` }} />
                                  <div className="absolute inset-y-[-2px] w-0.5 bg-saffron" style={{ left: pct(c.posterior_precision) }} />
                                  <div className="absolute inset-y-[-3px] w-px bg-ink/50" style={{ left: pct(d.prior_confirmed_rate ?? 0) }} />
                                </div>
                                <div className="num mt-1 text-2xs text-muted">{pct(c.posterior_precision)} [{pct(c.interval_90[0], 0)}–{pct(c.interval_90[1], 0)}]</div>
                              </td>
                              <td className="num px-5 py-2.5 text-right">
                                <span className="text-muted">{c.configured_weight.toFixed(2)}</span> → <span className={c.learned_weight > c.configured_weight ? "text-warn" : c.learned_weight < c.configured_weight ? "text-info" : ""}>{c.learned_weight.toFixed(3)}</span>
                                <div className="text-2xs text-faint">×{c.multiplier.toFixed(2)}</div>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      <p className="px-5 pt-3 text-2xs text-faint">{t("learn.legend")}</p>
                    </CardBody>
                  </Card>
                </div>

                <Card>
                  <CardHeader
                    title={t("learn.rerankerTitle")}
                    action={<Badge tone={d.reranker?.trained ? "ok" : "outline"}>{d.reranker?.trained ? t("learn.trained", { n: count(d.reranker.n_learn ?? 0) }) : t("learn.notTrained", { n: d.reranker?.min_labels ?? 0 })}</Badge>}
                  />
                  <CardBody>
                    {d.reranker?.coefficients ? (
                      <div className="grid gap-2 md:grid-cols-3">
                        {Object.entries(d.reranker.coefficients).map(([k, v]) => (
                          <div key={k} className="flex items-center justify-between rounded-md border border-line px-3 py-2 text-sm">
                            <span>{CHANNELS[k] ?? k}</span>
                            <span className={`num font-medium ${v >= 0 ? "text-warn" : "text-info"}`}>{v >= 0 ? "+" : ""}{v.toFixed(2)}</span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-sm text-muted">{t("learn.rerankerWaiting")}</p>
                    )}
                    <p className="mt-3 text-2xs text-faint">{t("learn.rerankerNote")}</p>
                  </CardBody>
                </Card>
              </>
            )}
          </>
        )}
      </QueryState>
    </div>
  );
}
