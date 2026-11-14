from tests.db_cleanup import child_first_tables
import pytest


def test_children_are_deleted_before_parents_even_with_empty_intermediate_tables():
    names = ['users', 'orgs', 'memberships', 'events']
    order = child_first_tables(names, [('users', 'orgs'), ('orgs', 'memberships'), ('users', 'memberships'), ('memberships', 'events')])
    assert order.index('events') < order.index('memberships') < order.index('orgs') < order.index('users')
    assert set(order) == set(names)


def test_self_references_and_nonapplication_tables_do_not_trigger_ddl_or_cycles():
    assert child_first_tables(['runs', 'users'], [('runs', 'runs'), ('spatial_ref_sys', 'runs')]) == ['runs', 'users']


def test_intertable_cycle_is_refused_instead_of_disabling_foreign_keys():
    with pytest.raises(RuntimeError, match='FK cycle'):
        child_first_tables(['a', 'b'], [('a', 'b'), ('b', 'a')])
