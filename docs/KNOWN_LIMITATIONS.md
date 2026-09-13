# Known limitations

What MPLADS Sentinel does not do, does badly, or has not been tested on. The
figures are from `models/metrics.json` and the loaded database. If something
here stops being true, update this file.

## The data

- **No verified fraud labels.** The dataset's `anomaly_label` is a weighted sum
  of seven hand-written flags. Every model learns patterns or that proxy, never
  confirmed wrongdoing, and every output is a risk indicator for review.
- **A snapshot, not a ledger.** The eSAKSHI extract runs to 31 August 2026 and
  carries no entitlement, release or payment history.
  - "Entitlement" is the scheme rule (₹5 crore a year per MP), labelled as an
    estimate and shown only at All-India and single-MP scope.
  - Fund-lapse figures are undisbursed value multiplied by delay probability,
    labelled as estimates.
- **Vendors are free-text names.** There is no PAN, GSTIN, address or bank
  account, so vendor-network links are name similarity, and one firm spelt two
  ways counts as two vendors.
- **The state column is the MP's state.** A Rajya Sabha member can fund works
  in another state.
  - The Risk Map joins districts by state and name, placing 99.3% of works; the
    rest are counted in a footnote.
  - The citizen view lists districts by implementing agency to avoid the
    mismatch.
- **District boundaries are an older map.** Districts renamed or created
  recently are drawn inside their parent boundary (`configs/district_aliases.yaml`).
  Karnataka names in the source file were truncated and are repaired by census
  code.

## Detection

- **Split-work detection is weak.** It flags 46% of planted split groups and
  finds 5% in the top 5% of its queue. Without sanction-authority limits and
  vendor identifiers it catches textbook cases and misses subtle ones.
- **Duplicates are middling.** 73% of planted duplicates are flagged; 45% reach
  the top 5% of their queue.
- **Step 2b targets were missed.** The global top-5% recall targets were not met
  for any detector: duplicates 9%, fast completion 81%, inflated cost 53%,
  split groups 12%. Per-queue recall is the fairer measure, but the misses are
  real.
- **Injection recall is an upper bound.** Planted cases are cleaner than real
  ones, so detector sensitivity to them overstates sensitivity in the field.
- **The proxy model reproduces the rule label.** Its 0.935 PR-AUC measures how
  learnable the rules are. It carries the lowest fusion weight for that reason.
- **Severe rules widen the queue.** The floor lifts 2,539 works, taking High plus
  Critical from 5.0% to 8.5% of training works, above the intended 5%. We kept it
  because those rules describe cases a reviewer should see.
- **Cost depends on the work-type guess.** A work typed wrongly is priced against
  the wrong peers; the Bhatpara CCTV works were grouped with computers. The
  state-relative cost comparison is shown but kept out of the score, because it
  lowered planted-cost recall from 78.7% to 61.3%.
- **Uploads are scored on thinner context.** Duplicates and the unsupervised
  layer are computed within the uploaded batch. Split detection adds works from
  the same agencies. In the step-2e demo set, 5 of 13 demo works landed in their
  intended band.

## Learning from reviewers

- **The demonstration labels are not reviewer verdicts.** Positives are planted
  synthetic cases and negatives are rule-seeded benign patterns. Precision at 50
  (0.94 configured, 0.96 re-weighted and re-ranked) shows the mechanism working,
  not precision in the field.
- **Nothing learned is applied automatically.** Changing production weights is a
  manual decision, previewed in the threshold simulator.

## Privacy

- **Masking is a heuristic.** Presentation mode masks names found by context:
  honorifics, S/o, D/o and W/o, "ke ghar", "house of", and phone numbers. It
  touches 13,195 descriptions and over-masks slightly. A name with no context
  word around it can still pass.
- **Screenshots are not text-checked.** They are protected by the end-to-end
  suite refusing to run unless the API reports presentation mode.
  `scripts/privacy_scan.py` checks every committed text file and the deck
  against all real MP and vendor names.
- **Git history holds an earlier holdout record.** The step 2e commit's
  `configs/holdout.yaml` lists four Rajya Sabha members' names as held-out
  "constituencies": excluded from training, with no score or flag. The current
  file records them as digests. History was not rewritten, because the project
  never force-pushes.
- **Real names appear when presentation mode is off.** That mode is meant for
  authorised officials on private screens.

## Engineering

- **Not deployed.** `docker-compose.yml`, the Dockerfiles, `render.yaml` and the
  Makefile are untested because Docker and make are not installed on the build
  machine. `demo.ps1` is the verified path.
- **Postgres is supported but untested end to end.** SQLite is what was run.
- **Authentication is demo-grade.**
  - JWT (HS256) with PBKDF2 password hashes.
  - No single sign-on, rate limiting or lockout.
  - The demo accounts share the published password `demo123`, and must be
    changed before any real use.
- **The nightly re-score expects the pipeline's hardware.** It needs a GPU and a
  few minutes, so the scheduler is disabled in the demo.
- **Some text stays English in Hindi mode.** The whole interface and every
  generated reason switch, but some API-supplied notes, rule labels and model
  captions do not. PDF briefs are English only, because the standard PDF fonts
  cannot shape Devanagari.
- **Accessibility was designed, not audited.** Colour tokens were chosen for AA
  contrast, and components use Radix primitives with keyboard support. No
  automated audit (such as axe) has been run.
- **Built for a 1920×1080 screen.** The dashboard is not designed for phones.
- **Not built:** the optional anomaly time machine.
- **Pins are machine-specific.** Windows Smart App Control on the build machine
  blocks new compiled Python wheels. Pins in `pyproject.toml` (numpy, scipy,
  scikit-learn, regex, lxml) are versions verified to load there.
