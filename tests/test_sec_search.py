"""MySQL-backed checks for search login and organization scope (SEC-1, SEC-2).

Uses a separate schema, iggybase_sec, so the empty iggybase database stays empty.
The MySQL root account recreates that schema. The application user then owns it.
"""
import json
import os
import unittest
import uuid

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("SECURITY_PASSWORD_SALT", "test-salt")
os.environ.setdefault("DB_USER", "iggybase")
os.environ.setdefault("DB_PASSWORD", "change-me")
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "3306")
os.environ["DATA_DB_NAME"] = "iggybase_sec"
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
        _cur.execute("DROP DATABASE IF EXISTS iggybase_sec")
        _cur.execute(
            "CREATE DATABASE iggybase_sec CHARACTER SET utf8mb4 "
            "COLLATE utf8mb4_unicode_ci"
        )
        _cur.execute(
            "GRANT ALL PRIVILEGES ON iggybase_sec.* TO 'iggybase'@'%'"
        )
        _cur.execute("FLUSH PRIVILEGES")
    _conn.commit()
finally:
    _conn.close()

from flask_security.utils import hash_password
from iggybase import create_app
from iggybase.admin import models
from iggybase.database import db_session, init_db

PASSWORD = "search-secret"
EMAIL = "searcher@example.com"


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
        outsider = _add(models.Organization, name="outsider-org", active=True)
        db_session.flush()
        root.organization_id = root.id
        everyone.organization_id = root.id
        outsider.organization_id = outsider.id

        visible = _add(
            models.Organization,
            name="visible-lab",
            active=True,
            organization_id=root.id,
        )
        hidden = _add(
            models.Organization,
            name="hidden-lab",
            active=True,
            organization_id=outsider.id,
        )
        db_session.flush()

        level = _add(models.Level, name="user", active=True, order=1,
                     organization_id=root.id)
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
            name="searcher",
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
            name="searcher-lab-user",
            active=True,
            organization_id=root.id,
            user_id=user.id,
            role_id=role.id,
        )
        db_session.flush()
        user.current_user_role_id = user_role.id
        _add(
            models.UserOrganization,
            name="searcher-root",
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
        for path in ("search", "search_results"):
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

        data_type = _add(
            models.DataType,
            name="string",
            active=True,
            organization_id=root.id,
            db_data_type="varchar",
        )
        table_object = _add(
            models.TableObject,
            name="table_object",
            active=True,
            organization_id=root.id,
            admin_table=True,
        )
        table_object_role = _add(
            models.TableObject,
            name="table_object_role",
            active=True,
            organization_id=root.id,
            admin_table=True,
        )
        organization_table = _add(
            models.TableObject,
            name="organization",
            active=True,
            organization_id=root.id,
            admin_table=True,
        )
        widget = _add(
            models.TableObject,
            name="widget",
            active=True,
            organization_id=root.id,
            admin_table=False,
        )
        db_session.flush()
        for table in (table_object, table_object_role, organization_table, widget):
            _add(
                models.TableObjectRole,
                name="tor-" + table.name,
                active=True,
                organization_id=root.id,
                role_id=role.id,
                table_object_id=table.id,
            )
        name_field = _add(
            models.Field,
            name="organization-name",
            active=True,
            organization_id=root.id,
            display_name="name",
            table_object_id=organization_table.id,
            data_type_id=data_type.id,
        )
        org_field = _add(
            models.Field,
            name="widget-org",
            active=True,
            organization_id=root.id,
            display_name="org",
            table_object_id=widget.id,
            data_type_id=data_type.id,
            foreign_key_table_object_id=organization_table.id,
        )
        db_session.flush()
        for field in (name_field, org_field):
            _add(
                models.FieldRole,
                name="fr-" + field.name,
                active=True,
                organization_id=root.id,
                role_id=role.id,
                field_id=field.id,
                display_name=field.display_name,
                visible=True,
                search_field=(field.display_name == "name"),
                order=1,
            )
        db_session.commit()
        # Keep the names referenced so a reader can see which rows the filter uses.
        assert visible.name == "visible-lab"
        assert hidden.name == "hidden-lab"


class SearchAccessTest(unittest.TestCase):
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
        self.assertIn("core.search", endpoints)
        self.assertIn("core.search_results", endpoints)

    def test_anonymous_search_does_not_return_rows(self):
        client = self.app.test_client()
        for path in ("/lab/core/search", "/lab/core/search_results"):
            response = client.get(path)
            self.assertEqual(302, response.status_code, path)
            self.assertIn("/login", response.headers.get("Location", ""))
            body = response.get_data(as_text=True)
            self.assertNotIn("visible-lab", body)
            self.assertNotIn("hidden-lab", body)

    def test_signed_in_search_hides_other_org_and_escapes_field_names(self):
        client = self.app.test_client()
        login = client.post(
            "/login",
            data={"email": EMAIL, "password": PASSWORD, "submit": "Login"},
        )
        self.assertIn(login.status_code, (302, 303), login.get_data(as_text=True)[:1500])

        scoped = self._search(client, "lab", modal_open=True)
        self.assertEqual(200, scoped.status_code, scoped.get_data(as_text=True)[:2000])
        body = scoped.get_data(as_text=True)
        self.assertIn("visible-lab", body)
        self.assertNotIn("hidden-lab", body)

        escaped = self._search(
            client,
            "no-such-lab",
            modal_open=True,
            extra={"search_<script>": "no-such-lab"},
        )
        self.assertEqual(200, escaped.status_code, escaped.get_data(as_text=True)[:2000])
        escaped_body = escaped.get_data(as_text=True)
        self.assertIn("&lt;Script&gt;", escaped_body)
        self.assertNotIn("<script", escaped_body.lower())
        self.assertNotIn("<Script", escaped_body)

    def _search(self, client, value, modal_open, extra=None):
        vals = {
            "table_name": "widget",
            "input_id": "widget-org-1",
            "display_name": "org",
            "value": value,
            "by_field": value,
            "field_key": "widget|org",
            "modal_open": modal_open,
        }
        if extra:
            vals.update(extra)
        return client.post(
            "/lab/core/search_results",
            query_string={"search_vals": json.dumps(vals)},
        )


if __name__ == "__main__":
    unittest.main()
