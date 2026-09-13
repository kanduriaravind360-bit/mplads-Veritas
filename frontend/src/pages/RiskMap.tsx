import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { GeoJSON, MapContainer, useMap } from "react-leaflet";
import L, { type Layer, type PathOptions } from "leaflet";
import type { Feature, FeatureCollection, Geometry } from "geojson";
import { ArrowUpRight, MapPinOff } from "lucide-react";
import { useLang } from "@/lib/i18n";
import { useApi } from "@/lib/query";
import { resolveToken, useTheme } from "@/lib/theme";
import { count, inr, ofTotal, pct, score } from "@/lib/format";
import type { GeoDistrictRow } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Caveat } from "@/components/Caveat";
import { EmptyState, ErrorState, LowVolume, Money, PageHeader } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, Segmented, Skeleton } from "@/components/ui/primitives";

type Metric = "risk" | "money" | "util" | "delay";
type Props = { district: string; state: string; key: string };
type Boundaries = FeatureCollection<Geometry, Props> & { attribution: string };

const RAMP = ["#23466B", "#4F7394", "#D8A24A", "#E2772F", "#D63C3C"];
// Utilisation is good when high, so its ramp runs the other way.
const RAMP_UTIL = ["#D63C3C", "#E2772F", "#D8A24A", "#4F9C8A", "#2D7F6E"];

const METRIC_VALUE: Record<Metric, (r: GeoDistrictRow) => number | null> = {
  risk: (r) => r.mean_risk,
  money: (r) => r.money_at_risk,
  util: (r) => r.utilisation,
  delay: (r) => r.mean_delay_risk,
};

function formatMetric(metric: Metric, value: number | null, lang: "en" | "hi"): string {
  if (value === null || Number.isNaN(value)) return "—";
  if (metric === "money") return inr(value, lang);
  if (metric === "util" || metric === "delay") return pct(value, 0);
  return score(value);
}

/** Quantile breaks over districts with enough works to support a rate. */
function breaks(values: number[]): number[] {
  if (!values.length) return [];
  const sorted = [...values].sort((a, b) => a - b);
  return [0.2, 0.4, 0.6, 0.8].map((q) => sorted[Math.min(sorted.length - 1, Math.floor(q * sorted.length))] ?? 0);
}

function classOf(value: number, cuts: number[]): number {
  let i = 0;
  while (i < cuts.length && value > (cuts[i] ?? Infinity)) i++;
  return i;
}

function FitToData({ bounds }: { bounds: L.LatLngBounds | null }) {
  const map = useMap();
  useEffect(() => {
    if (bounds?.isValid()) map.fitBounds(bounds, { padding: [16, 16], maxZoom: 8 });
  }, [bounds, map]);
  return null;
}

export default function RiskMap() {
  const { t, lang } = useLang();
  const [metric, setMetric] = useState<Metric>("risk");
  const [hovered, setHovered] = useState<string | null>(null);
  const [pinned, setPinned] = useState<string | null>(null);
  const { theme } = useTheme();
  // Canvas paths cannot read CSS variables, so theme colours are resolved here.
  const palette = useMemo(
    () => ({ empty: resolveToken("map-empty", 0.9), line: resolveToken("line"), edge: theme === "dark" ? "rgba(5, 13, 26, 0.6)" : "rgba(255, 255, 255, 0.85)", active: theme === "dark" ? "#FFFFFF" : "#0B1F3A" }),
    [theme],
  );

  const geo = useQuery<Boundaries>({
    queryKey: ["geo-boundaries"],
    queryFn: async () => {
      const response = await fetch("/geo/india_districts.json");
      if (!response.ok) throw new Error(`Boundary file failed to load (${response.status})`);
      return (await response.json()) as Boundaries;
    },
    staleTime: Infinity,
  });
  const rowsQuery = useApi<{ rows: GeoDistrictRow[]; note: string }>("/geo/districts");

  const rows = rowsQuery.data?.rows;
  const byKey = useMemo(() => {
    const map = new Map<string, GeoDistrictRow>();
    rows?.forEach((r) => map.set(r.map_key, r));
    return map;
  }, [rows]);

  const featureKeys = useMemo(() => new Set(geo.data?.features.map((f) => f.properties.key)), [geo.data]);

  const coverage = useMemo(() => {
    if (!rows || !geo.data) return null;
    const total = rows.reduce((s, r) => s + r.works, 0);
    const unmatched = rows.filter((r) => !featureKeys.has(r.map_key)).reduce((s, r) => s + r.works, 0);
    return { total, unmatched };
  }, [rows, geo.data, featureKeys]);

  const cuts = useMemo(() => {
    if (!rows) return [];
    return breaks(
      rows
        .filter((r) => !r.low_volume && featureKeys.has(r.map_key))
        .map(METRIC_VALUE[metric])
        .filter((v): v is number => v !== null),
    );
  }, [rows, metric, featureKeys]);

  const ramp = metric === "util" ? RAMP_UTIL : RAMP;

  const dataBounds = useMemo(() => {
    if (!geo.data || !rows) return null;
    const withData = geo.data.features.filter((f) => byKey.has(f.properties.key));
    if (!withData.length) return null;
    return L.geoJSON({ type: "FeatureCollection", features: withData } as FeatureCollection).getBounds();
  }, [geo.data, rows, byKey]);

  const style = (feature?: Feature<Geometry, Props>): PathOptions => {
    const row = feature ? byKey.get(feature.properties.key) : undefined;
    const value = row ? METRIC_VALUE[metric](row) : null;
    const active = feature && (feature.properties.key === hovered || feature.properties.key === pinned);
    if (!row || value === null) {
      return { color: palette.line, weight: 0.4, fillColor: palette.empty, fillOpacity: 1 };
    }
    return {
      color: active ? palette.active : palette.edge,
      weight: active ? 2 : 0.5,
      fillColor: ramp[classOf(value, cuts)],
      fillOpacity: row.low_volume ? 0.35 : 0.88,
      dashArray: row.low_volume ? "2 3" : undefined,
    };
  };

  const onEachFeature = (feature: Feature<Geometry, Props>, layer: Layer) => {
    const row = byKey.get(feature.properties.key);
    const html = row
      ? `<div class="text-xs"><div class="font-semibold text-sm">${feature.properties.district}</div><div class="text-muted mb-1">${feature.properties.state}</div>
         <div>${t("common.worksCap")}: <b class="num">${count(row.works)}</b></div>
         <div>${t(`map.metric${metric === "risk" ? "Risk" : metric === "money" ? "Money" : metric === "util" ? "Util" : "Delay"}`)}: <b class="num">${formatMetric(metric, METRIC_VALUE[metric](row), lang)}</b></div>
         <div>${t("common.highOrCritical")}: <span class="num">${ofTotal(row.high_or_critical, row.works, lang)}</span></div>
         ${row.low_volume ? `<div class="mt-1 text-muted">${t("common.lowVolume")}</div>` : ""}</div>`
      : `<div class="text-xs"><div class="font-semibold">${feature.properties.district}</div><div class="text-muted">${t("map.noData")}</div></div>`;
    layer.bindTooltip(html, { sticky: true, className: "sentinel-tip", direction: "top", offset: [0, -8] });
    layer.on({
      mouseover: () => setHovered(feature.properties.key),
      mouseout: () => setHovered((k) => (k === feature.properties.key ? null : k)),
      click: () => row && setPinned(feature.properties.key),
    });
  };

  const selected = (pinned && byKey.get(pinned)) || (hovered && byKey.get(hovered)) || null;
  const ranked = useMemo(
    () =>
      (rows ?? [])
        .filter((r) => !r.low_volume && METRIC_VALUE[metric](r) !== null)
        .sort((a, b) => (METRIC_VALUE[metric](b) ?? 0) - (METRIC_VALUE[metric](a) ?? 0))
        .slice(0, 8),
    [rows, metric],
  );

  const metricOptions: { value: Metric; label: string }[] = [
    { value: "risk", label: t("map.metricRisk") },
    { value: "money", label: t("map.metricMoney") },
    { value: "delay", label: t("map.metricDelay") },
    { value: "util", label: t("map.metricUtil") },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("map.title")}
        subtitle={t("map.subtitle")}
        actions={<Segmented label={t("map.metric")} value={metric} onChange={setMetric} options={metricOptions} size="sm" />}
      />
      <Caveat />
      <div className="grid gap-4 xl:grid-cols-[1fr_380px]">
        <Card className="relative overflow-hidden">
          {geo.isError || rowsQuery.isError ? (
            <ErrorState error={geo.error ?? rowsQuery.error} onRetry={() => { void geo.refetch(); void rowsQuery.refetch(); }} />
          ) : !geo.data || !rows ? (
            <Skeleton className="h-[680px] w-full rounded-none" />
          ) : rows.length === 0 ? (
            <EmptyState icon={<MapPinOff className="size-5" />} title={t("map.noData")} className="h-[680px]" />
          ) : (
            <>
              <MapContainer
                center={[22.8, 82.5]}
                zoom={4.6}
                zoomSnap={0.25}
                minZoom={4}
                maxZoom={9}
                preferCanvas
                attributionControl={false}
                className="h-[720px] w-full"
                style={{ background: "rgb(var(--surface))" }}
                data-testid="risk-map"
              >
                <GeoJSON key={`${metric}-${theme}-${lang}-${rows.length}-${cuts.join(",")}`} data={geo.data} style={style} onEachFeature={onEachFeature} />
                <FitToData bounds={dataBounds} />
              </MapContainer>
              <div className="pointer-events-none absolute bottom-14 left-4 z-[500] rounded-md border border-line bg-surface/90 p-3 text-xs shadow-card backdrop-blur">
                <div className="eyebrow mb-2">{metricOptions.find((m) => m.value === metric)?.label}</div>
                <div className="flex items-end gap-1">
                  {ramp.map((colour, i) => (
                    <div key={colour} className="flex flex-col items-start">
                      <div className="h-2.5 w-14 rounded-sm" style={{ background: colour }} />
                      <span className="num mt-1 text-2xs text-muted">
                        {i < cuts.length ? `≤ ${formatMetric(metric, cuts[i] ?? null, lang)}` : `> ${formatMetric(metric, cuts[cuts.length - 1] ?? null, lang)}`}
                      </span>
                    </div>
                  ))}
                </div>
                <div className="mt-2 flex items-center gap-2 text-2xs text-muted">
                  <span className="inline-block h-2.5 w-4 rounded-sm border border-dashed border-muted opacity-60" /> {t("common.lowVolume")}
                </div>
              </div>
            </>
          )}
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-4 py-2 text-2xs text-muted">
            <span data-testid="map-coverage">
              {coverage
                ? t("map.unmatched", { works: count(coverage.unmatched), share: pct(coverage.total ? coverage.unmatched / coverage.total : 0) })
                : null}
            </span>
            <span>{geo.data?.attribution}</span>
          </div>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader title={selected ? selected.district : t("map.selected")} eyebrow={selected?.state} />
            <CardBody>
              {selected ? (
                <div className="space-y-4">
                  <dl className="grid grid-cols-2 gap-3 text-sm">
                    <Fact label={t("common.worksCap")} value={count(selected.works)} extra={selected.low_volume ? <LowVolume /> : null} />
                    <Fact label={t("map.metricRisk")} value={score(selected.mean_risk)} />
                    <Fact label={t("common.sanctioned")} value={<Money value={selected.sanctioned} />} />
                    <Fact label={t("common.moneyAtRisk")} value={<Money value={selected.money_at_risk} />} />
                    <Fact label={t("common.highOrCritical")} value={ofTotal(selected.high_or_critical, selected.works, lang)} />
                    <Fact label={t("common.utilisation")} value={pct(selected.utilisation)} />
                    <Fact label={t("common.completion")} value={pct(selected.completion_rate)} />
                    <Fact label={t("map.metricDelay")} value={selected.mean_delay_risk === null ? "—" : pct(selected.mean_delay_risk, 0)} />
                  </dl>
                  <Button asChild variant="primary" size="sm" className="w-full">
                    <Link to={`/alerts?district=${encodeURIComponent(selected.district)}`}>
                      {t("map.openAlerts")} <ArrowUpRight />
                    </Link>
                  </Button>
                </div>
              ) : (
                <p className="text-sm text-muted">{t("map.hoverHint")}</p>
              )}
            </CardBody>
          </Card>
          <Card>
            <CardHeader title={metricOptions.find((m) => m.value === metric)?.label} hint={rowsQuery.data?.note} />
            <CardBody className="px-0 pb-2">
              <ul>
                {ranked.map((r, i) => (
                  <li key={r.map_key}>
                    <button
                      type="button"
                      onClick={() => setPinned(r.map_key)}
                      className={cn(
                        "flex w-full items-center gap-3 px-5 py-2 text-left text-sm hover:bg-raised/50",
                        pinned === r.map_key && "bg-raised",
                      )}
                    >
                      <span className="num w-4 text-2xs text-faint">{i + 1}</span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium">{r.district}</span>
                        <span className="block text-2xs text-muted">{r.state} · {count(r.works)} {t("common.works")}</span>
                      </span>
                      <span className="num font-medium">{formatMetric(metric, METRIC_VALUE[metric](r), lang)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </CardBody>
          </Card>
        </div>
      </div>
    </div>
  );
}

function Fact({ label, value, extra }: { label: string; value: ReactNode; extra?: ReactNode }) {
  return (
    <div className="rounded-md border border-line bg-bg/40 p-2.5">
      <dt className="text-2xs text-muted">{label}</dt>
      <dd className="num mt-0.5 flex items-center gap-2 font-semibold">
        {value} {extra}
      </dd>
    </div>
  );
}
