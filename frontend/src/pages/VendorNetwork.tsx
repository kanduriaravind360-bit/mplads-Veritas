import { useMemo, useState } from "react";
import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY, type SimulationLinkDatum, type SimulationNodeDatum } from "d3-force";
import { Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useLang } from "@/lib/i18n";
import { useApi } from "@/lib/query";
import { count, inr, pct } from "@/lib/format";
import type { ModelsSummary } from "@/lib/types";
import { bandColor, cn } from "@/lib/utils";
import { axis, ChartTooltip, colors, grid } from "@/components/charts";
import { Caveat } from "@/components/Caveat";
import { Money, PageHeader, PanelSkeleton, QueryState } from "@/components/common";
import { Badge, Card, CardBody, CardHeader, Segmented } from "@/components/ui/primitives";

interface GraphNode {
  id: string;
  type: "vendor" | "district";
  label: string;
  works?: number;
  value: number;
  mean_risk?: number;
  high_or_critical?: number;
}
interface GraphEdge {
  source: string;
  target: string;
  type: "works_in" | "similar_name";
  works?: number;
  value?: number;
  similarity?: number;
}
interface Graph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  similar_name_edges: number;
  note: string;
}
interface Concentration {
  rows: { district: string; state: string; works: number; value: number; vendors: number; hhi: number; concentration: string; top_vendor: string | null; top_vendor_share: number; top_vendor_works: number }[];
  note: string;
}
interface BenfordSeries {
  n: number;
  digits: { digit: number; observed: number; expected: number; count: number }[];
  mad: number;
  conformity: string;
}
interface Benford {
  all_amounts: BenfordSeries;
  excluding_round_lakh: BenfordSeries;
  round_lakh_share: number;
  note: string;
}

type SimNode = GraphNode & SimulationNodeDatum & { r: number };
type SimLink = SimulationLinkDatum<SimNode> & GraphEdge;

const W = 1000;
const H = 720;

/** Colour a vendor's mean risk with the pipeline's own band cut-offs (from metrics). */
function riskColour(mean: number | undefined, cutoffs: ModelsSummary["band_cutoffs"] | undefined): string {
  if (mean === undefined || !cutoffs) return "rgb(var(--faint))";
  if (mean >= cutoffs.critical) return bandColor("Critical");
  if (mean >= cutoffs.high) return bandColor("High");
  if (mean >= cutoffs.medium) return bandColor("Medium");
  return bandColor("Low");
}

function useLayout(graph: Graph | undefined) {
  return useMemo(() => {
    if (!graph) return null;
    const maxValue = Math.max(...graph.nodes.map((n) => n.value), 1);
    const nodes: SimNode[] = graph.nodes.map((n) => ({
      ...n,
      r: n.type === "vendor" ? 7 + 26 * Math.sqrt(n.value / maxValue) : 5 + 9 * Math.sqrt(n.value / maxValue),
    }));
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const links: SimLink[] = graph.edges.filter((e) => byId.has(e.source) && byId.has(e.target)).map((e) => ({ ...e }));
    const simulation = forceSimulation(nodes)
      .force("link", forceLink<SimNode, SimLink>(links).id((d) => d.id).distance((l) => (l.type === "similar_name" ? 36 : 48)).strength((l) => (l.type === "similar_name" ? 0.7 : 0.5)))
      .force("charge", forceManyBody().strength(-60))
      .force("collide", forceCollide<SimNode>().radius((d) => d.r + 4))
      // Most vendors work in one district, so the graph is many small components;
      // gentle x/y pulls pack them into one readable cluster.
      .force("x", forceX(W / 2).strength(0.07))
      .force("y", forceY(H / 2).strength(0.1))
      .force("center", forceCenter(W / 2, H / 2))
      .stop();
    // Deterministic: a fixed number of ticks from the same start, no animation jitter in screenshots.
    for (let i = 0; i < 320; i++) simulation.tick();
    const xs = nodes.map((n) => n.x ?? 0);
    const ys = nodes.map((n) => n.y ?? 0);
    const pad = 40;
    const box = { x: Math.min(...xs) - pad, y: Math.min(...ys) - pad, w: Math.max(...xs) - Math.min(...xs) + 2 * pad, h: Math.max(...ys) - Math.min(...ys) + 2 * pad };
    const neighbours = new Map<string, Set<string>>();
    for (const l of links) {
      const s = (l.source as SimNode).id;
      const t = (l.target as SimNode).id;
      if (!neighbours.has(s)) neighbours.set(s, new Set());
      if (!neighbours.has(t)) neighbours.set(t, new Set());
      neighbours.get(s)?.add(t);
      neighbours.get(t)?.add(s);
    }
    return { nodes, links, box, neighbours };
  }, [graph]);
}

export default function VendorNetwork() {
  const { t, lang } = useLang();
  const [limit, setLimit] = useState("60");
  const [hover, setHover] = useState<string | null>(null);
  const [benfordView, setBenfordView] = useState<"all" | "ex">("ex");
  const graph = useApi<Graph>("/network/vendors", { limit });
  const concentration = useApi<Concentration>("/network/concentration", { limit: 12 });
  const benford = useApi<Benford>("/network/benford");
  const models = useApi<ModelsSummary>("/models/summary", undefined, { staleTime: Infinity });
  const cutoffs = models.data?.band_cutoffs;
  const layout = useLayout(graph.data);
  const active = hover ? new Set([hover, ...(layout?.neighbours.get(hover) ?? [])]) : null;
  const hovered = layout?.nodes.find((n) => n.id === hover);

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("nav.network")}
        subtitle={t("network.subtitle")}
        actions={<Segmented size="sm" label={t("network.vendorsShown")} value={limit} onChange={setLimit} options={[{ value: "40", label: "40" }, { value: "60", label: "60" }, { value: "120", label: "120" }]} />}
      />
      <Caveat />
      <div className="grid gap-4 xl:grid-cols-12">
        <Card className="relative overflow-hidden xl:col-span-8">
          <CardHeader
            title={t("network.graph")}
            hint={graph.data?.note}
            action={graph.data ? <Badge tone={graph.data.similar_name_edges ? "saffron" : "outline"}>{t("network.similarEdges", { n: graph.data.similar_name_edges })}</Badge> : null}
          />
          <QueryState query={graph} skeleton={<PanelSkeleton rows={12} />}>
            {() =>
              layout ? (
                <div className="relative" data-testid="vendor-graph">
                  <svg viewBox={`${layout.box.x} ${layout.box.y} ${layout.box.w} ${layout.box.h}`} className="h-[640px] w-full" role="img" aria-label={t("network.graph")}>
                    {layout.links.map((l, i) => {
                      const s = l.source as SimNode;
                      const tg = l.target as SimNode;
                      const on = !active || (active.has(s.id) && active.has(tg.id));
                      return (
                        <line
                          key={i}
                          x1={s.x}
                          y1={s.y}
                          x2={tg.x}
                          y2={tg.y}
                          stroke={l.type === "similar_name" ? colors.saffron : "rgb(var(--muted))"}
                          strokeOpacity={on ? (l.type === "similar_name" ? 0.9 : 0.28) : 0.05}
                          strokeWidth={l.type === "similar_name" ? 2 : 1}
                          strokeDasharray={l.type === "similar_name" ? "5 4" : undefined}
                        />
                      );
                    })}
                    {layout.nodes.map((n) => {
                      const on = !active || active.has(n.id);
                      return (
                        <g key={n.id} transform={`translate(${n.x},${n.y})`} opacity={on ? 1 : 0.18} onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)} className="cursor-pointer">
                          {n.type === "vendor" ? (
                            <circle r={n.r} fill={riskColour(n.mean_risk, cutoffs)} fillOpacity={0.85} stroke="rgb(var(--surface))" strokeWidth={1.5} />
                          ) : (
                            <rect x={-n.r} y={-n.r} width={n.r * 2} height={n.r * 2} rx={2} fill="rgb(var(--info))" fillOpacity={0.55} stroke="rgb(var(--surface))" />
                          )}
                          {(n.type === "vendor" && n.r > 16) || hover === n.id ? (
                            <text y={n.r + 13} textAnchor="middle" className="fill-[rgb(var(--ink))] text-[11px]" style={{ paintOrder: "stroke", stroke: "rgb(var(--surface))", strokeWidth: 3 }}>
                              {n.label}
                            </text>
                          ) : null}
                        </g>
                      );
                    })}
                  </svg>
                  <div className="pointer-events-none absolute left-4 top-2 space-y-1 rounded-md border border-line bg-surface/90 p-3 text-2xs text-muted">
                    <div className="flex items-center gap-2"><span className="size-2.5 rounded-full" style={{ background: bandColor("Critical") }} /> {t("network.legendVendor")}</div>
                    <div className="flex items-center gap-2"><span className="size-2.5 rounded-sm bg-info/60" /> {t("common.district")}</div>
                    <div className="flex items-center gap-2"><span className="w-4 border-t-2 border-dashed border-saffron" /> {t("network.legendSimilar")}</div>
                  </div>
                  {hovered ? (
                    <div className="absolute right-4 top-2 w-64 rounded-md border border-line bg-raised p-3 text-xs shadow-pop">
                      <div className="font-semibold text-ink">{hovered.label}</div>
                      <div className="text-muted">{hovered.type === "vendor" ? t("work.vendor") : t("common.district")}</div>
                      <div className="mt-2 grid grid-cols-2 gap-1">
                        <span className="text-muted">{t("common.sanctioned")}</span><span className="num text-right">{inr(hovered.value, lang)}</span>
                        {hovered.works !== undefined ? <><span className="text-muted">{t("common.worksCap")}</span><span className="num text-right">{count(hovered.works)}</span></> : null}
                        {hovered.mean_risk !== undefined ? <><span className="text-muted">{t("map.metricRisk")}</span><span className="num text-right">{hovered.mean_risk.toFixed(1)}</span></> : null}
                        {hovered.high_or_critical !== undefined && hovered.works ? <><span className="text-muted">{t("common.highOrCritical")}</span><span className="num text-right">{count(hovered.high_or_critical)} / {count(hovered.works)}</span></> : null}
                      </div>
                    </div>
                  ) : null}
                </div>
              ) : null
            }
          </QueryState>
        </Card>

        <div className="space-y-4 xl:col-span-4">
          <Card>
            <CardHeader title={t("network.concentration")} hint={concentration.data?.note} />
            <CardBody className="px-0 pb-2">
              <QueryState query={concentration} isEmpty={(d) => !d.rows.length}>
                {(d) => (
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-line text-left text-2xs uppercase tracking-wider text-muted">
                        <th className="px-5 pb-2 font-medium">{t("common.district")}</th>
                        <th className="px-2 pb-2 text-right font-medium">HHI</th>
                        <th className="px-5 pb-2 text-right font-medium">{t("network.topShare")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {d.rows.map((r) => (
                        <tr key={`${r.district}-${r.state}`} className="border-b border-line/50 last:border-0">
                          <td className="px-5 py-2">
                            <div className="font-medium">{r.district}</div>
                            <div className="text-2xs text-muted">{r.state} · {t("network.vendorsOfWorks", { vendors: count(r.vendors), works: count(r.works) })}</div>
                          </td>
                          <td className="px-2 py-2 text-right">
                            <span className={cn("num font-semibold", r.hhi >= 2500 && "text-warn")}>{count(r.hhi)}</span>
                          </td>
                          <td className="px-5 py-2 text-right">
                            <div className="num">{pct(r.top_vendor_share, 0)}</div>
                            <div className="truncate text-2xs text-muted" title={r.top_vendor ?? ""}>{r.top_vendor}</div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </QueryState>
            </CardBody>
          </Card>
          <Card>
            <CardHeader
              title={t("network.benford")}
              hint={benford.data?.note}
              action={<Segmented size="sm" label={t("network.benford")} value={benfordView} onChange={setBenfordView} options={[{ value: "ex", label: t("network.exRound") }, { value: "all", label: t("common.all") }]} />}
            />
            <CardBody>
              <QueryState query={benford}>
                {(b) => {
                  const series = benfordView === "all" ? b.all_amounts : b.excluding_round_lakh;
                  return (
                    <div data-testid="benford">
                      <div className="h-[220px]">
                        <ResponsiveContainer width="100%" height="100%">
                          <ComposedChart data={series.digits.map((d) => ({ ...d, observed: d.observed * 100, expected: d.expected * 100 }))} margin={{ left: -12, right: 8, top: 8 }}>
                            <CartesianGrid {...grid} />
                            <XAxis dataKey="digit" {...axis} />
                            <YAxis {...axis} tickFormatter={(v: number) => `${v}%`} />
                            <Tooltip content={<ChartTooltip />} cursor={{ fill: "rgb(var(--raised))" }} formatter={(v: number) => `${v.toFixed(1)}%`} />
                            <Bar dataKey="observed" name={t("network.observed")} fill={colors.info} radius={[3, 3, 0, 0]} isAnimationActive={false} />
                            <Line dataKey="expected" name={t("network.expected")} stroke={colors.saffron} strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
                          </ComposedChart>
                        </ResponsiveContainer>
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2 text-xs">
                        <Badge tone="outline">n = {count(series.n)}</Badge>
                        <Badge tone="outline">MAD {series.mad.toFixed(4)}</Badge>
                        <Badge tone={series.conformity === "nonconformity" ? "warn" : "ok"}>{series.conformity}</Badge>
                        <Badge tone="outline">{t("network.roundShare", { share: pct(b.round_lakh_share, 0) })}</Badge>
                      </div>
                    </div>
                  );
                }}
              </QueryState>
            </CardBody>
          </Card>
        </div>
      </div>
      <p className="text-xs text-muted">
        <Money value={graph.data?.nodes.filter((n) => n.type === "vendor").reduce((s, n) => s + n.value, 0) ?? null} /> {t("network.footer")}
      </p>
    </div>
  );
}
