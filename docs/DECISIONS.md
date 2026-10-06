# Architecture decisions

| Decision | Reason / implementation |
|---|---|
| Treat models as untrusted | Authority is defined by validator, contracts, broker, budgets and confirmation code |
| Authorize each resolved action | Replanning and data substitution can change the intent or target; approval of the previous action is insufficient |
| Bind confirmation to executable fields | Prompt text and a capability tier cannot identify the exact operation; arguments, resources and targets are hashed |
| Derive verification in trusted code | Planner predicates are hints; they cannot establish successful execution |
| Stop changed shell repairs | Automatic command replacement would execute a command the user did not approve |
| Observe OS outcomes | `postcondition_observer.py` distinguishes a return value from durable state |
| Authenticate command transports | REST bearer checks and bounded WebSocket first-frame authentication |
| Keep the service local | Single-user Windows prototype, loopback default, explicit browser Origin allowlist |
| Fail closed on dependency installation | npm requires Docker; no host fallback; pip host execution disabled |
| Regenerate models locally | Generated classifiers/embeddings are outside public Git; artifact-free routing is separately tested |
| Keep learning default off | Learned skills and improvement proposals do not widen policy authority |
| Publish methodology, archive raw output | Results need commit, environment, routing mode and dataset provenance |

These decisions do not establish complete process isolation or production readiness.
See the [security boundary](../SECURITY.md) and [roadmap](../ROADMAP.md).
