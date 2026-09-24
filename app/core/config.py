from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "微专业就业成效追踪系统"
    DATABASE_URL: str = "sqlite:///./gradtrack.db"

    class Config:
        case_sensitive = True


settings = Settings()
