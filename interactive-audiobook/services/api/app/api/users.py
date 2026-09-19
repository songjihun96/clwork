from fastapi import APIRouter, status

from app.api.auth import AuthServiceDep
from app.dependencies import CurrentUserDep
from app.schemas.auth import DeleteAccountRequest, UserResponse
from app.schemas.common import ERROR_RESPONSES

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse, responses=ERROR_RESPONSES)
async def get_me(current: CurrentUserDep) -> UserResponse:
    user = current.user
    return UserResponse(
        id=user.id, email=user.email, display_name=user.display_name, created_at=user.created_at
    )


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT, responses=ERROR_RESPONSES)
async def delete_me(body: DeleteAccountRequest, current: CurrentUserDep, service: AuthServiceDep) -> None:
    """Permanently delete the account (App Store / Play account-deletion requirement)."""
    await service.delete_account(user=current.user, claims=current.claims, password=body.password)
