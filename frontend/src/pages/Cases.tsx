import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Briefcase, FileText, FolderPlus, Layers, MapPin, Plus } from "lucide-react";
import { api, download } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import { useApi } from "@/lib/query";
import { count, dateTime } from "@/lib/format";
import type { AlertSummary, AuditEvent, Page } from "@/lib/types";
import { alertTypeLabel, cn } from "@/lib/utils";
import { BandBadge, EmptyState, Money, PageHeader, PanelSkeleton, QueryState } from "@/components/common";
import { AuditTimeline, Section } from "@/components/evidence";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardBody, CardHeader, Input, Select, Textarea } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";

export interface CaseSummary {
  id: number;
  title: string;
  kind: string;
  status: string;
  owner: string;
  state: string | null;
  ida: string | null;
  summary: string | null;
  alerts: number;
  value: number;
  created_at: string;
  updated_at: string;
}
interface CaseDetail extends CaseSummary {
  linked_alerts: AlertSummary[];
  work_ids: string[];
  notes: { id: number; author: string; body: string; created_at: string }[];
  audit: AuditEvent[];
}
interface Suggestions {
  split_groups: { title: string; kind: string; alert_ids: string[]; value: number; n_works: number }[];
  district_patterns: { title: string; kind: string; district: string; state: string; alerts: number; value: number }[];
}

const STATUSES = ["Open", "In progress", "Referred", "Closed"] as const;

export default function Cases() {
  const { t } = useLang();
  const toast = useToast();
  const client = useQueryClient();
  const [params, setParams] = useSearchParams();
  const selected = params.get("case") ? Number(params.get("case")) : null;
  const cases = useApi<CaseSummary[]>("/cases");
  const suggestions = useApi<Suggestions>("/cases/suggestions");
  const [title, setTitle] = useState("");

  const open = (id: number) => setParams({ case: String(id) }, { replace: true });
  const refresh = () => void client.invalidateQueries({ predicate: (q) => String(q.queryKey[0]).startsWith("/cases") });

  const create = useMutation({
    mutationFn: async (input: { title: string; kind: string; alert_ids?: string[]; district?: string }) => {
      let alertIds = input.alert_ids ?? [];
      if (input.district) {
        const page = await api<Page<AlertSummary>>(`/alerts?district=${encodeURIComponent(input.district)}&limit=100&sort=risk`);
        alertIds = page.items.map((a) => a.alert_id);
      }
      return api<CaseSummary>("/cases", { body: { title: input.title, kind: input.kind, alert_ids: alertIds } });
    },
    onSuccess: (c) => {
      toast("success", t("cases.created"), c.title);
      setTitle("");
      refresh();
      open(c.id);
    },
    onError: (e: Error) => toast("error", t("states.errorTitle"), e.message),
  });

  useEffect(() => {
    if (!selected && cases.data?.[0]) open(cases.data[0].id);
  }, [cases.data]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="space-y-6">
      <PageHeader title={t("cases.title")} subtitle={t("cases.subtitle")} />
      <div className="grid gap-4 xl:grid-cols-[380px_1fr]">
        <div className="space-y-4">
          <Card>
            <CardHeader title={t("cases.yours")} action={<Badge tone="outline">{count(cases.data?.length ?? 0)}</Badge>} />
            <CardBody className="space-y-3">
              <form
                className="flex gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (title.trim().length >= 3) create.mutate({ title: title.trim(), kind: "custom" });
                }}
              >
                <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder={t("cases.newPlaceholder")} aria-label={t("cases.new")} />
                <Button type="submit" variant="primary" size="icon" disabled={title.trim().length < 3 || create.isPending} aria-label={t("cases.new")}>
                  <Plus />
                </Button>
              </form>
              <QueryState query={cases} isEmpty={(d) => !d.length} empty={<EmptyState icon={<Briefcase className="size-5" />} title={t("cases.none")} body={t("cases.noneBody")} />}>
                {(d) => (
                  <ul className="space-y-1.5" data-testid="case-list">
                    {d.map((c) => (
                      <li key={c.id}>
                        <button
                          type="button"
                          onClick={() => open(c.id)}
                          className={cn("w-full rounded-md border px-3 py-2.5 text-left transition-colors", selected === c.id ? "border-saffron/50 bg-raised" : "border-line hover:border-saffron/30")}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="truncate text-sm font-medium">{c.title}</span>
                            <Badge tone={c.status === "Closed" ? "outline" : c.status === "Referred" ? "warn" : "info"}>{c.status}</Badge>
                          </div>
                          <div className="mt-1 flex justify-between text-2xs text-muted">
                            <span>#{c.id} · {count(c.alerts)} {t("cases.alerts")}</span>
                            <Money value={c.value} />
                          </div>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </QueryState>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title={t("cases.suggested")} hint={t("cases.suggestedHint")} />
            <CardBody className="space-y-2">
              <QueryState query={suggestions} skeleton={<PanelSkeleton rows={4} className="p-0" />}>
                {(s) => (
                  <>
                    {s.split_groups.slice(0, 4).map((g) => (
                      <Suggestion
                        key={g.alert_ids.join()}
                        icon={<Layers className="size-4 text-warn" />}
                        title={g.title}
                        meta={<><Money value={g.value} /> · {g.n_works} {t("common.works")}</>}
                        onOpen={() => create.mutate({ title: g.title, kind: g.kind, alert_ids: g.alert_ids })}
                        busy={create.isPending}
                      />
                    ))}
                    {s.district_patterns.slice(0, 4).map((d) => (
                      <Suggestion
                        key={`${d.district}-${d.state}`}
                        icon={<MapPin className="size-4 text-info" />}
                        title={d.title}
                        meta={<>{d.state} · {count(d.alerts)} {t("cases.alerts")} · <Money value={d.value} /></>}
                        onOpen={() => create.mutate({ title: d.title, kind: d.kind, district: d.district })}
                        busy={create.isPending}
                      />
                    ))}
                  </>
                )}
              </QueryState>
            </CardBody>
          </Card>
        </div>

        {selected ? <CaseView caseId={selected} onChanged={refresh} /> : (
          <Card><EmptyState icon={<FolderPlus className="size-5" />} title={t("cases.select")} body={t("cases.noneBody")} /></Card>
        )}
      </div>
      <p className="text-xs text-muted">{t("cases.framing")}</p>
    </div>
  );
}

function Suggestion({ icon, title, meta, onOpen, busy }: { icon: React.ReactNode; title: string; meta: React.ReactNode; onOpen: () => void; busy: boolean }) {
  const { t } = useLang();
  return (
    <div className="flex items-center gap-3 rounded-md border border-line px-3 py-2">
      {icon}
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm">{title}</div>
        <div className="text-2xs text-muted">{meta}</div>
      </div>
      <Button size="sm" variant="outline" disabled={busy} onClick={onOpen}>{t("cases.open")}</Button>
    </div>
  );
}

function CaseView({ caseId, onChanged }: { caseId: number; onChanged: () => void }) {
  const { t, lang } = useLang();
  const toast = useToast();
  const detail = useApi<CaseDetail>(`/cases/${caseId}`, undefined, { placeholderData: undefined });
  const [summary, setSummary] = useState("");
  const [note, setNote] = useState("");

  useEffect(() => setSummary(detail.data?.summary ?? ""), [detail.data?.id, detail.data?.summary]);

  const update = useMutation({
    mutationFn: (body: Record<string, unknown>) => api(`/cases/${caseId}`, { method: "PATCH", body }),
    onSuccess: () => { toast("success", t("cases.saved")); void detail.refetch(); onChanged(); },
    onError: (e: Error) => toast("error", t("states.errorTitle"), e.message),
  });
  const addNote = useMutation({
    mutationFn: () => api(`/cases/${caseId}/notes`, { body: { body: note } }),
    onSuccess: () => { setNote(""); void detail.refetch(); onChanged(); },
    onError: (e: Error) => toast("error", t("states.errorTitle"), e.message),
  });

  return (
    <Card className="min-w-0">
      <QueryState query={detail} skeleton={<PanelSkeleton rows={10} />}>
        {(c) => (
          <div className="space-y-6 p-6" data-testid="case-detail">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="eyebrow">#{c.id} · {c.kind.replace(/_/g, " ")} · {c.ida?.split("(")[0] ?? c.state ?? t("cases.national")}</div>
                <h2 className="mt-1 font-display text-2xl font-semibold">{c.title}</h2>
                <div className="mt-1 text-xs text-muted">{t("cases.owner")}: {c.owner} · {t("cases.updated")} {dateTime(c.updated_at, lang)}</div>
              </div>
              <div className="flex items-center gap-2">
                <Select aria-label={t("common.status")} value={c.status} onChange={(e) => update.mutate({ status: e.target.value })}>
                  {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                </Select>
                <Button variant="primary" size="sm" onClick={() => void download(`/reports/cases/${c.id}.pdf`, `case_${c.id}_brief.pdf`).catch((e: Error) => toast("error", t("states.errorTitle"), e.message))}>
                  <FileText /> {t("alerts.brief")}
                </Button>
              </div>
            </div>

            <div className="grid grid-cols-3 gap-3">
              <Stat label={t("cases.alerts")} value={count(c.alerts)} />
              <Stat label={t("common.worksCap")} value={count(c.work_ids.length)} />
              <Stat label={t("common.amount")} value={<Money value={c.value} />} />
            </div>

            <Section title={t("cases.summary")} hint={t("cases.summaryHint")}>
              <Textarea value={summary} onChange={(e) => setSummary(e.target.value)} className="min-h-[96px]" aria-label={t("cases.summary")} />
              <Button size="sm" disabled={summary === (c.summary ?? "") || update.isPending} onClick={() => update.mutate({ summary })}>{t("common.save")}</Button>
            </Section>

            <Section title={t("cases.linked")}>
              {c.linked_alerts.length ? (
                <ul className="divide-y divide-line/60 rounded-md border border-line">
                  {c.linked_alerts.map((a) => (
                    <li key={a.alert_id} className="flex items-center gap-3 px-3 py-2 text-sm">
                      <BandBadge band={a.severity} />
                      <Link to={`/alerts?id=${encodeURIComponent(a.alert_id)}`} className="min-w-0 flex-1 hover:text-saffron-text">
                        <span className="block truncate">{alertTypeLabel(a.alert_type)} · {a.district}</span>
                        <span className="block truncate font-mono text-2xs text-muted">{a.alert_id}</span>
                      </Link>
                      <Money value={a.amount} />
                      <Badge tone="outline">{a.status}</Badge>
                      <Button size="sm" variant="ghost" onClick={() => update.mutate({ remove_alert_ids: [a.alert_id] })}>{t("cases.remove")}</Button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-muted">{t("cases.noAlerts")}</p>
              )}
            </Section>

            <Section title={t("cases.notes")}>
              <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); if (note.trim()) addNote.mutate(); }}>
                <Textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder={t("alerts.commentPlaceholder")} aria-label={t("cases.notes")} />
                <Button type="submit" size="sm" disabled={!note.trim() || addNote.isPending}>{t("common.submit")}</Button>
              </form>
              <ul className="space-y-2">
                {c.notes.map((n) => (
                  <li key={n.id} className="rounded-md border border-line p-3 text-sm">
                    <div className="flex justify-between text-2xs text-muted"><span>{n.author}</span><span>{dateTime(n.created_at, lang)}</span></div>
                    <p className="mt-1 whitespace-pre-wrap">{n.body}</p>
                  </li>
                ))}
              </ul>
            </Section>

            <Section title={t("alerts.audit")}>
              <AuditTimeline events={c.audit} />
            </Section>
          </div>
        )}
      </QueryState>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-line bg-bg/40 p-4">
      <div className="text-2xs text-muted">{label}</div>
      <div className="num mt-1 font-display text-xl font-semibold">{value}</div>
    </div>
  );
}
