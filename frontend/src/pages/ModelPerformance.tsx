import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AlertTriangle, FlaskConical, Info } from "lucide-react";
import { useLang } from "@/lib/i18n";
import { useApi } from "@/lib/query";
import { count, pct } from "@/lib/format";
import type { Band, ModelsSummary } from "@/lib/types";
import { BAND_ORDER, bandColor } from "@/lib/utils";
import { axis, colors, grid } from "@/components/charts";
import { PageHeader, PanelSkeleton, QueryState } from "@/components/common";
import { Badge, Card, CardBody, CardHeader } from "@/components/ui/primitives";
import { Tip } from "@/components/ui/tooltip";

const DETECTOR_LABELS: Record<string, string> = {
  duplicate: "Duplicate works",
  fast_complete: "Implausibly fast completion",
  inflated_cost: "Inflated cost",
  split_group: "Split work",
  stuck_work: "Stalled work",
  vendor_concentration: "Vendor concentration",
};

function Explain({ text }: { text: string | undefined }) {
  if (!text) return null;
  return (
    <Tip content={text}>
      <button type="button" aria-label="Explain" className="text-faint hover:text-muted"><Info className="size-3.5" /></button>
    </Tip>
  );
}

function RecallCell({ value }: { value: number }) {
  const colour = value >= 0.7 ? "rgb(var(--ok))" : value >= 0.5 ? bandColor("Medium") : bandColor("Critical");
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-24 overflow-hidden rounded-full bg-raised">
        <div className="h-full rounded-full" style={{ width: pct(value, 0), background: colour }} />
      </div>
      <span className="num w-12 text-right">{pct(value, 1)}</span>
    </div>
  );
}

export default function ModelPerformance() {
  const { t } = useLang();
  const summary = useApi<ModelsSummary>("/models/summary");

  return (
    <div className="space-y-6">
      <PageHeader title={t("nav.models")} subtitle={t("models.subtitle")} />
      <QueryState query={summary} skeleton={<Card><PanelSkeleton rows={12} /></Card>}>
        {(m) => (
          <>
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="flex gap-3 rounded-lg border border-warn/35 bg-warn/[0.07] p-4" data-testid="weak-spot">
                <AlertTriangle className="mt-0.5 size-5 shrink-0 text-warn" />
                <div>
                  <div className="font-semibold">{t("models.weakSpot")}</div>
                  <p className="mt-1 text-sm text-muted">{m.weak_spot}</p>
                </div>
              </div>
              <div className="flex gap-3 rounded-lg border border-info/30 bg-info/[0.06] p-4" data-testid="proxy-caveat">
                <FlaskConical className="mt-0.5 size-5 shrink-0 text-info" />
                <div>
                  <div className="font-semibold">{t("models.proxyTitle")}</div>
                  <p className="mt-1 text-sm text-muted">{m.caveats[0]}</p>
                </div>
              </div>
            </div>

            <Card>
              <CardHeader title={t("models.perDetector")} hint={t("models.perDetectorHint")} />
              <CardBody className="overflow-x-auto px-0">
                <table className="w-full text-sm" data-testid="detector-table">
                  <thead>
                    <tr className="border-b border-line text-left text-2xs uppercase tracking-wider text-muted">
                      <th className="px-5 pb-2 font-medium">{t("models.detector")}</th>
                      <th className="px-3 pb-2 font-medium"><span className="flex items-center gap-1">{t("models.fired")} <Explain text={m.explanations.detector_fired} /></span></th>
                      <th className="px-3 pb-2 font-medium"><span className="flex items-center gap-1">{t("models.recall5")} <Explain text={m.explanations.recall_at_top_5pct} /></span></th>
                      <th className="px-3 pb-2 font-medium"><span className="flex items-center gap-1">{t("models.recall10")} <Explain text={m.explanations.recall_at_top_10pct} /></span></th>
                      <th className="px-3 pb-2 text-right font-medium"><span className="flex items-center justify-end gap-1">{t("models.precision5")} <Explain text={m.explanations.precision_at_top_5pct} /></span></th>
                      <th className="px-5 pb-2 text-right font-medium">{t("models.queue")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {m.per_detector.map((d) => (
                      <tr key={d.detector} className="border-b border-line/50 last:border-0">
                        <td className="px-5 py-3 font-medium">{DETECTOR_LABELS[d.detector] ?? d.detector}</td>
                        <td className="px-3 py-3"><RecallCell value={d.fired} /></td>
                        <td className="px-3 py-3"><RecallCell value={d.recall_at_top_5pct} /></td>
                        <td className="px-3 py-3"><RecallCell value={d.recall_at_top_10pct} /></td>
                        <td className="num px-3 py-3 text-right">{pct(d.precision_at_top_5pct, 1)}</td>
                        <td className="num px-5 py-3 text-right text-muted">{count(d.queue_size)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="px-5 pt-3 text-2xs text-faint">{m.caveats.find((c) => c?.toLowerCase().includes("injection")) ?? ""}</p>
              </CardBody>
            </Card>

            <div className="grid gap-4 xl:grid-cols-3">
              <Card>
                <CardHeader title={t("models.delay")} hint={m.explanations.delay_roc_auc} />
                <CardBody>
                  <div className="grid grid-cols-2 gap-3">
                    {(["train", "holdout"] as const).map((k) => (
                      <div key={k} className="rounded-lg border border-line bg-bg/40 p-4">
                        <div className="eyebrow">{k === "train" ? t("models.timeSplit") : t("models.holdout")}</div>
                        <div className="num mt-2 font-display text-3xl font-semibold">{m.delay_model[k].roc_auc.toFixed(3)}</div>
                        <div className="text-2xs text-muted">ROC-AUC</div>
                        <div className="num mt-2 text-lg font-semibold">{m.delay_model[k].pr_auc.toFixed(3)}</div>
                        <div className="text-2xs text-muted">PR-AUC</div>
                      </div>
                    ))}
                  </div>
                  <p className="mt-3 text-xs text-muted">
                    {t("models.holdoutNote", { n: count(m.delay_model.holdout.n_labelled), rate: pct(m.delay_model.holdout.delay_rate), works: count(m.holdout_size.works), constituencies: m.holdout_size.constituencies })}
                  </p>
                </CardBody>
              </Card>

              <Card>
                <CardHeader title={t("models.proxy")} hint={m.explanations.proxy_pr_auc} />
                <CardBody>
                  <div className="rounded-lg border border-line bg-bg/40 p-4">
                    <div className="num font-display text-3xl font-semibold">{m.proxy_model.pr_auc_oof.toFixed(3)}</div>
                    <div className="text-2xs text-muted">PR-AUC {t("models.oof")} · ROC-AUC {m.proxy_model.roc_auc_oof.toFixed(3)}</div>
                  </div>
                  <p className="mt-3 text-xs leading-relaxed text-muted">{m.proxy_model.caveat ?? m.caveats[0]}</p>
                  <Badge tone="warn" className="mt-2">{t("models.notFraud")}</Badge>
                </CardBody>
              </Card>

              <Card>
                <CardHeader title={t("models.bandsHoldout")} hint={m.explanations.holdout} />
                <CardBody className="h-[240px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={BAND_ORDER.map((b) => ({ band: b, train: (m.holdout_bands.train.shares[b as Band] ?? 0) * 100, holdout: (m.holdout_bands.holdout.shares[b as Band] ?? 0) * 100 }))} margin={{ left: -16, right: 8, top: 8 }}>
                      <CartesianGrid {...grid} />
                      <XAxis dataKey="band" {...axis} />
                      <YAxis {...axis} tickFormatter={(v: number) => `${v}%`} />
                      <Tooltip formatter={(v: number) => `${v.toFixed(1)}%`} contentStyle={{ background: "rgb(var(--raised))", border: "1px solid rgb(var(--line))", borderRadius: 8, fontSize: 12 }} />
                      <Legend wrapperStyle={{ fontSize: 12 }} />
                      <Bar dataKey="train" name={`${t("models.train")} (n=${count(m.holdout_bands.train.n)})`} fill={colors.info} radius={[3, 3, 0, 0]} isAnimationActive={false} />
                      <Bar dataKey="holdout" name={`${t("models.holdout")} (n=${count(m.holdout_bands.holdout.n)})`} fill={colors.saffron} radius={[3, 3, 0, 0]} isAnimationActive={false} />
                    </BarChart>
                  </ResponsiveContainer>
                </CardBody>
              </Card>
            </div>

            <div className="grid gap-4 xl:grid-cols-3">
              <Card>
                <CardHeader title={t("models.beforeAfter")} hint={t("models.beforeAfterHint")} />
                <CardBody className="px-0 pb-2">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-line text-left text-2xs uppercase tracking-wider text-muted">
                        <th className="px-5 pb-2 font-medium">{t("models.detector")}</th>
                        <th className="px-2 pb-2 text-right font-medium">{t("models.before")}</th>
                        <th className="px-2 pb-2 text-right font-medium">{t("models.after")}</th>
                        <th className="px-5 pb-2 text-right font-medium">{t("models.target")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(m.before_after).map(([k, v]) => (
                        <tr key={k} className="border-b border-line/50 last:border-0">
                          <td className="px-5 py-2">{DETECTOR_LABELS[k] ?? k}</td>
                          <td className="num px-2 py-2 text-right text-muted">{pct(v.before_step2b, 1)}</td>
                          <td className="num px-2 py-2 text-right">{pct(v.after_step2b, 1)}</td>
                          <td className="px-5 py-2 text-right"><Badge tone={v.target_met ? "ok" : "warn"}>{pct(v.target, 0)} {v.target_met ? "✓" : t("models.notMet")}</Badge></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </CardBody>
              </Card>

              <Card>
                <CardHeader title={t("models.fusion")} hint={t("models.fusionHint")} />
                <CardBody className="space-y-2.5">
                  {Object.entries(m.weights).sort((a, b) => b[1] - a[1]).map(([k, v]) => (
                    <div key={k} className="grid grid-cols-[8rem_1fr_3rem] items-center gap-3 text-sm">
                      <span className="text-muted">{k}</span>
                      <div className="h-2 rounded-full bg-raised"><div className="h-full rounded-full bg-saffron" style={{ width: pct(v / Math.max(...Object.values(m.weights))) }} /></div>
                      <span className="num text-right">{v.toFixed(2)}</span>
                    </div>
                  ))}
                  <div className="flex flex-wrap gap-2 pt-2 text-xs">
                    <Badge tone="outline">Critical ≥ {m.band_cutoffs.critical.toFixed(1)}</Badge>
                    <Badge tone="outline">High ≥ {m.band_cutoffs.high.toFixed(1)}</Badge>
                    <Badge tone="outline">Medium ≥ {m.band_cutoffs.medium.toFixed(1)}</Badge>
                  </div>
                </CardBody>
              </Card>

              <Card>
                <CardHeader title={t("models.floor")} hint={t("models.floorHint")} />
                <CardBody className="space-y-3 text-sm">
                  <div className="flex justify-between"><span className="text-muted">{t("models.lifted")}</span><span className="num font-semibold">{count(m.severe_floor.works_lifted)}</span></div>
                  <div className="flex justify-between"><span className="text-muted">{t("models.changedBand")}</span><span className="num font-semibold">{count(m.severe_floor.works_changing_band)}</span></div>
                  <div className="space-y-1.5 pt-1">
                    {BAND_ORDER.map((b) => (
                      <div key={b} className="flex items-center justify-between text-xs">
                        <span className="flex items-center gap-2"><span className="size-2 rounded-full" style={{ background: bandColor(b) }} />{b}</span>
                        <span className="num text-muted">{count(m.severe_floor.bands_before_floor[b as Band] ?? 0)} → <span className="text-ink">{count(m.holdout_bands.train.counts[b as Band] ?? 0)}</span></span>
                      </div>
                    ))}
                  </div>
                  <p className="border-t border-line pt-3 text-xs text-muted">
                    {t("models.stateChannel", { n: count(Number(m.cost_state_channel.works_where_state_channel_would_lead ?? 0)) })}
                  </p>
                </CardBody>
              </Card>
            </div>

            <Card>
              <CardHeader title={t("models.allCaveats")} />
              <CardBody>
                <ul className="list-disc space-y-1.5 pl-5 text-sm text-muted">
                  {m.caveats.filter(Boolean).map((c, i) => <li key={i}>{c}</li>)}
                </ul>
              </CardBody>
            </Card>
          </>
        )}
      </QueryState>
    </div>
  );
}
