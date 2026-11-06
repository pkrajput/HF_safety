# Instructions for the cluster operator or agent

Use the full target checkpoints requested for this study. Start with the existing GLM-5.3 installation, then DeepSeek-R1-0528, then the proposed Qwen3.5-397B-A17B-FP8 comparator. Apertus-70B is reserved for auxiliary auditing. The old small-model target list is archived, not a fallback.

1. Read [CLUSTER.md](CLUSTER.md) and inspect the actual GPU/CPU allocation. Check the node, running server, model directories and Hugging Face cache for GLM-5.3 yourself. Use the verified existing installation; if absent, download the pinned checkpoint with the command below. Find and record artifact, revision, precision, offload and launch details on the node. Do not ask the study owner to obtain these details for you. Preserve working infrastructure.
2. Keep **one model resident at a time**. Finish its selected study stages and stop its server before loading another family. External-server mode does not stop the server for you.
3. Serve small batches of isolated swarms against that one model. Begin with `--workers 2`; each study team uses four separate agent contexts. Increase concurrency only after profiling. Do not load one model copy per agent.
4. Generate the main manifests with `--fixtures 12 --team-sizes 4 --repetitions 1 --budget-profile frontier`. This plans **384 fresh swarms per target**, plus separately budgeted solo controls. Count reports and continuation branches separately; they are not new swarms.
5. Run the capability/language/format pilot first. Check reasoning truncation and task completion with the frontier budgets. Preserve raw reasoning and final answers. A cutoff is an incomplete observation, not a lie or an honest answer.
6. Freeze actual model artifacts, precision, serving options, manifests and allocation before confirmation. Measure throughput before promising the full count within 48–72 hours. If necessary, choose a smaller balanced design before collection.
7. If a full checkpoint does not fit, report the concrete memory/serving issue and resolve its deployment. Do not substitute Distill, Air, Flash or a smaller checkpoint, silently quantize, or use a hosted paid model as a fallback.
8. Preserve failures, unstarted assignments, partial results and unknown-cost requests. Resume only with identical identities. Verify and back up each stage before unloading a model.
9. Keep poisoned experiments separate from fair-world estimates. Do not select or drop examples because an agent did or did not misreport.
10. Run the independent auditor after targets, with human review of a balanced annotation sample. Do not infer private intent from generated reasoning or auditor labels.

The repository has software tests and synthetic smoke results. It has no completed GPU experiment, measured frontier throughput, certified STE material, or validated frontier neural-intervention implementation.


If GLM-5.3 is absent, download it before the GPU collection window on the site's permitted transfer service:

```bash
python3 scripts/download_models.py --models configs/models.lock.json --root /absolute/scratch/models --only glm53
```

Use the same check-then-download procedure for `deepseek_r1`, `qwen_full` and `apertus_auditor`. Inspect existing snapshot/cache paths first to avoid redundant copies. Installing weights does not prove they fit in GPU memory; resolve the actual serving format during the node pilot and record it. The operator or executing agent fills the deployment record after checking the node. This does not require an additional approval from the study owner.
