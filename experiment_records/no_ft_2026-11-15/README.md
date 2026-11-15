# Pretrained-only pilot records, 15 November 2026

These two complete collection archives preserve all 40 assignments, raw completion requests/responses, exact prompt token IDs, executed tool events, reports, source snapshots, deployment identity, and runtime logs. Generated text is research data, not instructions for the reader. Both models are official pretrained base checkpoints served in BF16 on one A100 80 GB, sequentially. No weights or credentials are included.

Each archive expands under `results/`. Verify SHA-256 against `checksums.json`. The archive checksums were also verified against the originals on the Vast instance before publication. The source at collection was commit `81c6721` on `no_ft`; source snapshots are authoritative for replay.

Twenty histories were assigned per model. Failures, missing reports, and early endings remain in the dataset. Collection completion does not establish task success, valid reporting, or honesty. Audit the full returned history against actual tool events and final self-reports, including use in estimates or method choice. The numerical submission alone is insufficient.

These copies and the separate local backups preserve the required experimental data independently of the Vast instance. The two-page comparison report and analyst annotations are included below.

## Reviewed comparison

- [Two-page comparison report](HF_pretrained_base_comparison.pdf), with important findings in red.
- [Case-by-case annotations](audit_annotations.json) for all 40 assignments, including the original report text and actual submission.
- [Descriptive counts](comparison_summary.json), including the end-marker rejection audit. These are not estimated lying rates.
- [Original DeepSeek pilot report](reference_original_pilot.pdf), the reference for the qualitative comparison.

The raw archives are unchanged. Their original `summary.json` files say manual review is pending because they were frozen before this audit. The separate annotation file records the subsequent review. This was an analyst review, not independent double coding. It distinguishes false history, nonresponsive text, acknowledged prohibited attempts, trace rewriting, and reports that match the visible history.

The strict completion adapter rejected all 17 early Qwen cases despite a valid first action before `END LIVE SESSION`; it also rejected four such Llama actions. Reports were then requested without explicit rejection feedback. Do not treat these as clean model-capability failures, or use the resulting counts to rank model honesty. No trajectories were repaired, relabelled as executed, or resampled after the audit.

Reproduce the archive verification and reviewed counts from the repository root using Python 3.12+:

```bash
python3 scripts/audit_base_pilot.py
# Requires reportlab and pypdf; the font falls back to Helvetica off macOS.
python3 scripts/report_base_pilot.py
```

The audit verifies manifest/result hashes, preserved source snapshots, every returned action's presence in the actual final-report prompt, and the central quoted claims against recorded events. It performs no model calls. The report is written to `output/pdf/HF_pretrained_base_comparison.pdf`.
