"""Central settings — every module reads config from here, never os.environ directly."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "dev"
    api_prefix: str = "/api/v1"

    database_url: str = "postgresql+asyncpg://healthdoc:change-me@localhost:5432/healthdoc"
    mongo_uri: str = "mongodb://localhost:27017/healthdoc"
    redis_url: str = "redis://localhost:6379/0"

    jwt_issuer: str = "http://keycloak:8080/realms/healthdoc"
    oidc_audience: str = "account"

    minio_endpoint: str = "localhost:9000"
    minio_root_user: str = "healthdoc"
    minio_root_password: str = "change-me"
    minio_bucket_files: str = "hd-files"
    minio_bucket_reports: str = "hd-reports"

    abdm_gateway_base_url: str = "https://dev.abdm.gov.in/gateway"
    abdm_client_id: str = "change-me"
    abdm_client_secret: str = "change-me"
    abdm_hfr_facility_id: str = "change-me"


@lru_cache
def get_settings() -> Settings:
    return Settings()
