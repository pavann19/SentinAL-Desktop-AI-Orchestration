# Evaluation methodology

## Three distinct measurements

1. Router accuracy compares predicted intents against versioned expected labels.
2. Pipeline task evaluation checks routing, approval and outcome expectations.
3. Desktop benchmarks verify task outcomes using OS-state observations independent
   of the pipeline's success message. These require a real supervised Windows desktop.

```powershell
python scripts/reproduce_router_accuracy.py
python -m eval.run_eval --run-id local
python benchmarks/run_benchmark.py --repeat 3
```

Full task evaluation and benchmarks can mutate the desktop. Read `eval/tasks.yaml`
and `benchmarks/tasks.py`, use a disposable workspace, and review setup/teardown.
The safe focused offline subset is documented in the root README.

Record the commit and dirty state, Python/dependency versions, machine/OS, provider,
model identity, feature flags, classifier hash/presence, dataset hash, task selection,
seed and repetitions. Router-only evaluation is exhaustive; full-pipeline sampling
must state its sample seed. Finetuning uses stratified splits with random seed 42.
Downloaded model revisions and ranged dependencies can drift; exact numeric replay
requires preserving those resolved versions alongside results.

Benchmark summaries use Wilson confidence intervals. Preserve failures; do not
cherry-pick repetitions or treat a launched process as completed work. Postcondition
settling polls are not a retry of the action itself. Report skipped/unverifiable
actions separately, including conversational actions with no durable OS fact.

The benchmark is primarily self-authored. `benchmarks/external/` supports declarative
external tasks, currently a small set; this does not constitute an independent audit.

## Headless reproduction

```powershell
docker build -t sentinal-eval .
docker run --rm sentinal-eval
docker run --rm sentinal-eval python -m eval.measure_intent_accuracy --mode router-only --run-id docker
```

The image trains from source datasets and writes temporary evidence inside the
container. First use downloads embedding weights. It cannot execute Windows desktop
actions and does not depend on an existing private `_evidence` directory.

Detailed outputs belong in ignored `_evidence/` and `benchmarks/results/`, or a
protected external archive. Publish only reviewed summaries or sanitized release
assets with provenance. Reports can contain prompts, paths and machine information.
