from abc import ABC, abstractmethod
from typing import Tuple, List, Optional
from app.schemas.canonical import CanonicalTransaction, AccountSummary

class BaseBankParser(ABC):
    """Abstract interface for all statement parsers."""

    @abstractmethod
    def can_parse(self, content: bytes, filename: str) -> Tuple[bool, float]:
        """
        Determines if parser can handle this file.
        Returns: (is_capable, confidence_score 0.0-1.0)
        """
        pass

    @abstractmethod
    def parse_to_canonical(
        self,
        content: bytes,
        filename: str,
        tenant_id: str,
        client_entity_id: str = "default"
    ) -> Tuple[List[CanonicalTransaction], Optional[AccountSummary]]:
        """
        Parses raw content into CanonicalTransactions and optional AccountSummary.
        """
        pass
