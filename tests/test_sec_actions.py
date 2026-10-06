"""MySQL-backed checks for action imports (SEC-13, SEC-14).

Uses iggybase_sec8 so the other security schemas and the empty iggybase
database stay untouched.
"""
import os
import unittest
import uuid

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("SECURITY_PASSWORD_SALT", "test-salt")
os.environ.setdefault("DB_USER", "iggybase")
os.environ.setdefault("DB_PASSWORD", "change-me")
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "3306")
os.environ["DATA_DB_NAME"] = "iggybase_sec8"
os.environ.setdefault("UPLOAD_FOLDER", "/tmp/iggybase-uploads")
os.environ.setdefault("FILE_FOLDER", "/tmp/iggybase-sec8-files")
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
        _cur.execute("DROP DATABASE IF EXISTS iggybase_sec8")
        _cur.execute(
            "CREATE DATABASE iggybase_sec8 CHARACTER SET utf8mb4 "
            "COLLATE utf8mb4_unicode_ci"
        )
        _cur.execute(
            "GRANT ALL PRIVILEGES ON iggybase_sec8.* TO 'iggybase'@'%'"
        )
        _cur.execute("FLUSH PRIVILEGES")
    _conn.commit()
finally:
    _conn.close()

from flask_security.utils import hash_password
from iggybase import create_app
from iggybase.admin import models
from iggybase.database import db_session, init_db

EMAIL = "actions@example.com"
PASSWORD = "actions-secret"


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


def _seed_world(app):
    with app.app_context():
        root = _add(models.Organization, name="facility-root", active=True)
        everyone = _add(models.Organization, name="Everyone", active=True)
        db_session.flush()
        root.organization_id = root.id
        everyone.organization_id = root.id
        everyone.parent_id = root.id
        lab_org = _add(
            models.Organization,
            name="lab-org",
            active=True,
            organization_id=root.id,
            parent_id=root.id,
        )
        db_session.flush()
        level = _add(
            models.Level, name="user", active=True, order=1, organization_id=root.id
        )
        facility = _add(
            models.Facility,
            name="lab",
            active=True,
            organization_id=root.id,
            root_organization_id=root.id,
        )
        db_session.flush()
        role = _add(
            models.Role,
            name="lab-user",
            active=True,
            organization_id=root.id,
            facility_id=facility.id,
            level_id=level.id,
        )
        db_session.flush()
        user = _add(
            models.User,
            name="action-user",
            email=EMAIL,
            password=hash_password(PASSWORD),
            fs_uniquifier=uuid.uuid4().hex,
            active=True,
            verified=True,
            organization_id=lab_org.id,
        )
        db_session.flush()
        link = _add(
            models.UserRole,
            name="action-user-role",
            active=True,
            organization_id=root.id,
            user_id=user.id,
            role_id=role.id,
        )
        db_session.flush()
        user.current_user_role_id = link.id
        _add(
            models.UserOrganization,
            name="action-user-org",
            active=True,
            organization_id=root.id,
            user_id=user.id,
            user_organization_id=lab_org.id,
            default_organization=True,
        )
        for name, namespace, function in (
            ("os-action", "os", "system"),
            ("off-list", "iggybase.billing.functions", "insert_line_item"),
            ("add-record", "iggybase.core.actions", "add_record"),
        ):
            _add(
                models.Action,
                name=name,
                active=True,
                organization_id=root.id,
                namespace=namespace,
                function=function,
            )
        db_session.commit()


class ActionImportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _seed_module()
        cls.app = create_app()
        cls.app.testing = True
        cls.app.config["PROPAGATE_EXCEPTIONS"] = True
        cls.app.config["WTF_CSRF_ENABLED"] = False
        _seed_world(cls.app)

    @classmethod
    def tearDownClass(cls):
        db_session.remove()

    def setUp(self):
        db_session.remove()

    def test_os_namespace_does_not_import(self):
        import iggybase.core.action as action_module
        import iggybase.utilities as utilities

        calls = []
        status = self._run(lambda: self._execute("os-action", action_module, calls))
        self.assertFalse(status)
        self.assertEqual([], calls)

        calls = []
        resolved = self._spy_call(utilities, calls, lambda: utilities.get_func("os", "system"))
        self.assertIsNone(resolved)
        self.assertEqual([], calls)

    def test_unlisted_iggybase_function_does_not_import(self):
        import iggybase.core.action as action_module
        import iggybase.utilities as utilities

        calls = []
        status = self._run(
            lambda: self._execute("off-list", action_module, calls)
        )
        self.assertFalse(status)
        self.assertEqual([], calls)

        calls = []
        resolved = self._spy_call(
            utilities,
            calls,
            lambda: utilities.get_func("iggybase.billing.functions", "insert_line_item"),
        )
        self.assertIsNone(resolved)
        self.assertEqual([], calls)

    def test_allowlisted_function_resolves_and_is_called(self):
        import iggybase.core.action as action_module
        import iggybase.core.actions as actions
        import iggybase.utilities as utilities

        resolved = utilities.get_func("iggybase.core.actions", "add_record")
        self.assertIs(resolved, actions.add_record)
        with self.assertRaises(KeyError) as raised:
            resolved()
        self.assertEqual("table_name", raised.exception.args[0])

        calls = []
        with self.assertRaises(KeyError) as raised:
            self._run(lambda: self._execute("add-record", action_module, calls))
        self.assertEqual("table_name", raised.exception.args[0])
        self.assertEqual(["iggybase.core.actions"], calls)

    def test_workflow_route_import_rejects_an_arbitrary_module(self):
        import inspect

        import iggybase.core.action_allowlist as allowlist
        from iggybase.core.routes import work_item_group

        source = inspect.getsource(work_item_group)
        self.assertIn("import_step_routes", source)
        self.assertNotIn("import_module", source)

        calls = []
        rejected = self._spy_call(allowlist, calls, lambda: allowlist.import_step_routes("os"))
        self.assertIsNone(rejected)
        self.assertEqual([], calls)

        calls = []
        module = self._spy_call(
            allowlist, calls, lambda: allowlist.import_step_routes("sequencing")
        )
        self.assertEqual("iggybase.sequencing.routes", module.__name__)
        self.assertEqual(["iggybase.sequencing.routes"], calls)

    def _execute(self, action_name, action_module, calls):
        from types import SimpleNamespace

        from flask import g

        from iggybase.admin import models
        from iggybase.core.action import Action

        original = action_module.import_module

        def wrapped(name, *args, **kwargs):
            calls.append(name)
            return original(name, *args, **kwargs)

        action_module.import_module = wrapped
        try:
            # get_action's ActionEmail join does not return the row on
            # SQLAlchemy 2. Load the stored action and hand it to the runner.
            row = g.db_session.query(models.Action).filter_by(name=action_name).one()
            runner = Action(None)
            runner.current_action = SimpleNamespace(Action=row, ActionEmail=None)
            return runner.execute_action()
        finally:
            action_module.import_module = original

    def _spy_call(self, module, calls, fn):
        original = module.import_module

        def wrapped(name, *args, **kwargs):
            calls.append(name)
            return original(name, *args, **kwargs)

        module.import_module = wrapped
        try:
            return fn()
        finally:
            module.import_module = original

    def _run(self, fn):
        client = self.app.test_client()
        login = client.post(
            "/login",
            data={"email": EMAIL, "password": PASSWORD, "submit": "Login"},
        )
        self.assertIn(login.status_code, (302, 303), login.get_data(as_text=True)[:1500])
        cookie = client.get_cookie("session")
        self.assertIsNotNone(cookie)
        with self.app.test_request_context(
            "/welcome",
            headers={"Cookie": "%s=%s" % (cookie.key, cookie.value)},
        ):
            blocked = self.app.preprocess_request()
            self.assertIsNone(blocked)
            return fn()


if __name__ == "__main__":
    unittest.main()
