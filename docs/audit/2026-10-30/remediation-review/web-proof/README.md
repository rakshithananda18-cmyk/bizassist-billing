# Synthetic web review proofs

These artifacts use only synthetic A/B identities and mocked requests. They
are independent from the old audit's tests that asserted the presence of bugs.
The component assertions here require **correct behavior**; failures document
remaining conditions in the reviewed working tree.

From the repository root, the two Node probes run directly:

```powershell
node --experimental-vm-modules docs/audit/2026-10-30/remediation-review/web-proof/outbox-replay.cjs
node docs/audit/2026-10-30/remediation-review/web-proof/invoice-read-error.cjs
```

The outbox probe expects correct replay containment and passes. Its output
retains both original operations after the account change. The invoice probe
executes the current catch callback in isolation and reports whether the
intended error state is reached; the captured result exposes the missing
`logger` import. Both scripts read the current product modules, so results can
change after subsequent fixes. They write synthetic output under `scratch/`.

Component tests use existing Billing app React/Vitest/jsdom dependencies through
the archived config. To rerun without altering product/test files:

1. Copy `vitest.config.cjs.txt` to
   `scratch/remediation-web-vitest.config.cjs`.
2. Copy the four `*.test.jsx.txt` files here to the corresponding
   `scratch/remediation-web-tests/*.test.jsx` names, removing `.txt`.
3. Run from the repository root:

```powershell
.\frontend-billing\node_modules\.bin\vitest.cmd run --config scratch/remediation-web-vitest.config.cjs --reporter=dot
```

The recorded component outputs are `component-probes.log` (six initial checks:
three pass, three fail) and `late-queue-probe.log` (one additional failing check).
Together they represent seven disjoint checks, with three passing and four
failing correct-behavior expectations. No dependency installation, live backend,
browser account, external message, or financial database is needed.
