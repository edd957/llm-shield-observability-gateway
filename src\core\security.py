from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from src.core.config import Settings, get_settings

api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)


def verify_api_key(
    provided_key: str | None = Security(api_key_header),
    settings: Settings = Depends(get_settings),
) -> None:
    """Validate consumer access to the proxy without leaking configured keys."""

    if not provided_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "missing_api_key", "message": "Missing x-api-key header."},
        )

    valid_keys = {key.get_secret_value() for key in settings.api_keys}
    if provided_key not in valid_keys:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "invalid_api_key",
                "message": "The provided API key is not authorized.",
            },
        )
