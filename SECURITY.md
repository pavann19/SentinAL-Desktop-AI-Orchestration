# Security policy

SentinAL is a local, supervised research prototype. Keep the backend on loopback,
protect `.env` and `.sentinal_token`, and use a disposable desktop for risky tasks.
No supported multi-user or internet-facing deployment exists.

## Boundaries

Models propose actions; deterministic code enforces policy and confirmation.
REST bearer authentication and WebSocket first-frame authentication protect command
entry points. Browser WebSocket origins are explicitly restricted. Health endpoints
remain public. The token is a capability for the local service: anyone who steals it
can submit policy-permitted commands.

Policy validation does not replace process isolation. Docker npm installs mount the
chosen workspace writable and permit network access. Missing Docker, script preparation
errors and Linux native-module output never authorize a host fallback. Host pip
installation is disabled. CodeAct requires Windows Sandbox and fails closed if unavailable. Other OS capabilities run with the user's permissions;
containment and postcondition coverage must be assessed per capability.

Only load joblib classifiers produced by trusted local training. Pickle-based model
files can execute code. Do not accept arbitrary model files from issues or downloads.

## Reporting

Report suspected vulnerabilities privately to the maintainer at
`pavangannoju.germany@gmail.com`. Include affected commit, a minimal reproduction,
and impact; omit live tokens, private prompts and personal files. Do not post working
credentials in public issues. No response-time SLA or supported-release policy is promised.

Removing a secret from the current tree does not remove it from Git history. Rotate
exposed credentials first; coordinate any history rewrite separately.
