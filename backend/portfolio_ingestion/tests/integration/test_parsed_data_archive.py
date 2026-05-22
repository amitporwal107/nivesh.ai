"""Integration tests for the Mongo raw-parsed-data archive."""
from __future__ import annotations

import os
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio

from portfolio_ingestion.clients import mongo as mongo_client
from portfolio_ingestion.config import reset_settings_for_test
from portfolio_ingestion.schemas.parsed_data import (
    DematAccount,
    DematHolding,
    ParsedData,
)
from portfolio_ingestion.services import parsed_data_archive as archive_mod


pytestmark = pytest.mark.skipif(
    not os.environ.get("PI_MONGO_URL"),
    reason="PI_MONGO_URL not set; Mongo integration tests skipped",
)


@pytest_asyncio.fixture
async def mongo_db():
    reset_settings_for_test()
    mongo_client.reset_client_for_test()
    archive_mod.reset_indexes_cache_for_test()
    db = await mongo_client.get_database()
    yield db
    # Clean up any docs our test inserted
    await db[archive_mod.COLLECTION].delete_many({"pan_hash": {"$regex": "^itest-"}})
    await mongo_client.close_client()
    mongo_client.reset_client_for_test()


@pytest.mark.integration
async def test_archive_inserts_document_with_indexes(mongo_db) -> None:
    job_id = uuid.uuid4()
    pan_hash = f"itest-{uuid.uuid4().hex}"
    payload = ParsedData(demat_accounts=[DematAccount(holdings=[
        DematHolding(isin="INE002A01018", name="X", quantity=Decimal("10"), value=Decimal("1000")),
    ])])

    object_id = await archive_mod.archive(
        ingestion_job_id=job_id,
        pan_hash=pan_hash,
        source_type="ECAS_CDSL",
        sdk_metadata={"method": "upload", "cas_type": "cdsl"},
        parsed_data=payload,
    )
    assert object_id

    fetched = await archive_mod.fetch(job_id)
    assert fetched is not None
    assert fetched["pan_hash"] == pan_hash
    assert fetched["source_type"] == "ECAS_CDSL"
    assert fetched["parsed_data"]["demat_accounts"][0]["holdings"][0]["isin"] == "INE002A01018"

    # The unique index on ingestion_job_id should exist after our first insert.
    index_names = [ix["name"] async for ix in mongo_db[archive_mod.COLLECTION].list_indexes()]
    assert "ingestion_job_id_uniq" in index_names
    assert "pan_received_desc" in index_names


@pytest.mark.integration
async def test_archive_second_call_is_idempotent_upsert(mongo_db) -> None:
    """Same ingestion_job_id replays must not duplicate the document."""
    job_id = uuid.uuid4()
    pan_hash = f"itest-{uuid.uuid4().hex}"
    payload = ParsedData()
    await archive_mod.archive(
        ingestion_job_id=job_id, pan_hash=pan_hash,
        source_type="ECAS_CDSL", sdk_metadata={}, parsed_data=payload,
    )
    await archive_mod.archive(
        ingestion_job_id=job_id, pan_hash=pan_hash,
        source_type="ECAS_CDSL", sdk_metadata={}, parsed_data=payload,
    )
    count = await mongo_db[archive_mod.COLLECTION].count_documents(
        {"ingestion_job_id": str(job_id)}
    )
    assert count == 1


@pytest.mark.integration
async def test_archive_handles_decimal_serialisation(mongo_db) -> None:
    """Pydantic Decimals are coerced to strings before BSON insertion."""
    job_id = uuid.uuid4()
    pan_hash = f"itest-{uuid.uuid4().hex}"
    payload = ParsedData(demat_accounts=[DematAccount(holdings=[
        DematHolding(isin="INE002A01018", name="Y", quantity=Decimal("1.23456"), value=Decimal("99999.99")),
    ])])
    await archive_mod.archive(
        ingestion_job_id=job_id, pan_hash=pan_hash,
        source_type="ECAS_CDSL", sdk_metadata={}, parsed_data=payload,
    )
    doc = await archive_mod.fetch(job_id)
    h = doc["parsed_data"]["demat_accounts"][0]["holdings"][0]
    # JSON-normalised strings (Pydantic serialises Decimal as a number via mode=json)
    assert str(h["quantity"]) in {"1.23456", "1.234560000000000"}
    assert str(h["value"]).startswith("99999.99")
