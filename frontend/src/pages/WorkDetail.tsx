import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, CalendarClock, CircleDollarSign, Clock3, Receipt } from "lucide-react";
import { idPath } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import { useApi } from "@/lib/query";
import { count, date, pct } from "@/lib/format";
import type { ModelsSummary, WorkDetail as Work } from "@/lib/types";
import { alertTypeLabel, bandColor } from "@/lib/utils";
import { Caveat } from "@/components/Caveat";
import { BandBadge, Money, PanelSkeleton, QueryState, RiskDial } from "@/components/common";
import { AttributionBars, AuditTimeline, Completeness, CostCheck, PeerChart, Reasons, RulesFired, Section, SignalBars, WhatWouldClear } from "@/components/evidence";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardBody, CardHeader } from "@/components/ui/primitives";

export default function WorkDetail() {
  const { t, lang } = useLang();
  const navigate = useNavigate();
  const workId = useParams()["*"] ?? "";
  const work = useApi<Work>(workId ? `/works/${idPath(workId)}` : null, undefined, { placeholderData: undefined });
  const models = useApi<ModelsSummary>("/models/summary", undefined, { staleTime: Infinity });
  const delayThreshold = models.data?.thresholds.high_delay_risk ?? Infinity;

  return (
    <div className="space-y-6">
      <Button variant="ghost" size="sm" onClick={() => navigate(-1)}>
        <ArrowLeft /> {t("work.back")}
      </Button>
      <QueryState query={work} skeleton={<Card><PanelSkeleton rows={10} /></Card>}>
        {(w) => (
          <>
            <Card className="p-6">
              <div className="flex flex-wrap items-start gap-6">
                <RiskDial score={w.risk_score} band={w.band} size={104} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <BandBadge band={w.band} />
                    <Badge tone="outline">{w.work_type}</Badge>
                    <Badge tone="neutral">{w.work_status}</Badge>
                    {w.severe_floor_applied ? <Badge tone="danger">{t("work.floorApplied")} · {t("work.baseScore")} {w.base_risk_score.toFixed(1)}</Badge> : null}
                    {w.source !== "training" ? <Badge tone="info">{w.source}</Badge> : null}
                  </div>
                  <h1 className="mt-3 font-display text-2xl font-semibold leading-snug" data-testid="work-title">
                    {w.work_description}
                  </h1>
                  <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm text-muted">
                    <span className="font-mono text-xs">{w.work_id}</span>
                    <span>{w.district}, {w.state}</span>
                    <span>{t("work.constituency")}: {w.constituency ?? "—"}</span>
                    <span>{t("work.agency")}: {w.ida}</span>
                    <span>{t("work.vendor")}: {w.vendor_name ?? "—"}</span>
                  </div>
                  <p className="mt-3 text-xs text-faint">{t("app.framing")}</p>
                </div>
              </div>
              <div className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
                <Fact icon={<CircleDollarSign className="size-4" />} label={t("common.sanctioned")} value={<Money value={w.sanction_amount} />} />
                <Fact
                  icon={<Receipt className="size-4" />}
                  label={t("work.disbursedShare")}
                  value={w.total_fund_disbursed === null ? "—" : pct(w.total_fund_disbursed / Math.max(w.sanction_amount, 1), 0)}
                  sub={w.total_fund_disbursed === null ? undefined : <Money value={w.total_fund_disbursed} />}
                />
                <Fact icon={<CalendarClock className="size-4" />} label={t("work.daysSince")} value={w.days_since_sanction === null ? "—" : count(w.days_since_sanction)} sub={w.is_open ? t("work.notCompleted") : `${t("work.completed")} ${date(w.completion_date, lang)}`} />
                <Fact icon={<Clock3 className="size-4" />} label={t("common.delayRisk")} value={w.is_open ? pct(w.delay_risk, 0) : "—"} valueColor={w.is_open && w.delay_risk >= delayThreshold ? bandColor("High") : undefined} sub={w.is_open ? "open work, probability of running past a year" : "completed"} />
              </div>
            </Card>

            <Caveat />

            <div className="grid gap-4 xl:grid-cols-12">
              <div className="space-y-4 xl:col-span-7">
                <Card>
                  <CardHeader title={t("work.reasons")} />
                  <CardBody>
                    <Reasons en={w.reasons_en} hi={w.reasons_hi} />
                  </CardBody>
                </Card>
                <Card>
                  <CardHeader title={t("work.cost")} />
                  <CardBody className="space-y-5">
                    <CostCheck work={w} />
                    <PeerChart workId={w.work_id} />
                  </CardBody>
                </Card>
                <Card>
                  <CardHeader title={t("clear.title")} hint={t("clear.hint")} />
                  <CardBody>
                    <WhatWouldClear workId={w.work_id} />
                  </CardBody>
                </Card>
                <Card>
                  <CardHeader title={t("alerts.drivers")} />
                  <CardBody>
                    <AttributionBars attributions={w.attributions} />
                  </CardBody>
                </Card>
              </div>
              <div className="space-y-4 xl:col-span-5">
                <Card>
                  <CardHeader title={t("alerts.signalChannels")} hint={t("alerts.signalHint")} />
                  <CardBody>
                    <SignalBars signals={w.signals} />
                  </CardBody>
                </Card>
                <Card>
                  <CardHeader title={t("work.timeline")} hint={t("work.snapshot")} />
                  <CardBody>
                    <ol className="relative space-y-3 border-l border-line pl-5">
                      {[
                        [t("work.recommended"), w.recommended_date],
                        [t("work.sanctionedOn"), w.sanction_date],
                        [t("work.lastExpenditure"), w.latest_expenditure_date],
                        [t("work.completed"), w.completion_date],
                      ].map(([label, value]) => (
                        <li key={label} className="relative text-sm">
                          <span className={`absolute -left-[25px] top-1.5 size-2.5 rounded-full border-2 border-surface ${value ? "bg-saffron" : "bg-line"}`} />
                          <span className="text-muted">{label}</span>
                          <span className="num float-right">{value ? date(value, lang) : "—"}</span>
                        </li>
                      ))}
                    </ol>
                    <div className="mt-4 flex flex-wrap gap-2 text-xs text-muted">
                      <Badge tone="outline">{t("work.payments")}: {w.num_payments ?? "—"}</Badge>
                      {w.latest_payment_status ? <Badge tone="outline">{w.latest_payment_status}</Badge> : null}
                      {w.days_to_sanction !== null ? <Badge tone="outline">{count(w.days_to_sanction)} days to sanction</Badge> : null}
                      {w.duration_days !== null ? <Badge tone="outline">{count(w.duration_days)} days to completion</Badge> : null}
                    </div>
                  </CardBody>
                </Card>
                <Card>
                  <CardHeader title={t("alerts.rulesFired")} />
                  <CardBody>
                    <RulesFired rules={w.rules} severe={w.severe_rules} />
                  </CardBody>
                </Card>
                <Card>
                  <CardHeader title={t("alerts.completeness")} />
                  <CardBody>
                    <Completeness items={w.data_completeness} />
                  </CardBody>
                </Card>
                {w.alerts.length ? (
                  <Card>
                    <CardHeader title={t("work.relatedAlerts")} />
                    <CardBody className="space-y-2">
                      {w.alerts.map((a) => (
                        <Link key={a.alert_id} to={`/alerts?id=${encodeURIComponent(a.alert_id)}`} className="flex items-center justify-between rounded-md border border-line px-3 py-2 text-sm hover:border-saffron/40">
                          <span>
                            <span className="block font-medium">{alertTypeLabel(a.alert_type)}</span>
                            <span className="block font-mono text-2xs text-muted">{a.alert_id}</span>
                          </span>
                          <span className="flex items-center gap-2">
                            <Badge tone="outline">{a.status}</Badge>
                            <BandBadge band={a.severity} />
                          </span>
                        </Link>
                      ))}
                    </CardBody>
                  </Card>
                ) : null}
                {w.similar_works.length ? (
                  <Card>
                    <CardHeader title={t("work.similar")} />
                    <CardBody className="space-y-2">
                      {w.similar_works.map((s) => (
                        <Link key={s.pair_id} to={`/duplicates?pair=${s.pair_id}`} className="block rounded-md border border-line px-3 py-2 text-sm hover:border-saffron/40">
                          <div className="flex items-center justify-between gap-3">
                            <span className="truncate">{s.work_description}</span>
                            <span className="num shrink-0 font-semibold">{pct(s.pair_score, 0)}</span>
                          </div>
                          <div className="mt-0.5 flex justify-between text-2xs text-muted">
                            <span className="font-mono">{s.work_id}</span>
                            <span><Money value={s.sanction_amount} /> · {date(s.sanction_date, lang)}</span>
                          </div>
                        </Link>
                      ))}
                    </CardBody>
                  </Card>
                ) : null}
                <Card>
                  <CardHeader title={t("alerts.audit")} />
                  <CardBody>
                    <AuditTimeline events={w.audit} />
                  </CardBody>
                </Card>
              </div>
            </div>
          </>
        )}
      </QueryState>
      {!workId ? <Section title="No work selected"><p className="text-sm text-muted">Open a work from the alerts inbox or search.</p></Section> : null}
    </div>
  );
}

function Fact({ icon, label, value, sub, valueColor }: { icon: React.ReactNode; label: string; value: React.ReactNode; sub?: React.ReactNode; valueColor?: string }) {
  return (
    <div className="rounded-lg border border-line bg-bg/40 p-4">
      <div className="flex items-center gap-2 text-xs text-muted">
        {icon} {label}
      </div>
      <div className="num mt-2 font-display text-xl font-semibold" style={valueColor ? { color: valueColor } : undefined}>
        {value}
      </div>
      {sub ? <div className="mt-0.5 text-2xs text-muted">{sub}</div> : null}
    </div>
  );
}
