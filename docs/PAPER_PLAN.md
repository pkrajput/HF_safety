# Paper plan

Working title: **Language Under Audit**.

Research question: How do controlled language and computational opportunity affect agents' interpretations and reports of their own actions, and what causal intervention prevents a demonstrated failure?

The paper should lead with a tested linguistic mechanism. Security provides the motivating setting. Neither an isolated exploit demonstration nor a cross-model leaderboard is sufficient for that contribution.

## Proposed main-text structure

1. Introduction: the ambiguity between interpreting a rule, selecting a criterion, and reporting a known event; state only contributions supported by collected evidence.
2. Related work: controlled language, pragmatic narrowing and misleading truthful statements, agent evaluation, causal abstraction, and external enforcement. Organise around the remaining gap.
3. Definitions and experimental design: the three axes, objective versus ambiguous rules, fair task affordances, language review, and preregistered estimands.
4. Language and compute results: assigned language effects and adherence; search-cost baseline and target-budget effects; capability and utility controls.
5. Mechanism and intervention: discriminating counterfactual predictions, failures of alternative explanations, held-out intervention tests, and the safeguard's exact scope.
6. Discussion and conclusion: what replicated across the tested families and what remains unknown.
7. Limitations: mandatory dedicated section; synthetic task scope, model selection, language compliance, few task templates, compute window, and limits on intent claims.
8. Ethics and reproducibility: sandboxed assets, no external exploitation, raw data/analysis access, compute accounting, annotation process, and disclosure of writing/coding assistance under applicable policy.

## Evidence required before writing claims

- A validated language treatment or honest use of the term "STE instruction" instead of "STE-compliant language".
- Independently specified truth conditions and ambiguity review.
- At least one statistically interpretable primary contrast, with unit of analysis and missing-data handling fixed in advance.
- Held-out tests that could reject the proposed mechanism, rather than a probe that only predicts the output.
- A safeguard assessed jointly on safety and useful completion.
- Per-model results, including nulls and reversals. Three selected checkpoints cannot support a prevalence claim about most LLMs.

The official ACL 2027 schedule currently lists January 4, 2027 as the ARR submission deadline. This leaves roughly two months from the preparation date. Prioritise a defensible central result and its critical controls; do not turn every proposed subhypothesis into a claimed contribution.
