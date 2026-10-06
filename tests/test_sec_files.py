"""MySQL-backed checks for file downloads (SEC-6).

Uses iggybase_sec3 and its own file directory so the other security schemas
and the empty iggybase database stay untouched.
"""
import os
import shutil
import unittest
import uuid

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("SECURITY_PASSWORD_SALT", "test-salt")
os.environ.setdefault("DB_USER", "iggybase")
os.environ.setdefault("DB_PASSWORD", "change-me")
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "3306")
os.environ["DATA_DB_NAME"] = "iggybase_sec3"
os.environ["UPLOAD_FOLDER"] = "/tmp/iggybase-sec3-uploads"
os.environ["FILE_FOLDER"] = "/tmp/iggybase-sec3-files"
os.environ.setdefault("ALLOWED_EXTENSIONS", "pdf,csv,txt")

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
        _cur.execute("DROP DATABASE IF EXISTS iggybase_sec3")
        _cur.execute(
            "CREATE DATABASE iggybase_sec3 CHARACTER SET utf8mb4 "
            "COLLATE utf8mb4_unicode_ci"
        )
        _cur.execute(
            "GRANT ALL PRIVILEGES ON iggybase_sec3.* TO 'iggybase'@'%'"
        )
        _cur.execute("FLUSH PRIVILEGES")
    _conn.commit()
finally:
    _conn.close()

from flask_security.utils import hash_password
from iggybase import create_app
from iggybase.admin import models
from iggybase.database import db_session, init_db

PASSWORD = "file-secret"
EMAIL = "filer@example.com"
VISIBLE = b"visible-file-marker"
HIDDEN = b"hidden-file-marker"
FLAT_VISIBLE = b"flat-visible-marker"
FLAT_HIDDEN = b"flat-hidden-marker"
OUTSIDE = b"outside-file-marker"


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


def _write(folder, *parts, content):
    path = os.path.join(folder, *parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(content)


def _seed_world(app):
    with app.app_context():
        root = _add(models.Organization, name="facility-root", active=True)
        everyone = _add(models.Organization, name="Everyone", active=True)
        outsider = _add(models.Organization, name="outsider-org", active=True)
        db_session.flush()
        root.organization_id = root.id
        everyone.organization_id = root.id
        outsider.organization_id = outsider.id
        # Everyone is in org_ids and is not the caller's current org.
        _add(
            models.Organization,
            name="visible-lab",
            active=True,
            organization_id=everyone.id,
        )
        _add(
            models.Organization,
            name="hidden-lab",
            active=True,
            organization_id=outsider.id,
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
            name="filer",
            email=EMAIL,
            password=hash_password(PASSWORD),
            fs_uniquifier=uuid.uuid4().hex,
            active=True,
            verified=True,
            organization_id=root.id,
        )
        db_session.flush()
        user_role = _add(
            models.UserRole,
            name="filer-lab-user",
            active=True,
            organization_id=root.id,
            user_id=user.id,
            role_id=role.id,
        )
        db_session.flush()
        user.current_user_role_id = user_role.id
        _add(
            models.UserOrganization,
            name="filer-root",
            active=True,
            organization_id=root.id,
            user_id=user.id,
            user_organization_id=root.id,
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
        # url_path is the URL segment route_access checks, not the function name.
        for path in ("files", "file"):
            route = _add(
                models.Route,
                name="core-" + path,
                active=True,
                organization_id=root.id,
                module_id=module.id,
                url_path=path,
            )
            db_session.flush()
            _add(
                models.RouteRole,
                name="role-" + path,
                active=True,
                organization_id=root.id,
                role_id=role.id,
                route_id=route.id,
            )
        _add(
            models.TableObject,
            name="organization",
            active=True,
            organization_id=root.id,
            admin_table=True,
        )
        db_session.commit()

    folder = app.config["FILE_FOLDER"]
    shutil.rmtree(folder, ignore_errors=True)
    _write(folder, "organization", "visible-lab", "note.txt", content=VISIBLE)
    _write(folder, "organization", "hidden-lab", "note.txt", content=HIDDEN)
    _write(folder, "organization", "visible-lab.txt", content=FLAT_VISIBLE)
    _write(folder, "organization", "hidden-lab.txt", content=FLAT_HIDDEN)
    _write(folder, "organization", "secret.txt", content=OUTSIDE)
    _write(folder, "secret.txt", content=OUTSIDE)


class FileAccessTest(unittest.TestCase):
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

    def test_routes_are_registered(self):
        endpoints = {rule.endpoint for rule in self.app.url_map.iter_rules()}
        self.assertIn("core.file_row", endpoints)
        self.assertIn("core.file", endpoints)

    def test_in_org_file_is_returned(self):
        client = self.app.test_client()
        self._login(client)

        nested = self._get(client, "/lab/core/files/organization/visible-lab/note.txt")
        self.assertEqual(200, nested.status_code, nested.get_data()[:500])
        self.assertEqual(VISIBLE, nested.get_data())

        flat = self._get(client, "/lab/core/file/organization/visible-lab.txt")
        self.assertEqual(200, flat.status_code, flat.get_data()[:500])
        self.assertEqual(FLAT_VISIBLE, flat.get_data())

    def test_out_of_org_file_is_404(self):
        client = self.app.test_client()
        self._login(client)

        nested = self._get(client, "/lab/core/files/organization/hidden-lab/note.txt")
        self.assertEqual(404, nested.status_code, nested.get_data()[:500])
        self.assertNotIn(HIDDEN, nested.get_data())
        self.assertNotIn(VISIBLE, nested.get_data())

        flat = self._get(client, "/lab/core/file/organization/hidden-lab.txt")
        self.assertEqual(404, flat.status_code, flat.get_data()[:500])
        self.assertNotIn(FLAT_HIDDEN, flat.get_data())
        self.assertNotIn(FLAT_VISIBLE, flat.get_data())

    def test_parent_filename_does_not_escape(self):
        client = self.app.test_client()
        self._login(client)

        nested = self._get(client, "/lab/core/files/organization/visible-lab/..")
        self.assertEqual(404, nested.status_code, nested.get_data()[:500])
        self.assertNotIn(OUTSIDE, nested.get_data())
        self.assertNotIn(HIDDEN, nested.get_data())

        flat = self._get(client, "/lab/core/file/organization/..")
        self.assertEqual(404, flat.status_code, flat.get_data()[:500])
        self.assertNotIn(OUTSIDE, flat.get_data())
        self.assertNotIn(FLAT_HIDDEN, flat.get_data())

    def _get(self, client, path):
        response = client.get(path)
        # Read before close so the file handle from send_file is released
        # and later get_data calls use the cached body.
        response.get_data()
        response.close()
        return response

    def _login(self, client):
        login = client.post(
            "/login",
            data={"email": EMAIL, "password": PASSWORD, "submit": "Login"},
        )
        self.assertIn(login.status_code, (302, 303), login.get_data(as_text=True)[:1500])


if __name__ == "__main__":
    unittest.main()
