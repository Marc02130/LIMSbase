# Plan — updating libraries

Spec: `documents/spec/updating-libraries.md`
Requirements: `documents/requirements/updating-libraries.md`

Goal: the tree installs and imports on Python 3.14. Route authorization stays as it is.

Do not start the next slice until the current one has been reviewed.

## Slice 1 — Pins and imports

LIB-1, LIB-2, LIB-3, LIB-4.

- Replace `requirements.txt` with the package set in the spec. Pin versions that publish Python 3.14 wheels on the day this slice runs.
- Apply the import map. Point `login_view` at `security.login`.
- Leave `setup.py` unused. Do not delete it in this slice.

Done when `python3.14 -m pip install -r requirements.txt` exits 0, and a search of `iggybase/` finds no `flask.ext`.

## Slice 2 — Configuration

LIB-5, LIB-6, LIB-7.

- Add `config.py` reading the environment, with the URL concatenation `database.py` already uses.
- Open the SPINAL engine on first use, not at import.
- Add `.env.example` only if the Docker plan has not landed yet; otherwise the Docker plan owns that file. This slice may add it early so the import check can be repeated. Placeholders only.

Done when `import config` fails with a named variable when `SECRET_KEY` is unset, and succeeds when the required variables are set.

## Slice 3 — Flask-Security-Too model

LIB-8, LIB-9, LIB-10.

- Widen `User.password`, add `fs_uniquifier`, keep `verified` and the `is_active` rule.
- Confirm `SQLAlchemyUserDatastore` uses `DBFactory.session`.
- Adjust `ExtendedLoginForm` and `ExtendedRegisterForm` only as far as the new base classes require.
- Against a reachable empty MySQL database, `import iggybase` succeeds and admin tables exist.

Done when that import check passes. No route review.

## Slice 4 — Bootstrap helpers

LIB-11.

- Restore `bootstrap_find_resource`, `bootstrap_is_hidden_field`, and `bootstrap/wtf.html` for Bootstrap 3, by a shim or by Bootstrap-Flask.
- Render the login template far enough to see the form fields. A full browser pass waits for Docker if no local server is up. If a local server is up, open `/login`.

Done when the login template renders without a missing-macro error.

## Slice 5 — Pillow and WeasyPrint

LIB-12.

- Confirm Pillow imports.
- Confirm WeasyPrint imports where Cairo and Pango exist. If the machine has neither, record that and leave the proof to DKR-2. The packages must still be in `requirements.txt`.

Done when Pillow imports and the WeasyPrint result is recorded.

## Out of scope

Login policy, CSRF, org filters, the container, invoice PDF rendering, and analysis §7.
