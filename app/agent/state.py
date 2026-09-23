"""
电商问数Agent状态定义

State是langgraph个节点之间传递和更新的共享数据
本章在用户原始问题之外，新增关键词列表和三鹿召回结果
并把召回到的实体整理成后续提示词更容易消费的表信息和指标信息
SQL生成闭环会继续写入候选SQL以及检验错误信息，用于控制校正或执行分支
"""

from typing import TypedDict

from app.entities.column_info import ColumnInfo
from app.entities.metric_info import MetricInfo
from app.entities.value_info import ValueInfo

class MetricInfoState(TypedDict):
    #面向提示词的指标结构，不再保留内部id
    name: str
    description: str
    relevant_columns: list[str]
    alias: list[str]

class ColumnInfoState(TypedDict):
    #面向提示词的字段结构，只保留SQL生成需要理解的字段属性
    name: str
    type: str
    role: str
    examples: list
    description: str
    alias: list[str]

class TableInfoState(TypedDict):
    #表信息会嵌套字段列表，方便后续按表组织SQL上下文
    name: str
    role: str
    description: str
    columns: list[ColumnInfoState]

class DateInfoState(TypedDict):
    date: str
    weekday: str
    quarter: str

class DBInfoState(TypedDict):
    dialect: str
    version: str


class DataAgentState(TypedDict):
    """一次问数链路中的核心状态"""

    query: str#用户输入的查询
    keywords: list[str]#抽取的关键词
    retrieved_column_infos: list[ColumnInfo] #检索到的字段信息
    retrieved_metric_infos: list[MetricInfo] #检索到的指标信息
    retrieved_value_infos: list[ValueInfo] #检索到的取值信息

    table_infos: list[TableInfoState] #表信息
    metric_infos: list[MetricInfoState] #合并后的值表上下文

    date_info: DateInfoState #当前日期 星期和季度信息
    db_info: DBInfoState #数据库方言和版本信息

    sql: str #生成或校正后的SQL

    error: str