from flask import g


def get_role_access_control():
    if not hasattr(g, 'rac'):
        from iggybase.core.role_access_control import RoleAccessControl
        g.rac = RoleAccessControl()
    return g.rac


def get_org_access_control():
    if not hasattr(g, 'oac'):
        from iggybase.core.organization_access_control import OrganizationAccessControl
        g.oac = OrganizationAccessControl()
    return g.oac
