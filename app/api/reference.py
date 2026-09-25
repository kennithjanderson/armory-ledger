from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.dependencies import (
    get_current_user,
    get_db,
)
from app.models.user import User
from app.services.caliber_service import create_caliber


router = APIRouter(
    prefix="/reference",
    tags=["reference"],
)


class CaliberCreateRequest(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=100,
    )


@router.post(
    "/calibers",
    status_code=status.HTTP_201_CREATED,
)
async def caliber_create(
    payload: CaliberCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        caliber = create_caliber(
            db,
            payload.name,
        )
    except ValueError as exc:
        return {
            "success": False,
            "error": str(exc),
        }

    return {
        "success": True,
        "caliber": {
            "id": str(caliber.id),
            "name": caliber.name,
        },
    }