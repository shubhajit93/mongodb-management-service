"""API routers."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import AppContainer, get_container, require_token
from app.api.mappers import job_to_response
from app.api.response import ok
from app.domain.constants import MANIFEST_TIMESTAMP_RE
from app.domain.errors import ValidationError
from app.schemas import (
    BackupCreateRequest,
    ConfigUpdateRequest,
    RestoreCreateRequest,
)

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_token)])


@router.get("/health")
def health(container: Annotated[AppContainer, Depends(get_container)]):
    data = container.health_service.check()
    message = "Host checks passed" if data.healthy else "Host checks failed"
    return ok(message, data.model_dump(mode="json"))


@router.post("/backups", status_code=202)
def create_backup(
    body: BackupCreateRequest,
    container: Annotated[AppContainer, Depends(get_container)],
):
    job = container.backup_service.start(body)
    return ok("Backup job accepted", job_to_response(job).model_dump(mode="json"))


@router.get("/backups")
def list_backups(
    container: Annotated[AppContainer, Depends(get_container)],
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    jobs, total = container.backup_service.list(page=page, size=size)
    return ok(
        "Backup jobs listed",
        {
            "items": [job_to_response(job).model_dump(mode="json") for job in jobs],
            "page": page,
            "size": size,
            "total": total,
        },
    )


@router.get("/backups/{job_id}")
def get_backup(job_id: str, container: Annotated[AppContainer, Depends(get_container)]):
    job = container.backup_service.get(job_id)
    return ok("Backup job fetched", job_to_response(job).model_dump(mode="json"))


@router.post("/restores", status_code=202)
def create_restore(
    body: RestoreCreateRequest,
    container: Annotated[AppContainer, Depends(get_container)],
):
    job = container.restore_service.start(body)
    return ok("Restore job accepted", job_to_response(job).model_dump(mode="json"))


@router.get("/restores")
def list_restores(
    container: Annotated[AppContainer, Depends(get_container)],
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    jobs, total = container.restore_service.list(page=page, size=size)
    return ok(
        "Restore jobs listed",
        {
            "items": [job_to_response(job).model_dump(mode="json") for job in jobs],
            "page": page,
            "size": size,
            "total": total,
        },
    )


@router.get("/restores/{job_id}")
def get_restore(job_id: str, container: Annotated[AppContainer, Depends(get_container)]):
    job = container.restore_service.get(job_id)
    return ok("Restore job fetched", job_to_response(job).model_dump(mode="json"))


@router.get("/manifests")
def list_manifests(
    container: Annotated[AppContainer, Depends(get_container)],
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    items = container.manifest_client.list_manifests()
    total = len(items)
    start = (page - 1) * size
    end = start + size
    page_items = items[start:end]
    return ok(
        "Manifests listed",
        {
            "items": page_items,
            "page": page,
            "size": size,
            "total": total,
        },
    )


@router.get("/manifests/{timestamp}")
def get_manifest(timestamp: str, container: Annotated[AppContainer, Depends(get_container)]):
    if not MANIFEST_TIMESTAMP_RE.match(timestamp):
        raise ValidationError("timestamp must match YYYY-MM-DDTHHMMZ")
    data = container.manifest_client.get_manifest(timestamp)
    return ok("Manifest fetched", data)


@router.get("/config")
def get_config(container: Annotated[AppContainer, Depends(get_container)]):
    data = container.config_service.get()
    return ok("Config fetched", data.model_dump(mode="json"))


@router.put("/config")
def update_config(
    body: ConfigUpdateRequest,
    container: Annotated[AppContainer, Depends(get_container)],
):
    data = container.config_service.update(body)
    return ok("Config updated", data.model_dump(mode="json"))


@router.get("/schedule")
def get_schedule(container: Annotated[AppContainer, Depends(get_container)]):
    data = container.schedule_reader.read()
    return ok("Schedule fetched", data)