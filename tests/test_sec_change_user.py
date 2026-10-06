"""MySQL-backed checks for change_user (SEC-7, SEC-8).

Uses iggybase_sec4 so the other security schemas and the empty iggybase
database stay untouched.
"""
import json
import logging
import os
import re
import unittest
import uuid

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("SECURITY_PASSWORD_SALT", "test-salt")
os.environ.setdefault("DB_USER", "iggybase")
os.environ.setdefault("DB_PASSWORD", "change-me")
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "3306")
os.environ["DATA_DB_NAME"] = "iggybase_sec4"
os.environ.setdefault("UPLOAD_FOLDER", "/tmp/iggybase-uploads")
os.environ.setdefault("FILE_FOLDER", "/tmp/iggybase-files")
os.environ.setdefault("ALLOWED_EXTENSIONS", "pdf,csv")

import pymysql

_ROOT_PASSWORD = os.environ.get("MYSQL_ROOT_PASSWORD", "change-me")
_conn = pymysql.connect(
    host=os.environ["DB_HOST"],
    port=int(os.environ["DB_PORT"]),
    user="root",
    password=_ROOT_PASSWORD,
)
try:
    with _conn.cursor() as _cur:
        _cur.execute("DROP DATABASE IF EXISTS iggybase_sec4")
        _cur.execute(
            "CREATE DATABASE iggybase_sec4 CHARACTER SET utf8mb4 "
            "COLLATE utf8mb4_unicode_ci"
        )
        _cur.execute(
            "GRANT ALL PRIVILEGES ON iggybase_sec4.* TO 'iggybase'@'%'"
        )
        _cur.execute("FLUSH PRIVILEGES")
    _conn.commit()
finally:
    _conn.close()

from flask_security.utils import hash_password
from iggybase import create_app
from iggybase.admin import models
from iggybase.database import db_session, init_db

NONADMIN_EMAIL = "nonadmin@example.com"
NONADMIN_PASSWORD = "nonadmin-secret"
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "admin-secret"
TARGET_PASSWORD = "target-secret"
BODY_SECRET = "super-secret-password"
_TIMESTAMP = re.compile(r"at=\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


def _add(model, **kwargs):
    row = model()
    for key, value in kwargs.items():
        setattr(row, key, value)
    db_session.add(row)
    return row


def _seed_module():
    init_db()
    _add(models.Module, name="core", blueprint=True, active=True)
    db_session.commit()


def _user(name, email, password, organization_id):
    return _add(
        models.User,
        name=name,
        email=email,
        password=hash_password(password),
        fs_uniquifier=uuid.uuid4().hex,
        active=True,
        verified=True,
        organization_id=organization_id,
    )


def _seed_world(app):
    with app.app_context():
        root = _add(models.Organization, name="facility-root", active=True)
        everyone = _add(models.Organization, name="Everyone", active=True)
        db_session.flush()
        root.organization_id = root.id
        everyone.organization_id = root.id
        # Both labs sit under the facility root, so each member's org is in
        # scope. A member of one lab does not receive the other lab.
        visible = _add(
            models.Organization,
            name="visible-lab",
            active=True,
            organization_id=root.id,
            parent_id=root.id,
        )
        hidden = _add(
            models.Organization,
            name="hidden-lab",
            active=True,
            organization_id=root.id,
            parent_id=root.id,
        )
        db_session.flush()

        user_level = _add(
            models.Level, name="user", active=True, order=2, organization_id=root.id
        )
        # Spaces and capital letters must still count as admin.
        admin_level = _add(
            models.Level, name=" Admin ", active=True, order=1, organization_id=root.id
        )
        facility = _add(
            models.Facility,
            name="lab",
            active=True,
            organization_id=root.id,
            root_organization_id=root.id,
        )
        db_session.flush()
        user_role = _add(
            models.Role,
            name="lab-user",
            active=True,
            organization_id=root.id,
            facility_id=facility.id,
            level_id=user_level.id,
        )
        admin_role = _add(
            models.Role,
            name="lab-admin",
            active=True,
            organization_id=root.id,
            facility_id=facility.id,
            level_id=admin_level.id,
        )
        db_session.flush()

        nonadmin = _user("nonadmin", NONADMIN_EMAIL, NONADMIN_PASSWORD, visible.id)
        admin = _user("admin-user", ADMIN_EMAIL, ADMIN_PASSWORD, visible.id)
        target = _user("target-user", "target@example.com", TARGET_PASSWORD, hidden.id)
        db_session.flush()

        nonadmin_link = _add(
            models.UserRole,
            name="nonadmin-lab-user",
            active=True,
            organization_id=root.id,
            user_id=nonadmin.id,
            role_id=user_role.id,
        )
        admin_link = _add(
            models.UserRole,
            name="admin-lab-admin",
            active=True,
            organization_id=root.id,
            user_id=admin.id,
            role_id=admin_role.id,
        )
        # The target shares each caller's role, so the old lookup would
        # switch either caller. The level gate is what stops the non-admin.
        _add(
            models.UserRole,
            name="target-lab-user",
            active=True,
            organization_id=root.id,
            user_id=target.id,
            role_id=user_role.id,
        )
        target_admin_link = _add(
            models.UserRole,
            name="target-lab-admin",
            active=True,
            organization_id=root.id,
            user_id=target.id,
            role_id=admin_role.id,
        )
        db_session.flush()
        nonadmin.current_user_role_id = nonadmin_link.id
        admin.current_user_role_id = admin_link.id
        target.current_user_role_id = target_admin_link.id

        for person, org in ((nonadmin, visible), (admin, visible), (target, hidden)):
            _add(
                models.UserOrganization,
                name=person.name + "-org",
                active=True,
                organization_id=root.id,
                user_id=person.id,
                user_organization_id=org.id,
                default_organization=True,
            )

        module = db_session.query(models.Module).filter_by(name="core").one()
        _add(
            models.ModuleFacility,
            name="lab-core",
            active=True,
            organization_id=root.id,
            facility_id=facility.id,
            module_id=module.id,
        )
        route = _add(
            models.Route,
            name="core-change-user",
            active=True,
            organization_id=root.id,
            module_id=module.id,
            url_path="change_user",
        )
        db_session.flush()
        for role, label in ((user_role, "user"), (admin_role, "admin")):
            _add(
                models.RouteRole,
                name="role-change-user-" + label,
                active=True,
                organization_id=root.id,
                role_id=role.id,
                route_id=route.id,
            )
        db_session.commit()
        return {
            "nonadmin_id": nonadmin.id,
            "admin_id": admin.id,
            "target_id": target.id,
            "visible_id": visible.id,
            "hidden_id": hidden.id,
        }


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.INFO)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


class ChangeUserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _seed_module()
        cls.app = create_app()
        cls.app.testing = True
        cls.app.config["PROPAGATE_EXCEPTIONS"] = True
        cls.app.config["WTF_CSRF_ENABLED"] = False
        ids = _seed_world(cls.app)
        cls.nonadmin_id = ids["nonadmin_id"]
        cls.admin_id = ids["admin_id"]
        cls.target_id = ids["target_id"]
        cls.visible_id = ids["visible_id"]
        cls.hidden_id = ids["hidden_id"]
        cls.audit = logging.getLogger("iggybase.audit")
        cls.audit.setLevel(logging.INFO)

    @classmethod
    def tearDownClass(cls):
        db_session.remove()

    def setUp(self):
        self.capture = _Capture()
        self.audit.addHandler(self.capture)

    def tearDown(self):
        self.audit.removeHandler(self.capture)

    def test_routes_are_registered(self):
        endpoints = {rule.endpoint for rule in self.app.url_map.iter_rules()}
        self.assertIn("core.change_user", endpoints)

    def test_non_admin_post_leaves_org_scope_unchanged(self):
        client = self.app.test_client()
        self._login(client, NONADMIN_EMAIL, NONADMIN_PASSWORD)
        response = self._change_user(client)
        self.assertEqual(200, response.status_code, response.get_data(as_text=True)[:1500])
        self.assertEqual({"success": False}, json.loads(response.get_data(as_text=True)))
        org = self._org_scope(client)
        self.assertEqual(self.visible_id, org["current_org_id"])
        self.assertNotIn(self.hidden_id, org["org_ids"])
        self.assertEqual([], self.capture.messages)

    def test_admin_post_audits_without_password_or_cookie(self):
        client = self.app.test_client()
        self._login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
        cookie = client.get_cookie("session")
        self.assertTrue(cookie.value)
        response = self._change_user(client)
        self.assertEqual(200, response.status_code, response.get_data(as_text=True)[:1500])
        self.assertEqual({"success": True}, json.loads(response.get_data(as_text=True)))
        org = self._org_scope(client)
        self.assertEqual(self.hidden_id, org["current_org_id"])
        self.assertIn(self.hidden_id, org["org_ids"])
        self.assertNotIn(self.visible_id, org["org_ids"])

        self.assertEqual(1, len(self.capture.messages), self.capture.messages)
        line = self.capture.messages[0]
        self.assertIn("actor_id=%s" % self.admin_id, line)
        self.assertIn("target_id=%s" % self.target_id, line)
        self.assertIn("facility=lab", line)
        self.assertRegex(line, _TIMESTAMP)
        self.assertNotIn(ADMIN_PASSWORD, line)
        self.assertNotIn(NONADMIN_PASSWORD, line)
        self.assertNotIn(TARGET_PASSWORD, line)
        self.assertNotIn(BODY_SECRET, line)
        self.assertNotIn(cookie.value, line)
        self.assertNotIn("session", line.lower())

    def _login(self, client, email, password):
        login = client.post(
            "/login",
            data={"email": email, "password": password, "submit": "Login"},
        )
        self.assertIn(login.status_code, (302, 303), login.get_data(as_text=True)[:1500])

    def _change_user(self, client):
        return client.post(
            "/lab/core/change_user",
            json={"user_id": self.target_id, "password": BODY_SECRET},
        )

    def _org_scope(self, client):
        with client.session_transaction() as sess:
            return {
                "current_org_id": sess["org_id"]["current_org_id"],
                "org_ids": list(sess["org_id"]["org_ids"]),
            }


if __name__ == "__main__":
    unittest.main()
