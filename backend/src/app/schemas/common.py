"""Common schema base classes and utilities."""

from pydantic import BaseModel, ConfigDict


class ORMBase(BaseModel):
    """Base Pydantic model with ORM attribute extraction enabled."""

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )
