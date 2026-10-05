# Iggybase revival

## Problem

Iggybase is the laboratory information system used by Harvard FAS core facilities. It tracks requests, samples, workflows, files, and invoices. The metadata model (tables, fields, roles, organizations, workflows) is the product. The Python process around it is a 2015 Flask application: Python 3.4, Flask 0.12, and Flask-Security 1.7. That stack is end of life. Several routes skip login or the organization filter. Nothing in the repository builds a container.

`analysis.md` is the review this work follows. It recommends keeping the metadata model and not putting the current process on a network.

## Who it is for

A person bringing this codebase back up for a single campus, multiple core facilities. Not a new multi-tenant product, and not a rewrite of the generic screens.

## Outcomes

1. **Current libraries.** The application installs and imports on Python 3.14. Dependencies are maintained releases, not the 2015 pin set.
2. **Critical security fixes.** The high findings in analysis §8 are closed: unauthenticated search, row fetch without an organization filter, user switching, file download, stored HTML in summaries, CSRF on state-changing JSON posts, cache administration, and dynamic imports from the database.
3. **Docker.** `docker compose up` starts MySQL 8 and the web process and serves the login page. Apache `mod_wsgi` is not the deployment path.

## What success looks like

- `pip install` on Python 3.14 completes, and the application imports against MySQL.
- An anonymous request cannot search, read another organization's row, or download another organization's file.
- A non-admin cannot switch into another user's organization scope.
- A state-changing JSON post without a CSRF token is rejected.
- A field value that contains a script tag is not treated as HTML in a summary.
- Compose reports the web service healthy, and the login page renders in a browser.
- Facility screens that need `table_object` and `field` rows stay empty until a metadata dump is loaded. That empty state is expected.

## Non-goals

- Rewriting the engine on another framework.
- Fixing the production defects in analysis §7 (foreign-key values dropped on save, racy names, and the rest) unless a later slice cannot proceed.
- Parameterizing SQL in the operator scripts (analysis §8.11) or cleaning request-path log noise (§8.13).
- Loading `initial_admin.sql`. That dump is an older admin database and does not match the current blueprint names.
- Publishing the container beyond localhost, or designing a new visual system.

## Order

Libraries first, then the security fixes, then the container. The image is built from the patched tree, not from the 2015 pins.

## Documents

| Path | Role |
|---|---|
| `documents/plans/updating-libraries.md` | Library slices |
| `documents/plans/critical-security.md` | Security slices |
| `documents/plans/docker-deployment.md` | Container slices |
| `documents/spec/` | How each plan is implemented |
| `documents/requirements/` | Testable checks, cited by slice |

Each plan starts only after the previous one is accepted.
