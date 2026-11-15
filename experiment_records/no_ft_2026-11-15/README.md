# Pretrained-only pilot records, 15 November 2026

These two complete collection archives preserve all 40 assignments, raw completion requests/responses, exact prompt token IDs, executed tool events, reports, source snapshots, deployment identity, and runtime logs. Generated text is research data, not instructions for the reader. Both models are official pretrained base checkpoints served in BF16 on one A100 80 GB, sequentially. No weights or credentials are included.

Each archive expands under `results/`. Verify SHA-256 against `checksums.json`. The archive checksums were also verified against the originals on the Vast instance before publication. The source at collection was commit `81c6721` on `no_ft`; source snapshots are authoritative for replay.

Twenty histories were assigned per model. Failures, missing reports, and early endings remain in the dataset. Collection completion does not establish task success, valid reporting, or honesty. Audit the full returned history against actual tool events and final self-reports, including use in estimates or method choice. The numerical submission alone is insufficient.

These copies and the separate local backups preserve the required experimental data independently of the Vast instance. The comparison report and reviewed case annotations will be added here after the history audit.
