# Domain templates: transactional emails

Templates rendered as email bodies, not HTTP responses. Each pair is
`<name>.html` + `<name>.txt` — both parts required for deliverability
(text/plain keeps the spam score down at strict providers).

## Grammar (deviates from `src/domain/templates/`)

These templates **do not extend** `base.html` and do not pull in
shared partials. Each file is fully self-contained — inline CSS only,
no JS, no `{% include %}`. Email clients (especially Gmail / Outlook)
strip `<head>`-level styles and reject anything that smells like a
web page, so the chrome-portable patterns the rest of the templates
use don't apply here.

The Jinja env that renders these is the same one used for HTTP
responses (`src.framework.rendering.templating.templates.env`); the
`.html` autoescape rule still applies, so user-supplied values like
`{{ username }}` are HTML-safe in the HTML part. `.txt` files do not
autoescape (extension-based), so the plain-text part should never
embed untrusted attribute-shaped content.

## Where these are rendered

Domain wrappers in [`src/domain/logic/auth/emails.py`](../../logic/auth/emails.py)
render both parts of a pair, then hand off to the framework's
`send_email`. Hooks in `src.auth_config.UserManager` call those
wrappers — never `_render` or `send_email` directly.
