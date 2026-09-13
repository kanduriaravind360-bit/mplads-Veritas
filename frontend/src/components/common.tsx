/** Shared building blocks: money with words, band badges, states, page header, KPI card. */
import { Component, useEffect, useRef, useState, type ErrorInfo, type ReactNode } from "react";
import { animate, motion, useReducedMotion } from "framer-motion";
import { AlertTriangle, Inbox, RefreshCw, ShieldAlert, WifiOff } from "lucide-react";
import type { UseQueryResult } from "@tanstack/react-query";
import { ApiError } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import { count, inr, inrFull, rupeesInWords } from "@/lib/format";
import { bandColor, cn } from "@/lib/utils";
import { Tip } from "@/components/ui/tooltip";
import { Button } from "@/components/ui/button";
import { Badge, Card, Skeleton } from "@/components/ui/primitives";

// ------------------------------------------------------------------ money

/** Compact rupees; hover (or focus) shows the exact figure and the amount in words. */
export function Money({ value, className }: { value: number | null | undefined; className?: string }) {
  const { lang } = useLang();
  if (value === null || value === undefined) return <span className={className}>—</span>;
  return (
    <Tip
      content={
        <span className="block">
          <span className="num block font-semibold">{inrFull(value)}</span>
          <span className="mt-1 block text-muted">{rupeesInWords(value, lang)}</span>
        </span>
      }
    >
      <span tabIndex={0} className={cn("num cursor-help decoration-dotted underline-offset-4 hover:underline", className)}>
        {inr(value, lang)}
      </span>
    </Tip>
  );
}

// ------------------------------------------------------------------ bands

export function BandBadge({ band, score }: { band: string; score?: number }) {
  const { t } = useLang();
  return (
    <span
      className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 text-2xs font-semibold"
      style={{ color: bandColor(band), borderColor: bandColor(band, 0.35), background: bandColor(band, 0.12) }}
    >
      <span className="size-1.5 rounded-full" style={{ background: bandColor(band) }} />
      {t(`bands.${band}`, band)}
      {score !== undefined ? <span className="num font-medium opacity-80">{score.toFixed(1)}</span> : null}
    </span>
  );
}

export function RiskDial({ score, band, size = 88 }: { score: number; band: string; size?: number }) {
  const r = size / 2 - 7;
  const c = 2 * Math.PI * r;
  const reduce = useReducedMotion();
  return (
    <div className="relative" style={{ width: size, height: size }} aria-label={`Risk score ${score.toFixed(1)} of 100`}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgb(var(--raised))" strokeWidth={7} />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={bandColor(band)}
          strokeWidth={7}
          strokeLinecap="round"
          strokeDasharray={c}
          initial={{ strokeDashoffset: reduce ? c * (1 - score / 100) : c }}
          animate={{ strokeDashoffset: c * (1 - score / 100) }}
          transition={{ duration: 0.7, ease: "easeOut" }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="num font-display text-2xl font-semibold leading-none">{score.toFixed(1)}</span>
        <span className="text-2xs text-muted">/ 100</span>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ states

export function EmptyState({ title, body, icon, className }: { title?: string; body?: ReactNode; icon?: ReactNode; className?: string }) {
  const { t } = useLang();
  return (
    <div className={cn("flex flex-col items-center justify-center gap-3 px-6 py-12 text-center", className)} data-testid="empty-state">
      <div className="grid size-12 place-items-center rounded-full border border-line bg-raised text-muted">
        {icon ?? <Inbox className="size-5" />}
      </div>
      <div className="font-medium text-ink">{title ?? t("states.emptyTitle")}</div>
      <div className="max-w-sm text-sm text-muted">{body ?? t("states.emptyBody")}</div>
    </div>
  );
}

export function ErrorState({ error, onRetry, className }: { error: unknown; onRetry?: () => void; className?: string }) {
  const { t } = useLang();
  const api = error instanceof ApiError ? error : null;
  const offline = api?.status === -1;
  const forbidden = api?.status === 403;
  const message = api?.message ?? (error instanceof Error ? error.message : String(error));
  return (
    <div role="alert" className={cn("flex flex-col items-center justify-center gap-3 px-6 py-12 text-center", className)}>
      <div className="grid size-12 place-items-center rounded-full border border-danger/30 bg-danger/10 text-danger">
        {offline ? <WifiOff className="size-5" /> : forbidden ? <ShieldAlert className="size-5" /> : <AlertTriangle className="size-5" />}
      </div>
      <div className="font-medium text-ink">{t("states.errorTitle")}</div>
      <div className="max-w-md text-sm text-muted">{offline ? t("states.offline") : message}</div>
      {onRetry && !forbidden ? (
        <Button size="sm" variant="outline" onClick={onRetry}>
          <RefreshCw /> {t("common.retry")}
        </Button>
      ) : null}
    </div>
  );
}

/** Loading, error and empty handling for one query, so every panel fails gracefully. */
export function QueryState<T>({
  query,
  children,
  skeleton,
  isEmpty,
  empty,
}: {
  query: UseQueryResult<T, ApiError>;
  children: (data: T) => ReactNode;
  skeleton?: ReactNode;
  isEmpty?: (data: T) => boolean;
  empty?: ReactNode;
}) {
  if (query.isError && !query.data) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (query.data === undefined) return <>{skeleton ?? <PanelSkeleton />}</>;
  if (isEmpty?.(query.data)) return <>{empty ?? <EmptyState />}</>;
  return <>{children(query.data)}</>;
}

export function PanelSkeleton({ rows = 4, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn("space-y-3 p-5", className)} aria-busy>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className={cn("h-4", i % 3 === 2 ? "w-2/3" : "w-full")} />
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ page header

export function PageHeader({
  title,
  subtitle,
  actions,
  children,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="font-display text-[28px] font-semibold leading-tight text-ink">{title}</h1>
        {subtitle ? <div className="mt-1 text-sm text-muted">{subtitle}</div> : null}
        {children}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}

// ------------------------------------------------------------------ KPI

function CountUp({ value, format }: { value: number; format: (n: number) => string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const reduce = useReducedMotion();
  const first = useRef(true);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (reduce || !first.current) {
      node.textContent = format(value);
      return;
    }
    first.current = false;
    const controls = animate(0, value, {
      duration: 0.6,
      ease: "easeOut",
      onUpdate: (v) => {
        node.textContent = format(v);
      },
    });
    return () => controls.stop();
  }, [value, format, reduce]);
  return <span ref={ref}>{format(value)}</span>;
}

export function KpiCard({
  label,
  value,
  kind = "count",
  sub,
  hint,
  accent,
  icon,
}: {
  label: string;
  value: number;
  kind?: "count" | "money" | "percent";
  sub?: ReactNode;
  hint?: ReactNode;
  accent?: string;
  icon?: ReactNode;
}) {
  const { lang } = useLang();
  const formatter = (n: number) =>
    kind === "money" ? inr(n, lang) : kind === "percent" ? `${(n * 100).toFixed(1)}%` : count(n);
  const main = (
    <div className="num font-display text-[28px] font-semibold leading-none tracking-tight" style={accent ? { color: accent } : undefined}>
      <CountUp value={value} format={formatter} />
    </div>
  );
  return (
    <Card className="relative overflow-hidden p-5">
      <div className="flex items-center justify-between">
        <span className="eyebrow">{label}</span>
        <span className="text-faint">{icon}</span>
      </div>
      <div className="mt-3">
        {kind === "money" ? (
          <Tip content={<span className="block"><span className="num block font-semibold">{inrFull(value)}</span><span className="mt-1 block text-muted">{rupeesInWords(value, lang)}</span></span>}>
            <div tabIndex={0} className="w-fit cursor-help">{main}</div>
          </Tip>
        ) : (
          main
        )}
      </div>
      {sub ? <div className="mt-2 text-xs text-muted">{sub}</div> : null}
      {hint ? <div className="mt-1 text-2xs text-faint">{hint}</div> : null}
    </Card>
  );
}

// ------------------------------------------------------------------ misc

export function LowVolume() {
  const { t } = useLang();
  return (
    <Tip content={t("common.lowVolume")}>
      <span tabIndex={0}>
        <Badge tone="outline" className="cursor-help">n&lt;20</Badge>
      </span>
    </Tip>
  );
}

export function EstimateTag() {
  const { t } = useLang();
  return <Badge tone="warn">{t("common.estimate")}</Badge>;
}

export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidUpdate(prev: { resetKey?: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.warn("View crashed", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <Card className="mx-auto mt-12 max-w-lg">
          <ErrorState error={this.state.error} onRetry={() => this.setState({ error: null })} />
        </Card>
      );
    }
    return this.props.children;
  }
}

/** Keep a value stable for a short while, so fast typing does not flood the API. */
export function useDebounced<T>(value: T, ms = 250): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return debounced;
}
