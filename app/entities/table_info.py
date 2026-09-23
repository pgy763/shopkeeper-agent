"""
表元数据业务实体

这一层对应文档里”先把配置描述转换成业务实体“的部分，用于在Service
和Repository之间传递统一的表语义信息，而不是直接暴露ORM模型
"""

from dataclasses import dataclass

@dataclass
class TableInfo:
    """系统内部统一使用的表元数据表达"""

    id: str
    name: str
    role: str
    description: str