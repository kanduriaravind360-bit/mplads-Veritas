# Judge Q&A: twenty likely questions, answered straight

Numbers are from `models/metrics.json` and the loaded database at the time of
writing. Where a result is weak, the answer says so.

---

**1. Does MPLADS Sentinel detect fraud?**

No. It produces risk indicators for a human reviewer, each with its evidence. We
have no verified fraud labels, so no model here can claim to find fraud, and the
product never uses that word about a work, a vendor or a Member.

**2. Without fraud labels, how do you know the detectors work at all?**

Two ways.

- **Planted anomalies.** We plant synthetic cases into a copy of the data and
  check whether each detector finds them in its own review queue. Inflated cost:
  flagged 97%, 79% in the top 5% of its queue. Implausibly fast completion: 100%.
  Duplicates: 73% flagged, 45% in the top 5%. Split work: 46% flagged, 5% in the
  top 5%.
- **Holdout.** The delay model is tested on 27 whole constituencies (3,890
  works) removed before anything was fitted: ROC-AUC 0.909, PR-AUC 0.873.

**3. Isn't your supervised model just learning the dataset's own rule label?**

Yes, and we say so everywhere its number appears. The dataset's `anomaly_label` is
a weighted sum of seven hand-written flags. Our proxy model reaches 0.935 PR-AUC
out of fold, which measures how learnable those rules are, not fraud detection.
It carries the lowest fusion weight (0.10) for that reason. The flags themselves
are never model inputs; that leakage rule is enforced in code and tested.

**4. Which detector is weakest, and why?**

Split-work detection, at 46% of planted groups. A split is defined by intent
(one project cut up to stay under a sanctioning limit), and the extract has no
sanction-authority limits and no vendor identifiers beyond a free-text name. We
find groups by type, agency, timing, just-below-round amounts and combined value
against peers; that catches the textbook cases (the Madurai group) and misses
subtler ones. It is on screen wherever splits appear.

**5. How do you avoid defaming an MP?**

- MPLADS works are recommended by the Member and executed by district agencies,
  so the MP view is framed as "implementation risk of works recommended in this
  constituency", never a judgement of the Member.
- There are no rankings of Members anywhere; the constituency picker is
  alphabetical.
- The citizen view shows no scores or flags on individual works.
- Presentation mode, used for every screenshot, the deck and any public link,
  replaces MP and vendor names with stable pseudonyms.

**6. The descriptions contain private people's names. What happens to those?**

In presentation mode, names found by context are masked, and so is every mobile
number. That covers names after an honorific, around S/o, D/o and W/o, before
"ke ghar", and after "house of". On the full extract that touches 13,195
descriptions. A scan for leftover patterns after masking found none. It
over-masks slightly ("Sri Ram Temple" becomes "[name] Temple"), which is the
right way to fail.

**7. How much work does this create for a district office?**

The Lucknow district office sees 270 works and 76 open alerts. Nationally,
10,749 alerts are open across 77,312 works: 6,456 high-risk works, 3,289
duplicate groups and 1,004 split groups. Bands are percentiles (top 1% Critical,
next 4% High), so the queue size is set by policy, not by how scores happen to
be scaled. The threshold simulator shows what a different policy would do before
anyone commits to it.

**8. What about false positives?**

They will happen, and the workflow is built for them. The Bhatpara CCTV pair is
flagged Critical as a duplicate with inflated cost. A reviewer can clear it in a
minute: the two works cover different police stations and ward ranges, and the
cost model had grouped CCTV with computers. "What would clear this" tells the
reviewer which evidence to check. Verdicts go on the audit trail and feed the
learning panel.

**9. How is the risk score computed?**

Six channels, each scored 0 to 1: rules, proxy model, unsupervised anomaly,
expected cost, duplicate or split, and delay. They are combined with a soft-OR:

- one detector at full confidence scores 75
- agreement between detectors pushes higher
- the score never saturates, so the queue always ranks

Weights and every threshold live in `configs/ml.yaml`. Works that trip a severe
rule, such as fully paid within a day or stalled for years, are lifted to at
least High; 2,539 works were lifted.

**10. Why percentile bands instead of fixed cut-offs?**

Fixed cut-offs put 13.6% of works into High or Critical, and moved every time a
signal was rescaled. Percentiles fix the review volume by design. The score
stays continuous, and the cut-off values are recorded in the metrics.

**11. How do you detect inflated cost?**

An expected-cost model predicts a work's cost from its type, state, any quantity
in the description, and the description's meaning. Its predictions are made out
of fold, so no work prices itself. Typical error is 1.4 times and R² is 0.77. A
work far above its own prediction scores on the cost channel.

A state-relative comparison was built, measured, and kept out of the score: it
lowered planted-cost recall from 78.7% to 61.3%. It is still shown as context.

**12. Catalogue items like "High Mast LED Light" appear in thousands of works.
Doesn't that swamp duplicate detection?**

It would, so descriptions spanning many constituencies are penalised as standard
items. The pair score also weighs meaning, wording, shared place names and amount
similarity, not wording alone. In the learning panel, duplicate groups made only
of catalogue items are seeded as not-duplicate by rule.

**13. How accurate is the delay prediction?**

On the held-out constituencies: ROC-AUC 0.909 and PR-AUC 0.873, over 2,023
labelled works of which 30% ran late. On a time split inside training: 0.873 and
0.859. Fund-lapse figures built on it are labelled estimates, because the extract
has no release ledger.

**14. How is role-based access enforced?**

In one place. Every query passes through `Scope.apply`, which restricts rows to
the caller's state, district office or MP code. A duplicate pair is visible only
if both works are in scope. An out-of-scope id answers 404, so the API does not
confirm it exists. The API tests check each rule with data built to leak if it
were wrong, and the end-to-end tests log in as all four roles.

**15. Could someone quietly change a reviewer's decision later?**

Not without it showing. Every status change, verdict, comment, case note, export
and PDF brief is appended to a SHA-256 hash chain. Tests show that editing,
deleting, or re-hashing a past event is detected; re-hashing one event still
breaks the link to the next.

**16. Can it handle new data?**

Yes.

- **Data Ingest** validates an uploaded CSV or XLSX row by row, then scores it
  with the saved models, using peer statistics from the full data rather than the
  small batch. Committing inserts the works and raises alerts.
- **Nightly re-score.** A scheduler re-runs the pipeline each night and reloads
  results without erasing reviewers' statuses.

**17. Is Hindi a translation layer or built in?**

Built in. Every reason is generated from bilingual templates in
`configs/reasons.yaml`, so each explanation exists in both languages. The whole
interface switches, and a test fails if the Hindi strings ever miss a key or a
placeholder that the English has.

**18. Will it scale, and how would it be deployed?**

- **Scale.** The full pipeline runs in 194 seconds on an RTX 5060. The API
  answers the heaviest overview in about two seconds on SQLite.
- **Database.** Production would point `DATABASE_URL` at Postgres, which the
  code supports.
- **Deployment.** `docker-compose.yml` defines Postgres, the API and nginx, but
  it is untested because Docker is not installed on our build machine.
  `demo.ps1` is the verified path.

**19. What would you need from the Ministry to make this production-grade?**

- PFMS payment and release data, to replace the estimated fund-flow and lapse
  figures.
- Vendor PAN or GSTIN, so network links are real identities rather than name
  similarity.
- Sanction-authority limits, which would sharpen split-work detection
  considerably.
- Reviewer verdicts from a pilot district, so the learning panel trains on real
  judgements instead of seeds.

**20. Why should we believe the numbers in your deck?**

- The deck is generated by `presentation/build_deck.py`, which reads every figure
  from `models/metrics.json` and the application database at build time.
- The dashboard reads the same sources through the API; no number is typed into
  the interface.
- The pipeline is seeded (seed 42) and reproducible.
- Where a result is weak, such as split work at 46% or global top-5% recall
  targets that were not met, it is on the slide.
