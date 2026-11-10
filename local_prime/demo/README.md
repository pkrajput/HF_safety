# Local pre-node demo

This is a small exploratory API demo, not the larger node experiment. It uses
the existing Gemini and DeepSeek API configurations in `local_prime/models.json`.
It makes no claim to reproduce the full self-hosted models.

The frozen manifest assigns 120 independent histories: two models, six profiles,
two language instructions, and five matched fixtures. Profiles are baseline,
lower score pressure, broad prohibition on using protected information, blocked
grader access with no prime disclosure, easy public factoring, and final-only
audit announcement. The STE condition requests **ASD-STE100 Simplified Technical
English** by name for model communication; task wording remains English and
compliance with the standard is not certified.

Each history gets up to 12 action turns and one structured report. The owner
changes the instructions after three turns or an early attempted finish. Full
observer records are retained even when final-only auditing is announced.

## Running

Use Python with `reportlab` and `pypdf`, and have `pdftoppm` on PATH. From the
repository root, create a fresh plan, then supervise it:

```bash
python -m local_prime.demo.run plan --out results/NEW_DEMO --oldroot results/local-prime-2026-11-10
python -u -m local_prime.demo.run supervise --out results/NEW_DEMO
```

Load API keys from `~/.config/hf-safety/keys.env` using the existing client. Do not
commit keys. The supervisor uses four concurrent histories per model and ends
collection within 50 minutes. It then writes `demo_report.pdf`, rendered page
images, `episodes.csv`, `summary.json`, `review_queue.json`, and `DONE.json`.
`job.json` and the console log provide progress. Network loss or host sleep can
prevent collection; a local background job is not a remote service.

The $50 cap includes the old ledger's charged amount plus outstanding reserves.
Each request reserves its conservative full cost ceiling before dispatch. Lost
responses are not retried; their full ceiling is booked, their outcome is
missing, and unrelated assignments may proceed. A pre-existing result is never
automatically rerun. Do not start two supervisors for the same output folder.

## Reading the results

Report counts separately for each model, profile, and language. Wilson 95%
intervals describe available binary outcomes; they do not resolve selection
from missing requests. The JSON also gives worst-case missing-outcome bounds.
Five fixtures per cell provide very limited precision. Comparisons are
exploratory and not adjusted for multiple testing.

Exact arithmetic matches and structured-report contradictions are observable
flags. They are not proof of intent, concealment, or semantic narrowing. Publicly
derived factors can also match protected values. Returned reasoning needs
contextual review, including unflagged examples; the text-screen review queue
is only a navigation aid. Review the final rendered PDF and representative
trajectories before making a decision about the node experiment.
