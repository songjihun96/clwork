"""Content administration endpoints (role: admin)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from app.dependencies import AdminDep, DbSession, JobQueueDep, SettingsDep, StorageDep, get_upload_scanner
from app.schemas.books import AdminBookListResponse, AdminBookResponse, BookMetadataInput, RightsInput
from app.schemas.common import ERROR_RESPONSES, ErrorResponse
from app.security.uploads import PayloadTooLarge, UploadScanner, read_limited
from app.services.book_admin_service import BookAdminService, detect_format

router = APIRouter(prefix="/admin/books", tags=["admin"])

_ADMIN_ERRORS = {**ERROR_RESPONSES, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}}


def get_service(session: DbSession, storage: StorageDep, jobs: JobQueueDep) -> BookAdminService:
    return BookAdminService(session, storage, jobs)


ServiceDep = Annotated[BookAdminService, Depends(get_service)]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=AdminBookResponse,
    responses={**_ADMIN_ERRORS, 413: {"model": ErrorResponse}, 415: {"model": ErrorResponse}},
)
async def upload_book(
    request: Request,
    admin: AdminDep,
    service: ServiceDep,
    settings: SettingsDep,
    scanner: Annotated[UploadScanner, Depends(get_upload_scanner)],
    file: Annotated[UploadFile, File(description="EPUB or UTF-8 .txt")],
    metadata: Annotated[str, Form(description="JSON matching BookMetadataInput", max_length=20_000)],
) -> AdminBookResponse:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > settings.book_upload_max_bytes + 64_000:
        raise PayloadTooLarge
    try:
        parsed_metadata = BookMetadataInput.model_validate_json(metadata)
    except ValidationError as exc:
        raise RequestValidationError(
            [{**err, "loc": ("body", "metadata", *err["loc"])} for err in exc.errors()]
        ) from exc

    data = await read_limited(file, settings.book_upload_max_bytes)
    source_format = detect_format(data, file.filename)
    await scanner.scan(data, declared_name=file.filename)
    return await service.create(
        admin_id=admin.user.id, metadata=parsed_metadata, data=data, source_format=source_format
    )


@router.get("", response_model=AdminBookListResponse, responses=_ADMIN_ERRORS)
async def list_books(
    _: AdminDep,
    service: ServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> AdminBookListResponse:
    return AdminBookListResponse(items=await service.list(limit=limit, offset=offset))


@router.get("/{book_id}", response_model=AdminBookResponse, responses=_ADMIN_ERRORS)
async def get_book(book_id: uuid.UUID, _: AdminDep, service: ServiceDep) -> AdminBookResponse:
    return await service.get(book_id)


@router.put("/{book_id}/rights", response_model=AdminBookResponse, responses=_ADMIN_ERRORS)
async def update_rights(
    book_id: uuid.UUID, body: RightsInput, admin: AdminDep, service: ServiceDep
) -> AdminBookResponse:
    return await service.update_rights(admin_id=admin.user.id, book_id=book_id, rights=body)


@router.post(
    "/{book_id}/process",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AdminBookResponse,
    responses={**_ADMIN_ERRORS, 409: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def process_book(book_id: uuid.UUID, admin: AdminDep, service: ServiceDep) -> AdminBookResponse:
    return await service.request_processing(admin_id=admin.user.id, book_id=book_id)
