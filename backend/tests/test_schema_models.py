from app.common.db import Base
from app.inventory import models as inventory_models  # noqa: F401
from app.pharmacy import models as pharmacy_models  # noqa: F401


def test_inventory_and_pharmacy_models_registered_in_metadata():
    tables = Base.metadata.tables
    expected_tables = {
        "suppliers",
        "inventory_items",
        "stock_locations",
        "inventory_batches",
        "stock_ledger",
        "pharmacy_dispenses",
        "pharmacy_dispense_items",
        "grn",
        "grn_items",
        "indents",
        "indent_items",
        "adjustments",
        "facility_settings",
    }
    for table_name in expected_tables:
        assert table_name in tables, f"Table '{table_name}' was not registered in Base.metadata"


def test_inventory_batches_columns_and_constraints():
    t = Base.metadata.tables["inventory_batches"]
    assert "row_version" in t.columns
    assert "quantity" in t.columns
    ck_names = [c.name for c in t.constraints if hasattr(c, "name") and c.name]
    assert "ck_inventory_batches_quantity" in ck_names
    uq_names = [c.name for c in t.constraints if hasattr(c, "name") and c.name]
    assert "uq_inventory_batches_item_id_batch_number_stock_location_id" in uq_names


def test_inventory_items_constraint_names():
    t = Base.metadata.tables["inventory_items"]
    ck_names = [c.name for c in t.constraints if hasattr(c, "name") and c.name]
    assert "ck_inventory_items_form" in ck_names
    assert "ck_inventory_items_item_type" in ck_names


def test_stock_locations_constraint_names():
    t = Base.metadata.tables["stock_locations"]
    ck_names = [c.name for c in t.constraints if hasattr(c, "name") and c.name]
    assert "ck_stock_locations_location_type" in ck_names


def test_stock_ledger_constraint_names():
    t = Base.metadata.tables["stock_ledger"]
    ck_names = [c.name for c in t.constraints if hasattr(c, "name") and c.name]
    assert "ck_stock_ledger_transaction_type" in ck_names
    assert "ck_stock_ledger_quantity_nonzero" in ck_names
    assert "ck_stock_ledger_quantity_sign_matches_type" in ck_names


def test_pharmacy_dispenses_constraint_names():
    t = Base.metadata.tables["pharmacy_dispenses"]
    ck_names = [c.name for c in t.constraints if hasattr(c, "name") and c.name]
    assert "ck_pharmacy_dispenses_status" in ck_names
    uq_names = [c.name for c in t.constraints if hasattr(c, "name") and c.name]
    assert "uq_pharmacy_dispenses_prescription_id_version" in uq_names
    idx_names = [i.name for i in t.indexes]
    assert "uq_pharmacy_dispenses_current" in idx_names


def test_pharmacy_dispenses_version_has_server_default():
    t = Base.metadata.tables["pharmacy_dispenses"]
    assert t.c.version.server_default is not None
    assert t.c.is_current.server_default is not None


def test_pharmacy_dispense_items_constraint_names():
    t = Base.metadata.tables["pharmacy_dispense_items"]
    ck_names = [c.name for c in t.constraints if hasattr(c, "name") and c.name]
    assert "ck_pharmacy_dispense_items_approval_status" in ck_names
    assert "ck_pharmacy_dispense_items_quantity_dispensed_nonneg" in ck_names
    assert "ck_pharmacy_dispense_items_dispensed_not_over_prescribed" in ck_names
    assert "ck_pharmacy_dispense_items_substitute_reason_required" in ck_names


def test_adjustments_constraints():
    t = Base.metadata.tables["adjustments"]
    assert "facility_id" in t.columns
    assert "first_approver_id" in t.columns
    assert "second_approver_id" in t.columns
    ck_names = [c.name for c in t.constraints if hasattr(c, "name") and c.name]
    assert "ck_adjustments_distinct_approvers" in ck_names
    assert "ck_adjustments_second_approver_required_when_approved" in ck_names
    assert "ck_adjustments_creator_not_first_approver" in ck_names
    assert "ck_adjustments_creator_not_second_approver" in ck_names
    assert "ck_adjustments_quantity_change_nonzero" in ck_names
    assert "ck_adjustments_status" in ck_names


def test_grn_items_constraint_names():
    t = Base.metadata.tables["grn_items"]
    ck_names = [c.name for c in t.constraints if hasattr(c, "name") and c.name]
    assert "ck_grn_items_quantity_positive" in ck_names


def test_grn_constraint_names():
    t = Base.metadata.tables["grn"]
    ck_names = [c.name for c in t.constraints if hasattr(c, "name") and c.name]
    assert "ck_grn_status" in ck_names


def test_indents_constraint_names():
    t = Base.metadata.tables["indents"]
    ck_names = [c.name for c in t.constraints if hasattr(c, "name") and c.name]
    assert "ck_indents_status" in ck_names


def test_indent_items_constraint_names():
    t = Base.metadata.tables["indent_items"]
    ck_names = [c.name for c in t.constraints if hasattr(c, "name") and c.name]
    assert "ck_indent_items_quantity_requested_positive" in ck_names


def test_facility_settings_constraint_names():
    t = Base.metadata.tables["facility_settings"]
    ck_names = [c.name for c in t.constraints if hasattr(c, "name") and c.name]
    assert "ck_facility_settings_stock_deduction_policy" in ck_names


def test_suppliers_grn_indents_adjustments_have_facility_id():
    for table_name in ["suppliers", "grn", "indents", "adjustments"]:
        t = Base.metadata.tables[table_name]
        assert "facility_id" in t.columns, f"{table_name} missing facility_id column"
