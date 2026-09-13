import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

export const BAND_ORDER = ["Critical", "High", "Medium", "Low"] as const;

/** CSS colour for a band, read from the theme tokens so both themes work. */
export function bandColor(band: string | null | undefined, alpha = 1): string {
  const name = (band ?? "low").toLowerCase();
  return `rgb(var(--band-${name}) / ${alpha})`;
}

export function tokenColor(name: string, alpha = 1): string {
  return `rgb(var(--${name}) / ${alpha})`;
}

export function titleCase(text: string | null | undefined): string {
  if (!text) return "";
  return text.toLowerCase().replace(/(^|[\s(/-])([a-z])/g, (_, p: string, c: string) => p + c.toUpperCase());
}

export function alertTypeLabel(type: string): string {
  return (
    {
      high_risk_work: "High-risk work",
      duplicate_group: "Possible duplicates",
      split_work_group: "Possible split work",
    }[type] ?? type
  );
}

export function clamp(x: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, x));
}
