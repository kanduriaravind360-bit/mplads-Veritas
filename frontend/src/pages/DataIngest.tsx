import { useRef, useState, type DragEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Download, FileSpreadsheet, Loader2, UploadCloud, XCircle } from "lucide-react";
import { api, download } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import { useApi } from "@/lib/query";
import { count, dateTime } from "@/lib/format";
import type { Band } from "@/lib/types";
import { BAND_ORDER, bandColor, cn } from "@/lib/utils";
import { BandBadge, EmptyState, Money, PageHeader, QueryState } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardBody, CardHeader } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";

interface Issue {
  row: number | null;
  column: string | null;
  message: string;
}
interface UploadResult {
  filename: string;
  rows: number;
  valid_rows: number;
  errors: Issue[];
  warnings: Issue[];
  scored: {
    scored: number;
    elapsed_seconds: number;
    bands: Record<Band, number>;
    top: { work_id: string; work_description: string | null; sanction_amount: number; risk_score: number; band: Band; reasons_en: string[]; reasons_hi: string[] }[];
    scoring_scope: string | null;
  } | null;
  committed: { works: number; alerts: number } | null;
  run_id: number;
}
interface Run {
  id: number;
  filename: string;
  rows: number;
  valid_rows: number;
  committed: boolean;
  errors: number;
  created_at: string;
}

export default function DataIngest() {
  const { t, lang } = useLang();
  const toast = useToast();
  const client = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [result, setResult] = useState<UploadResult | null>(null);
  const runs = useApi<Run[]>("/ingest/runs");

  const upload = useMutation({
    mutationFn: (commit: boolean) => {
      if (!file) throw new Error("Choose a file first");
      const form = new FormData();
      form.append("file", file);
      form.append("commit", commit ? "true" : "false");
      return api<UploadResult>("/ingest", { form, method: "POST", timeoutMs: 300_000 });
    },
    onSuccess: (data, commit) => {
      setResult(data);
      void client.invalidateQueries({ queryKey: ["/ingest/runs"] });
      if (commit && data.committed) {
        toast("success", t("ingest.committed", { works: count(data.committed.works), alerts: count(data.committed.alerts) }));
        void client.invalidateQueries();
      }
    },
    onError: (e: Error) => toast("error", t("states.errorTitle"), e.message),
  });

  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    const dropped = event.dataTransfer.files[0];
    if (dropped) {
      setFile(dropped);
      setResult(null);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("nav.ingest")}
        subtitle={t("ingest.subtitle")}
        actions={
          <Button variant="outline" size="sm" onClick={() => void download("/ingest/template.csv", "mplads_upload_template.csv")}>
            <Download /> {t("ingest.template")}
          </Button>
        }
      />
      <div className="grid gap-4 xl:grid-cols-12">
        <div className="space-y-4 xl:col-span-5">
          <Card>
            <CardBody className="pt-5">
              <div
                role="button"
                tabIndex={0}
                onClick={() => input.current?.click()}
                onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
                onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
                onDragLeave={() => setDragging(false)}
                onDrop={onDrop}
                className={cn(
                  "grid-bg flex min-h-[240px] cursor-pointer flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed p-8 text-center transition-colors",
                  dragging ? "border-saffron bg-saffron/5" : "border-line hover:border-saffron/50",
                )}
                data-testid="dropzone"
              >
                <UploadCloud className="size-10 text-saffron-text" />
                <div className="font-medium">{file ? file.name : t("ingest.drop")}</div>
                <div className="text-xs text-muted">{file ? `${count(file.size / 1024)} KB` : t("ingest.formats")}</div>
                <input
                  ref={input}
                  type="file"
                  accept=".csv,.xlsx"
                  className="hidden"
                  onChange={(e) => { setFile(e.target.files?.[0] ?? null); setResult(null); }}
                  data-testid="file-input"
                />
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button variant="primary" disabled={!file || upload.isPending} onClick={() => upload.mutate(false)}>
                  {upload.isPending && upload.variables === false ? <Loader2 className="animate-spin" /> : <FileSpreadsheet />} {t("ingest.validate")}
                </Button>
                <Button variant="outline" disabled={!result?.scored || !!result.committed || upload.isPending} onClick={() => upload.mutate(true)}>
                  {upload.isPending && upload.variables === true ? <Loader2 className="animate-spin" /> : null} {t("ingest.commit")}
                </Button>
              </div>
              <p className="mt-3 text-xs text-muted">{t("ingest.hint")}</p>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title={t("ingest.runs")} />
            <CardBody className="px-0 pb-2">
              <QueryState query={runs} isEmpty={(d) => !d.length} empty={<EmptyState title={t("ingest.noRuns")} body={t("ingest.noRunsBody")} />}>
                {(d) => (
                  <ul>
                    {d.map((r) => (
                      <li key={r.id} className="flex items-center justify-between border-t border-line/60 px-5 py-2.5 text-sm">
                        <span className="min-w-0">
                          <span className="block truncate font-medium">{r.filename}</span>
                          <span className="block text-2xs text-muted">{dateTime(r.created_at, lang)} · {count(r.valid_rows)} / {count(r.rows)} {t("ingest.validRows")}</span>
                        </span>
                        <span className="flex gap-1.5">
                          {r.errors ? <Badge tone="danger">{r.errors} {t("ingest.errors")}</Badge> : null}
                          <Badge tone={r.committed ? "ok" : "outline"}>{r.committed ? t("ingest.isCommitted") : t("ingest.dryRun")}</Badge>
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </QueryState>
            </CardBody>
          </Card>
        </div>

        <div className="space-y-4 xl:col-span-7">
          {!result ? (
            <Card>
              <EmptyState icon={<FileSpreadsheet className="size-5" />} title={t("ingest.resultsTitle")} body={t("ingest.resultsBody")} />
            </Card>
          ) : (
            <>
              <Card className="p-5" data-testid="ingest-result">
                <div className="flex flex-wrap items-center gap-3">
                  {result.errors.length ? <XCircle className="size-5 text-danger" /> : <CheckCircle2 className="size-5 text-ok" />}
                  <span className="font-semibold">{result.filename}</span>
                  <Badge tone="outline">{count(result.valid_rows)} / {count(result.rows)} {t("ingest.validRows")}</Badge>
                  {result.scored ? <Badge tone="info">{t("ingest.scoredIn", { seconds: result.scored.elapsed_seconds })}</Badge> : null}
                  {result.committed ? <Badge tone="ok">{t("ingest.committed", { works: count(result.committed.works), alerts: count(result.committed.alerts) })}</Badge> : null}
                </div>
                {result.scored ? (
                  <div className="mt-4 grid grid-cols-4 gap-3">
                    {BAND_ORDER.map((b) => (
                      <div key={b} className="rounded-md border border-line bg-bg/40 p-3">
                        <div className="flex items-center gap-2 text-xs text-muted"><span className="size-2 rounded-full" style={{ background: bandColor(b) }} />{t(`bands.${b}`)}</div>
                        <div className="num mt-1 font-display text-xl font-semibold">{count(result.scored?.bands[b as Band] ?? 0)}</div>
                      </div>
                    ))}
                  </div>
                ) : null}
                {result.scored?.scoring_scope ? <p className="mt-3 text-xs text-muted">{result.scored.scoring_scope}</p> : null}
              </Card>

              {result.errors.length || result.warnings.length ? (
                <Card>
                  <CardHeader title={t("ingest.issues")} />
                  <CardBody className="max-h-[260px] space-y-1.5 overflow-y-auto">
                    {[...result.errors.map((e) => ({ ...e, kind: "error" as const })), ...result.warnings.map((w) => ({ ...w, kind: "warning" as const }))].map((issue, i) => (
                      <div key={i} className={cn("flex gap-3 rounded-md border px-3 py-2 text-sm", issue.kind === "error" ? "border-danger/30 bg-danger/5" : "border-warn/30 bg-warn/5")}>
                        <Badge tone={issue.kind === "error" ? "danger" : "warn"}>{issue.kind}</Badge>
                        <span className="num text-xs text-muted">{issue.row !== null ? `row ${issue.row}` : ""} {issue.column ?? ""}</span>
                        <span>{issue.message}</span>
                      </div>
                    ))}
                  </CardBody>
                </Card>
              ) : null}

              {result.scored?.top.length ? (
                <Card>
                  <CardHeader title={t("ingest.top")} hint={t("app.framing")} />
                  <CardBody className="space-y-2">
                    {result.scored.top.map((w) => (
                      <div key={w.work_id} className="rounded-md border border-line px-4 py-3">
                        <div className="flex items-start justify-between gap-4">
                          <div className="min-w-0">
                            <div className="truncate font-medium">{w.work_description}</div>
                            {result.committed ? (
                              <Link to={`/works/${w.work_id}`} className="font-mono text-2xs text-saffron-text hover:underline">{w.work_id}</Link>
                            ) : (
                              <span className="font-mono text-2xs text-muted">{w.work_id}</span>
                            )}
                          </div>
                          <div className="flex flex-col items-end gap-1">
                            <Money value={w.sanction_amount} className="font-semibold" />
                            <BandBadge band={w.band} score={w.risk_score} />
                          </div>
                        </div>
                        <ul className="mt-2 list-disc space-y-0.5 pl-5 text-xs text-muted">
                          {(lang === "hi" ? w.reasons_hi : w.reasons_en).map((r, i) => <li key={i}>{r}</li>)}
                        </ul>
                      </div>
                    ))}
                  </CardBody>
                </Card>
              ) : null}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
