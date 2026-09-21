from fastapi import HTTPException, Request, status


def get_current_user(request: Request) -> dict:
    user = request.session.get("user")

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    return user
