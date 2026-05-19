# Posts templates

Polymorphic intake (`referral` / `opening` / `program_availability`) — pages extend `base.html` directly because the kind-picker and the per-kind forms don't fit the resource grammar's single-form-page shape.

## Kind picker

`form_new.html` renders `GET /posts/form` (no `?kind=`) as a `.kind-picker` chooser — one `<a class="kind-picker-option" data-kind="…">` per registered kind, each with a Lucide icon + title + 1-line description, round-tripping back to the same route with `?kind=…`. Adding a kind means adding another option block here, and extending the `[data-kind="…"]` border rule in [`../../../framework/templates/base.html`](../../../framework/templates/base.html) if the new kind needs its own accent color. The chooser shares the `--form-max-width` envelope with the per-kind forms it routes to.

## Two-layer per-kind forms

Each kind ships a pair: a `_<kind>_form.html` macro `(hx_method, action, submit_label, post=None)` that renders the full intake form (shared field macros from [`../../../framework/templates/_shared/form_fields.html`](../../../framework/templates/_shared/form_fields.html)), and a thin `new_<kind>.html` / `edit_<kind>.html` wrapper that calls the macro with the right method/action. Adding a kind = add the macro + two wrappers and register their paths on the kind's `PostKindSpec` in [`../../models/posts/post_kinds.py`](../../models/posts/post_kinds.py); the route layer reads `spec.create_template` / `spec.edit_template`.

`list.html` / `detail.html` / `_item.html` carry kind-aware branches (`{% if post.kind == "<kind>" %}`). When a new kind ships, add the branch in both. Filter and chip vocabularies come from `ChoiceFilter("kind", ...)` in [`../../specs/post.py`](../../specs/post.py).

## Insurance posture

The unified 4-state insurance posture is derived per-post by [`../../logic/posts/view.py`](../../logic/posts/view.py)`::insurance_posture_for_post` (registered as the `insurance_posture` Jinja global) — collapses the asymmetric CR (`network_preference` + nullable `insurance_carrier`) and PA (Provider's `in_network_carriers` + `accepts_out_of_network` / `sliding_scale` flags) into one labeled chunk.

## Wire-shape normalization

Multi-checkbox fields (`desired_times`, `services`, `settings`) are normalized on the wire schema by `_scalar_to_list` in [`../../logic/posts/schema.py`](../../logic/posts/schema.py) — forms submit form-encoded data via `hx-{post,patch}`.

## New controlled-vocabulary

Tuple + `*_LABELS` + `*_ICONS` (Lucide icon names) all three live in [`../../models/enums.py`](../../models/enums.py); register all three as Jinja globals in [`../../../framework/rendering/templating.py`](../../../framework/rendering/templating.py). The `test_icons_cover_their_tuples` guard in `test_schema.py` fails the build if an icon entry is missing.
