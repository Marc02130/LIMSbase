"""MySQL-backed checks for the cache admin page (SEC-12).

Uses iggybase_sec7 so the other security schemas and the empty iggybase
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
os.environ["DATA_DB_NAME"] = "iggybase_sec7"
os.environ.setdefault("UPLOAD_FOLDER", "/tmp/iggybase-uploads")
os.environ.setdefault("FILE_FOLDER", "/tmp/iggybase-sec7-files")
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
        _cur.execute("DROP DATABASE IF EXISTS iggybase_sec7")
        _cur.execute(
            "CREATE DATABASE iggybase_sec7 CHARACTER SET utf8mb4 "
            "COLLATE utf8mb4_unicode_ci"
        )
        _cur.execute(
            "GRANT ALL PRIVILEGES ON iggybase_sec7.* TO 'iggybase'@'%'"
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
CACHE_URL = "/lab/core/cache/"
STORED_KEY = "summary|1|1|sample"
STORED_VALUE = "original-summary"


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
        everyone.parent_id = root.id
        lab_org = _add(
            models.Organization,
            name="lab-org",
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
        # A second active role gives the navbar a Role entry. Its level is
        # not admin, so it does not make the non-admin an admin.
        viewer_level = _add(
            models.Level, name="viewer", active=True, order=3, organization_id=root.id
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
        viewer_role = _add(
            models.Role,
            name="lab-viewer",
            active=True,
            organization_id=root.id,
            facility_id=facility.id,
            level_id=viewer_level.id,
        )
        db_session.flush()

        nonadmin = _user("nonadmin", NONADMIN_EMAIL, NONADMIN_PASSWORD, lab_org.id)
        admin = _user("admin-user", ADMIN_EMAIL, ADMIN_PASSWORD, lab_org.id)
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
        for person in (nonadmin, admin):
            _add(
                models.UserRole,
                name=person.name + "-viewer",
                active=True,
                organization_id=root.id,
                user_id=person.id,
                role_id=viewer_role.id,
            )
        db_session.flush()
        nonadmin.current_user_role_id = nonadmin_link.id
        admin.current_user_role_id = admin_link.id

        for person in (nonadmin, admin):
            _add(
                models.UserOrganization,
                name=person.name + "-org",
                active=True,
                organization_id=root.id,
                user_id=person.id,
                user_organization_id=lab_org.id,
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
            name="core-cache",
            active=True,
            organization_id=root.id,
            module_id=module.id,
            url_path="cache",
        )
        db_session.flush()
        for role, label in ((user_role, "user"), (admin_role, "admin")):
            _add(
                models.RouteRole,
                name="role-cache-" + label,
                active=True,
                organization_id=root.id,
                role_id=role.id,
                route_id=route.id,
            )

        _add(
            models.PageForm,
            name="forbidden",
            active=True,
            organization_id=root.id,
            page_title="Forbidden",
            page_header="Forbidden",
            page_template="errors/forbidden_page.html",
        )
        _add(
            models.PageForm,
            name="cache",
            active=True,
            organization_id=root.id,
            page_title="Cache",
            page_header="Cache",
            page_template="cache.html",
        )
        for menu_name in ("AdminNavBar", "AdminSideBar"):
            _add(
                models.Menu,
                name=menu_name,
                active=True,
                organization_id=root.id,
                display_name=menu_name,
            )
        db_session.commit()


class CacheAdminTest(unittest.TestCase):
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
        self.app.cache.store.clear()
        self.app.cache.version.clear()
        self.app.cache.refresh_key.clear()

    def test_non_admin_cache_is_forbidden(self):
        self.app.cache.set(STORED_KEY, STORED_VALUE, set_refresh=False)
        client = self.app.test_client()
        self._login(client, NONADMIN_EMAIL, NONADMIN_PASSWORD)
        fetched = client.get(CACHE_URL)
        self.assertEqual(403, fetched.status_code, fetched.get_data(as_text=True)[:1500])
        posted = client.post(
            CACHE_URL,
            data={"set_key": "Set", "key": STORED_KEY, "value": "pwned"},
        )
        self.assertEqual(403, posted.status_code, posted.get_data(as_text=True)[:1500])
        self.assertEqual(STORED_VALUE, self.app.cache.get(STORED_KEY))
        self.assertEqual({STORED_KEY}, set(self.app.cache.store._cache))

    def test_admin_set_key_does_not_change_the_cache(self):
        self.app.cache.set(STORED_KEY, STORED_VALUE, set_refresh=False)
        client = self.app.test_client()
        self._login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
        response = client.post(
            CACHE_URL,
            data={"set_key": "Set", "key": STORED_KEY, "value": "pwned"},
        )
        body = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code, body[:1500])
        self.assertNotIn("successfully set key", body)
        self.assertEqual(STORED_VALUE, self.app.cache.get(STORED_KEY))
        fresh = client.post(
            CACHE_URL,
            data={"set_key": "Set", "key": "injected", "value": "pwned"},
        )
        self.assertEqual(200, fresh.status_code, fresh.get_data(as_text=True)[:1500])
        self.assertIsNone(self.app.cache.get("injected"))

    def test_admin_set_version_does_not_change_the_cache(self):
        self.app.cache.version["sample"] = 2
        client = self.app.test_client()
        self._login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
        response = client.post(
            CACHE_URL,
            data={"set_version": "Set", "refresh_obj": "sample", "version": "99"},
        )
        body = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code, body[:1500])
        self.assertNotIn("set version", body)
        self.assertEqual(2, self.app.cache.get_version("sample"))
        other = client.post(
            CACHE_URL,
            data={"set_version": "Set", "refresh_obj": "other", "version": "5"},
        )
        self.assertEqual(200, other.status_code, other.get_data(as_text=True)[:1500])
        self.assertIsNone(self.app.cache.get_version("other"))

    def test_admin_can_read_a_key(self):
        self.app.cache.set(STORED_KEY, STORED_VALUE, set_refresh=False)
        client = self.app.test_client()
        self._login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
        response = client.post(
            CACHE_URL,
            data={"get_value": "Get", "key": STORED_KEY},
        )
        body = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code, body[:1500])
        self.assertIn(STORED_VALUE, body)
        self.assertEqual(STORED_VALUE, self.app.cache.get(STORED_KEY))

    def _login(self, client, email, password):
        login = client.post(
            "/login",
            data={"email": email, "password": password, "submit": "Login"},
        )
        self.assertIn(login.status_code, (302, 303), login.get_data(as_text=True)[:1500])


if __name__ == "__main__":
    unittest.main()
