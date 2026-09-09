import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

class Settings(BaseSettings):
    PROJECT_NAME: str = "Statement2Muster API"
    VERSION: str = "2.0.0"
    ENVIRONMENT: str = "development"
    
    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./statement2muster.db"
    
    # Asymmetric JWT configuration (RS256) per Architect ADR-001
    JWT_ALGORITHM: str = "RS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 10
    JWT_PRIVATE_KEY_PEM: Optional[str] = None
    JWT_PUBLIC_KEY_PEM: Optional[str] = None
    
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
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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
