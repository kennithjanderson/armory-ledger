from authlib.integrations.starlette_client import OAuth

from app.core.config import settings


oauth = OAuth()

oauth.register(
    name="authentik",
    client_id=settings.oidc_client_id,
    client_secret=settings.oidc_client_secret,
    server_metadata_url=(
        f"{settings.oidc_issuer.rstrip('/')}/.well-known/openid-configuration"
    ),
    client_kwargs={
        "scope": "openid profile email",
    },
)
