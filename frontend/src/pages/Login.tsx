import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Building2, CheckCircle2, Landmark, Languages, Loader2, MapPinned, Shield, Users } from "lucide-react";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { setLang, useLang } from "@/lib/i18n";
import { count } from "@/lib/format";
import { useApi } from "@/lib/query";
import { Button } from "@/components/ui/button";
import { Card, Input } from "@/components/ui/primitives";

// Demo accounts from configs/api.yaml. The password is a published demo value.
const DEMO = [
  { email: "ministry@demo", role: "MINISTRY", icon: Building2, scope: "All India" },
  { email: "state.up@demo", role: "STATE", icon: MapPinned, scope: "Uttar Pradesh" },
  { email: "district.lucknow@demo", role: "DISTRICT", icon: Users, scope: "Lucknow" },
  { email: "mp.0147@demo", role: "MP", icon: Landmark, scope: "MP code 147" },
] as const;

export default function LoginPage() {
  const { t, lang } = useLang();
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const from = (location.state as { from?: string } | null)?.from ?? "/";
  const summary = useApi<{ works: number }>("/public/summary", undefined, { staleTime: Infinity, retry: false });

  if (user) return <Navigate to={from} replace />;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email.trim(), password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401 ? t("login.failed") : err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid min-h-full lg:grid-cols-[1.1fr_1fr]">
      <section className="grid-bg relative hidden flex-col justify-between overflow-hidden border-r border-line bg-navy-900 p-12 text-[#E6EDF7] lg:flex">
        <div className="pointer-events-none absolute -right-40 -top-40 size-[520px] rounded-full bg-saffron/10 blur-3xl" />
        <div className="flex items-center gap-3">
          <div className="grid size-10 place-items-center rounded-md bg-navy ring-1 ring-saffron/50">
            <Shield className="size-5 text-saffron" />
          </div>
          <div>
            <div className="font-display text-lg font-semibold">MPLADS Sentinel</div>
            <div className="text-xs text-[#94A6BF]">Ministry of Statistics and Programme Implementation · SIH 2026 · PS 26102</div>
          </div>
        </div>
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }} className="max-w-xl">
          <h1 className="font-display text-[44px] font-semibold leading-[1.1] tracking-tight">
            {t("app.tagline")}
          </h1>
          <p className="mt-5 min-h-[3.25rem] text-base leading-relaxed text-[#B8C5D8]">
            {summary.data ? t("login.pitch", { works: count(summary.data.works) }) : null}
          </p>
          <ul className="mt-8 space-y-3 text-sm text-[#D5DEEA]">
            {(["point1", "point2", "point3"] as const).map((key) => (
              <li key={key} className="flex items-center gap-3">
                <CheckCircle2 className="size-4 text-saffron" /> {t(`login.${key}`)}
              </li>
            ))}
          </ul>
        </motion.div>
        <p className="text-xs text-[#94A6BF]">{t("app.framing")}</p>
      </section>

      <section className="flex items-center justify-center p-8">
        <div className="w-full max-w-md">
          <div className="mb-8 flex items-center justify-between">
            <div>
              <h2 className="font-display text-2xl font-semibold">{t("login.title")}</h2>
              <p className="mt-1 text-sm text-muted">{t("login.subtitle")}</p>
            </div>
            <Button variant="ghost" size="sm" onClick={() => setLang(lang === "hi" ? "en" : "hi")}>
              <Languages /> {t("common.language")}
            </Button>
          </div>
          <form onSubmit={submit} className="space-y-4" aria-describedby={error ? "login-error" : undefined}>
            <label className="block space-y-1.5">
              <span className="text-sm font-medium">{t("login.email")}</span>
              <Input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
            </label>
            <label className="block space-y-1.5">
              <span className="text-sm font-medium">{t("login.password")}</span>
              <Input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            </label>
            {error ? (
              <p id="login-error" role="alert" className="rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
                {error}
              </p>
            ) : null}
            <Button type="submit" variant="primary" size="lg" className="w-full" disabled={busy}>
              {busy ? <Loader2 className="animate-spin" /> : null} {t("login.submit")}
            </Button>
          </form>

          <Card className="mt-8 p-4">
            <div className="eyebrow mb-3">{t("login.demo")}</div>
            <div className="grid grid-cols-2 gap-2">
              {DEMO.map((d) => (
                <button
                  key={d.email}
                  type="button"
                  data-testid={`demo-${d.role}`}
                  onClick={() => {
                    setEmail(d.email);
                    setPassword("demo123");
                  }}
                  className="flex items-center gap-3 rounded-md border border-line bg-bg/40 p-3 text-left transition-colors hover:border-saffron/50"
                >
                  <d.icon className="size-4 text-saffron-text" />
                  <span className="min-w-0">
                    <span className="block text-sm font-medium">{t(`role.${d.role}`)}</span>
                    <span className="block truncate text-2xs text-muted">{d.scope}</span>
                  </span>
                </button>
              ))}
            </div>
            <p className="mt-3 text-2xs text-muted">{t("login.demoNote")}</p>
          </Card>
          <p className="mt-6 text-center text-sm text-muted">
            {t("login.citizenPrompt")}{" "}
            <Link to="/public" className="font-medium text-saffron-text hover:underline">
              {t("nav.citizen")}
            </Link>
          </p>
        </div>
      </section>
    </div>
  );
}
