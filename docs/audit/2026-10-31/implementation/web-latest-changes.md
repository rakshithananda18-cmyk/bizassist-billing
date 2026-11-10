# Field frontend review — 31 October 2026

**Recommendation: keep the Field changes with the targeted corrections now applied. A blanket revert would discard useful route, collection and mobile interaction improvements.** The latest complete Field run passes **89 tests in 22 files**, and its production build passes. These are local results against the current working tree, not a deployed-device acceptance claim.

The review covered the full latest changes to `components/Icons.jsx`, `components/MapView.jsx`, `components/ui.jsx`, `layouts/StaffLayout.jsx`, `lib/format.test.js`, `lib/geo.js`, new `lib/geo.test.js`, `pages/staff/MyScore.jsx`, `MyTasks.jsx`, `NewRequest.jsx`, `Today.jsx`, `styles.css` and `vite.config.js`. Existing backend/session contracts were traced where these changes depend on them. The earlier whole-code audit and remediation review remain historical in the 30 October folder.

## Keep

- The map/list route views, shop distance, explicit route/task summaries, clearer task types, collection amount chips, cash change calculation, bottom sheets and refresh actions.
- The task and score screen presentation, request form improvements, GPS/duty visibility and reduced phone interaction effort.
- The development proxy's explicit `127.0.0.1` backend target. The `0.0.0.0` development host permits intended phone access; production output is unaffected. Browser GPS still requires HTTPS outside trusted localhost contexts.

## Corrections applied before acceptance

1. **Payment destination and QR privacy:** Field had added a staff-VPA/hardcoded fallback and external QR-image request. It now uses only the current Billing merchant's `billing_business.upi_vpa`, validates the destination and positive amount, and renders the QR locally using locked `qrcode.react@4.2.0`. A missing merchant VPA displays an actionable message. Showing the QR does not mark payment received. Root added the tenant-owned merchant VPA to the backend profile contract.
2. **Map controls:** changing only `centerOn` now centers the map; equal-length changed path coordinates and marker colors/popups redraw; click callbacks use current state; expanded/resized maps invalidate their dimensions. OpenStreetMap attribution is visible. Staff GPS updates preserve a user's pan; owner map fitting retains its existing behavior.
3. **Route access:** the default map view now exposes Start route and a selector for every assigned route. A completed route no longer presents its first completed stop as the next stop. Stop-owned sheets reset when switching focused stops. The all-method collection total is labelled Collected rather than Cash In.
4. **Account ownership across GPS and reads:** Staff actions capture the original session/body before awaiting GPS and refuse to post after an account change. Late day responses cannot populate the new account. Trackers are recreated for their immutable business/worker/session owner, and the authenticated page subtree resets across identities.
5. **Request shop/stop consistency:** changing the selected shop no longer sends the original URL's unrelated stop ID. Source read failures are visible, request history does not become a false empty list, invalid quantities are excluded, and concurrent duplicate submits are locked. The form says Order Request, matching its owner-review workflow.
6. **Attendance labels:** zero recorded attendance now says No attendance recorded this month. Perfect is shown only with positive recorded attendance and no late days.
7. **Smaller interaction correctness:** modal/sheet Escape handling respects the topmost dialog, switch keyboard focus is visible, new sheet/map animations respect reduced-motion preferences, invalid coordinates/distances do not become proximity claims, and UPI input rejects malformed addresses/non-finite amounts.

No entire feature or screen was reverted. Changes preserve the user's layout and visual direction.

## Acceptance evidence

| Check | Actual result |
| --- | --- |
| `frontend-task`: `npm test -- --maxWorkers=2 --minWorkers=1 --reporter=dot` | 89 passed; 22 files; 31.87s |
| `frontend-task`: `npm run build` | Passed; 4.77s |
| New regression coverage compared with the 74-test baseline | 15 additional passing tests: map 3, Today 4, StaffLayout 2, NewRequest 2, MyScore 2, geo 2 |
| `frontend-admin`: `npm run lint` | Passed with zero warnings, including the restored useful rules |
| Frontend working-tree whitespace check |`git diff --check` passed |

Runnable regression sources are checked into the working tree alongside the implementation: `components/MapView.test.jsx`, `layouts/StaffLayout.test.jsx`, `pages/staff/{Today,NewRequest,MyScore}.test.jsx` and `lib/geo.test.js`. They use synthetic data and no real payments or external messages. The acceptance command/result metadata is in [web-apps-results.json](web-apps-results.json).

The final Field bundle is 528.35kB minified / 154.69kB gzip. Vite reports its 500kB chunk-size warning; this does not fail the build. The now-large `Today.jsx` is a maintenance cost: extracting collection, route cockpit and duty components is a reasonable follow-up after this behavior is stable. This is not a reason to discard the feature work.

Physical-phone GPS/background behavior, installed-PWA lifecycle, merchant-app payment receipt and map tile availability were not exercised by the local component suite. Test them on a phone before release. No live payment was initiated and no production service was modified.

## Next steps

1. Keep the current corrected working tree; review the new tests together with the affected workflows.
2. Run one phone acceptance pass covering check-in, Start route, switching routes, GPS center/expand, one linked collection, merchant QR display and switching accounts while location is pending.
3. Use the final [root acceptance record](root-results.json) for backend/sync and the Billing rerun. Prior complete frontend evidence is distinguished from fresh results in the results files.
4. Consider splitting the Field entry bundle and `Today.jsx` after release acceptance; preserve the new regression coverage.

## Subsequent server print regression

The broader backend suite exposed four unclosed financial-summary conditions in `backend/core/billing/templates/invoice_classic_a4.html`. Their missing `endif` tags are now restored. The thermal template's corresponding conditions were already closed correctly. No print-payload or financial calculation code changed.

`check-server-templates.py` in this folder parses both server invoice templates and renders each with and without credit/refund adjustments: two templates parsed and four synthetic render cases passed. The isolated API regression `tests/test_phase1b.py::test_invoice_pdf_route` also passed (one test; 23.37s). This test validates the endpoint's PDF or documented HTML-fallback response, depending on available renderer dependencies.

## Shared backend acceptance

The complete standalone Field backend suite passed 155 tests with ten explicit
contract/PostgreSQL skips. The subsequent complete suite on a fresh PostgreSQL
database migrated through Billing's actual Alembic history and Field's own
history passed **165 tests with zero skips**. This includes the current merchant
VPA, Billing ticket exchange, credit-adjusted collections, concurrent completion
and planning, and business-deletion lifecycle. The fixture database used UTF8;
external-schema test writes now use Billing's full models and valid tenant
relationships rather than its read-only mirror. No production constraint was
weakened to obtain the result. Exact commands and limits are in root-results.json.
