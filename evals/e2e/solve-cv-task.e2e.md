# Manual E2E — Plain-Language Router

**Status:** specification only; historical routing metrics predate the current route set.

## Preconditions

- Sentinel is loaded in a recorded host/version.
- A public-safe sample problem and any representative media are available.

## Sequence

1. Start with a vague outcome, such as: “Use this camera to tell me when pallets pile up.”
2. Assert Sentinel inspects available artifacts and asks no more than three plain operational questions.
3. Assert the response identifies action, required output unit, independent evidence, first success gate, data boundary, and one owning route.
4. Test ambiguity discriminators: per-frame count vs identity event, whole-image verdict vs per-person PPE, pixel mask vs calibrated physical measurement, and accepted-model delivery vs new build.
5. Assert exact platform/model/tool truth is delegated upstream and no volatile recipe is copied.
6. Continue into the selected specialist until a frozen acceptance artifact exists; do not accept routing alone as task completion.
7. For an already accepted capability, assert routing to `deliver-cv-project`. For setup failure, assert routing to `check-sentinel-setup`/`auth-setup`.

## Accept only when

Every labeled prompt routes to the intended owner or a justified ambiguity response, no negative-control prompt fires a build route, and the current route set—including delivery and setup—is covered in repeated Codex and Claude runs. This condition is not yet met by committed live evidence.
