#
# Copyright Elasticsearch B.V. and/or licensed to Elasticsearch B.V. under one
# or more contributor license agreements. Licensed under the Elastic License 2.0;
# you may not use this file except in compliance with the Elastic License 2.0.
#
import json
from datetime import datetime
import asyncio

from aioresponses import aioresponses
from elasticsearch import AsyncElasticsearch
import pytest

from connectors.byoei import ElasticServer
from connectors.byoc import (
    e2str,
    Status,
    iso_utc,
    SyncJob,
    JobStatus,
    BYOIndex,
    _CONNECTORS_CACHE,
)


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_responses():
    with aioresponses() as m:
        yield m


def test_e2str():
    # The BYOC protocol uses lower case
    assert e2str(Status.NEEDS_CONFIGURATION) == "needs_configuration"


def test_utc():
    # All dates are in ISO 8601 UTC so we can serialize them
    now = datetime.utcnow()
    then = json.loads(json.dumps({"date": iso_utc(when=now)}))["date"]
    assert now.isoformat() == then


@pytest.mark.asyncio
async def test_sync_job(mock_responses):
    _CONNECTORS_CACHE.clear()

    client = AsyncElasticsearch(hosts=["http://nowhere.com:9200"])

    job = SyncJob("connector-id", client)

    headers = {"X-Elastic-Product": "Elasticsearch"}
    mock_responses.post(
        "http://nowhere.com:9200/.elastic-connectors-sync-jobs/_doc",
        payload={"_id": "1"},
        headers=headers,
    )

    mock_responses.put(
        "http://nowhere.com:9200/.elastic-connectors-sync-jobs/_doc/1",
        payload={"_id": "1"},
        headers=headers,
    )
    await job.start()
    assert job.status == JobStatus.IN_PROGRESS
    assert job.job_id is not None

    await job.done(12, 34)
    assert job.status == JobStatus.COMPLETED
    await client.close()


mongo = {
    "api_key_id": "",
    "configuration": {
        "host": {"value": "mongodb://127.0.0.1:27021", "label": "MongoDB Host"},
        "database": {"value": "sample_airbnb", "label": "MongoDB Database"},
        "collection": {
            "value": "listingsAndReviews",
            "label": "MongoDB Collection",
        },
    },
    "index_name": "search-airbnb",
    "service_type": "mongo",
    "status": "configured",
    "last_sync_status": "null",
    "last_sync_error": "",
    "last_synced": "",
    "last_seen": "",
    "created_at": "",
    "updated_at": "",
    "scheduling": {"enabled": True, "interval": "0 * * * *"},
    "sync_now": True,
}


@pytest.mark.asyncio
async def test_connectors_get_list(mock_responses):
    _CONNECTORS_CACHE.clear()

    config = {"host": "http://nowhere.com:9200", "user": "tarek", "password": "blah"}
    headers = {"X-Elastic-Product": "Elasticsearch"}

    mock_responses.post(
        "http://nowhere.com:9200/.elastic-connectors/_search?expand_wildcards=hidden",
        payload={"hits": {"hits": [{"_id": "1", "_source": mongo}]}},
        headers=headers,
    )

    connectors = BYOIndex(config)
    conns = []

    async for connector in connectors.get_list():
        conns.append(connector)

    assert len(conns) == 1
    await connectors.close()


@pytest.mark.asyncio
async def test_sync_mongo(mock_responses):
    _CONNECTORS_CACHE.clear()

    config = {"host": "http://nowhere.com:9200", "user": "tarek", "password": "blah"}
    headers = {"X-Elastic-Product": "Elasticsearch"}

    mock_responses.post(
        "http://nowhere.com:9200/.elastic-connectors/_search?expand_wildcards=hidden",
        payload={"hits": {"hits": [{"_id": "1", "_source": mongo}]}},
        headers=headers,
    )
    mock_responses.put(
        "http://nowhere.com:9200/.elastic-connectors/_doc/1",
        payload={"_id": "1"},
        headers=headers,
    )
    mock_responses.put(
        "http://nowhere.com:9200/.elastic-connectors/_doc/1",
        payload={"_id": "1"},
        headers=headers,
    )
    mock_responses.post(
        "http://nowhere.com:9200/.elastic-connectors-sync-jobs/_doc",
        payload={"_id": "1"},
        headers=headers,
    )
    mock_responses.put(
        "http://nowhere.com:9200/.elastic-connectors-sync-jobs/_doc/1",
        payload={"_id": "1"},
        headers=headers,
    )
    mock_responses.head(
        "http://nowhere.com:9200/search-airbnb?expand_wildcards=hidden", headers=headers
    )
    mock_responses.get(
        "http://nowhere.com:9200/search-airbnb",
        payload={"hits": {"hits": [{"_id": "1", "_source": mongo}]}},
        headers=headers,
    )
    mock_responses.get(
        "http://nowhere.com:9200/search-airbnb/_search?scroll=5m",
        payload={"hits": {"hits": [{"_id": "1", "_source": mongo}]}},
        headers=headers,
    )
    mock_responses.post(
        "http://nowhere.com:9200/search-airbnb/_search?scroll=5m",
        payload={"_id": "1"},
        headers=headers,
    )
    mock_responses.put(
        "http://nowhere.com:9200/search-airbnb/_search?scroll=5m",
        payload={"_id": "1"},
        headers=headers,
    )
    mock_responses.put(
        "http://nowhere.com:9200/_bulk",
        payload={"items": []},
        headers=headers,
    )

    doc = {"_id": 1}

    class Data:
        async def ping(self):
            pass

        async def get_docs(self, *args, **kw):
            for d in [doc, doc]:
                yield {"_id": 1}

    es = ElasticServer(config)
    connectors = BYOIndex(config)
    try:
        async for connector in connectors.get_list():
            await connector.sync(Data(), es, 0)
    finally:
        await connectors.close()