import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { ChevronsLeft, ChevronsRight, Command as CommandIcon, Languages, LogOut, Moon, Search, Shield, Sun } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { setLang, useLang } from "@/lib/i18n";
import { useApi } from "@/lib/query";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";
import { navFor } from "@/components/nav";
import { CommandPalette } from "@/components/CommandPalette";
import { ErrorBoundary } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Badge, Kbd } from "@/components/ui/primitives";
import { Tip } from "@/components/ui/tooltip";

const COLLAPSE_KEY = "sentinel.sidebar";

export function AppShell() {
  const { t, lang } = useLang();
  const { user, logout } = useAuth();
  const { theme, toggle } = useTheme();
  const location = useLocation();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(COLLAPSE_KEY) === "1";
    } catch {
      return false;
    }
  });
  const health = useApi<{ ok: boolean; presentation_mode: boolean }>("/health", undefined, { staleTime: Infinity });

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSE_KEY, collapsed ? "1" : "0");
    } catch {
      /* ignore */
    }
  }, [collapsed]);

  return (
    <div className="flex h-full">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[100] focus:rounded-md focus:bg-raised focus:px-3 focus:py-2">
        Skip to content
      </a>
      <aside
        className={cn(
          "flex shrink-0 flex-col border-r border-line bg-surface/80 transition-[width] duration-200",
          collapsed ? "w-[72px]" : "w-[248px]",
        )}
      >
        <div className="flex h-16 items-center gap-3 border-b border-line px-5">
          <div className="grid size-8 shrink-0 place-items-center rounded-md bg-navy ring-1 ring-saffron/40">
            <Shield className="size-4 text-saffron" />
          </div>
          {!collapsed ? (
            <div className="min-w-0 leading-tight">
              <div className="font-display text-[15px] font-semibold tracking-tight">MPLADS Sentinel</div>
              <div className="truncate text-2xs text-muted">MoSPI · PS 26102</div>
            </div>
          ) : null}
        </div>
        <nav className="flex-1 overflow-y-auto px-3 py-4" aria-label="Main">
          {navFor(user?.role).map((group) => (
            <div key={group.key} className="mb-5">
              {!collapsed ? <div className="eyebrow mb-2 px-3">{t(`nav.${group.key}`)}</div> : null}
              <ul className="space-y-0.5">
                {group.items.map((item) => {
                  const link = (
                    <NavLink
                      to={item.to}
                      end={item.to === "/"}
                      className={({ isActive }) =>
                        cn(
                          "group relative flex h-9 items-center gap-3 rounded-md px-3 text-sm font-medium transition-colors",
                          isActive ? "bg-raised text-ink" : "text-muted hover:bg-raised/60 hover:text-ink",
                          collapsed && "justify-center px-0",
                        )
                      }
                    >
                      {({ isActive }) => (
                        <>
                          {isActive ? <span className="absolute left-0 top-2 h-5 w-[3px] rounded-r bg-saffron" /> : null}
                          <item.icon className={cn("size-4 shrink-0", isActive && "text-saffron-text")} />
                          {!collapsed ? <span className="truncate">{t(`nav.${item.key}`)}</span> : <span className="sr-only">{t(`nav.${item.key}`)}</span>}
                        </>
                      )}
                    </NavLink>
                  );
                  return (
                    <li key={item.to}>
                      {collapsed ? <Tip content={t(`nav.${item.key}`)} side="right">{link}</Tip> : link}
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>
        <div className="border-t border-line p-3">
          <Button
            variant="ghost"
            size="sm"
            className={cn("w-full", collapsed ? "justify-center" : "justify-start")}
            onClick={() => setCollapsed((c) => !c)}
            aria-label={collapsed ? t("nav.expand") : t("nav.collapse")}
          >
            {collapsed ? <ChevronsRight /> : <ChevronsLeft />}
            {!collapsed ? t("nav.collapse") : null}
          </Button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-16 shrink-0 items-center gap-4 border-b border-line bg-surface/60 px-6 backdrop-blur">
          <button
            type="button"
            onClick={() => setPaletteOpen(true)}
            className="flex h-9 w-full max-w-md items-center gap-3 rounded-md border border-line bg-bg/60 px-3 text-sm text-faint hover:border-saffron/40"
            aria-label={t("common.search")}
          >
            <Search className="size-4" />
            <span className="flex-1 text-left">{t("common.searchHint")}</span>
            <span className="flex items-center gap-1">
              <Kbd>
                <CommandIcon className="size-3" />
              </Kbd>
              <Kbd>K</Kbd>
            </span>
          </button>
          <div className="ml-auto flex items-center gap-2">
            {health.data?.presentation_mode ? <Badge tone="info">{t("app.presentation")}</Badge> : null}
            {user ? (
              <div className="hidden items-center gap-2 rounded-md border border-line bg-bg/40 px-3 py-1.5 lg:flex" data-testid="scope-chip">
                <Badge tone="saffron">{t(`role.${user.role}`)}</Badge>
                <span className="max-w-[260px] truncate text-xs text-muted" title={user.scope_label ?? ""}>
                  {user.scope_label}
                </span>
              </div>
            ) : null}
            <Tip content={t("common.language")}>
              <Button variant="ghost" size="sm" onClick={() => setLang(lang === "hi" ? "en" : "hi")} aria-label="Switch language">
                <Languages /> {lang === "hi" ? "EN" : "हि"}
              </Button>
            </Tip>
            <Tip content={t("common.theme")}>
              <Button variant="ghost" size="icon" onClick={toggle} aria-label={t("common.theme")}>
                {theme === "dark" ? <Sun /> : <Moon />}
              </Button>
            </Tip>
            <Tip content={`${user?.email ?? ""} · ${t("common.logout")}`}>
              <Button variant="ghost" size="icon" onClick={logout} aria-label={t("common.logout")}>
                <LogOut />
              </Button>
            </Tip>
          </div>
        </header>
        <main id="main" className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[1680px] px-8 py-8">
            <ErrorBoundary resetKey={location.pathname}>
              <Outlet />
            </ErrorBoundary>
          </div>
        </main>
      </div>
      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
    </div>
  );
}
