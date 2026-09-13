import { useState } from "react";
import { Link } from "react-router-dom";
import { useLang } from "@/lib/i18n";
import { useApi } from "@/lib/query";
import { count, pct } from "@/lib/format";
import { Caveat } from "@/components/Caveat";
import { PageHeader, PanelSkeleton, QueryState } from "@/components/common";
import { Card, CardBody, CardHeader, Segmented } from "@/components/ui/primitives";
import { Tabs, TabsContent, TabsList } from "@/components/ui/tabs";
import { Tip } from "@/components/ui/tooltip";

interface Rules {
  rules: { key: string; label: string }[];
  rows: { district: string; state: string; works: number; rates: Record<string, number> }[];
  baseline: Record<string, number>;
  note: string;
}
interface Completeness {
  fields: { key: string; label: string }[];
  rows: { district: string; state: string; works: number; shares: Record<string, number> }[];
  note: string;
}

/** Heat for a rate against the national baseline: 1x is neutral, 3x or more is hot. */
function heat(rate: number, baseline: number): string {
  if (!baseline) return "transparent";
  const ratio = rate / baseline;
  if (ratio <= 1) return `rgb(var(--info) / ${0.08 + 0.12 * ratio})`;
  const t = Math.min(1, (ratio - 1) / 2);
  return `rgb(var(--band-high) / ${0.18 + 0.62 * t})`;
}

export default function Compliance() {
  const { t } = useLang();
  const [minWorks, setMinWorks] = useState("50");
  const rules = useApi<Rules>("/compliance/rules", { limit: 40, min_works: minWorks });
  const completeness = useApi<Completeness>("/compliance/completeness", { limit: 40 });

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("nav.compliance")}
        subtitle={t("compliance.subtitle")}
        actions={<Segmented size="sm" label={t("compliance.minWorks")} value={minWorks} onChange={setMinWorks} options={[{ value: "20", label: "≥ 20" }, { value: "50", label: "≥ 50" }, { value: "200", label: "≥ 200" }]} />}
      />
      <Caveat />
      <Tabs defaultValue="rules">
        <TabsList tabs={[{ value: "rules", label: t("compliance.rules") }, { value: "completeness", label: t("compliance.completeness") }]} />
        <TabsContent value="rules" className="pt-4">
          <Card>
            <CardHeader title={t("compliance.rulesTitle")} hint={rules.data?.note} />
            <CardBody className="px-0">
              <QueryState query={rules} skeleton={<PanelSkeleton rows={12} />} isEmpty={(d) => !d.rows.length}>
                {(d) => (
                  <div className="overflow-x-auto" data-testid="rules-heatmap">
                    <table className="w-full border-separate border-spacing-0 text-sm">
                      <thead>
                        <tr>
                          <th className="sticky left-0 bg-surface px-5 pb-3 text-left text-2xs font-medium uppercase tracking-wider text-muted">{t("common.district")}</th>
                          <th className="px-3 pb-3 text-right text-2xs font-medium uppercase tracking-wider text-muted">{t("common.worksCap")}</th>
                          {d.rules.map((r) => (
                            <th key={r.key} className="min-w-[112px] px-2 pb-3 text-center text-2xs font-medium text-muted">
                              <div className="leading-tight">{r.label}</div>
                              <div className="num mt-1 text-faint">{t("compliance.national")} {pct(d.baseline[r.key] ?? 0)}</div>
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {d.rows.map((row) => (
                          <tr key={`${row.district}-${row.state}`}>
                            <td className="sticky left-0 border-t border-line/60 bg-surface px-5 py-1.5">
                              <Link to={`/alerts?district=${encodeURIComponent(row.district)}`} className="font-medium hover:text-saffron-text">{row.district}</Link>
                              <div className="text-2xs text-muted">{row.state}</div>
                            </td>
                            <td className="num border-t border-line/60 px-3 py-1.5 text-right text-muted">{count(row.works)}</td>
                            {d.rules.map((r) => {
                              const rate = row.rates[r.key] ?? 0;
                              const base = d.baseline[r.key] ?? 0;
                              return (
                                <td key={r.key} className="border-t border-line/60 p-1">
                                  <Tip content={`${r.label}: ${count(Math.round(rate * row.works))} of ${count(row.works)} works (${pct(rate)}), national ${pct(base)}`}>
                                    <div tabIndex={0} className="num grid h-9 place-items-center rounded-md text-xs" style={{ background: heat(rate, base) }}>
                                      {rate ? pct(rate, rate < 0.1 ? 1 : 0) : <span className="text-faint">0</span>}
                                    </div>
                                  </Tip>
                                </td>
                              );
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <div className="mt-4 flex items-center gap-3 px-5 text-2xs text-muted">
                      <span>{t("compliance.legendBelow")}</span>
                      <span className="h-3 w-10 rounded" style={{ background: "rgb(var(--info) / 0.18)" }} />
                      <span className="h-3 w-10 rounded" style={{ background: "rgb(var(--band-high) / 0.3)" }} />
                      <span className="h-3 w-10 rounded" style={{ background: "rgb(var(--band-high) / 0.8)" }} />
                      <span>{t("compliance.legendAbove")}</span>
                    </div>
                  </div>
                )}
              </QueryState>
            </CardBody>
          </Card>
        </TabsContent>
        <TabsContent value="completeness" className="pt-4">
          <Card>
            <CardHeader title={t("compliance.completenessTitle")} hint={completeness.data?.note} />
            <CardBody className="px-0">
              <QueryState query={completeness} skeleton={<PanelSkeleton rows={12} />} isEmpty={(d) => !d.rows.length}>
                {(d) => (
                  <div className="overflow-x-auto" data-testid="completeness-matrix">
                    <table className="w-full border-separate border-spacing-0 text-sm">
                      <thead>
                        <tr>
                          <th className="px-5 pb-3 text-left text-2xs font-medium uppercase tracking-wider text-muted">{t("common.district")}</th>
                          <th className="px-3 pb-3 text-right text-2xs font-medium uppercase tracking-wider text-muted">{t("common.worksCap")}</th>
                          {d.fields.map((f) => (
                            <th key={f.key} className="min-w-[120px] px-2 pb-3 text-center text-2xs font-medium text-muted">{f.label}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {d.rows.map((row) => (
                          <tr key={`${row.district}-${row.state}`}>
                            <td className="border-t border-line/60 px-5 py-1.5">
                              <div className="font-medium">{row.district}</div>
                              <div className="text-2xs text-muted">{row.state}</div>
                            </td>
                            <td className="num border-t border-line/60 px-3 py-1.5 text-right text-muted">{count(row.works)}</td>
                            {d.fields.map((f) => {
                              const share = row.shares[f.key] ?? 0;
                              return (
                                <td key={f.key} className="border-t border-line/60 p-1">
                                  <div
                                    className="num grid h-9 place-items-center rounded-md text-xs"
                                    style={{ background: share >= 0.99 ? "rgb(var(--ok) / 0.14)" : `rgb(var(--danger) / ${0.12 + 0.5 * (1 - share)})` }}
                                    title={`${f.label}: ${pct(share)} of ${count(row.works)} works`}
                                  >
                                    {pct(share, 0)}
                                  </div>
                                </td>
                              );
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </QueryState>
            </CardBody>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
