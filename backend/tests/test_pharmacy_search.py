import uuid
from decimal import Decimal

from app.pharmacy.service import search_medicines
from tests.conftest import FakeResult


async def test_search_medicines_returns_fefo_ordered_batches(fake_session):
    item_id = uuid.uuid4()
    batch_early = {
        "item_id": item_id, "batch_id": uuid.uuid4(), "batch_number": "B1",
        "expiry_date": __import__("datetime").date(2026, 8, 1),
        "quantity": Decimal("10"), "stock_location_id": uuid.uuid4(),
        "issue_rate_mrp": Decimal("5.50"),
    }
    batch_later = {
        "item_id": item_id, "batch_id": uuid.uuid4(), "batch_number": "B2",
        "expiry_date": __import__("datetime").date(2027, 1, 1),
        "quantity": Decimal("20"), "stock_location_id": uuid.uuid4(),
        "issue_rate_mrp": Decimal("5.50"),
    }
    fake_session.expect(
        "FROM inventory_items",
        FakeResult(rows=[{
            "id": item_id, "name": "Paracetamol", "generic_name": "Paracetamol",
            "strength": "500mg", "form": "tablet", "is_controlled_drug": False,
        }]),
    )
    fake_session.expect(
        "FROM inventory_batches", FakeResult(rows=[batch_early, batch_later])
    )

    results = await search_medicines(fake_session, q="para", facility_id=uuid.uuid4())

    assert len(results) == 1
    result = results[0]
    assert result.name == "Paracetamol"
    assert result.total_available_quantity == Decimal("30")
    assert [b.batch_number for b in result.batches] == ["B1", "B2"]
    assert result.batches[0].expiry_date == "2026-08-01"


async def test_search_medicines_no_match_returns_empty_without_batch_query(fake_session):
    fake_session.expect("FROM inventory_items", FakeResult(rows=[]))

    results = await search_medicines(fake_session, q="nonexistent-drug-xyz", facility_id=uuid.uuid4())

    assert results == []
    assert not any("FROM inventory_batches" in sql for sql, _ in fake_session.calls)


async def test_search_medicines_item_with_no_stock_has_empty_batches(fake_session):
    item_id = uuid.uuid4()
    fake_session.expect(
        "FROM inventory_items",
        FakeResult(rows=[{
            "id": item_id, "name": "Amoxicillin", "generic_name": None,
            "strength": "250mg", "form": "capsule", "is_controlled_drug": False,
        }]),
    )
    fake_session.expect("FROM inventory_batches", FakeResult(rows=[]))

    results = await search_medicines(fake_session, q="amox", facility_id=uuid.uuid4())

    assert len(results) == 1
    assert results[0].batches == []
    assert results[0].total_available_quantity == Decimal("0")
