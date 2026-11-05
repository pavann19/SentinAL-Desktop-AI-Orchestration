# Evaluation and reproducibility

Results belong to a dataset, configuration and source checkpoint. The revised [thesis](../thesis/Thesis.md) contains the detailed methodology and downloadable evidence inventory. Earlier thesis material remains in the [historical record](../historical-record/README.md).

## Reported measurements

| Stage | Measurement | Interpretation |
|---|---|---|
| Earlier zero-shot router | 54.6% intent accuracy; 57.4% deterministic fast-path resolution on 704 utterances | Original evaluation configuration |
| Earlier trained-classifier evaluation | 99.3% held-out and 92.0% OOD accuracy; 94.2% and 84.7% fast-path resolution respectively | Earlier datasets/splits; not directly comparable to later corpora |
| Later real-world phrasing evaluation | 92.33% accuracy | MASSIVE-derived supported-intent corpus |
| Later synthetic OOD evaluation | 83.68% accuracy | Separately authored harder examples |
| Classifier-era router | 88.45% resolution without fallback LLM invocation | Local routing still uses a classifier/embedding model; “no LLM” does not mean “no model” |
| Real desktop benchmark | 116/120 successful tasks, 96.7%; reported 95% CI 91.7–98.7% | Self-authored tasks, independent OS checks; not hosted CI |
| Earlier privacy-routing slice | 4/4 local vs 3/4 cloud-default success | Four tasks; insufficient for a statistical performance claim |
| Security fixtures | 66/66 blocked | Finite authored adversarial suite |
| October 6, 2026 CI | 1,333 passed, 2 skipped; 86.75% coverage | [Identified historical run](https://github.com/pavann19/SentinAL-Desktop-AI-Orchestration/actions/runs/37445301449) |

Changing corpus size, labels, router configuration or model artifacts can change the result. These figures are not a single before/after controlled experiment. Generated reports and trained classifier artifacts are not bundled in the public repository; source availability alone does not reproduce their exact values.

## Router evaluation

After installing dependencies and providing the intended model artifacts:

```powershell
python scripts/reproduce_router_accuracy.py --run-id local-review
```

This evaluates the committed `eval/intent_dataset.json` without invoking an LLM. It records dataset identity and per-intent outcomes under `_evidence/intent_accuracy/`. Embedding weights may download on first use. If the trained classifier is absent, the router uses its available fallback configuration; do not label that result a reproduction of the trained-classifier measurement.

A smaller Linux environment is available for router-only evaluation:

```powershell
docker build -t sentinal-router-eval .
docker run --rm sentinal-router-eval
```

The image runs as a non-root user and evaluates the public router configuration. It does not contain the private/generated classifier, provide desktop execution, or reproduce the 120-task benchmark. Model loading can require network access; output is printed and the JSON report lives inside the container unless an output directory is mounted.

## Desktop evaluation

`benchmarks/run_benchmark.py --repeat 3` is a live Windows benchmark, not a safe headless smoke command. Inspect task definitions first and use a disposable, supervised desktop environment. Retain source/configuration identities, raw outcomes, independent OS observations and failed attempts. Do not run it against personal data.

## Automated checks

[CONTRIBUTING.md](../CONTRIBUTING.md) documents the exact CI selection, retained exclusions, coverage threshold and report artifacts. Current workflow status is available in [GitHub Actions](https://github.com/pavann19/SentinAL-Desktop-AI-Orchestration/actions/workflows/ci.yml). Automated suites and real-machine benchmarks answer different questions.
