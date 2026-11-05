# Security boundaries

SentinAL is a supervised research prototype that can execute real Windows desktop actions. It is intended for a trusted local user on a loopback service. The public evaluation is not a security certification.

## Implemented controls and limits

- Proposed intents pass deterministic validation and capability controls before dispatch. Language-model output is a proposal, not permission.
- Filesystem checks reject selected unsafe targets and traversal patterns. These application checks are not a Windows security boundary, container or general filesystem sandbox.
- Confirmation support differs by channel. The REST helper defaults to `SENTINAL_REQUIRE_CONFIRMATION=false`. Enabling it alone does not establish immutable, complete-plan authorization across all entry points.
- Supported postconditions are checked against OS state. Other actions lack a durable independent check; a clean return is insufficient evidence of success for those actions.
- REST command, task and log endpoints require a bearer token. WebSocket routes have separate handling and do not enforce that same bearer-token boundary. Origin/CORS restrictions do not authenticate arbitrary clients.
- Privacy-aware LLM routing does not make the full voice pipeline local. Speech providers, logs and persisted data need separate review.

The 66-case adversarial regression covers its authored fixtures. It does not demonstrate resistance to every prompt injection, path race, GUI failure or malicious client. Historical containment proposals in [the architecture audit](CONTAINMENT_ARCHITECTURE.md) must not be assumed implemented.

## Operating guidance

Keep the service bound to `127.0.0.1`. Use a dedicated test directory and a supervised interactive Windows session. Review provider configuration before submitting sensitive speech or text. Do not expose the API directly to a network or rely on the prototype for unattended destructive operations.

Local `.env` files, bearer tokens and runtime stores must remain outside source control and desktop release resources. The Electron source configuration requires an independently provisioned Python environment and models; it is not a self-contained security-isolated distribution.

## Reporting

Report non-sensitive defects through [GitHub issues](https://github.com/pavann19/SentinAL-Desktop-AI-Orchestration/issues). For vulnerabilities, email the maintainer at pavangannoju.germany@gmail.com with affected revision, reproduction steps and a synthetic example. Do not post credentials, private documents or exploit details containing personal data in a public issue. No response-time or supported-release guarantee is currently offered.
