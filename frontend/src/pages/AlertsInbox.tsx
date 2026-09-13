import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, Download, FileText, Filter, Lightbulb, Loader2, Search, X } from "lucide-react";
import { api, download, idPath, qs } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useLang } from "@/lib/i18n";
import { useApi } from "@/lib/query";
import { count, date, dateTime } from "@/lib/format";
import type { AlertDetail, AlertsSummary, AlertSummary, Band, Page } from "@/lib/types";
import { alertTypeLabel, BAND_ORDER, bandColor, cn } from "@/lib/utils";
import { Caveat } from "@/components/Caveat";
import { BandBadge, EmptyState, ErrorState, Money, PageHeader, PanelSkeleton, QueryState, RiskDial, useDebounced } from "@/components/common";
import { AttributionBars, AuditTimeline, Completeness, CostCheck, PeerChart, Reasons, RulesFired, Section, SignalBars, WhatWouldClear, WorksTable } from "@/components/evidence";
import { Button } from "@/components/ui/button";
import { Badge, Card, Input, Kbd, Segmented, Textarea } from "@/components/ui/primitives";
import { Sheet } from "@/components/ui/overlay";
import { Tabs, TabsContent, TabsList } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/toast";

const PAGE = 50;
const TYPES = ["high_risk_work", "split_work_group", "duplicate_group"] as const;
const STATUSES = ["Open", "Under Review", "Confirmed", "False positive", "Resolved"] as const;
const VERDICTS = ["confirmed", "false_positive", "not_duplicate", "needs_more_info"] as const;

export default function AlertsInbox() {
  const { t, lang } = useLang();
  const { isReviewer } = useAuth();
  const [params, setParams] = useSearchParams();
  const [cursor, setCursor] = useState(0);
  const searchRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const severity = params.getAll("severity");
  const type = params.get("type") ?? "";
  const status = params.get("status") ?? "";
  const district = params.get("district") ?? "";
  const assignee = params.get("assignee") ?? "";
  const offset = Number(params.get("offset") ?? 0);
  const openId = params.get("id");
  const [text, setText] = useState(params.get("q") ?? "");
  const q = useDebounced(text, 300);

  const update = useCallback(
    (changes: Record<string, string | string[] | null>, keepOffset = false) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [key, value] of Object.entries(changes)) {
            next.delete(key);
            if (Array.isArray(value)) value.forEach((v) => next.append(key, v));
            else if (value) next.set(key, value);
          }
          if (!keepOffset) next.delete("offset");
          return next;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  useEffect(() => {
    if ((params.get("q") ?? "") !== q) update({ q: q || null });
  }, [q]); // eslint-disable-line react-hooks/exhaustive-deps

  const filters = {
    severity,
    alert_type: type || undefined,
    status: status || undefined,
    district: district || undefined,
    assignee: assignee || undefined,
    q: q || undefined,
  };
  const list = useApi<Page<AlertSummary>>("/alerts", { ...filters, limit: PAGE, offset, sort: "severity" });
  const summary = useApi<AlertsSummary>("/alerts/summary");
  const items = list.data?.items ?? [];

  useEffect(() => setCursor(0), [list.data?.offset, list.data?.total]);

  const open = (alertId: string | undefined) => update({ id: alertId ?? null }, true);

  // Keyboard triage: j/k move, e or Enter open, Esc close, / search.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (target.closest("input, textarea, select, [contenteditable=true], [role=dialog] form")) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.key === "j" || event.key === "ArrowDown") {
        event.preventDefault();
        setCursor((c) => Math.min(items.length - 1, c + 1));
      } else if (event.key === "k" || event.key === "ArrowUp") {
        event.preventDefault();
        setCursor((c) => Math.max(0, c - 1));
      } else if (event.key === "e" || event.key === "Enter") {
        const item = items[cursor];
        if (item) {
          event.preventDefault();
          open(item.alert_id);
        }
      } else if (event.key === "/") {
        event.preventDefault();
        searchRef.current?.focus();
      } else if (event.key === "Escape" && openId) {
        open(undefined);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }); // re-bound each render so it sees the current list

  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>(`[data-index="${cursor}"]`)?.scrollIntoView({ block: "nearest" });
    const item = items[cursor];
    if (openId && item && item.alert_id !== openId) open(item.alert_id);
  }, [cursor]); // eslint-disable-line react-hooks/exhaustive-deps

  const filtersActive = severity.length || type || status || district || assignee || q;

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("alerts.title")}
        subtitle={t("alerts.subtitle")}
        actions={
          <>
            <span className="hidden items-center gap-1.5 text-xs text-muted xl:flex" aria-label={t("alerts.keyboard")}>
              <Kbd>j</Kbd>
              <Kbd>k</Kbd>
              <span className="mr-2">{t("alerts.kMove")}</span>
              <Kbd>e</Kbd>
              <span className="mr-2">{t("alerts.kOpen")}</span>
              <Kbd>/</Kbd>
              <span className="mr-3">{t("alerts.kSearch")}</span>
            </span>
            <Button variant="outline" size="sm" onClick={() => void download(`/alerts/export.csv${qs(filters)}`, "alerts.csv")}>
              <Download /> {t("common.export")}
            </Button>
          </>
        }
      />
      <Caveat />

      <div className="grid gap-4 xl:grid-cols-[260px_1fr]">
        <Card className="h-fit space-y-5 p-4">
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-2 text-sm font-semibold">
              <Filter className="size-4 text-muted" /> {t("alerts.filters")}
            </span>
            {filtersActive ? (
              <Button variant="ghost" size="sm" onClick={() => { setText(""); update({ severity: null, type: null, status: null, district: null, assignee: null, q: null }); }}>
                <X /> {t("common.clear")}
              </Button>
            ) : null}
          </div>
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-2.5 size-4 text-faint" />
            <Input ref={searchRef} value={text} onChange={(e) => setText(e.target.value)} placeholder={t("common.search")} className="pl-9" aria-label={t("common.search")} />
          </div>
          <FilterGroup label={t("common.severity")}>
            {BAND_ORDER.filter((b) => b !== "Low").map((band) => {
              const on = severity.includes(band);
              return (
                <Chip key={band} active={on} onClick={() => update({ severity: on ? severity.filter((s) => s !== band) : [...severity, band] })}>
                  <span className="size-2 rounded-full" style={{ background: bandColor(band) }} />
                  {t(`bands.${band}`)}
                  <span className="num ml-auto text-2xs text-muted">{count(summary.data?.by_severity[band as Band] ?? 0)}</span>
                </Chip>
              );
            })}
          </FilterGroup>
          <FilterGroup label={t("common.type")}>
            {TYPES.map((key) => (
              <Chip key={key} active={type === key} onClick={() => update({ type: type === key ? null : key })}>
                {alertTypeLabel(key)}
                <span className="num ml-auto text-2xs text-muted">{count(summary.data?.by_type[key] ?? 0)}</span>
              </Chip>
            ))}
          </FilterGroup>
          <FilterGroup label={t("common.status")}>
            {STATUSES.map((key) => (
              <Chip key={key} active={status === key} onClick={() => update({ status: status === key ? null : key })}>
                {key}
                <span className="num ml-auto text-2xs text-muted">{count(summary.data?.by_status[key] ?? 0)}</span>
              </Chip>
            ))}
          </FilterGroup>
          {isReviewer ? (
            <FilterGroup label="Assignee">
              <Chip active={assignee === "me"} onClick={() => update({ assignee: assignee === "me" ? null : "me" })}>{t("alerts.assignedToMe")}</Chip>
              <Chip active={assignee === "unassigned"} onClick={() => update({ assignee: assignee === "unassigned" ? null : "unassigned" })}>{t("alerts.unassigned")}</Chip>
            </FilterGroup>
          ) : null}
          {district ? (
            <FilterGroup label={t("common.district")}>
              <Chip active onClick={() => update({ district: null })}>
                {district} <X className="ml-auto size-3" />
              </Chip>
            </FilterGroup>
          ) : null}
        </Card>

        <Card className="min-w-0 overflow-hidden">
          <div className="flex items-center justify-between border-b border-line px-5 py-3 text-xs text-muted">
            <span className="num" data-testid="alerts-total">
              {list.data
                ? t("common.showing", {
                    from: count(list.data.total ? offset + 1 : 0),
                    to: count(Math.min(offset + PAGE, list.data.total)),
                    total: count(list.data.total),
                  })
                : t("common.loading")}
            </span>
            <span className="flex items-center gap-2">
              {list.isFetching ? <Loader2 className="size-3.5 animate-spin" /> : null}
              <Button variant="ghost" size="sm" disabled={offset === 0} onClick={() => update({ offset: String(Math.max(0, offset - PAGE)) }, true)}>
                {t("common.previous")}
              </Button>
              <Button variant="ghost" size="sm" disabled={!list.data || offset + PAGE >= list.data.total} onClick={() => update({ offset: String(offset + PAGE) }, true)}>
                {t("common.next")}
              </Button>
            </span>
          </div>
          {list.isError && !list.data ? (
            <ErrorState error={list.error} onRetry={() => void list.refetch()} />
          ) : !list.data ? (
            <PanelSkeleton rows={10} />
          ) : !items.length ? (
            <EmptyState />
          ) : (
            <div ref={listRef} role="listbox" aria-label={t("alerts.title")} className="max-h-[calc(100vh-320px)] min-h-[480px] overflow-y-auto" data-testid="alert-list">
              {items.map((a, i) => (
                <button
                  key={a.alert_id}
                  type="button"
                  role="option"
                  aria-selected={i === cursor}
                  data-index={i}
                  onClick={() => { setCursor(i); open(a.alert_id); }}
                  className={cn(
                    "relative grid w-full grid-cols-[auto_1fr_auto] items-center gap-4 border-b border-line/60 px-5 py-3 text-left transition-colors hover:bg-raised/40",
                    i === cursor && "bg-raised/70",
                    openId === a.alert_id && "bg-raised",
                  )}
                >
                  {i === cursor ? <span className="absolute inset-y-0 left-0 w-[3px] bg-saffron" /> : null}
                  <span className="grid size-9 place-items-center rounded-md border" style={{ borderColor: bandColor(a.severity, 0.35), background: bandColor(a.severity, 0.1) }}>
                    <span className="num text-[11px] font-semibold" style={{ color: bandColor(a.severity) }}>{a.risk_score.toFixed(1)}</span>
                  </span>
                  <span className="min-w-0">
                    <span className="flex items-center gap-2">
                      <span className="text-sm font-medium">{alertTypeLabel(a.alert_type)}</span>
                      {a.n_works > 1 ? <Badge tone="outline">{a.n_works} {t("common.works")}</Badge> : null}
                      <span className="truncate font-mono text-2xs text-faint">{a.alert_id}</span>
                    </span>
                    <span className="mt-0.5 block truncate text-sm text-muted">{lang === "hi" ? (a.top_reason_hi ?? a.top_reason_en) : a.top_reason_en}</span>
                    <span className="mt-0.5 block text-2xs text-faint">
                      {a.district} · {a.state} · {a.work_type} · {t("alerts.raised")} {date(a.raised_at, lang)}
                    </span>
                  </span>
                  <span className="flex flex-col items-end gap-1">
                    <Money value={a.amount} className="text-sm font-semibold" />
                    <span className="flex items-center gap-1.5">
                      <BandBadge band={a.severity} />
                      <Badge tone={a.status === "Open" ? "neutral" : a.status === "Under Review" ? "info" : "outline"}>{a.status}</Badge>
                    </span>
                  </span>
                </button>
              ))}
            </div>
          )}
        </Card>
      </div>

      <Sheet open={!!openId} onOpenChange={(o) => !o && open(undefined)} title={t("alerts.title")}>
        {openId ? <AlertDrawer alertId={openId} onClose={() => open(undefined)} /> : null}
      </Sheet>
    </div>
  );
}

function FilterGroup({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div className="eyebrow mb-2">{label}</div>
      <div className="flex flex-col gap-1">{children}</div>
    </div>
  );
}

function Chip({ active, onClick, children }: { active?: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={!!active}
      onClick={onClick}
      className={cn(
        "flex h-8 items-center gap-2 rounded-md border px-2.5 text-left text-sm transition-colors",
        active ? "border-saffron/50 bg-saffron/10 text-ink" : "border-transparent text-muted hover:bg-raised hover:text-ink",
      )}
    >
      {children}
    </button>
  );
}

// ------------------------------------------------------------------ drawer

function AlertDrawer({ alertId, onClose }: { alertId: string; onClose: () => void }) {
  const { t, lang } = useLang();
  const { isReviewer, can } = useAuth();
  const toast = useToast();
  const client = useQueryClient();
  const [reasonLang, setReasonLang] = useState<"en" | "hi">(lang);
  const [note, setNote] = useState("");
  const [comment, setComment] = useState("");
  const detail = useApi<AlertDetail>(`/alerts/${idPath(alertId)}`, undefined, { placeholderData: undefined });
  const chain = useApi<{ ok: boolean; events_checked: number }>(can("MINISTRY", "STATE") ? "/audit/verify" : null);

  useEffect(() => setReasonLang(lang), [lang]);

  const refresh = () => {
    void client.invalidateQueries({ predicate: (query) => String(query.queryKey[0]).startsWith("/alerts") || String(query.queryKey[0]).startsWith("/audit") });
  };
  const onError = (error: Error) => toast("error", t("states.errorTitle"), error.message);

  const transition = useMutation({
    mutationFn: (to: string) => api(`/alerts/${idPath(alertId)}/transition`, { body: { to_status: to, note: note || null } }),
    onSuccess: (_, to) => { toast("success", t("alerts.transitionDone", { status: to })); setNote(""); refresh(); },
    onError,
  });
  const feedback = useMutation({
    mutationFn: (verdict: string) => api(`/alerts/${idPath(alertId)}/feedback`, { body: { verdict, note: note || null } }),
    onSuccess: () => { toast("success", t("alerts.feedbackDone")); setNote(""); refresh(); },
    onError,
  });
  const addComment = useMutation({
    mutationFn: () => api(`/alerts/${idPath(alertId)}/comments`, { body: { body: comment } }),
    onSuccess: () => { toast("success", t("alerts.commentDone")); setComment(""); refresh(); },
    onError,
  });

  return (
    <QueryState query={detail} skeleton={<PanelSkeleton rows={12} className="pt-16" />}>
      {(a) => {
        const work = a.work;
        return (
          <div className="flex h-full min-h-0 flex-col" data-testid="alert-drawer">
            <div className="border-b border-line px-6 pb-4 pt-5">
              <div className="flex items-start gap-4 pr-8">
                <RiskDial score={a.risk_score} band={a.severity} size={72} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <BandBadge band={a.severity} />
                    <Badge tone="outline">{alertTypeLabel(a.alert_type)}</Badge>
                    <Badge tone={a.status === "Open" ? "neutral" : "info"}>{a.status}</Badge>
                    {a.escalated_at ? <Badge tone="warn">Escalated to {a.level}</Badge> : null}
                  </div>
                  <h2 className="mt-2 truncate font-display text-lg font-semibold">
                    {work?.work_description ?? `${alertTypeLabel(a.alert_type)} · ${a.work_type ?? ""}`}
                  </h2>
                  <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                    <span className="font-mono">{a.alert_id}</span>
                    <span>{a.district}, {a.state}</span>
                    <span><Money value={a.amount} className="text-ink" /> · {a.n_works} {t("common.works")}</span>
                    <span>{t("alerts.raised")} {dateTime(a.raised_at, lang)}</span>
                  </div>
                </div>
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                {work ? (
                  <Button asChild size="sm" variant="outline">
                    <Link to={`/works/${work.work_id}`} onClick={onClose}>
                      <ArrowUpRight /> {t("work.title")}
                    </Link>
                  </Button>
                ) : null}
                {isReviewer ? (
                  <Button size="sm" variant="outline" onClick={() => void download(`/reports/alerts/${idPath(a.alert_id)}.pdf`, "alert_brief.pdf").catch((e: Error) => onError(e))}>
                    <FileText /> {t("alerts.brief")}
                  </Button>
                ) : null}
              </div>
            </div>

            <Tabs defaultValue="explanation" className="flex min-h-0 flex-1 flex-col">
              <TabsList
                className="px-4"
                tabs={[
                  { value: "explanation", label: t("alerts.explanation") },
                  { value: "evidence", label: t("alerts.evidence"), count: a.works.length },
                  ...(work
                    ? [
                        { value: "clear", label: t("clear.tab") },
                        { value: "signals", label: t("alerts.signals") },
                        { value: "peers", label: t("alerts.peers") },
                      ]
                    : []),
                  { value: "review", label: t("alerts.review"), count: a.comments.length + a.feedback.length || undefined },
                  { value: "audit", label: t("alerts.audit"), count: a.audit.length },
                ]}
              />
              <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
                <TabsContent value="explanation" className="space-y-6">
                  <Section title={t("work.reasons")} hint={t("app.framing")}>
                    <div className="flex justify-end">
                      <Segmented size="sm" label="Explanation language" value={reasonLang} onChange={setReasonLang} options={[{ value: "en", label: "English" }, { value: "hi", label: "हिन्दी" }]} />
                    </div>
                    <div lang={reasonLang}>
                      <Reasons en={a.reasons_en} hi={a.reasons_hi} forceLang={reasonLang} />
                    </div>
                  </Section>
                  {a.suggested_action ? (
                    <div className="flex gap-3 rounded-lg border border-saffron/30 bg-saffron/[0.07] p-4" data-testid="suggested-action">
                      <Lightbulb className="mt-0.5 size-4 shrink-0 text-saffron-text" />
                      <div>
                        <div className="text-sm font-semibold">{t("alerts.suggested")}</div>
                        <p className="mt-1 text-sm text-muted">{a.suggested_action}</p>
                      </div>
                    </div>
                  ) : null}
                  {work ? (
                    <Section title={t("work.cost")}>
                      <CostCheck work={work} />
                    </Section>
                  ) : null}
                </TabsContent>

                <TabsContent value="evidence" className="space-y-6">
                  <Section title={t("alerts.worksInAlert")}>
                    <WorksTable works={a.works} onOpen={onClose} />
                  </Section>
                  {work ? (
                    <>
                      <Section title={t("alerts.rulesFired")}>
                        <RulesFired rules={work.rules} severe={work.severe_rules} />
                      </Section>
                      <Section title={t("alerts.completeness")} hint={t("work.snapshot")}>
                        <Completeness items={work.data_completeness} />
                      </Section>
                    </>
                  ) : null}
                </TabsContent>

                {work ? (
                  <>
                    <TabsContent value="clear">
                      <Section title={t("clear.title")} hint={t("clear.hint")}>
                        <WhatWouldClear workId={work.work_id} />
                      </Section>
                    </TabsContent>
                    <TabsContent value="signals" className="space-y-6">
                      <Section title={t("alerts.signalChannels")} hint={t("alerts.signalHint")}>
                        <SignalBars signals={work.signals} />
                      </Section>
                      <Section title={t("alerts.drivers")}>
                        <AttributionBars attributions={work.attributions} />
                      </Section>
                    </TabsContent>
                    <TabsContent value="peers">
                      <Section title={t("alerts.peerChart")}>
                        <PeerChart workId={work.work_id} />
                      </Section>
                    </TabsContent>
                  </>
                ) : null}

                <TabsContent value="review" className="space-y-6">
                  {isReviewer ? (
                    <>
                      <Section title={t("alerts.moveTo")}>
                        <Textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder={t("alerts.commentPlaceholder")} aria-label={t("common.note")} />
                        <div className="flex flex-wrap gap-2">
                          {a.allowed_transitions.length ? (
                            a.allowed_transitions.map((to) => (
                              <Button key={to} size="sm" variant={to === "Under Review" ? "primary" : "outline"} disabled={transition.isPending} onClick={() => transition.mutate(to)}>
                                {to}
                              </Button>
                            ))
                          ) : (
                            <span className="text-xs text-muted">No transitions are open to your role from {a.status}.</span>
                          )}
                        </div>
                      </Section>
                      <Section title={t("alerts.verdict")} hint={t("alerts.verdictNote")}>
                        <div className="flex flex-wrap gap-2">
                          {VERDICTS.filter((v) => v !== "not_duplicate" || a.alert_type === "duplicate_group").map((v) => (
                            <Button key={v} size="sm" variant="outline" disabled={feedback.isPending} onClick={() => feedback.mutate(v)}>
                              {t(`verdicts.${v}`)}
                            </Button>
                          ))}
                        </div>
                      </Section>
                      <Section title={t("alerts.comment")}>
                        <form
                          className="space-y-2"
                          onSubmit={(e) => {
                            e.preventDefault();
                            if (comment.trim()) addComment.mutate();
                          }}
                        >
                          <Textarea value={comment} onChange={(e) => setComment(e.target.value)} placeholder={t("alerts.commentPlaceholder")} aria-label={t("alerts.comment")} />
                          <Button type="submit" size="sm" disabled={!comment.trim() || addComment.isPending}>
                            {t("common.submit")}
                          </Button>
                        </form>
                      </Section>
                    </>
                  ) : (
                    <p className="rounded-md border border-line bg-bg/40 p-3 text-sm text-muted">{t("common.readOnly")}</p>
                  )}
                  {a.feedback.length ? (
                    <Section title="Verdicts">
                      <ul className="space-y-2">
                        {a.feedback.map((f, i) => (
                          <li key={i} className="rounded-md border border-line p-3 text-sm">
                            <div className="flex items-center justify-between">
                              <span className="font-medium">{t(`verdicts.${f.verdict}`, f.verdict)}</span>
                              <span className="text-2xs text-muted">{dateTime(f.created_at, lang)}{f.is_seed ? " · seeded demo verdict" : ""}</span>
                            </div>
                            {f.note ? <p className="mt-1 text-muted">{f.note}</p> : null}
                          </li>
                        ))}
                      </ul>
                    </Section>
                  ) : null}
                  {a.comments.length ? (
                    <Section title="Comments">
                      <ul className="space-y-2">
                        {a.comments.map((c) => (
                          <li key={c.id} className="rounded-md border border-line p-3 text-sm">
                            <div className="flex items-center justify-between text-2xs text-muted">
                              <span>{c.author}</span>
                              <span>{dateTime(c.created_at, lang)}</span>
                            </div>
                            <p className="mt-1">{c.body}</p>
                          </li>
                        ))}
                      </ul>
                    </Section>
                  ) : null}
                </TabsContent>

                <TabsContent value="audit" className="space-y-4">
                  {chain.data ? (
                    <Badge tone={chain.data.ok ? "ok" : "danger"} className="px-3 py-1 text-xs">
                      {chain.data.ok ? t("alerts.chainIntact") : "Chain broken"} · {count(chain.data.events_checked)} events verified
                    </Badge>
                  ) : null}
                  <AuditTimeline events={a.audit} />
                </TabsContent>
              </div>
            </Tabs>
          </div>
        );
      }}
    </QueryState>
  );
}
