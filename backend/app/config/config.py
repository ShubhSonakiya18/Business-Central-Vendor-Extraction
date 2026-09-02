from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
   
    APP_TITLE: str = "Vendor Form Extractor"
    DEBUG: bool = False

    
    GEMINI_API_KEY: str
    GEMINI_MODEL: str = "gemini-flash-lite-latest"
    DEFAULT_PIPELINE: str = "auto"

    # Security
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Database
    DATABASE_URL: str

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()