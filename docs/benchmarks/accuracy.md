# Result interpretation

## Current artifact-free checkpoint (2026-10-05)

`python scripts/reproduce_router_accuracy.py --run-id release-clean` measured
**2,002/3,230 correct (61.98%)** on the committed synthetic dataset
(SHA-256 prefix `ee781fc2276e3b21`). This run used no generated classifier,
Python 3.13.3, sentence-transformers 6.1.0, transformers 5.18.0 and torch 2.14.1
on CPU with cached MiniLM weights. It measures intent labels, not task completion
or security strength. Per-intent performance varies substantially; CodeAct routing
scored 0/165 in this mode. The raw report is archived outside public Git.

## Current training reproduction (2026-10-05)

The documented `python -m eval.finetune_classifier --run-id release-clean` command
also completed in an external source-only copy using the same updated environment.
The standalone logistic-regression classifier scored **477/485 (98.35%)** on its
stratified synthetic test split and **164/190 (86.32%)** on the versioned synthetic
OOD set. Split seed: 42; selected C: 10.0. These are classifier-component scores,
not an end-to-end router score, real-world accuracy or OS-task success rate.
Training created embeddings, split indices and a trusted classifier outside the
public tree; no pre-generated artifact was needed. This host reproduction does
not verify the Docker build or container execution.

## Historical trained/configured observations

Historical project documentation recorded 116/120 successful OS-verified task
attempts (96.7%, Wilson 95% interval 91.7–98.7%), 92.33% real-world routing accuracy,
83.68% synthetic OOD accuracy, and 88.45% fast-path resolution. These came from
specific local model/classifier configurations. They are **historical observations**,
not a score for the current clean checkout or a production reliability guarantee.

The original raw outputs are preserved outside the public source tree. The public
source retains the datasets, benchmark tasks and verification implementation.
Without the original environment/result manifest, independent confirmation of
those exact historical numbers remains unverified.

A fresh checkout has no generated classifier. Report artifact-free routing separately
from locally trained routing. Do not carry historical classifier accuracy over to
fallback mode. Run the commands in [methodology](methodology.md) and publish the
resulting provenance before changing numerical claims.

Adversarial regression tests are a finite sample, not a guarantee of universal
blocking. Passing CI measures its configured code/test/coverage scope only.
