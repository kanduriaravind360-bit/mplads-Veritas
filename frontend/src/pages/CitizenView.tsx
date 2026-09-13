import { useState } from "react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Building2, CheckCircle2, Languages, LogIn, MapPin, Search, Shield, Wallet } from "lucide-react";
import { setLang, useLang } from "@/lib/i18n";
import { useApi } from "@/lib/query";
import { count, inr, monthLabel, ofTotal, pct } from "@/lib/format";
import { axis, ChartTooltip, colors, grid } from "@/components/charts";
import { EmptyState, KpiCard, PanelSkeleton, QueryState, useDebounced } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, Input, Select } from "@/components/ui/primitives";

interface Summary {
  works: number;
  sanctioned: number;
  disbursed: number;
  completed: number;
  completion_rate: number;
  districts: number;
  states: number;
  note: string;
}
interface DistrictList {
  districts: { district: string; state: string; works: number; ida: string }[];
  states: string[];
  note: string;
}
interface District {
  district: string;
  state: string;
  works: number;
  sanctioned: number;
  disbursed: number;
  completed: number;
  completion_rate: number;
  asset_types: { work_type: string; works: number; sanctioned: number }[];
  status_mix: { status: string; works: number }[];
  monthly: { month: string; works: number; sanctioned: number }[];
  note: string;
}

/**
 * The citizen view: what was sanctioned, spent and completed, by district.
 * Public and read-only. It never shows a risk score or a flag for any work.
 */
export default function CitizenView() {
  const { t, lang } = useLang();
  const [query, setQuery] = useState("");
  const [state, setState] = useState("");
  const [picked, setPicked] = useState<{ district: string; ida: string } | null>(null);
  const q = useDebounced(query, 250);
  const summary = useApi<Summary>("/public/summary", undefined, { staleTime: Infinity });
  const list = useApi<DistrictList>("/public/districts", { q: q || undefined, state: state || undefined, limit: 60 });
  const detail = useApi<District>(
    picked ? `/public/districts/${encodeURIComponent(picked.district)}` : null,
    picked ? { ida: picked.ida } : undefined,
    { placeholderData: undefined },
  );

  return (
    <div className="min-h-full bg-bg">
      <header className="border-b border-line bg-surface/70">
        <div className="mx-auto flex h-16 max-w-[1440px] items-center gap-3 px-8">
          <div className="grid size-9 place-items-center rounded-md bg-navy ring-1 ring-saffron/40">
            <Shield className="size-4 text-saffron" />
          </div>
          <div className="leading-tight">
            <div className="font-display font-semibold">{t("citizen.title")}</div>
            <div className="text-2xs text-muted">MPLADS · {t("citizen.tagline")}</div>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => setLang(lang === "hi" ? "en" : "hi")}>
              <Languages /> {t("common.language")}
            </Button>
            <Button asChild variant="outline" size="sm">
              <Link to="/login"><LogIn /> {t("citizen.officialLogin")}</Link>
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1440px] space-y-6 px-8 py-8">
        <div>
          <h1 className="font-display text-[32px] font-semibold">{t("citizen.heading")}</h1>
          <p className="mt-1 max-w-3xl text-sm text-muted">{summary.data?.note}</p>
        </div>

        <div className="grid grid-cols-2 gap-4 xl:grid-cols-4" data-testid="citizen-kpis">
          {summary.data ? (
            <>
              <KpiCard label={t("common.worksCap")} value={summary.data.works} icon={<Building2 className="size-4" />} sub={t("citizen.coverage", { districts: count(summary.data.districts), states: count(summary.data.states) })} />
              <KpiCard label={t("common.sanctioned")} value={summary.data.sanctioned} kind="money" />
              <KpiCard label={t("common.disbursed")} value={summary.data.disbursed} kind="money" icon={<Wallet className="size-4" />} sub={`${pct(summary.data.disbursed / Math.max(summary.data.sanctioned, 1))} ${t("common.utilisation").toLowerCase()}`} />
              <KpiCard label={t("command.kpiCompletion")} value={summary.data.completion_rate} kind="percent" icon={<CheckCircle2 className="size-4" />} sub={ofTotal(summary.data.completed, summary.data.works, lang)} />
            </>
          ) : (
            [0, 1, 2, 3].map((i) => <Card key={i} className="h-[132px]"><PanelSkeleton rows={2} /></Card>)
          )}
        </div>

        <div className="grid gap-4 xl:grid-cols-[380px_1fr]">
          <Card>
            <CardHeader title={t("citizen.find")} />
            <CardBody className="space-y-3">
              <div className="relative">
                <Search className="pointer-events-none absolute left-3 top-2.5 size-4 text-faint" />
                <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("citizen.searchPlaceholder")} className="pl-9" aria-label={t("citizen.find")} />
              </div>
              <Select value={state} onChange={(e) => setState(e.target.value)} aria-label={t("common.state")} className="w-full">
                <option value="">{t("citizen.allStates")}</option>
                {list.data?.states.map((s) => <option key={s} value={s}>{s}</option>)}
              </Select>
              <QueryState query={list} skeleton={<PanelSkeleton rows={8} className="p-0" />} isEmpty={(d) => !d.districts.length}>
                {(d) => (
                  <ul className="max-h-[560px] space-y-1 overflow-y-auto" data-testid="citizen-districts">
                    {d.districts.map((row) => (
                      <li key={row.ida}>
                        <button
                          type="button"
                          onClick={() => setPicked({ district: row.district, ida: row.ida })}
                          className={`flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm hover:bg-raised ${picked?.ida === row.ida ? "bg-raised" : ""}`}
                        >
                          <MapPin className="size-4 text-muted" />
                          <span className="min-w-0 flex-1">
                            <span className="block truncate font-medium">{row.district}</span>
                            <span className="block text-2xs text-muted">{row.state}</span>
                          </span>
                          <span className="num text-xs text-muted">{count(row.works)}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </QueryState>
            </CardBody>
          </Card>

          {!picked ? (
            <Card><EmptyState icon={<MapPin className="size-5" />} title={t("citizen.pick")} body={t("citizen.pickBody")} /></Card>
          ) : (
            <QueryState query={detail} skeleton={<Card><PanelSkeleton rows={10} /></Card>}>
              {(dd) => (
                <div className="space-y-4" data-testid="citizen-district">
                  <Card className="p-6">
                    <div className="eyebrow">{dd.state}</div>
                    <h2 className="mt-1 font-display text-2xl font-semibold">{dd.district}</h2>
                    <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
                      <Fact label={t("common.worksCap")} value={count(dd.works)} />
                      <Fact label={t("common.sanctioned")} value={inr(dd.sanctioned, lang)} />
                      <Fact label={t("common.disbursed")} value={inr(dd.disbursed, lang)} />
                      <Fact label={t("command.kpiCompletion")} value={ofTotal(dd.completed, dd.works, lang)} />
                    </div>
                  </Card>
                  <div className="grid gap-4 xl:grid-cols-2">
                    <Card>
                      <CardHeader title={t("citizen.assets")} />
                      <CardBody className="space-y-2">
                        {dd.asset_types.map((a) => (
                          <div key={a.work_type} className="grid grid-cols-[1fr_auto] gap-2 text-sm">
                            <span className="truncate">{a.work_type}</span>
                            <span className="num text-muted">{count(a.works)} · {inr(a.sanctioned, lang)}</span>
                            <div className="col-span-2 h-1.5 rounded-full bg-raised"><div className="h-full rounded-full bg-info/70" style={{ width: pct(a.sanctioned / Math.max(dd.sanctioned, 1)) }} /></div>
                          </div>
                        ))}
                      </CardBody>
                    </Card>
                    <Card>
                      <CardHeader title={t("citizen.status")} />
                      <CardBody className="space-y-2">
                        {[...dd.status_mix].sort((a, b) => b.works - a.works).map((s) => (
                          <div key={s.status} className="flex justify-between rounded-md border border-line/60 px-3 py-2 text-sm">
                            <span>{s.status}</span>
                            <span className="num">{ofTotal(s.works, dd.works, lang)}</span>
                          </div>
                        ))}
                      </CardBody>
                    </Card>
                  </div>
                  <Card>
                    <CardHeader title={t("command.monthly")} />
                    <CardBody className="h-[260px]">
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={dd.monthly} margin={{ left: 0, right: 8, top: 8 }}>
                          <CartesianGrid {...grid} />
                          <XAxis dataKey="month" {...axis} tickFormatter={(m: string) => monthLabel(m, lang)} interval={2} />
                          <YAxis {...axis} tickFormatter={(v: number) => inr(v, lang)} width={64} />
                          <Tooltip content={<ChartTooltip money={["sanctioned"]} labelFormat="month" />} cursor={{ fill: "rgb(var(--raised))" }} />
                          <Bar dataKey="sanctioned" name={t("common.sanctioned")} fill={colors.info} radius={[3, 3, 0, 0]} isAnimationActive={false} />
                        </BarChart>
                      </ResponsiveContainer>
                    </CardBody>
                  </Card>
                  <p className="text-xs text-muted">{dd.note}</p>
                </div>
              )}
            </QueryState>
          )}
        </div>
      </main>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-line bg-bg/40 p-4">
      <div className="text-2xs text-muted">{label}</div>
      <div className="num mt-1 font-display text-lg font-semibold">{value}</div>
    </div>
  );
}
