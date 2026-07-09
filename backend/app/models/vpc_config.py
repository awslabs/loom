"""VpcConfig ORM model for named VPC networking configurations."""
import json
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime
from app.db import Base


class VpcConfig(Base):
    """A named VPC configuration (subnet IDs + security group IDs) selectable at agent deploy time."""
    __tablename__ = "vpc_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True, nullable=False)
    description = Column(Text, nullable=True)
    vpc_id = Column(String, nullable=False)
    subnet_ids = Column(Text, nullable=False)   # JSON array
    sg_ids = Column(Text, nullable=False)        # JSON array
    created_at = Column(DateTime, nullable=True, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_subnet_ids(self) -> list[str]:
        try:
            return json.loads(self.subnet_ids) if self.subnet_ids else []
        except json.JSONDecodeError:
            return []

    def set_subnet_ids(self, ids: list[str]) -> None:
        self.subnet_ids = json.dumps(ids)

    def get_sg_ids(self) -> list[str]:
        try:
            return json.loads(self.sg_ids) if self.sg_ids else []
        except json.JSONDecodeError:
            return []

    def set_sg_ids(self, ids: list[str]) -> None:
        self.sg_ids = json.dumps(ids)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "vpc_id": self.vpc_id,
            "subnet_ids": self.get_subnet_ids(),
            "sg_ids": self.get_sg_ids(),
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
            "updated_at": self.updated_at.isoformat() + "Z" if self.updated_at else None,
        }
