# Local validation

Preparation date: 2026-11-06. These checks validate software behaviour. They are not experimental model results.

- 23 unit/integration tests passed on local Python 3.14.6, including an actual loopback HTTP client/server contract check.
- Both task families have scripted legitimate solutions in solvable and recoverable conditions.
- Direct reads are denied in the vulnerable condition; the catalog/export route succeeds; the hardened resolver denies that route.
- Authorised-access controls remain usable under the hardened resolver.
- The language assignment does not change world files or mechanical truth labels.
- The scope probe truth table covers both agreement and disagreement cases.
- Hash-chain editing is detected; code/configuration mismatch prevents silently reusing a completed episode.
- Unresolved in-flight requests are not automatically retried.
- A complete mock CLI pipeline produced 32 synthetic episodes, 96 paired reports and 96 replay contexts, with no infrastructure errors. Mock output is excluded from publication results.
- Self-auditing with the same model family is rejected.
- Python source compilation and Slurm script shell syntax checks passed.
- Four model repository revisions were pinned by metadata lookup. No model weights were downloaded.

The CI workflow tests Python 3.11–3.13. Its remote status must be checked after pushing; local success does not imply the workflow has run.

Not validated locally: GPU loading, vLLM execution on CSCS, actual target capability, throughput, model adherence to ASD-STE100, equivalence of all prompt wording, human annotation agreement, neural interventions, or experiment power. The cluster instructions and study protocol identify these checks explicitly.
