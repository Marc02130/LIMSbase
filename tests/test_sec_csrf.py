"""MySQL-backed checks for CSRF (SEC-9, SEC-10).

Uses iggybase_sec5 so the other security schemas and the empty iggybase
database stay untouched. CSRF stays enabled in this process. The other
security tests set WTF_CSRF_ENABLED false and must not be run here.
"""
import hashlib
import json
import os
import re
import unittest
import uuid
from urllib.parse import quote

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("SECURITY_PASSWORD_SALT", "test-salt")
os.environ.setdefault("DB_USER", "iggybase")
os.environ.setdefault("DB_PASSWORD", "change-me")
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "3306")
os.environ["DATA_DB_NAME"] = "iggybase_sec5"
os.environ.setdefault("UPLOAD_FOLDER", "/tmp/iggybase-uploads")
os.environ.setdefault("FILE_FOLDER", "/tmp/iggybase-sec5-files")
os.environ.setdefault("ALLOWED_EXTENSIONS", "pdf,csv")

import pymysql
from itsdangerous import URLSafeTimedSerializer
from sqlalchemy import text

_ROOT_PASSWORD = os.environ.get("MYSQL_ROOT_PASSWORD", "change-me")
_conn = pymysql.connect(
    host=os.environ["DB_HOST"],
    port=int(os.environ["DB_PORT"]),
    user="root",
    password=_ROOT_PASSWORD,
)
try:
    with _conn.cursor() as _cur:
        _cur.execute("DROP DATABASE IF EXISTS iggybase_sec5")
        _cur.execute(
            "CREATE DATABASE iggybase_sec5 CHARACTER SET utf8mb4 "
            "COLLATE utf8mb4_unicode_ci"
        )
        _cur.execute(
            "GRANT ALL PRIVILEGES ON iggybase_sec5.* TO 'iggybase'@'%'"
        )
        _cur.execute("FLUSH PRIVILEGES")
    _conn.commit()
finally:
    _conn.close()

from flask_security.utils import hash_password
from flask_wtf.csrf import CSRFError
from iggybase import create_app
from iggybase.admin import models
from iggybase.database import db_session, engine, init_db

EMAIL = "csrf@example.com"
PASSWORD = "csrf-secret"
_FORM_TOKEN = re.compile(
    r'name="csrf_token"[^>]*value="([^"]+)"|value="([^"]+)"[^>]*name="csrf_token"'
)
_ROUTES = (
    ("core", "update_table_rows"),
    ("core", "change_role"),
    ("core", "change_user"),
    ("core", "modal_add_submit"),
    ("core", "multiple_entry"),
    ("billing", "generate_invoices"),
)


def _add(model, **kwargs):
    row = model()
    for key, value in kwargs.items():
        setattr(row, key, value)
    db_session.add(row)
    return row


def _seed_modules():
    init_db()
    _add(models.Module, name="core", blueprint=True, active=True)
    _add(models.Module, name="billing", blueprint=True, active=True)
    db_session.commit()


def _seed_world(app):
    with app.app_context():
        root = _add(models.Organization, name="facility-root", active=True)
        everyone = _add(models.Organization, name="Everyone", active=True)
        db_session.flush()
        root.organization_id = root.id
        everyone.organization_id = root.id
        visible = _add(
            models.Organization,
            name="visible-lab",
            active=True,
            organization_id=root.id,
            parent_id=root.id,
        )
        db_session.flush()
        level = _add(
            models.Level, name="user", active=True, order=2, organization_id=root.id
        )
        facility = _add(
            models.Facility,
            name="lab",
            active=True,
            organization_id=root.id,
            root_organization_id=root.id,
        )
        db_session.flush()
        role_a = _add(
            models.Role,
            name="lab-user",
            active=True,
            organization_id=root.id,
            facility_id=facility.id,
            level_id=level.id,
        )
        role_b = _add(
            models.Role,
            name="lab-user-other",
            active=True,
            organization_id=root.id,
            facility_id=facility.id,
            level_id=level.id,
        )
        db_session.flush()
        user = _add(
            models.User,
            name="csrf-user",
            email=EMAIL,
            password=hash_password(PASSWORD),
            fs_uniquifier=uuid.uuid4().hex,
            active=True,
            verified=True,
            organization_id=visible.id,
        )
        db_session.flush()
        link_a = _add(
            models.UserRole,
            name="csrf-role-a",
            active=True,
            organization_id=root.id,
            user_id=user.id,
            role_id=role_a.id,
        )
        link_b = _add(
            models.UserRole,
            name="csrf-role-b",
            active=True,
            organization_id=root.id,
            user_id=user.id,
            role_id=role_b.id,
        )
        db_session.flush()
        user.current_user_role_id = link_a.id
        _add(
            models.UserOrganization,
            name="csrf-user-org",
            active=True,
            organization_id=root.id,
            user_id=user.id,
            user_organization_id=visible.id,
            default_organization=True,
        )
        modules = {
            row.name: row
            for row in db_session.query(models.Module).all()
        }
        for module_name, module in modules.items():
            _add(
                models.ModuleFacility,
                name="lab-" + module_name,
                active=True,
                organization_id=root.id,
                facility_id=facility.id,
                module_id=module.id,
            )
        for module_name, url_path in _ROUTES:
            route = _add(
                models.Route,
                name=module_name + "-" + url_path,
                active=True,
                organization_id=root.id,
                module_id=modules[module_name].id,
                url_path=url_path,
            )
            db_session.flush()
            for role, label in ((role_a, "a"), (role_b, "b")):
                _add(
                    models.RouteRole,
                    name="rr-" + url_path + "-" + label,
                    active=True,
                    organization_id=root.id,
                    role_id=role.id,
                    route_id=route.id,
                )
        db_session.commit()
        return {
            "user_id": user.id,
            "role_a_id": role_a.id,
            "role_b_id": role_b.id,
            "link_a_id": link_a.id,
            "link_b_id": link_b.id,
        }


class CsrfTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _seed_modules()
        cls.app = create_app()
        cls.app.testing = True
        cls.app.config["PROPAGATE_EXCEPTIONS"] = True
        ids = _seed_world(cls.app)
        cls.user_id = ids["user_id"]
        cls.role_a_id = ids["role_a_id"]
        cls.role_b_id = ids["role_b_id"]
        cls.link_a_id = ids["link_a_id"]
        cls.link_b_id = ids["link_b_id"]

    @classmethod
    def tearDownClass(cls):
        db_session.remove()

    def test_login_uses_its_own_form_token(self):
        client = self.app.test_client()
        page = client.get("/login")
        html = page.get_data(as_text=True)
        self.assertEqual(200, page.status_code, html[:800])
        self.assertIn('<meta name="csrf-token"', html)
        self.assertIn('name="csrf-token"', html)
        missing = client.post(
            "/login",
            data={"email": EMAIL, "password": PASSWORD, "submit": "Login"},
        )
        self.assertEqual(400, missing.status_code, missing.get_data(as_text=True)[:800])
        self.assertIn("CSRF", missing.get_data(as_text=True))
        signed_in = self._login(client)
        self.assertIn(signed_in.status_code, (302, 303), signed_in.get_data(as_text=True)[:800])
        static = client.get("/static/main.js")
        script = static.get_data(as_text=True)
        static.close()
        self.assertEqual(200, static.status_code)
        self.assertIn("X-CSRFToken", script)

    def test_posts_without_a_token_do_not_write(self):
        client = self.app.test_client()
        self._login(client)
        before_rows = self._row_counts()
        before_role = self._role_link()
        for url, kwargs in self._posts():
            response = client.post(url, **kwargs)
            body = response.get_data(as_text=True)
            self.assertEqual(400, response.status_code, url + " " + body[:800])
            self.assertIn("CSRF", body)
        self.assertEqual(before_rows, self._row_counts())
        self.assertEqual(before_role, self._role_link())

    def test_valid_token_reaches_the_handlers(self):
        client = self.app.test_client()
        self._login(client)
        headers = {"X-CSRFToken": self._signed_token(client)}
        before_rows = self._row_counts()

        changed = client.post(
            "/lab/core/change_user",
            json={"user_id": self.user_id},
            headers=headers,
        )
        self.assertEqual(200, changed.status_code, changed.get_data(as_text=True)[:800])
        self.assertEqual({"success": False}, json.loads(changed.get_data(as_text=True)))
        self.assertEqual(self.link_a_id, self._role_link())

        rows = self._dispatch(
            lambda: client.post(
                "/lab/core/update_table_rows/sample",
                json={},
                headers=headers,
            )
        )
        self._assert_reached(rows)
        modal = self._dispatch(
            lambda: client.post(
                "/lab/core/modal_add_submit/sample",
                data={},
                headers=headers,
            )
        )
        self._assert_reached(modal)
        invoices = self._dispatch(
            lambda: client.post(
                "/lab/billing/generate_invoices/2024/1/",
                json={"orgs": ["visible-lab"]},
                headers=headers,
            )
        )
        self._assert_reached(invoices)
        entry = self._dispatch(
            lambda: client.post(
                self._multiple_entry_url(),
                data={"csrf_token": headers["X-CSRFToken"]},
                headers=headers,
            )
        )
        self._assert_reached(entry)
        self.assertEqual(before_rows, self._row_counts())
        self.assertEqual(self.link_a_id, self._role_link())

        other = self.role_b_id
        switched = client.post(
            "/lab/core/change_role",
            json={"role_id": other},
            headers=headers,
        )
        self.assertEqual(200, switched.status_code, switched.get_data(as_text=True)[:800])
        self.assertEqual({"success": "lab"}, json.loads(switched.get_data(as_text=True)))
        self.assertEqual(self.link_b_id, self._role_link())

    def test_multiple_entry_bad_token_does_not_save(self):
        client = self.app.test_client()
        self._login(client)
        before_rows = self._row_counts()
        before_role = self._role_link()
        missing = client.post(self._multiple_entry_url(), data={"name": "should-not-save"})
        forged = client.post(
            self._multiple_entry_url(),
            data={"csrf_token": "not-a-token", "name": "should-not-save"},
            headers={"X-CSRFToken": "not-a-token"},
        )
        for response in (missing, forged):
            body = response.get_data(as_text=True)
            self.assertEqual(400, response.status_code, body[:800])
            self.assertIn("CSRF", body)
        self.assertEqual(before_rows, self._row_counts())
        self.assertEqual(before_role, self._role_link())

    def _posts(self):
        return (
            ("/lab/core/update_table_rows/sample", {"json": {"updates": {"name": "rewritten"}}}),
            ("/lab/core/change_role", {"json": {"role_id": self.role_b_id}}),
            ("/lab/core/change_user", {"json": {"user_id": self.user_id}}),
            ("/lab/core/modal_add_submit/sample", {"data": {"name": "inserted"}}),
            (self._multiple_entry_url(), {"data": {"name": "inserted"}}),
            (
                "/lab/billing/generate_invoices/2024/1/",
                {"json": {"orgs": ["visible-lab"]}},
            ),
        )

    def _multiple_entry_url(self):
        return "/lab/core/multiple_entry/sample/" + quote('["new"]', safe="")

    def _login(self, client):
        page = client.get("/login")
        html = page.get_data(as_text=True)
        self.assertEqual(200, page.status_code, html[:800])
        found = _FORM_TOKEN.search(html)
        self.assertIsNotNone(found, html[:800])
        token = found.group(1) or found.group(2)
        return client.post(
            "/login",
            data={
                "email": EMAIL,
                "password": PASSWORD,
                "submit": "Login",
                "csrf_token": token,
            },
        )

    def _signed_token(self, client):
        with client.session_transaction() as sess:
            raw = sess.get("csrf_token")
            if not raw:
                raw = hashlib.sha1(os.urandom(64)).hexdigest()
                sess["csrf_token"] = raw
        serializer = URLSafeTimedSerializer(self.app.secret_key, salt="wtf-csrf-token")
        return serializer.dumps(raw)

    def _role_link(self):
        with self.app.app_context():
            db_session.expire_all()
            user = db_session.query(models.User).filter_by(id=self.user_id).one()
            return user.current_user_role_id

    def _row_counts(self):
        counts = {}
        with engine.connect() as conn:
            names = conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = DATABASE()"
                )
            ).fetchall()
            for (name,) in names:
                if not re.fullmatch(r"[A-Za-z0-9_]+", name):
                    continue
                counts[name] = conn.execute(text("SELECT COUNT(*) FROM `%s`" % name)).scalar()
        return counts

    def _dispatch(self, func):
        try:
            return func()
        except Exception as exc:
            with self.app.app_context():
                db_session.rollback()
            return exc

    def _assert_reached(self, outcome):
        if isinstance(outcome, Exception):
            self.assertNotIsInstance(outcome, CSRFError)
            return
        self.assertNotEqual(400, outcome.status_code, outcome.get_data(as_text=True)[:800])


if __name__ == "__main__":
    unittest.main()
