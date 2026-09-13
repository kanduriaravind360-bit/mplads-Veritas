import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Layers, X } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useLang } from "@/lib/i18n";
import { useApi } from "@/lib/query";
import { count, date, inr, pct } from "@/lib/format";
import type { AuditEvent, Page, WorkDetail, WorkSummary } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Caveat } from "@/components/Caveat";
import { BandBadge, EmptyState, ErrorState, Money, PageHeader, PanelSkeleton, QueryState } from "@/components/common";
import { AuditTimeline, Section, WorksTable } from "@/components/evidence";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardBody, CardHeader, Meter, Segmented, Textarea } from "@/components/ui/primitives";
import { Tabs, TabsContent, TabsList } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/toast";

interface PairFields {
  pair_id: number;
  pair_score: number;
  dup_group_id: string | null;
  decision: "duplicate" | "not_duplicate" | null;
  days_apart: number | null;
  is_standard_item: boolean;
  shared_location_words: string | null;
  breakdown: { component: string; key: string; value: number; weight: number }[];
}
interface PairRow extends PairFields {
  work_a: WorkSummary;
  work_b: WorkSummary;
}
interface PairDetail extends PairFields {
  work_a: WorkDetail;
  work_b: WorkDetail;
  diff: { op: "equal" | "removed" | "added"; text: string }[];
  audit: AuditEvent[];
}
interface SplitGroup {
  split_group_id: string;
  state: string;
  ida: string;
  work_type: string;
  vendor_name: string | null;
  same_vendor: boolean;
  n_works: number;
  work_ids: string[];
  total_amount: number;
  split_score: number;
  detail: Record<string, number | string | null>;
}

const PAGE = 40;

export default function DuplicateFinder() {
  const { t } = useLang();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "pairs";
  return (
    <div className="space-y-6">
      <PageHeader title={t("nav.duplicates")} subtitle={t("dup.subtitle")} />
      <Caveat />
      <Tabs value={tab} onValueChange={(value) => setParams({ tab: value }, { replace: true })}>
        <TabsList tabs={[{ value: "pairs", label: t("dup.pairs") }, { value: "splits", label: t("dup.splits") }]} />
        <TabsContent value="pairs" className="pt-4">
          <Pairs />
        </TabsContent>
        <TabsContent value="splits" className="pt-4">
          <Splits />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function Pairs() {
  const { t, lang } = useLang();
  const [params, setParams] = useSearchParams();
  const [minScore, setMinScore] = useState("0.9");
  const [decision, setDecision] = useState("undecided");
  const [offset, setOffset] = useState(0);
  const selected = params.get("pair") ? Number(params.get("pair")) : null;
  const list = useApi<Page<PairRow>>("/duplicates", { min_score: minScore, decision: decision === "all" ? undefined : decision, limit: PAGE, offset });

  useEffect(() => setOffset(0), [minScore, decision]);
  useEffect(() => {
    const first = list.data?.items[0];
    if (!selected && first) setParams((p) => { const n = new URLSearchParams(p); n.set("pair", String(first.pair_id)); return n; }, { replace: true });
  }, [list.data, selected, setParams]);

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      <Card className="min-w-0 overflow-hidden">
        <div className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3">
          <Segmented size="sm" label={t("dup.similarity")} value={minScore} onChange={setMinScore} options={[{ value: "0", label: t("common.all") }, { value: "0.9", label: "≥ 90%" }, { value: "0.97", label: "≥ 97%" }]} />
          <Segmented size="sm" label={t("dup.decision")} value={decision} onChange={setDecision} options={[{ value: "undecided", label: t("dup.undecided") }, { value: "duplicate", label: t("dup.isDuplicate") }, { value: "not_duplicate", label: t("dup.notDuplicate") }, { value: "all", label: t("common.all") }]} />
        </div>
        <div className="flex items-center justify-between px-4 py-2 text-xs text-muted">
          <span className="num" data-testid="pairs-total">{list.data ? t("common.showing", { from: count(list.data.total ? offset + 1 : 0), to: count(Math.min(offset + PAGE, list.data.total)), total: count(list.data.total) }) : t("common.loading")}</span>
          <span>
            <Button variant="ghost" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>{t("common.previous")}</Button>
            <Button variant="ghost" size="sm" disabled={!list.data || offset + PAGE >= list.data.total} onClick={() => setOffset(offset + PAGE)}>{t("common.next")}</Button>
          </span>
        </div>
        {list.isError && !list.data ? (
          <ErrorState error={list.error} onRetry={() => void list.refetch()} />
        ) : !list.data ? (
          <PanelSkeleton rows={10} />
        ) : !list.data.items.length ? (
          <EmptyState />
        ) : (
          <ul className="max-h-[calc(100vh-340px)] min-h-[520px] overflow-y-auto">
            {list.data.items.map((p) => (
              <li key={p.pair_id}>
                <button
                  type="button"
                  onClick={() => setParams((prev) => { const n = new URLSearchParams(prev); n.set("pair", String(p.pair_id)); return n; }, { replace: true })}
                  className={cn("relative grid w-full grid-cols-[3.25rem_1fr] gap-3 border-t border-line/60 px-4 py-3 text-left hover:bg-raised/40", selected === p.pair_id && "bg-raised")}
                >
                  {selected === p.pair_id ? <span className="absolute inset-y-0 left-0 w-[3px] bg-saffron" /> : null}
                  <span className="num grid h-10 place-items-center rounded-md border border-line bg-bg/60 text-sm font-semibold">{pct(p.pair_score, 0)}</span>
                  <span className="min-w-0 text-sm">
                    <span className="block truncate">{p.work_a.work_description}</span>
                    <span className="block truncate text-muted">{p.work_b.work_description}</span>
                    <span className="mt-1 flex flex-wrap items-center gap-x-2 text-2xs text-faint">
                      <span>{p.work_a.district}</span>
                      <span>· {inr(p.work_a.sanction_amount, lang)} / {inr(p.work_b.sanction_amount, lang)}</span>
                      {p.days_apart !== null ? <span>· {t("dup.daysApart", { days: count(p.days_apart) })}</span> : null}
                      {p.is_standard_item ? <Badge tone="outline">{t("dup.standardItem")}</Badge> : null}
                      {p.decision ? <Badge tone={p.decision === "duplicate" ? "warn" : "ok"}>{p.decision === "duplicate" ? t("dup.isDuplicate") : t("dup.notDuplicate")}</Badge> : null}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>
      {selected ? <PairCompare pairId={selected} /> : <Card><EmptyState title={t("dup.selectPair")} /></Card>}
    </div>
  );
}

function PairCompare({ pairId }: { pairId: number }) {
  const { t, lang } = useLang();
  const { isReviewer } = useAuth();
  const toast = useToast();
  const client = useQueryClient();
  const [note, setNote] = useState("");
  const detail = useApi<PairDetail>(`/duplicates/${pairId}`, undefined, { placeholderData: undefined });
  const decide = useMutation({
    mutationFn: (decision: "duplicate" | "not_duplicate") => api(`/duplicates/${pairId}/decision`, { body: { decision, note: note || null } }),
    onSuccess: () => {
      toast("success", t("dup.decided"));
      setNote("");
      void client.invalidateQueries({ predicate: (q) => String(q.queryKey[0]).startsWith("/duplicates") || String(q.queryKey[0]).startsWith("/alerts") });
    },
    onError: (e: Error) => toast("error", t("states.errorTitle"), e.message),
  });

  return (
    <Card className="min-w-0">
      <QueryState query={detail} skeleton={<PanelSkeleton rows={12} />}>
        {(p) => (
          <div className="space-y-6 p-5" data-testid="pair-compare">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="eyebrow">{t("dup.pairScore")}</div>
                <div className="num font-display text-3xl font-semibold">{pct(p.pair_score, 1)}</div>
              </div>
              <div className="flex flex-wrap gap-2">
                {p.days_apart !== null ? <Badge tone="outline">{t("dup.daysApart", { days: count(p.days_apart) })}</Badge> : null}
                {p.dup_group_id ? (
                  <Link to={`/alerts?id=${encodeURIComponent(p.dup_group_id)}`}>
                    <Badge tone="saffron">{p.dup_group_id}</Badge>
                  </Link>
                ) : null}
                {p.is_standard_item ? <Badge tone="info">{t("dup.standardItem")}</Badge> : null}
              </div>
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              {[p.work_a, p.work_b].map((w, i) => (
                <div key={w.work_id} className="rounded-lg border border-line bg-bg/40 p-4">
                  <div className="flex items-center justify-between">
                    <Badge tone="outline">{i === 0 ? "A" : "B"}</Badge>
                    <BandBadge band={w.band} score={w.risk_score} />
                  </div>
                  <Link to={`/works/${w.work_id}`} className="mt-2 block font-mono text-2xs text-saffron-text hover:underline">{w.work_id}</Link>
                  <p className="mt-2 text-sm leading-relaxed">
                    {p.diff.filter((d) => d.op === "equal" || d.op === (i === 0 ? "removed" : "added")).map((d, k) => (
                      <span key={k} className={cn(d.op !== "equal" && (i === 0 ? "rounded bg-danger/15 text-danger" : "rounded bg-ok/15 text-ok"))}>{d.text} </span>
                    ))}
                  </p>
                  <dl className="mt-3 grid grid-cols-2 gap-2 text-xs">
                    <dt className="text-muted">{t("common.sanctioned")}</dt><dd className="text-right"><Money value={w.sanction_amount} /></dd>
                    <dt className="text-muted">{t("dup.sanctionDate")}</dt><dd className="num text-right">{date(w.sanction_date, lang)}</dd>
                    <dt className="text-muted">{t("common.status")}</dt><dd className="text-right">{w.work_status}</dd>
                    <dt className="text-muted">{t("work.vendor")}</dt><dd className="truncate text-right">{w.vendor_name ?? "—"}</dd>
                    <dt className="text-muted">{t("work.agency")}</dt><dd className="truncate text-right" title={w.ida}>{w.district}</dd>
                  </dl>
                </div>
              ))}
            </div>

            <Section title={t("dup.why")} hint={t("dup.whyHint")}>
              <div className="space-y-2.5">
                {p.breakdown.map((b) => (
                  <Meter key={b.key} labelWidth="14rem" label={b.component} value={b.value} right={`${pct(b.value, 0)}`} color={b.value >= 0.9 ? "rgb(var(--band-high))" : "rgb(var(--info))"} />
                ))}
              </div>
              <p className="text-2xs text-faint">{t("dup.weights")}: {p.breakdown.map((b) => `${b.component.split(" (")[0]} ${b.weight}`).join(" · ")}</p>
              {p.shared_location_words ? <p className="text-xs text-muted">{t("dup.sharedWords")}: <span className="text-ink">{p.shared_location_words}</span></p> : null}
            </Section>

            {isReviewer ? (
              <Section title={t("dup.decide")} hint={t("dup.decideHint")}>
                <Textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder={t("alerts.commentPlaceholder")} aria-label={t("common.note")} />
                <div className="flex gap-2">
                  <Button variant="primary" size="sm" disabled={decide.isPending} onClick={() => decide.mutate("duplicate")}><Check /> {t("dup.isDuplicate")}</Button>
                  <Button variant="outline" size="sm" disabled={decide.isPending} onClick={() => decide.mutate("not_duplicate")}><X /> {t("dup.notDuplicate")}</Button>
                  {p.decision ? <Badge tone="outline" className="ml-auto self-center">{t("dup.current")}: {p.decision.replace("_", " ")}</Badge> : null}
                </div>
              </Section>
            ) : null}

            <Section title={t("alerts.audit")}>
              <AuditTimeline events={p.audit} />
            </Section>
          </div>
        )}
      </QueryState>
    </Card>
  );
}

function Splits() {
  const { t, lang } = useLang();
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<string | null>(null);
  const list = useApi<Page<SplitGroup> & { note: string }>("/splits", { limit: 30, offset });
  const detail = useApi<SplitGroup & { works: WorkSummary[]; alert_id: string | null; alert_status: string | null }>(open ? `/splits/${open}` : null, undefined, { placeholderData: undefined });

  return (
    <div className="space-y-4">
      {list.data?.note ? (
        <div className="rounded-lg border border-warn/30 bg-warn/[0.07] px-4 py-3 text-sm text-ink" data-testid="split-weakness">
          <Layers className="mr-2 inline size-4 text-warn" />
          {list.data.note} {t("dup.splitHint")}
        </div>
      ) : null}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <Card className="overflow-hidden">
          <div className="flex items-center justify-between px-4 py-2 text-xs text-muted">
            <span className="num">{list.data ? t("common.showing", { from: count(list.data.total ? offset + 1 : 0), to: count(Math.min(offset + 30, list.data.total)), total: count(list.data.total) }) : t("common.loading")}</span>
            <span>
              <Button variant="ghost" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 30))}>{t("common.previous")}</Button>
              <Button variant="ghost" size="sm" disabled={!list.data || offset + 30 >= list.data.total} onClick={() => setOffset(offset + 30)}>{t("common.next")}</Button>
            </span>
          </div>
          <QueryState query={list} isEmpty={(d) => !d.items.length}>
            {(d) => (
              <ul className="max-h-[calc(100vh-380px)] min-h-[480px] overflow-y-auto">
                {d.items.map((g) => (
                  <li key={g.split_group_id}>
                    <button type="button" onClick={() => setOpen(g.split_group_id)} className={cn("w-full border-t border-line/60 px-4 py-3 text-left hover:bg-raised/40", open === g.split_group_id && "bg-raised")}>
                      <div className="flex items-center justify-between gap-3">
                        <span className="font-medium">{g.work_type}</span>
                        <Money value={g.total_amount} className="font-semibold" />
                      </div>
                      <div className="mt-1 flex flex-wrap gap-x-2 text-2xs text-muted">
                        <span>{g.ida.split("(")[0]}, {g.state}</span>
                        <span>· {g.n_works} {t("common.works")}</span>
                        {g.detail.span_days !== null && g.detail.span_days !== undefined ? <span>· {t("dup.withinDays", { days: g.detail.span_days })}</span> : null}
                        {g.same_vendor ? <Badge tone="warn">{t("dup.sameVendor")}</Badge> : null}
                        <span className="num">· score {Number(g.split_score).toFixed(2)}</span>
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </QueryState>
        </Card>
        <Card>
          {open ? (
            <QueryState query={detail}>
              {(g) => (
                <div className="space-y-5 p-5">
                  <CardHeader className="px-0 pt-0" title={`${g.work_type} · ${g.ida.split("(")[0]}`} eyebrow={g.split_group_id} action={g.alert_id ? <Button asChild size="sm" variant="outline"><Link to={`/alerts?id=${encodeURIComponent(g.alert_id)}`}>{g.alert_status}</Link></Button> : null} />
                  <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                    <Metric label={t("dup.combined")} value={inr(g.total_amount, lang)} />
                    <Metric label={t("dup.peerP90")} value={inr(Number(g.detail.peer_p90 ?? 0), lang)} />
                    <Metric label={t("dup.timesP90")} value={`${Number(g.detail.total_vs_p90 ?? 0).toFixed(1)}×`} />
                    <Metric label={t("dup.belowRound")} value={pct(Number(g.detail.share_just_below_round ?? 0), 0)} />
                  </div>
                  <WorksTable works={g.works} />
                </div>
              )}
            </QueryState>
          ) : (
            <CardBody><EmptyState title={t("dup.selectGroup")} body={t("dup.splitHint")} /></CardBody>
          )}
        </Card>
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-line bg-bg/40 p-3">
      <div className="text-2xs text-muted">{label}</div>
      <div className="num mt-1 font-display text-lg font-semibold">{value}</div>
    </div>
  );
}
