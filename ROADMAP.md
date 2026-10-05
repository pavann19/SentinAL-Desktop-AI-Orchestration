# Roadmap

SentinAL remains a supervised Windows research prototype. Priorities are release
reproducibility and tested security boundaries before wider autonomy.

## Current scope

Intent routing, deterministic validation, capability tiers, budgets, confirmations,
supported OS postconditions, authenticated local transports and reproducible evaluation
are implemented. Tests and CI verify their documented scope; they do not certify
desktop reliability across machines.

## Remaining verification

- Repeat OS-state benchmarks on the final release commit with public provenance.
- Measure GUI resolution across DPI and multi-monitor configurations.
- Validate long-running event handling and cancellation under a supervised soak.
- Expand independently authored external benchmark tasks.
- Review remaining host-executed capabilities and filesystem mount boundaries.
- Validate a supported installer and package-specific configuration/token lifecycle.
- Provide a complete upstream dataset export/mapping recipe and resolved environment lock.

## Experimental / deferred

Learned skills, procedural/semantic memory, environment modelling and bounded
improvement proposals remain opt-in. Real shadow evaluation is required before
activation. Cross-machine control, tool synthesis, unattended multi-session operation
and formal proofs are not implemented. No feature may change its own security policy.
