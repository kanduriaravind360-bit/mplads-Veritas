import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Command } from "cmdk";
import { FileText, Inbox, Languages, LogOut, MapPin, MoonStar, Search } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { setLang, useLang } from "@/lib/i18n";
import { useApi } from "@/lib/query";
import { useTheme } from "@/lib/theme";
import { inr } from "@/lib/format";
import { alertTypeLabel } from "@/lib/utils";
import type { SearchResult } from "@/lib/types";
import { navFor } from "@/components/nav";
import { Dialog, DialogContent } from "@/components/ui/overlay";
import { Kbd } from "@/components/ui/primitives";
import { BandBadge, useDebounced } from "@/components/common";

const itemClass =
  "flex cursor-pointer items-center gap-3 rounded-md px-3 py-2 text-sm text-ink aria-selected:bg-raised aria-selected:text-ink data-[disabled=true]:opacity-50";

export function CommandPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { t, lang } = useLang();
  const { user, logout } = useAuth();
  const { toggle } = useTheme();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const debounced = useDebounced(query.trim(), 220);
  const search = useApi<SearchResult>(debounced.length >= 2 ? "/search" : null, { q: debounced, limit: 6 });

  useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  const go = (to: string) => {
    onOpenChange(false);
    navigate(to);
  };
  const results = debounced.length >= 2 ? search.data : undefined;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title="Command palette" className="overflow-hidden p-0">
        <Command label="Command palette" shouldFilter={false} className="flex max-h-[70vh] flex-col">
          <div className="flex items-center gap-3 border-b border-line px-4">
            <Search className="size-4 text-muted" />
            <Command.Input
              autoFocus
              value={query}
              onValueChange={setQuery}
              placeholder={t("common.searchHint")}
              className="h-14 flex-1 bg-transparent text-base text-ink placeholder:text-faint focus:outline-none"
            />
            <Kbd>Esc</Kbd>
          </div>
          <Command.List className="overflow-y-auto p-2">
            <Command.Empty className="px-3 py-8 text-center text-sm text-muted">
              {search.isFetching ? t("common.loading") : t("states.emptyTitle")}
            </Command.Empty>

            {results?.works.length ? (
              <Command.Group heading={t("common.worksCap")} className="[&_[cmdk-group-heading]]:eyebrow [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-2">
                {results.works.map((w) => (
                  <Command.Item key={w.work_id} value={`work-${w.work_id}`} onSelect={() => go(`/works/${w.work_id}`)} className={itemClass}>
                    <FileText className="size-4 text-muted" />
                    <div className="min-w-0 flex-1">
                      <div className="truncate">{w.work_description}</div>
                      <div className="truncate text-2xs text-muted">
                        <span className="font-mono">{w.work_id}</span> · {w.district} · {inr(w.sanction_amount, lang)}
                      </div>
                    </div>
                    <BandBadge band={w.band} />
                  </Command.Item>
                ))}
              </Command.Group>
            ) : null}

            {results?.alerts.length ? (
              <Command.Group heading={t("nav.alerts")} className="[&_[cmdk-group-heading]]:eyebrow [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-2">
                {results.alerts.map((a) => (
                  <Command.Item key={a.alert_id} value={`alert-${a.alert_id}`} onSelect={() => go(`/alerts?id=${encodeURIComponent(a.alert_id)}`)} className={itemClass}>
                    <Inbox className="size-4 text-muted" />
                    <div className="min-w-0 flex-1">
                      <div className="truncate">{alertTypeLabel(a.alert_type)}</div>
                      <div className="truncate text-2xs text-muted">
                        <span className="font-mono">{a.alert_id}</span> · {a.district} · {a.status}
                      </div>
                    </div>
                    <BandBadge band={a.severity} />
                  </Command.Item>
                ))}
              </Command.Group>
            ) : null}

            {results?.districts.length ? (
              <Command.Group heading={t("common.district")} className="[&_[cmdk-group-heading]]:eyebrow [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-2">
                {results.districts.map((d) => (
                  <Command.Item key={`${d.state}-${d.district}`} value={`district-${d.state}-${d.district}`} onSelect={() => go(`/alerts?district=${encodeURIComponent(d.district)}`)} className={itemClass}>
                    <MapPin className="size-4 text-muted" />
                    <span className="flex-1">{d.district}</span>
                    <span className="text-2xs text-muted">
                      {d.state} · {d.works} {t("common.works")}
                    </span>
                  </Command.Item>
                ))}
              </Command.Group>
            ) : null}

            <Command.Group heading={t("nav.overview")} className="[&_[cmdk-group-heading]]:eyebrow [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-2">
              {navFor(user?.role)
                .flatMap((g) => g.items)
                .filter((item) => {
                  const q = query.trim().toLowerCase();
                  return !q || t(`nav.${item.key}`).toLowerCase().includes(q) || (item.keywords ?? "").includes(q);
                })
                .map((item) => (
                  <Command.Item key={item.to} value={`page-${item.to}`} onSelect={() => go(item.to)} className={itemClass}>
                    <item.icon className="size-4 text-muted" />
                    {t(`nav.${item.key}`)}
                  </Command.Item>
                ))}
              <Command.Item value="action-theme" onSelect={() => { toggle(); onOpenChange(false); }} className={itemClass}>
                <MoonStar className="size-4 text-muted" /> {t("common.theme")}
              </Command.Item>
              <Command.Item value="action-lang" onSelect={() => { setLang(lang === "hi" ? "en" : "hi"); onOpenChange(false); }} className={itemClass}>
                <Languages className="size-4 text-muted" /> {t("common.language")}
              </Command.Item>
              <Command.Item value="action-logout" onSelect={() => { onOpenChange(false); logout(); }} className={itemClass}>
                <LogOut className="size-4 text-muted" /> {t("common.logout")}
              </Command.Item>
            </Command.Group>
          </Command.List>
        </Command>
      </DialogContent>
    </Dialog>
  );
}
