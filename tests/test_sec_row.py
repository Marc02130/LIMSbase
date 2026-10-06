"""MySQL-backed checks for get_row and get_price (SEC-3, SEC-4, SEC-5).

Uses iggybase_sec2 so the empty iggybase database, and the search test's
iggybase_sec schema, stay untouched. MySQL root recreates the schema. The
application user then owns it.

price_list is a dynamic table. Its metadata is inserted before create_app,
which is what imports iggybase.models and builds the class.
"""
import json
import os
import sys
import unittest
import uuid

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("SECURITY_PASSWORD_SALT", "test-salt")
os.environ.setdefault("DB_USER", "iggybase")
os.environ.setdefault("DB_PASSWORD", "change-me")
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "3306")
os.environ["DATA_DB_NAME"] = "iggybase_sec2"
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
        _cur.execute("DROP DATABASE IF EXISTS iggybase_sec2")
        _cur.execute(
            "CREATE DATABASE iggybase_sec2 CHARACTER SET utf8mb4 "
            "COLLATE utf8mb4_unicode_ci"
        )
        _cur.execute(
            "GRANT ALL PRIVILEGES ON iggybase_sec2.* TO 'iggybase'@'%'"
        )
        _cur.execute("FLUSH PRIVILEGES")
    _conn.commit()
finally:
    _conn.close()

from flask_security.utils import hash_password
from iggybase import create_app
from iggybase.admin import models
from iggybase.database import Base, db_session, engine

PASSWORD = "row-secret"
EMAIL = "reader@example.com"
# Not 2, 6, 8, or 9: those ids take a different branch in TableFactory.
INTEGER_TYPE_ID = 3
VISIBLE_ITEM = 42
HIDDEN_ITEM = 43


def _add(model, **kwargs):
    row = model()
    for key, value in kwargs.items():
        setattr(row, key, value)
    db_session.add(row)
    return row


def _seed_before_models():
    """Admin rows the dynamic table factory reads at import time."""
    if "iggybase.models" in sys.modules:
        raise AssertionError("iggybase.models was imported before price_list existed")
    Base.metadata.create_all(bind=engine)

    root = _add(models.Organization, name="facility-root", active=True)
    everyone = _add(models.Organization, name="Everyone", active=True)
    outsider = _add(models.Organization, name="outsider-org", active=True)
    db_session.flush()
    root.organization_id = root.id
    everyone.organization_id = root.id
    outsider.organization_id = outsider.id

    # organization_id is Everyone, which is in org_ids and is not current_org_id.
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

    for name, blueprint in (("core", True), ("billing", True)):
        _add(
            models.Module,
            name=name,
            blueprint=blueprint,
            active=True,
            organization_id=root.id,
        )
    _add(
        models.DataType,
        id=INTEGER_TYPE_ID,
        name="Integer",
        active=True,
        organization_id=root.id,
        db_data_type="integer",
    )
    price_list = _add(
        models.TableObject,
        name="price_list",
        active=True,
        organization_id=root.id,
        admin_table=False,
    )
    db_session.flush()
    for display_name in ("price_item_id", "organization_type_id", "amount"):
        _add(
            models.Field,
            name="price-" + display_name,
            active=True,
            organization_id=root.id,
            display_name=display_name,
            table_object_id=price_list.id,
            data_type_id=INTEGER_TYPE_ID,
            primary_key=False,
            unique=False,
            default="",
        )
    db_session.commit()
    db_session.remove()


def _seed_world(app):
    with app.app_context():
        root = db_session.query(models.Organization).filter_by(name="facility-root").one()
        everyone = db_session.query(models.Organization).filter_by(name="Everyone").one()
        outsider = db_session.query(models.Organization).filter_by(name="outsider-org").one()

        org_type = _add(
            models.OrganizationType,
            name="lab-type",
            active=True,
            organization_id=root.id,
        )
        db_session.flush()
        root.organization_type_id = org_type.id

        level = _add(
            models.Level,
            name="user",
            active=True,
            order=1,
            organization_id=root.id,
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
            name="reader",
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
            name="reader-lab-user",
            active=True,
            organization_id=root.id,
            user_id=user.id,
            role_id=role.id,
        )
        db_session.flush()
        user.current_user_role_id = user_role.id
        _add(
            models.UserOrganization,
            name="reader-root",
            active=True,
            organization_id=root.id,
            user_id=user.id,
            user_organization_id=root.id,
            default_organization=True,
        )

        modules = {
            row.name: row
            for row in db_session.query(models.Module).all()
        }
        for module_name in ("core", "billing"):
            _add(
                models.ModuleFacility,
                name="lab-" + module_name,
                active=True,
                organization_id=root.id,
                facility_id=facility.id,
                module_id=modules[module_name].id,
            )
        for module_name, path in (("core", "get_row"), ("billing", "get_price")):
            route = _add(
                models.Route,
                name=module_name + "-" + path,
                active=True,
                organization_id=root.id,
                module_id=modules[module_name].id,
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

        organization_table = _add(
            models.TableObject,
            name="organization",
            active=True,
            organization_id=root.id,
            admin_table=True,
        )
        secret = _add(
            models.TableObject,
            name="secret_table",
            active=True,
            organization_id=root.id,
            admin_table=False,
        )
        price_list = db_session.query(models.TableObject).filter_by(name="price_list").one()
        db_session.flush()
        for table in (organization_table, price_list):
            _add(
                models.TableObjectRole,
                name="tor-" + table.name,
                active=True,
                organization_id=root.id,
                role_id=role.id,
                table_object_id=table.id,
            )
        # secret has a table row and no role, so has_access fails closed.
        assert secret.name == "secret_table"

        import iggybase.models as dynamic
        visible_price = dynamic.PriceList(
            name="visible-price",
            active=True,
            organization_id=everyone.id,
            price_item_id=VISIBLE_ITEM,
            organization_type_id=org_type.id,
            amount=10,
        )
        hidden_price = dynamic.PriceList(
            name="hidden-price",
            active=True,
            organization_id=outsider.id,
            price_item_id=HIDDEN_ITEM,
            organization_type_id=org_type.id,
            amount=99,
        )
        db_session.add(visible_price)
        db_session.add(hidden_price)
        db_session.commit()


class RowFetchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _seed_before_models()
        cls.app = create_app()
        cls.app.testing = True
        cls.app.config["PROPAGATE_EXCEPTIONS"] = True
        cls.app.config["WTF_CSRF_ENABLED"] = False
        import iggybase.models as dynamic
        columns = set(dynamic.PriceList.__table__.columns.keys())
        missing = {"price_item_id", "organization_type_id", "amount", "organization_id"} - columns
        if missing:
            raise AssertionError("price_list columns missing %s from %s" % (missing, columns))
        _seed_world(cls.app)

    @classmethod
    def tearDownClass(cls):
        db_session.remove()

    def test_routes_are_registered(self):
        endpoints = {rule.endpoint for rule in self.app.url_map.iter_rules()}
        self.assertIn("core.get_row", endpoints)
        self.assertIn("billing.get_price", endpoints)

    def test_get_row_hides_other_org_unknown_field_and_unreadable_table(self):
        client = self.app.test_client()
        self._login(client)

        visible = self._get_row(
            client,
            "organization",
            {"name": "visible-lab"},
            ["name", "query", "organization_fk"],
        )
        self.assertEqual(200, visible.status_code, visible.get_data(as_text=True)[:2000])
        self.assertEqual({"name": "visible-lab"}, json.loads(visible.get_data(as_text=True)))

        hidden = self._get_row(
            client,
            "organization",
            {"name": "hidden-lab"},
            ["name", "query"],
        )
        self.assertEqual(200, hidden.status_code, hidden.get_data(as_text=True)[:2000])
        self.assertEqual({}, json.loads(hidden.get_data(as_text=True)))
        self.assertNotIn("hidden-lab", hidden.get_data(as_text=True))

        denied = self._get_row(client, "secret_table", {"name": "hidden-lab"}, ["name"])
        self.assertEqual(404, denied.status_code, denied.get_data(as_text=True)[:2000])
        self.assertEqual({}, json.loads(denied.get_data(as_text=True)))
        self.assertNotIn("hidden-lab", denied.get_data(as_text=True))

    def test_get_price_hides_other_org_and_unknown_field(self):
        client = self.app.test_client()
        self._login(client)

        visible = self._get_price(
            client,
            {"price_item_id": VISIBLE_ITEM},
            ["amount", "query", "secret_note"],
        )
        self.assertEqual(200, visible.status_code, visible.get_data(as_text=True)[:2000])
        self.assertEqual({"amount": "10"}, json.loads(visible.get_data(as_text=True)))

        hidden = self._get_price(
            client,
            {"price_item_id": HIDDEN_ITEM},
            ["amount", "name"],
        )
        self.assertEqual(200, hidden.status_code, hidden.get_data(as_text=True)[:2000])
        self.assertEqual({}, json.loads(hidden.get_data(as_text=True)))
        self.assertNotIn("99", hidden.get_data(as_text=True))
        self.assertNotIn("hidden-price", hidden.get_data(as_text=True))

    def test_get_price_without_table_role_is_404(self):
        with self.app.app_context():
            link = db_session.query(models.TableObjectRole).filter_by(
                name="tor-price_list").one()
            role_id = link.role_id
            table_object_id = link.table_object_id
            organization_id = link.organization_id
            db_session.delete(link)
            db_session.commit()
        try:
            client = self.app.test_client()
            self._login(client)
            denied = self._get_price(client, {"price_item_id": VISIBLE_ITEM}, ["amount"])
            self.assertEqual(404, denied.status_code, denied.get_data(as_text=True)[:2000])
            body = denied.get_data(as_text=True)
            self.assertEqual({}, json.loads(body))
            self.assertNotIn("10", body)
            self.assertNotIn("99", body)
        finally:
            with self.app.app_context():
                db_session.add(models.TableObjectRole(
                    name="tor-price_list",
                    active=True,
                    organization_id=organization_id,
                    role_id=role_id,
                    table_object_id=table_object_id,
                ))
                db_session.commit()

    def _login(self, client):
        login = client.post(
            "/login",
            data={"email": EMAIL, "password": PASSWORD, "submit": "Login"},
        )
        self.assertIn(login.status_code, (302, 303), login.get_data(as_text=True)[:1500])

    def _get_row(self, client, table, criteria, fields):
        return client.post(
            "/lab/core/get_row/%s/ajax" % table,
            json={"criteria": criteria, "fields": fields},
        )

    def _get_price(self, client, criteria, fields):
        return client.post(
            "/lab/billing/get_price/ajax",
            json={"criteria": criteria, "fields": fields},
        )


if __name__ == "__main__":
    unittest.main()
