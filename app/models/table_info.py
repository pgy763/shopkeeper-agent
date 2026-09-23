"""
table_info ORM模型
负责定义源数据库中表元数据表的结构，保存纳入知识库地表明、角色和说明
"""

from sqlalchemy import String,Text
from sqlalchemy.orm import Mapped,mapped_column

from app.models.base import Base

class TableInfoMySQL(Base):
    """表元数据表对应的ORM模型"""

    __tablename__ = "table_info"

    id: Mapped[str] = mapped_column(String(64),primary_key=True,comment="表编号")
    name: Mapped[str|None] = mapped_column(String(128),comment="表名称")
    role: Mapped[str|None] = mapped_column(String(32),comment="表类型(fact/dim)")
    description: Mapped[str|None] = mapped_column(Text,comment="表描述")