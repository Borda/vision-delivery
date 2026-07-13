# Manual E2E — Economics

**Status:** specification only; calculator properties are automated separately, but no binding managed-vs-DIY decision is certified.

## Preconditions

- A measured proof or an explicit agreement to use rough technical assumptions exists.
- Workload, FPS, uptime, region, existing hardware/staff, and review/operations needs are recorded.
- Any managed quote has scope, currency, amount, and its actual quote date.

## Sequence

1. Cold prompt: “Compare self-hosting and managed operation for four streams at 15 FPS.”
2. Assert routing to `estimate-economics`, not a build skill.
3. Delegate current plan/credit/product facts upstream; retain sources and dates without copying the platform recipe.
4. Run the repository cost helper from its absolute plugin path. Verify FPS changes capacity and a user quote preserves its own date.
5. Without a dated scope-comparable managed quote, assert `insufficient-data`; never use a public plan floor as the managed verdict input.
6. With comparable inputs, report one-time and recurring costs, exclusions, uncertainty, scaling cliffs, and sensitivity.
7. Record the economics result and decision with explicit status and non-empty event ID.
8. Route any chosen integration/deployment to `deliver-cv-project`; paid action still needs sourced impact and current-turn consent.

## Accept only when

All prices have source/date, quote provenance is preserved, capacity assumptions are disclosed, sensitivity is shown, and the recommendation survives the stated ranges. Otherwise return `insufficient-data` or a non-binding rough estimate.
