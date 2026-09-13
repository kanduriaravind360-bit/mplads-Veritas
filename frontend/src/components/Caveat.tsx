import { useState } from "react";
import { ChevronDown, Info } from "lucide-react";
import { useLang } from "@/lib/i18n";
import { useApi } from "@/lib/query";
import type { ModelsSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * The honesty strip: framing, the proxy-label caveat and the weakest detector,
 * all read from the API (metrics.json), never typed into the UI.
 */
export function Caveat({ framing, className }: { framing?: string; className?: string }) {
  const { t } = useLang();
  const [open, setOpen] = useState(false);
  const summary = useApi<ModelsSummary>("/models/summary", undefined, { staleTime: Infinity });
  const caveats = (summary.data?.caveats ?? []).filter(Boolean);

  return (
    <div className={cn("rounded-lg border border-info/25 bg-info/[0.06] px-4 py-3 text-sm", className)} data-testid="caveat">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Info className="size-4 shrink-0 text-info" />
        <span className="font-medium text-ink">{framing ?? t("app.framing")}</span>
        {summary.data?.weak_spot ? <span className="text-muted">{summary.data.weak_spot}</span> : null}
        {caveats.length ? (
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            aria-expanded={open}
            className="ml-auto inline-flex items-center gap-1 text-xs font-medium text-info hover:underline"
          >
            {t("caveat.open")} <ChevronDown className={cn("size-3.5 transition-transform", open && "rotate-180")} />
          </button>
        ) : null}
      </div>
      {open ? (
        <ul className="mt-3 list-disc space-y-1.5 pl-9 text-xs leading-relaxed text-muted">
          {caveats.map((c, i) => (
            <li key={i}>{c}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
