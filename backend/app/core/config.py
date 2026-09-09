import os
from typing import Optional
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

class Settings(BaseSettings):
    PROJECT_NAME: str = "Statement2Muster API"
    VERSION: str = "2.0.0"
    ENVIRONMENT: str = "development"
    
    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./statement2muster.db"
    SQLITE_DB_PATH: Optional[str] = None
    
    # Asymmetric JWT configuration (RS256) per Architect ADR-001
    JWT_ALGORITHM: str = "RS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 10
    JWT_PRIVATE_KEY_PEM: Optional[str] = None
    JWT_PUBLIC_KEY_PEM: Optional[str] = None
    
    # Email Delivery Configuration (B01)
    EMAIL_BACKEND: str = os.getenv("EMAIL_BACKEND", "memory") # memory, smtp, file
    EMAIL_OUTBOX_PATH: str = "docs/audit_2026-09-09_round3/email_outbox.jsonl"
    SMTP_HOST: Optional[str] = os.getenv("SMTP_HOST", None)
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: Optional[str] = os.getenv("SMTP_USER", None)
    SMTP_PASSWORD: Optional[str] = os.getenv("SMTP_PASSWORD", None)
    SMTP_FROM: str = os.getenv("SMTP_FROM", "no-reply@statement2muster.com")
    
    # Stripe Billing Secrets
    STRIPE_SECRET_KEY: str = os.getenv("STRIPE_SECRET_KEY", "sk_test_mock")
    STRIPE_WEBHOOK_SECRET: str = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_mock")
    
    # Stripe Price IDs (from verified checkout links)
    STRIPE_PRICE_STARTER_MONTHLY: str = "price_starter_490"
    STRIPE_PRICE_PRO_MONTHLY: str = "price_pro_2900"
    STRIPE_PRICE_LIFETIME: str = "price_lifetime_8900"
    
    # Fair Use & Resource Budgets (ADR-001)
    MAX_FILE_SIZE_BYTES: int = 10 * 1024 * 1024       # 10 MiB
    MAX_BATCH_SIZE_BYTES: int = 50 * 1024 * 1024      # 50 MiB
    MAX_FILES_PER_BATCH: int = 12
    MAX_PAGES_PER_FILE: int = 100
    MAX_ROWS_PER_FILE: int = 10_000
    PARSER_TIMEOUT_SECONDS: int = 30
    OCR_TIMEOUT_SECONDS: int = 90
    PARSER_PROCESS_ISOLATION: bool = os.getenv("PARSER_PROCESS_ISOLATION", "true").lower() in ("true", "1")
    PARSER_WORKER_CONCURRENCY: int = int(os.getenv("PARSER_WORKER_CONCURRENCY", "4"))
    PARSER_MAX_QUEUE_DEPTH: int = int(os.getenv("PARSER_MAX_QUEUE_DEPTH", "8"))
    
    # RAM Cache Budget & Retention (B02 / B07)
    RAM_CACHE_TTL_SECONDS: int = 600                  # 10 minutes
    RAM_CACHE_MAX_BYTES: int = 50 * 1024 * 1024       # 50 MiB
    RAM_CACHE_MAX_ENTRIES: int = 100
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def reconcile_sqlite_path(self):
        sqlite_env = os.getenv("SQLITE_DB_PATH") or self.SQLITE_DB_PATH
        if sqlite_env and "sqlite" in self.DATABASE_URL:
            self.SQLITE_DB_PATH = sqlite_env
            self.DATABASE_URL = f"sqlite+aiosqlite:///{sqlite_env}"
        if self.ENVIRONMENT.lower() == "production" and self.EMAIL_BACKEND.lower() == "memory":
            raise ValueError("EMAIL_BACKEND cannot be 'memory' in production environment. Configure SMTP delivery.")
        return self

    def get_jwt_keys(self):
        """Returns (private_key_pem, public_key_pem). Generates ephemeral RSA pair if not set."""
        if self.JWT_PRIVATE_KEY_PEM and self.JWT_PUBLIC_KEY_PEM:
            return self.JWT_PRIVATE_KEY_PEM.encode(), self.JWT_PUBLIC_KEY_PEM.encode()
        
        # Auto-generate RSA key pair for local dev/testing
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        priv_pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        pub_pem = key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        return priv_pem, pub_pem

settings = Settings()
