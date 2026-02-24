from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict

class BaseSection(BaseModel):
    title: str = Field(description="The title or header of the section.")
    level: int = Field(description="The hierarchical level of the section (e.g., 1 for H1, 2 for H2).")
    page_start: int = Field(description="The page number where this section starts.")
    content: str = Field(description="The raw text content contained within this section.")

class DocumentNode(BaseModel):
    """
    Represents a specific parsed node derived from a document.
    """
    base_extraction: BaseSection
    domain_augmentation: Optional[Any] = Field(default=None, description="Domain-specific structured data returned by an LLM plugin")

class DocumentPackage(BaseModel):
    """
    The top-level payload that encapsulates the full document graph payload.
    """
    metadata: Dict[str, Any] = Field(description="Document-level metadata, e.g., {'project': 'MAT'}")
    outline: List[BaseSection] = Field(default_factory=list, description="The structural baseline parsed from the document.")
    nodes: List[DocumentNode] = Field(default_factory=list, description="The fully augmented document nodes ready for graph insertion.")
