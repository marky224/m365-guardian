# Security Model

M365 Guardian performs privileged Microsoft 365 administration from natural language, so its security
posture is the product, not an afterthought. This document describes the model at a conceptual level.

> Responsible disclosure: if you believe you've found a security issue, please contact the repository
> owner directly rather than opening a public issue.

## Threat model in one line

The system assumes the **LLM can be manipulated** (prompt injection via user input, tenant data, or
tool results) and is built so that a compromised model still cannot perform an unapproved write or
exceed its granted privileges.

## Controls

### 1. Two-layer, server-enforced write confirmation
- **Layer 1** — every mutating tool is gated server-side in the executor. A write cannot execute
  without an explicit confirmation flag that the model is structurally unable to set on its own behalf.
- **Layer 2** — confirmation is bound to a **human action** (web Approve/Cancel buttons; a Teams
  Adaptive Card) carrying a **server-minted, single-use token**. The token is validated **in code**
  against a server-stored pending record, and the **stored** action is what executes — never an action
  the model reconstructs at approval time.
- Consequence: a prompt-injected model cannot self-approve, cannot forge a token, and cannot swap the
  approved action for a different one.

### 2. Least privilege
- Graph **application** permissions are scoped to exactly the operations the tools perform.
- Privileged directory roles are granted narrowly (e.g. a helpdesk-tier role for password resets),
  and intentionally cannot act on higher-privileged targets — denials there are correct behavior.
- The Exchange sidecar exposes a **narrow** set of operations, not a general PowerShell endpoint.

### 3. Secretless identity (defense in depth)
Managed identity for Graph and Cosmos, optional Workload Identity Federation for web sign-in, and a
**keyless two-hop** path to the Exchange sidecar mean there are no long-lived secrets on the hot path
to steal or leak. Where a secret is unavoidable, it lives in Key Vault and is fetched via managed
identity at startup.

### 4. Full audit trail
Every read and write is recorded with who, what, when, and the conversation transcript, in an
append-only store — so any action the assistant takes is attributable and reviewable after the fact.

### 5. No silent failure
Unconfigured or unavailable capabilities return structured, truthful results (`not_implemented` and
similar) rather than fabricated success — a safety property as much as an honesty one, because it
prevents the assistant from reporting a privileged change that never occurred.

### 6. Data handling
- Passwords and secrets are masked in output and never echoed.
- Conversation/session data is scoped to the authenticated user.
- Provider isolation: customer data is not used for model training.

### 7. Network & supply-chain hygiene
- Platform-level access restrictions sit in front of the application.
- `gitleaks` secret scanning runs as a pre-commit hook and in CI across full history.
- Dependencies are pinned; CI type-checks against the real SDKs to avoid masked drift.

## What is intentionally not public

Exact resource names, tenant identifiers, permission GUID sets, and the step-by-step provisioning of
identities and role assignments are maintained privately. None of these are required to understand or
evaluate the security model above; they are operational details whose disclosure would only ease
unauthorized deployment.
