"""Code allowlist for action imports.

An action row chooses a module and a function. Only a pair listed here is
imported. The inventory is the module-level functions in
iggybase.core.actions, the action hooks that exist in this tree:

- add_record
- update_record
- initiate_billing

billing.functions.insert_line_item and find_price are not referenced as
action entry points. murray/action.py is empty. smallmolecule and sequencing
define calculations, not action hooks. A name that exists only on a database
row is not added here.

A workflow step imports iggybase.<module>.routes. That is a separate path
and is limited to the blueprint packages in the tree.
"""
import logging
from importlib import import_module

ACTIONS = {
    'iggybase.core.actions': {'add_record', 'update_record', 'initiate_billing'},
}

ROUTE_MODULES = {
    'core',
    'billing',
    'murray',
    'smallmolecule',
    'sequencing',
    'laboratory',
    'admin',
    'interfaces',
}


def action_allowed(module_name, function_name):
    """True when the pair may be imported and called."""
    if not module_name or not function_name:
        return False
    if not module_name.startswith('iggybase.'):
        return False
    names = ACTIONS.get(module_name)
    return names is not None and function_name in names


def import_step_routes(module_name):
    """Import iggybase.<name>.routes for a blueprint that exists in the tree.

    The module name comes from a workflow step row. Any other string is
    rejected and not imported.
    """
    if module_name not in ROUTE_MODULES:
        logging.info('rejected workflow route module %s', module_name)
        return None
    return import_module('iggybase.' + module_name + '.routes')
