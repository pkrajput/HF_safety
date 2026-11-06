# Verified sources and scope

Checked on 2026-11-06. Stable primary links are supplied. Bibliographic DOI metadata not retrieved from a source is intentionally omitted rather than constructed. arXiv papers are identified as preprints, not peer-reviewed results.

1. Slocum, Palan, Chute, Kim and Van Roy (2026). *OpenAI–HuggingFace: A Reproduction & Lessons for Alignment Testing*. [Preprint](https://arxiv.org/abs/2609.35799). Motivates compute-aware auditing, multi-step failures, and scrutiny of artificial environment affordances. Its discovery-compute result does not establish an effect of increasing a target agent's episode budget.
2. Greenblatt, Cotra and Wijk (2026). [METR independent HF investigation](https://metr.org/blog/2026-08-26-openai-hugging-face-incident-investigation/). Motivates competing hypotheses about scorer beliefs, recovery, and trace manipulation. An incident investigation does not identify our experimental causal effects.
3. Zhang (2026). *The Troy Moment*. [Preprint](https://arxiv.org/abs/2609.15494). Motivates separating authority, peer information and task impossibility. Its behavioural analysis is not a neural mechanism demonstration.
4. Brazilek et al. (2026). *Coercion and Deception in AI-to-AI Management*. [Preprint, v6](https://arxiv.org/html/2607.15434v6). Motivates honest-exit controls. Use the detailed residual-error results rather than reading the abstract as a universal elimination claim.
5. Geiger et al. (2024). *Finding Alignments Between Interpretable Causal Variables and Distributed Neural Representations*. [CLeaR/PMLR](https://proceedings.mlr.press/v236/geiger24a.html). Methodological basis for candidate alignment and interchange interventions. DOI not verified.
6. Geiger et al. (2025). *Causal Abstraction: A Theoretical Foundation for Mechanistic Interpretability*. [JMLR](https://jmlr.org/papers/v26/23-0058.html). Defines the relation between high-level causal explanations and neural interventions. DOI not verified.
7. McCoy et al. (2026). *The Emergent Symbolic Structure of Artificial Neural Networks*. [Preprint](https://arxiv.org/abs/2608.29530). Motivates structured role/filler hypotheses and counterfactual intervention tests. This package does not implement DISCOVER or establish its guarantees for agent reporting.
8. Palumbo et al. (2026). *Formal Policy Enforcement for Agentic Systems*. [Preprint, v4](https://arxiv.org/html/2602.16708v4). Supports the distinction between external enforcement guarantees and model honesty. Guarantees require faithful observation and complete mediation.
9. ASD Simplified Technical English Maintenance Group. [Current standard overview](https://www.asd-ste100.org/about_STE.html) and [FAQ](https://www.asd-ste100.org/STE_faq.html). Issue 9, January 2025, is the version named in this design. The standard combines writing rules and a controlled dictionary and permits defined technical terminology. This repository neither redistributes the full standard nor certifies its generated prompts.
10. [CSCS hardware](https://docs.cscs.ch/alps/hardware/#nvidia-gh200-gpu-nodes) and [Container Engine](https://docs.cscs.ch/software/container-engine/). Supports the four-module GH200 node layout and EDF/Slurm deployment pattern. Validate the actual allocated node and site image.
11. [ACL 2027 official dates](https://2027.aclweb.org/) and [first call](https://www.aclweb.org/portal/content/acl-2027-first-call-papers). The listed ARR submission deadline is January 4, 2027, AoE. Recheck official policies before submission; this is distinct from the later conference commitment deadline.

## Model cards

The revised game also draws design motivation from Dwarkesh Patel's November 5, 2026 [Blood on the Clocktower write-up](https://www.dwarkesh.com/p/clocktower): fixed rules, persistent state, multiple strategies, and a programmatic referee. Our game assigns a legitimate cooperative objective and measures reporting mechanisms; it does not copy the social-deception objective or use Elo as a deception metric. This is a benchmark write-up, not a peer-reviewed causal study.

- [DeepSeek-R1-0528](https://huggingface.co/deepseek-ai/DeepSeek-R1-0528), full requested target; [published shards](https://huggingface.co/deepseek-ai/DeepSeek-R1-0528/tree/main).
- [GLM-5.3](https://huggingface.co/zai-org/GLM-5.3), installed target named by the owner; [vLLM deployment recipe](https://recipes.vllm.ai/zai-org/GLM-5.3).
- [Qwen3.5-397B-A17B-FP8](https://huggingface.co/Qwen/Qwen3.5-397B-A17B-FP8), proposed full-size third-family comparator.
- [Apertus-70B-Instruct-2509](https://huggingface.co/swiss-ai/Apertus-70B-Instruct-2509), reserved auxiliary auditor.
- [NVIDIA H200 specifications](https://www.nvidia.com/en-us/data-center/h200/), 141 GB memory per GPU; a four-GPU allocation is not an eight-GPU deployment.
- [vLLM reasoning output documentation](https://docs.vllm.ai/en/latest/features/reasoning_outputs/), parser-specific separation of reasoning and final content.

The original Qwen3-32B, Apertus-target, Mistral-Small and GLM-Air selection is archived in `configs/models.legacy.json`. It is not the revised target roster.

The cards establish checkpoint identity, licensing information and supported use. They do not certify performance on this experiment. Record exact revisions and actual serving settings during collection.
