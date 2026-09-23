"""
元数据库MySQL仓储

这一层对应文档里的Meta Repository，负责接受业务实体并落到Meta MySQL
Repository 自身只关心”如何写入“,而”哪些写操作要放在同一笔事物里“，由Service层统一决定

表、字段、指标和字段指标关系都会先以业务实体流转，再在这里统一转成ORM模型
问数链路运行时也会从这里读取元数据，用来把召回道德id补齐成完整实体

"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.column_info import ColumnInfo
from app.entities.column_metric import ColumnMetric
from app.entities.metric_info import MetricInfo
from app.entities.table_info import TableInfo
from app.models.column_info import ColumnInfoMySQL
from app.models.table_info import TableInfoMySQL
from app.repositories.mysql.meta.mappers.column_info_mapper import ColumnInfoMapper
from app.repositories.mysql.meta.mappers.column_metric_mapper import ColumnMetricMapper
from app.repositories.mysql.meta.mappers.metric_info_mapper import MetricInfoMapper
from app.repositories.mysql.meta.mappers.table_info_mapper import TableInfoMapper

class MetaMySQLRepository:
    """负责把原数据实体持久化到Meta MySQL"""
    def __init__(self,session: AsyncSession):
        self.session=session

    def save_table_infos(self,table_infos: list[TableInfo]):
        """批量保存表元数据，输入仍然是业务实体，而不是ORM模型"""
        self.session.add_all(
            [TableInfoMapper.to_model(table_info) for table_info in table_infos]
        )

    def save_column_infos(self,column_infos: list[ColumnInfo]):
        """批量保存字段元数据，实体到模型转换同意通过Mapper完成"""
        self.session.add_all(
            [ColumnInfoMapper.to_model(column_info) for column_info in column_infos]
        )

    def save_metric_innfos(self,metric_infos: MetricInfo):
        """批量保存之表元数据，指标本身和字段关联分开写入"""
        self.session.add_all(
            [MetricInfoMapper.to_model(metric_info) for metric_info in metric_infos]
        )

    def save_column_metrics(self,column_metrics: list[ColumnMetric]):
        """批量保存字段和指标的关系"""
        self.session.add_all(
            [
                ColumnMetricMapper.to_model(column_metric)
                for column_metric in column_metrics
            ]
        )

    async def get_column_info_by_id(self,id: str)-> ColumnInfo | None:
        """按字段id查询字段段元数据，是招回信息合并阶段不起字段上下文"""

        column_info: ColumnInfoMySQL = await self.session.get(
            ColumnInfoMySQL,id
        )

        if column_info:
            return ColumnInfoMapper.to_entity(column_info)
        else:
            return None

    async def get_table_info_by_id(self, id: str) -> TableInfo | None:
        """按表 id 查询表元数据，最终组装成提示词里的表结构信息"""

        table_info: TableInfoMySQL | None = await self.session.get(TableInfoMySQL, id)
        if table_info:
            return TableInfoMapper.to_entity(table_info)
        else:
            return None

    async def get_key_columns_by_table_id(self,table_id: str)->list[ColumnInfo]:
        """查询指定表的主外键字段，避免Join关键字段被向量召回漏掉"""

        #主外键字段用于后续生成join条件，不能完全依赖向量找回命中
        sql = "select * from column_info where table_id = :table_id and role in ('primary_key','foreign_key')"
        # :table_id是SQLAchemy的占位符，实际值通过第二个参数转入
        result = await self.session.execute(text(sql),{"table_id": table_id})
        #mappings()会把结果行转成类似字典的结构，便于解包成ColumnInfo
        return [ColumnInfo(**dict(row)) for row in result.mappings().fetchall()]

