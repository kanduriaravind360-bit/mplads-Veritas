/** Small presentational primitives: card, badge, input, skeleton, kbd, segmented control. */
import { forwardRef, type HTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { Info } from "lucide-react";
import { cn } from "@/lib/utils";
import { Tip } from "@/components/ui/tooltip";

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("card", className)} {...props} />;
}

export function CardHeader({
  title,
  hint,
  action,
  className,
  eyebrow,
}: {
  title: ReactNode;
  hint?: ReactNode;
  action?: ReactNode;
  className?: string;
  eyebrow?: ReactNode;
}) {
  return (
    <div className={cn("flex items-start justify-between gap-4 px-5 pt-4", className)}>
      <div className="min-w-0">
        {eyebrow ? <div className="eyebrow mb-1">{eyebrow}</div> : null}
        <h2 className="flex items-center gap-2 text-[15px] font-semibold text-ink">
          {title}
          {hint ? (
            <Tip content={hint}>
              <button type="button" aria-label="About this panel" className="text-faint hover:text-muted">
                <Info className="size-3.5" />
              </button>
            </Tip>
          ) : null}
        </h2>
      </div>
      {action ? <div className="flex shrink-0 items-center gap-2">{action}</div> : null}
    </div>
  );
}

export function CardBody({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-5 pb-5 pt-3", className)} {...props} />;
}

type Tone = "neutral" | "saffron" | "ok" | "warn" | "danger" | "info" | "outline";

const TONES: Record<Tone, string> = {
  neutral: "bg-raised text-muted border-line",
  saffron: "bg-saffron/15 text-saffron-text border-saffron/30",
  ok: "bg-ok/12 text-ok border-ok/30",
  warn: "bg-warn/12 text-warn border-warn/30",
  danger: "bg-danger/12 text-danger border-danger/30",
  info: "bg-info/12 text-info border-info/30",
  outline: "bg-transparent text-muted border-line",
};

export function Badge({
  tone = "neutral",
  className,
  ...props
}: HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-2xs font-medium",
        TONES[tone],
        className,
      )}
      {...props}
    />
  );
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "h-9 w-full rounded-md border border-line bg-bg/60 px-3 text-sm text-ink placeholder:text-faint focus:border-saffron/60 focus:outline-none focus:ring-2 focus:ring-saffron/25",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => (
    <textarea
      ref={ref}
      className={cn(
        "min-h-[72px] w-full rounded-md border border-line bg-bg/60 px-3 py-2 text-sm text-ink placeholder:text-faint focus:border-saffron/60 focus:outline-none focus:ring-2 focus:ring-saffron/25",
        className,
      )}
      {...props}
    />
  ),
);
Textarea.displayName = "Textarea";

export function Select({
  className,
  label,
  children,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement> & { label?: string }) {
  const select = (
    <select
      className={cn(
        "h-9 rounded-md border border-line bg-bg/60 px-3 pr-8 text-sm text-ink focus:border-saffron/60 focus:outline-none focus:ring-2 focus:ring-saffron/25",
        className,
      )}
      {...props}
    >
      {children}
    </select>
  );
  if (!label) return select;
  return (
    <label className="flex flex-col gap-1">
      <span className="eyebrow">{label}</span>
      {select}
    </label>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return (
    <div className={cn("relative overflow-hidden rounded-md bg-raised", className)} aria-hidden>
      <div className="absolute inset-0 -translate-x-full animate-shimmer bg-gradient-to-r from-transparent via-line/40 to-transparent" />
    </div>
  );
}

export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <kbd
      className={cn(
        "inline-flex h-5 min-w-5 items-center justify-center rounded border border-line bg-raised px-1 font-mono text-[10px] text-muted",
        className,
      )}
    >
      {children}
    </kbd>
  );
}

export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
  size = "md",
}: {
  value: T;
  onChange: (value: T) => void;
  options: { value: T; label: ReactNode }[];
  label: string;
  size?: "sm" | "md";
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-md border border-line bg-bg/60 p-0.5">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={option.value === value}
          onClick={() => onChange(option.value)}
          className={cn(
            "rounded-[5px] px-3 font-medium transition-colors",
            size === "sm" ? "h-7 text-xs" : "h-8 text-sm",
            option.value === value ? "bg-raised text-ink shadow-sm" : "text-muted hover:text-ink",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/** A 0..1 horizontal bar with a label, for detector channels and shares. */
export function Meter({
  value,
  color,
  label,
  right,
  max = 1,
  labelWidth = "9rem",
}: {
  value: number;
  color?: string;
  label: ReactNode;
  right?: ReactNode;
  max?: number;
  labelWidth?: string;
}) {
  const width = `${Math.max(0, Math.min(1, value / max)) * 100}%`;
  return (
    <div className="grid items-center gap-3 text-sm" style={{ gridTemplateColumns: `minmax(0,${labelWidth}) 1fr auto` }}>
      <span className="truncate text-muted">{label}</span>
      <div className="h-2 overflow-hidden rounded-full bg-raised">
        <div className="h-full rounded-full" style={{ width, background: color ?? "rgb(var(--saffron-text))" }} />
      </div>
      <span className="num w-12 text-right text-ink">{right}</span>
    </div>
  );
}
