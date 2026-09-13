/** Evidence panels shared by the alert drawer and the work detail page. */
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Check, CircleSlash, Link2, Minus, ShieldCheck, X } from "lucide-react";
import { useLang, pick } from "@/lib/i18n";
import { useApi } from "@/lib/query";
import { idPath } from "@/lib/api";
import { count, date, dateTime, inr, pct } from "@/lib/format";
import type { AuditEvent, Peers, Percentiles, Signals, WorkDetail, WorkSummary } from "@/lib/types";
import { bandColor, cn } from "@/lib/utils";
import { BandBadge, EmptyState, Money, PanelSkeleton, QueryState } from "@/components/common";
import { Badge, Meter } from "@/components/ui/primitives";
import { Tip } from "@/components/ui/tooltip";

const CHANNEL_LABELS: Record<keyof Signals, string> = {
  rule: "Rule layer",
  supervised: "Proxy model",
  unsupervised: "Unsupervised anomaly",
  cost: "Cost",
  duplicate: "Duplicate",
  delay: "Delay model",
};

const FEATURE_LABELS: Record<string, string> = {
  amount_vs_peer_median: "Amount against peer median",
  cost_pct_in_type: "Cost percentile within type",
  vendor_share_of_ida: "Vendor share of agency's works",
  vendor_prior_delay_rate: "Vendor's past delay rate",
  ida_prior_delay_rate: "Agency's past delay rate",
  log_amount: "Amount (log scale)",
  days_to_sanction: "Days to sanction",
  days_since_sanction: "Days since sanction",
  duration_days: "Days to completion",
  vendor_work_count: "Vendor's number of works",
  cost_zscore: "Cost z-score",
  disbursed_ratio: "Disbursed share",
  ida_vendor_hhi: "Agency vendor concentration",
};

export function featureLabel(name: string): string {
  return FEATURE_LABELS[name] ?? name.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export function Section({ title, children, hint, className }: { title: ReactNode; children: ReactNode; hint?: ReactNode; className?: string }) {
  return (
    <section className={cn("space-y-3", className)}>
      <div>
        <h3 className="text-sm font-semibold text-ink">{title}</h3>
        {hint ? <p className="mt-0.5 text-xs text-muted">{hint}</p> : null}
      </div>
      {children}
    </section>
  );
}

export function Reasons({ en, hi, forceLang }: { en: string[]; hi: string[]; forceLang?: "en" | "hi" }) {
  const { lang } = useLang();
  const list = pick(forceLang ?? lang, en, hi.length ? hi : null);
  if (!list.length) return <p className="text-sm text-muted">—</p>;
  return (
    <ol className="space-y-2">
      {list.map((reason, i) => (
        <li key={i} className="flex gap-3 rounded-md border border-line bg-bg/40 px-3 py-2.5 text-sm leading-relaxed">
          <span className="num mt-0.5 grid size-5 shrink-0 place-items-center rounded-full bg-raised text-2xs text-muted">{i + 1}</span>
          <span>{reason}</span>
        </li>
      ))}
    </ol>
  );
}

export function SignalBars({ signals }: { signals: Signals }) {
  const entries = (Object.keys(CHANNEL_LABELS) as (keyof Signals)[]).map((k) => [k, signals[k] ?? 0] as const);
  return (
    <div className="space-y-2.5" data-testid="signal-bars">
      {entries
        .sort((a, b) => b[1] - a[1])
        .map(([key, value]) => (
          <Meter
            key={key}
            label={CHANNEL_LABELS[key]}
            value={value}
            right={value.toFixed(2)}
            color={value >= 0.8 ? bandColor("Critical") : value >= 0.5 ? bandColor("High") : "rgb(var(--info))"}
          />
        ))}
    </div>
  );
}

/** Signed feature contributions (SHAP values for the tree models) as diverging bars. */
export function AttributionBars({ attributions }: { attributions: Record<string, [string, number][]> }) {
  const groups = Object.entries(attributions).filter(([, rows]) => rows.length);
  if (!groups.length) return <p className="text-sm text-muted">No feature contributions were stored for this work.</p>;
  return (
    <div className="space-y-5">
      {groups.map(([model, rows]) => {
        const max = Math.max(...rows.map(([, v]) => Math.abs(v)), 1e-9);
        return (
          <div key={model}>
            <div className="eyebrow mb-2">{CHANNEL_LABELS[model as keyof Signals] ?? model}</div>
            <div className="space-y-1.5">
              {rows.map(([feature, value]) => (
                <div key={feature} className="grid grid-cols-[minmax(0,13rem)_1fr_3.5rem] items-center gap-3 text-sm">
                  <span className="truncate text-muted" title={feature}>
                    {featureLabel(feature)}
                  </span>
                  <div className="relative h-2.5 rounded-full bg-raised">
                    <div className="absolute inset-y-0 left-1/2 w-px bg-line" />
                    <div
                      className="absolute inset-y-0 rounded-full"
                      style={{
                        left: value >= 0 ? "50%" : `${50 - (Math.abs(value) / max) * 50}%`,
                        width: `${(Math.abs(value) / max) * 50}%`,
                        background: value >= 0 ? bandColor("High") : "rgb(var(--info))",
                      }}
                    />
                  </div>
                  <span className="num text-right text-xs text-ink">{value >= 0 ? "+" : ""}{value.toFixed(2)}</span>
                </div>
              ))}
            </div>
          </div>
        );
      })}
      <p className="text-2xs text-faint">Orange pushes the score up, blue pulls it down. Contributions explain the model, not the facts on the ground.</p>
    </div>
  );
}

export function RulesFired({ rules, severe }: { rules: Record<string, boolean>; severe?: Record<string, boolean> }) {
  const labels = useApi<{ rules: { key: string; label: string }[] }>("/compliance/rules", { limit: 5 }, { staleTime: Infinity });
  const label = (key: string) => labels.data?.rules.find((r) => r.key === key)?.label ?? key.replace(/^rule_/, "").replace(/_/g, " ");
  const fired = Object.entries(rules).filter(([, v]) => v);
  const severeFired = Object.entries(severe ?? {}).filter(([, v]) => v);
  return (
    <div className="flex flex-wrap gap-2">
      {Object.entries(rules).map(([key, on]) => (
        <span
          key={key}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs",
            on ? "border-saffron/40 bg-saffron/10 text-saffron-text" : "border-line text-faint",
          )}
        >
          {on ? <Check className="size-3" /> : <Minus className="size-3" />}
          {label(key)}
        </span>
      ))}
      {severeFired.map(([key]) => (
        <Badge key={key} tone="danger">Severe: {key.replace(/^severe_/, "").replace(/_/g, " ")}</Badge>
      ))}
      {!fired.length && !severeFired.length ? <span className="text-xs text-muted">No rule fired.</span> : null}
    </div>
  );
}

export function Completeness({ items }: { items: WorkDetail["data_completeness"] }) {
  return (
    <ul className="grid grid-cols-2 gap-2">
      {items.map((item) => (
        <li key={item.field} className="flex items-center gap-2 text-sm">
          {!item.applicable ? (
            <CircleSlash className="size-4 text-faint" />
          ) : item.present ? (
            <Check className="size-4 text-ok" />
          ) : (
            <X className="size-4 text-danger" />
          )}
          <span className={cn(!item.applicable && "text-faint")}>{item.label}</span>
        </li>
      ))}
    </ul>
  );
}

export function CostCheck({ work }: { work: WorkDetail }) {
  const c = work.cost;
  if (!c.expected_amount && !c.state_peer_median) return <p className="text-sm text-muted">No cost comparison is available for this work type.</p>;
  return (
    <dl className="grid grid-cols-3 gap-3 text-sm">
      <div className="rounded-md border border-line bg-bg/40 p-3">
        <dt className="text-2xs text-muted">Sanctioned</dt>
        <dd className="mt-1 font-semibold"><Money value={work.sanction_amount} /></dd>
      </div>
      <div className="rounded-md border border-line bg-bg/40 p-3">
        <dt className="text-2xs text-muted">Predicted from description</dt>
        <dd className="mt-1 font-semibold"><Money value={c.expected_amount} /></dd>
        {c.ratio ? <dd className="num text-2xs text-muted">{c.ratio.toFixed(1)}× predicted</dd> : null}
      </div>
      <div className="rounded-md border border-line bg-bg/40 p-3">
        <dt className="text-2xs text-muted">{c.state_peer_label ?? "State peer median"}</dt>
        <dd className="mt-1 font-semibold"><Money value={c.state_peer_median} /></dd>
        {c.state_cost_ratio ? (
          <dd className="num text-2xs text-muted">
            {c.state_cost_ratio.toFixed(1)}× median{c.state_channel_in_score ? "" : " · descriptive, not in the score"}
          </dd>
        ) : null}
      </div>
    </dl>
  );
}

// ------------------------------------------------------------------ peer chart

function PeerRow({ label, p, min, max, marks }: { label: string; p: Percentiles; min: number; max: number; marks: { value: number | null; color: string; name: string }[] }) {
  const x = (v: number) => `${((Math.log10(Math.max(v, 1)) - min) / (max - min)) * 100}%`;
  return (
    <div className="grid grid-cols-[9rem_1fr] items-center gap-3">
      <div className="text-sm">
        <div className="text-ink">{label}</div>
        <div className="num text-2xs text-muted">n = {count(p.n)}</div>
      </div>
      <div className="relative h-8">
        <div className="absolute inset-y-3 rounded-full bg-info/25" style={{ left: x(p.p10), width: `calc(${x(p.p90)} - ${x(p.p10)})` }} />
        <div className="absolute inset-y-2 rounded-sm bg-info/55" style={{ left: x(p.p25), width: `calc(${x(p.p75)} - ${x(p.p25)})` }} />
        <div className="absolute inset-y-1 w-0.5 bg-ink" style={{ left: x(p.median) }} title={`Median ${inr(p.median)}`} />
        {marks.map((m) =>
          m.value ? (
            <Tip key={m.name} content={`${m.name}: ${inr(m.value)}`}>
              <div className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rotate-45 border-2 border-surface" style={{ left: x(m.value), background: m.color }} />
            </Tip>
          ) : null,
        )}
      </div>
    </div>
  );
}

export function PeerChart({ workId }: { workId: string }) {
  const { t, lang } = useLang();
  const peers = useApi<Peers>(`/works/${idPath(workId)}/peers`);
  return (
    <QueryState query={peers} skeleton={<PanelSkeleton rows={3} className="p-0" />}>
      {(p) => {
        const rows = [
          p.state_peers ? { label: `${p.state}`, data: p.state_peers } : null,
          p.national_peers ? { label: "All India", data: p.national_peers } : null,
        ].filter((r): r is { label: string; data: Percentiles } => !!r);
        if (!rows.length) return <EmptyState title="No peer group" body={p.note} />;
        const values = [p.amount, p.expected_amount ?? p.amount, ...rows.flatMap((r) => [r.data.p10, r.data.p90])].filter((v) => v > 0);
        const min = Math.log10(Math.min(...values)) - 0.15;
        const max = Math.log10(Math.max(...values)) + 0.15;
        const marks = [
          { value: p.amount, color: bandColor("Critical"), name: t("alerts.thisWork") },
          { value: p.expected_amount, color: "rgb(var(--saffron-text))", name: t("alerts.expected") },
        ];
        return (
          <div className="space-y-3" data-testid="peer-chart">
            <p className="text-xs text-muted">
              {p.work_type} · {t("alerts.peerHint")}
            </p>
            {rows.map((r) => (
              <PeerRow key={r.label} label={r.label} p={r.data} min={min} max={max} marks={marks} />
            ))}
            <div className="flex flex-wrap items-center gap-4 pl-[9.75rem] text-2xs text-muted">
              {marks.map((m) => (m.value ? (
                <span key={m.name} className="flex items-center gap-1.5">
                  <span className="size-2.5 rotate-45" style={{ background: m.color }} /> {m.name} <span className="num text-ink">{inr(m.value, lang)}</span>
                </span>
              ) : null))}
              {p.ratio_to_state_median ? <span className="num">{p.ratio_to_state_median.toFixed(1)}× state median</span> : null}
            </div>
            <p className="text-2xs text-faint">{p.note} Log scale.</p>
          </div>
        );
      }}
    </QueryState>
  );
}

// ------------------------------------------------------------------ audit

const ACTION_LABELS: Record<string, string> = {
  status_change: "Status changed",
  comment: "Comment",
  feedback: "Verdict recorded",
  assign: "Assigned",
  brief_generated: "PDF brief generated",
  escalated: "Escalated",
  duplicate_decision: "Duplicate decision",
  alert_raised: "Alert raised",
};

export function AuditTimeline({ events }: { events: AuditEvent[] }) {
  const { t, lang } = useLang();
  if (!events.length) return <EmptyState title={t("alerts.noAudit")} body="Every status change, verdict, comment and brief is appended to a SHA-256 hash chain." icon={<ShieldCheck className="size-5" />} />;
  return (
    <ol className="relative space-y-4 border-l border-line pl-6" data-testid="audit-timeline">
      {events.map((e) => (
        <li key={e.seq} className="relative">
          <span className="absolute -left-[31px] top-1 grid size-4 place-items-center rounded-full border border-saffron/50 bg-surface">
            <span className="size-1.5 rounded-full bg-saffron" />
          </span>
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <span className="text-sm font-medium">{ACTION_LABELS[e.action] ?? e.action}</span>
            <span className="text-2xs text-muted">{dateTime(e.ts, lang)}</span>
          </div>
          <div className="text-xs text-muted">{e.actor}</div>
          {Object.keys(e.payload).length ? (
            <div className="mt-1 text-xs text-ink">
              {Object.entries(e.payload)
                .filter(([k]) => !["work_ids"].includes(k))
                .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
                .join(" · ")}
            </div>
          ) : null}
          <div className="mt-1 flex items-center gap-1.5 font-mono text-[10px] text-faint">
            <Link2 className="size-3" /> #{e.seq} {e.hash.slice(0, 12)}… ← {e.prev_hash.slice(0, 12)}…
          </div>
        </li>
      ))}
    </ol>
  );
}

// ------------------------------------------------------------------ works table

export function WorksTable({ works, onOpen }: { works: WorkSummary[]; onOpen?: () => void }) {
  const { t, lang } = useLang();
  return (
    <div className="overflow-x-auto rounded-md border border-line">
      <table className="w-full text-sm">
        <thead className="bg-raised/60">
          <tr className="text-left text-2xs uppercase tracking-wider text-muted">
            <th className="px-3 py-2 font-medium">Work</th>
            <th className="px-3 py-2 text-right font-medium">{t("common.sanctioned")}</th>
            <th className="px-3 py-2 font-medium">{t("common.band")}</th>
            <th className="px-3 py-2 font-medium">{t("common.status")}</th>
          </tr>
        </thead>
        <tbody>
          {works.map((w) => (
            <tr key={w.work_id} className="border-t border-line/60 align-top">
              <td className="px-3 py-2">
                <Link to={`/works/${w.work_id}`} onClick={onOpen} className="font-mono text-xs text-saffron-text hover:underline">
                  {w.work_id}
                </Link>
                <div className="line-clamp-2 text-xs text-muted">{w.work_description}</div>
                <div className="text-2xs text-faint">
                  {date(w.sanction_date, lang)} · {w.vendor_name ?? "no vendor recorded"}
                </div>
              </td>
              <td className="px-3 py-2 text-right">
                <Money value={w.sanction_amount} />
                {w.total_fund_disbursed !== null ? <div className="num text-2xs text-muted">{pct(w.total_fund_disbursed / Math.max(w.sanction_amount, 1), 0)} paid</div> : null}
              </td>
              <td className="px-3 py-2"><BandBadge band={w.band} score={w.risk_score} /></td>
              <td className="px-3 py-2 text-xs text-muted">{w.work_status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
