import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ArrowDownRight, ArrowUpRight, GraduationCap, Loader2, RotateCcw } from "lucide-react";
import { api } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import { useApi } from "@/lib/query";
import { count, inr, pct } from "@/lib/format";
import { cn } from "@/lib/utils";
import { axis, ChartTooltip, colors, grid } from "@/components/charts";
import { ErrorState, Money, PageHeader, PanelSkeleton, useDebounced } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardBody, CardHeader } from "@/components/ui/primitives";
import { Slider } from "@/components/ui/slider";

interface Defaults {
  weights: Record<string, number>;
  band_percentiles: { critical: number; high: number; medium: number };
  single_signal_target: number;
}
interface BandCount {
  band: string;
  works: number;
  amount: number;
}
interface SimResult {
  scope_works: number;
  cutoffs: Record<string, number>;
  current: { bands: BandCount[]; queue: number; money_at_risk: number };
  simulated: { bands: BandCount[]; queue: number; money_at_risk: number };
  entering: { works: number; amount: number };
  leaving: { works: number; amount: number };
  entering_examples: string[];
  verdicts: { labelled: number; confirmed_in_queue?: [number, number]; false_positive_in_queue?: [number, number] };
  note: string;
}

const CHANNELS: Record<string, string> = {
  rule: "Rule layer",
  supervised: "Proxy model",
  unsupervised: "Unsupervised anomaly",
  cost: "Cost",
  duplicate: "Duplicate",
  delay: "Delay model",
};

export default function Simulator() {
  const { t, lang } = useLang();
  const [params] = useSearchParams();
  const defaults = useApi<Defaults>("/simulator/defaults", undefined, { staleTime: Infinity });
  const [weights, setWeights] = useState<Record<string, number> | null>(null);
  const [percentiles, setPercentiles] = useState<Defaults["band_percentiles"] | null>(null);
  const learned = useApi<{ learned_weights?: Record<string, number> }>("/learning", undefined, { staleTime: 60_000 });

  const reset = () => {
    if (!defaults.data) return;
    setWeights({ ...defaults.data.weights });
    setPercentiles({ ...defaults.data.band_percentiles });
  };

  useEffect(() => {
    if (defaults.data && !weights) {
      reset();
      if (params.get("from") === "learning" && learned.data?.learned_weights) setWeights({ ...learned.data.learned_weights });
    }
  }, [defaults.data, learned.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const body = useDebounced(useMemo(() => ({ weights, band_percentiles: percentiles }), [weights, percentiles]), 250);
  const sim = useQuery<SimResult, Error>({
    queryKey: ["simulate", body],
    queryFn: ({ signal }) => api<SimResult>("/simulator", { body, signal, method: "POST" }),
    enabled: !!body.weights && !!body.band_percentiles,
    placeholderData: (previous) => previous,
    staleTime: Infinity,
  });

  const changed =
    !!defaults.data &&
    !!weights &&
    !!percentiles &&
    (JSON.stringify(weights) !== JSON.stringify(defaults.data.weights) ||
      JSON.stringify(percentiles) !== JSON.stringify(defaults.data.band_percentiles));

  const r = sim.data;
  const chart = r ? r.current.bands.map((b, i) => ({ band: b.band, current: b.works, simulated: r.simulated.bands[i]?.works ?? 0 })) : [];

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("sim.title")}
        subtitle={t("sim.subtitle")}
        actions={
          <>
            {learned.data?.learned_weights ? (
              <Button variant="outline" size="sm" onClick={() => setWeights({ ...learned.data!.learned_weights! })}>
                <GraduationCap /> {t("sim.loadLearned")}
              </Button>
            ) : null}
            <Button variant="primary" size="sm" onClick={reset} disabled={!changed} data-testid="sim-reset">
              <RotateCcw /> {t("sim.reset")}
            </Button>
          </>
        }
      />
      <div className="grid gap-4 xl:grid-cols-[420px_1fr]">
        <Card className="h-fit">
          <CardHeader title={t("sim.weights")} hint={t("sim.weightsHint")} />
          <CardBody className="space-y-5">
            {!weights || !percentiles || !defaults.data ? (
              <PanelSkeleton rows={8} className="p-0" />
            ) : (
              <>
                {Object.keys(CHANNELS).map((name) => (
                  <div key={name}>
                    <div className="mb-1.5 flex items-center justify-between text-sm">
                      <span>{CHANNELS[name]}</span>
                      <span className="num">
                        {(weights[name] ?? 0).toFixed(2)}
                        {Math.abs((weights[name] ?? 0) - (defaults.data!.weights[name] ?? 0)) > 1e-6 ? (
                          <span className="ml-2 text-2xs text-faint">{t("sim.was", { value: (defaults.data!.weights[name] ?? 0).toFixed(2) })}</span>
                        ) : null}
                      </span>
                    </div>
                    <Slider label={CHANNELS[name] ?? name} value={weights[name] ?? 0} min={0} max={0.5} step={0.01} onChange={(v) => setWeights({ ...weights, [name]: v })} />
                  </div>
                ))}
                <div className="border-t border-line pt-4">
                  <div className="eyebrow mb-3">{t("sim.bands")}</div>
                  {(
                    [
                      ["critical", t("sim.critical"), 0.001, 0.05],
                      ["high", t("sim.high"), 0.01, 0.2],
                      ["medium", t("sim.medium"), 0.05, 0.5],
                    ] as const
                  ).map(([key, label, lo, hi]) => {
                    const top = 1 - percentiles[key];
                    return (
                      <div key={key} className="mb-4">
                        <div className="mb-1.5 flex justify-between text-sm">
                          <span>{label}</span>
                          <span className="num">{t("sim.topShare", { share: pct(top, top < 0.01 ? 1 : 0) })}</span>
                        </div>
                        <Slider
                          label={label}
                          value={top}
                          min={lo}
                          max={hi}
                          step={0.001}
                          onChange={(v) => {
                            // Keep the bands nested: Critical inside High inside Medium.
                            const next = { ...percentiles, [key]: Math.round((1 - v) * 1000) / 1000 };
                            if (next.high >= next.critical) {
                              if (key === "critical") next.high = Math.round((next.critical - 0.005) * 1000) / 1000;
                              else next.critical = Math.min(0.999, Math.round((next.high + 0.005) * 1000) / 1000);
                            }
                            if (next.medium >= next.high) {
                              if (key === "medium") next.medium = Math.round((next.high - 0.01) * 1000) / 1000;
                              else next.medium = Math.round((next.high - 0.01) * 1000) / 1000;
                            }
                            setPercentiles(next);
                          }}
                        />
                      </div>
                    );
                  })}
                </div>
              </>
            )}
          </CardBody>
        </Card>

        <div className="space-y-4">
          {sim.isError && !r ? <Card><ErrorState error={sim.error} onRetry={() => void sim.refetch()} /></Card> : null}
          <div className="grid grid-cols-2 gap-4 xl:grid-cols-4" data-testid="sim-results">
            <Delta label={t("sim.queue")} before={r?.current.queue} after={r?.simulated.queue} format={count} loading={sim.isFetching} />
            <Delta label={t("common.moneyAtRisk")} before={r?.current.money_at_risk} after={r?.simulated.money_at_risk} format={(n) => inr(n, lang)} loading={sim.isFetching} />
            <Card className="p-5">
              <div className="eyebrow">{t("sim.entering")}</div>
              <div className="num mt-3 flex items-center gap-2 font-display text-2xl font-semibold text-warn"><ArrowUpRight className="size-5" />{r ? count(r.entering.works) : "—"}</div>
              <div className="mt-1 text-xs text-muted">{r ? <Money value={r.entering.amount} /> : null}</div>
            </Card>
            <Card className="p-5">
              <div className="eyebrow">{t("sim.leaving")}</div>
              <div className="num mt-3 flex items-center gap-2 font-display text-2xl font-semibold text-ok"><ArrowDownRight className="size-5" />{r ? count(r.leaving.works) : "—"}</div>
              <div className="mt-1 text-xs text-muted">{r ? <Money value={r.leaving.amount} /> : null}</div>
            </Card>
          </div>

          <Card>
            <CardHeader title={t("sim.bandChart")} hint={r?.note} action={r ? <Badge tone="outline">{t("sim.scopeWorks", { n: count(r.scope_works) })}</Badge> : null} />
            <CardBody className="h-[300px]">
              {r ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chart} margin={{ left: 8, right: 8, top: 8 }}>
                    <CartesianGrid {...grid} />
                    <XAxis dataKey="band" {...axis} />
                    <YAxis {...axis} tickFormatter={(v: number) => count(v)} width={64} />
                    <Tooltip content={<ChartTooltip />} cursor={{ fill: "rgb(var(--raised))" }} />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    <Bar dataKey="current" name={t("sim.current")} fill={colors.info} fillOpacity={0.6} radius={[3, 3, 0, 0]} isAnimationActive={false} />
                    <Bar dataKey="simulated" name={t("sim.simulated")} fill={colors.saffron} radius={[3, 3, 0, 0]} isAnimationActive={false} />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <PanelSkeleton rows={6} className="p-0" />
              )}
            </CardBody>
          </Card>

          <div className="grid gap-4 xl:grid-cols-2">
            <Card>
              <CardHeader title={t("sim.cutoffs")} />
              <CardBody className="space-y-2 text-sm">
                {r ? (["critical", "high", "medium"] as const).map((k) => (
                  <div key={k} className="flex justify-between"><span className="text-muted">{t(`bands.${k[0]!.toUpperCase()}${k.slice(1)}`)}</span><span className="num">≥ {r.cutoffs[k]?.toFixed(2)}</span></div>
                )) : <PanelSkeleton rows={3} className="p-0" />}
                {r?.entering_examples.length ? (
                  <div className="border-t border-line pt-3">
                    <div className="eyebrow mb-2">{t("sim.examples")}</div>
                    <ul className="space-y-1">
                      {r.entering_examples.map((id) => (
                        <li key={id}><Link to={`/works/${id}`} className="font-mono text-2xs text-saffron-text hover:underline">{id}</Link></li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </CardBody>
            </Card>
            <Card>
              <CardHeader title={t("sim.verdicts")} hint={t("sim.verdictsHint")} />
              <CardBody className="space-y-3 text-sm">
                {r && r.verdicts.labelled ? (
                  <>
                    <VerdictRow label={t("sim.confirmedKept")} pair={r.verdicts.confirmed_in_queue ?? [0, 0]} good="up" />
                    <VerdictRow label={t("sim.fpInQueue")} pair={r.verdicts.false_positive_in_queue ?? [0, 0]} good="down" />
                    <p className="text-2xs text-faint">{t("sim.labelled", { n: count(r.verdicts.labelled) })}</p>
                  </>
                ) : (
                  <p className="text-muted">{t("sim.noVerdicts")}</p>
                )}
              </CardBody>
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}

function Delta({ label, before, after, format, loading }: { label: string; before?: number; after?: number; format: (n: number) => string; loading: boolean }) {
  const diff = before !== undefined && after !== undefined ? after - before : 0;
  return (
    <Card className="p-5">
      <div className="flex items-center justify-between">
        <span className="eyebrow">{label}</span>
        {loading ? <Loader2 className="size-3.5 animate-spin text-faint" /> : null}
      </div>
      <div className="num mt-3 font-display text-2xl font-semibold">{after !== undefined ? format(after) : "—"}</div>
      <div className={cn("num mt-1 text-xs", diff > 0 ? "text-warn" : diff < 0 ? "text-ok" : "text-muted")}>
        {before !== undefined ? `${diff > 0 ? "+" : diff < 0 ? "−" : "±"}${format(Math.abs(diff))} · was ${format(before)}` : ""}
      </div>
    </Card>
  );
}

function VerdictRow({ label, pair, good }: { label: string; pair: [number, number]; good: "up" | "down" }) {
  const [now, sim] = pair;
  const better = good === "up" ? sim >= now : sim <= now;
  return (
    <div className="flex items-center justify-between">
      <span className="text-muted">{label}</span>
      <span className={cn("num font-medium", sim === now ? "text-ink" : better ? "text-ok" : "text-warn")}>{count(now)} → {count(sim)}</span>
    </div>
  );
}
