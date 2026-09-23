"""
ORM基类

定义项目中所有SQLAlchemy ORM模型共享的声明式基类
后续 table_info column_info metric_info和column_metric都会继承这里的Base

"""

from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    """项目统一的SQL Alchemy生命是基类"""

    pass