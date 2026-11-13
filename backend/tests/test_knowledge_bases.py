"""知识库接口层测试：鉴权与 OpenAPI 文档（不依赖数据库）。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import settings

API = settings.api_v1_prefix


def test_list_knowledge_bases_requires_auth(client: TestClient) -> None:
    response = client.get(f"{API}/knowledge-bases")

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_TOKEN"


def test_create_knowledge_base_requires_auth(client: TestClient) -> None:
    response = client.post(f"{API}/knowledge-bases", json={"name": "制度库"})

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_TOKEN"


def test_upload_document_requires_auth(client: TestClient) -> None:
    response = client.post(
        f"{API}/knowledge-bases/00000000-0000-0000-0000-000000000000/documents",
        files={"file": ("a.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_TOKEN"


def test_list_documents_requires_auth(client: TestClient) -> None:
    response = client.get(f"{API}/documents")

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_TOKEN"


def test_openapi_documents_knowledge_base_endpoints(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert f"{API}/knowledge-bases" in paths
    assert f"{API}/knowledge-bases/{{kb_id}}" in paths
    assert f"{API}/knowledge-bases/{{kb_id}}/documents" in paths
    assert f"{API}/documents" in paths
    assert f"{API}/documents/{{document_id}}" in paths
    assert f"{API}/documents/{{document_id}}/content" in paths
    assert f"{API}/documents/{{document_id}}/chunks" in paths
    assert f"{API}/documents/{{document_id}}/reprocess" in paths
