"""
元数据知识构建服务

负责组织元数据知识库构建的核心业务流程，位于脚本入口和仓储曾之间
一方面接受配置文件，另一方面协调员数据库和数仓查询仓储

当前这条主线已经覆盖字段入库，字段向量索引 字段取值全文索引
一级指标入库和指标向量索引构建逻辑
"""

import uuid
from dataclasses import asdict
from pathlib import Path

from langchain_huggingface import HuggingFaceEndpointEmbeddings
from omegaconf import OmegaConf
from openai import embeddings

from app.conf.meta_config import MetaConfig
from app.core.log import logger
from app.entities.column_info import ColumnInfo
from app.entities.column_metric import ColumnMetric
from app.entities.metric_info import MetricInfo
from app.entities.table_info import TableInfo
from app.entities.value_info import ValueInfo
from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository

class MetaKnowledgeService:
    """负责串联元数据知识库构建流程的应用服务"""

    def __init__(
            self,
            meta_mysql_repository: MetaMySQLRepository,
            dw_mysql_repository: DWMySQLRepository,
            column_qdrant_repository: ColumnQdrantRepository,
            embedding_client: HuggingFaceEndpointEmbeddings,
            value_es_repository: ValueESRepository,
            metric_qdrant_repository: MetricQdrantRepository,
    ):
        #meta repository负责结构化元数据的落库
        self.meta_mysql_repository: MetaMySQLRepository=meta_mysql_repository
        #dw repository负责到教学数仓中读取真是表结构和示例值
        self.dw_mysql_repository: DWMySQLRepository = dw_mysql_repository
        #字段向量集合的创建和写入同意交给Qdrant
        self.column_qdrant_repository: ColumnQdrantRepository = column_qdrant_repository
        #向量化动作放在service层
        self.embedding_client: HuggingFaceEndpointEmbeddings = embedding_client
        #字段值全文索引的写入统一交给ES Repository
        self.value_es_repository : ValueESRepository = value_es_repository
        #指标向量集合和字段向量集合分开管理，便于后续按对象类型独立找回
        self.metric_qdrant_repository: MetricQdrantRepository = metric_qdrant_repository

    async def _save_tables_to_meta_db(
            self,meta_config: MetaConfig
    )->list[ColumnInfo]:
        """把配置里的表字段信息部其后写入Meta MySQL"""
        table_infos: list[TableInfo] = []
        column_infos: list[ColumnInfo] = []

        for table in meta_config.tables:
            #先把配置里的表定义整理成业务实体，后面统一交给Meta Repository落库
            table_info = TableInfo(
                id=table.name,
                name=table.name,
                role=table.role,
                description=table.description,
            )
            table_infos.append(table_info)

            #字段类型属于束苍离的真实信息，所以这里仍然要回到DW查询
            column_types = await self.dw_mysql_repository.get_column_types(table.name)

            for column in table.columns:
                #这里只拿少量示例值，目的是让字段元数据更容易被人和模型理解
                column_values = await self.dw_mysql_repository.get_column_values(
                    table.name,column.name
                )

                #字段id使用table.column形式，后续在向量索引和全文索引都会服用
                column_info = ColumnInfo(
                    id=f"{table.name}.{column.name}",
                    name=column.name,
                    type=column_types[column.name],
                    role=column.role,
                    examples=column_values,
                    description=column.description,
                    alias=column.alias,
                    table_id=table.name,
                )
                column_infos.append(column_info)

        async with self.meta_mysql_repository.session.begin():
            self.meta_mysql_repository.save_table_infos(table_infos)
            self.meta_mysql_repository.save_column_infos(column_infos)

        return column_infos
    async def _save_column_info_to_qdrant(self,column_infos: list[ColumnInfo]):
        """吧字段元数据继续推进城可语义检索的Qdrant像两点"""
        await self.column_qdrant_repository.ensure_collection()

        points: list[dict] = []
        for column_info in column_infos:
            #一个字段不会只生成一个像两点，而是把名字 描述 别名都拆开建立语义入口
            points.append(
                {
                    "id": uuid.uuid4(),
                    "embedding_text": column_info.name,
                    "payload": asdict(column_info),
                }
            )

            points.append(
                {
                    "id": uuid.uuid4(),
                    "embedding_text": column_info.description,
                    "payload": asdict(column_info),
                }
            )

            for alia in column_info.alias:
                points.append(
                    {
                        "id": uuid.uuid4(),
                        "embedding_text": alia,
                        "payload": asdict(column_info),
                    }
                )

        #先把带向量化文本抽出来，再分批调用embedding 服务
        #这样更容易控制但此请求大小
        embeddings: list[list[float]] = []
        embedding_texts = [point["embedding_text"] for point in points]
        embedding_batch_size = 20
        for i in range(0,len(embedding_texts),embedding_batch_size):
            batch_embedding_texts = embedding_texts[i: i+embedding_batch_size]
            batch_embeddings = await self.embedding_client.aembed_documents(
                batch_embedding_texts
            )
            embeddings.extend(batch_embeddings)

        ids = [point["id"] for point in points]
        payloads = [point["payload"] for point in points]

        await self.column_qdrant_repository.upsert(ids,embeddings,payloads)

    async def _save_value_info_to_es(
            self,
            meta_config: MetaConfig,column_infos: list[ColumnInfo]
    ):
        """把允许同步的字段真是取值写入Elasticsearch全文索引"""
        await self.value_es_repository.ensure_index()

        #不是所有字段都需要同步真实值，是否同步有配置里的sync显示控制
        column2sync: dict[str,bool]={}
        for table in meta_config.tables:
            for column in table.columns:
                column2sync[f"{table.name}.{column.name}"] = column.sync

        value_infos: list[ValueInfo] = []
        for column_info in column_infos:
            sync = column2sync[column_info.id]
            if sync:
                #这里拿的是字段真实值全集
                current_column_values = (
                    await self.dw_mysql_repository.get_column_values(column_info.table_id,column_info.name,100000)
                )

                current_values_infos = [
                    ValueInfo(
                        id=f"{column_info.id}.{current_column_value}",
                        value=current_column_value,
                        column_id=column_info.id,
                    )
                    for current_column_value in current_column_values
                ]
                value_infos.extend(current_values_infos)

        await self.value_es_repository.index(value_infos)


    async def _save_metrics_to_meta_db(
            self,meta_config: MetaConfig)->list[MetricInfo]:
        """把配置里的指标信息和字段依赖关系写入Meta MySQL"""
        metric_infos: list[MetricInfo] = []
        column_metrics: list[ColumnMetric] = []

        for metric in meta_config.metrics:
            #MetricInfo表达指标本身，当前直接用指标名作为稳定业务id
            metric_info = MetricInfo(
                id=metric.name,
                name=metric.name,
                description=metric.description,
                relevant_columns=metric.relevant_columns,
                alias=metric.alias,
            )
            metric_infos.append(metric_info)
            for column in metric.relevant_columns:
                #ColumnMetric单独表达“某个指标以来某个字段”这层关系
                column_metric = ColumnMetric(column_id=column,metric_id=metric.name)
                column_metrics.append(column_metric)

        #指标本身和字段关系要放在同一鄙视物理，避免值写入其中一部分
        async with self.meta_mysql_repository.session.begin():
            self.meta_mysql_repository.save_metric_innfos(metric_infos)
            self.meta_mysql_repository.save_column_metrics(column_metrics)

        return metric_infos

    async def _save_metrics_to_qdrant(self,metric_infos: list[MetricInfo]):
        """把指标元数据继续推进成可予以检索的Qdrant像两点"""
        await self.metric_qdrant_repository.ensure_collection()

        points: list[dict] = []
        for metric_info in metric_infos:
            #和字段一样，。一个指标也会拆成名字 描述  别名这几类于一入口
            points.append(
                {
                    "id": uuid.uuid4(),
                    "embedding_text": metric_info.name,
                    "payload": asdict(metric_info),
                }
            )

            points.append(
                {
                    "id": uuid.uuid4(),
                    "embedding_text": metric_info.description,
                    "payload": asdict(metric_info),
                }
            )
            for alia in metric_info.alias:
                points.append(
                    {
                        "id": uuid.uuid4(),
                        "embedding_text": alia,
                        "payload": asdict(metric_info),
                    }
                )

        #先把带向量化沃森本手出来，再分批调用Embedding服务
        #返回的embeddings 要继续和前面deid  payload顺序对其
        embeddings: list[list[float]] = []
        embedding_texts = [point["embedding_text"]for point in points]
        embedding_batch_size = 20
        for i in range(0,len(embedding_texts),embedding_batch_size):
            batch_embedding_texts = embedding_texts[i: i+embedding_batch_size]
            batch_embeddings = await self.embedding_client.aembed_documents(
                batch_embedding_texts
            )
            embeddings.extend(batch_embeddings)

        ids = [point["id"]for point in points]
        payloads = [point["payload"]for point in points]

        await self.metric_qdrant_repository.upsert(ids,embeddings,payloads)


    async def build(self,config_path: Path):
        """读取配置并以此构建Meta MyuSQL Qdrant和ES中的源数据索引"""
        context = OmegaConf.load(config_path)
        schema = OmegaConf.structured(MetaConfig)
        meta_config: MetaConfig = OmegaConf.to_object(OmegaConf.merge(schema,context))


        #根据配置文件判断后需要进入那条构建链路
        if meta_config.tables:
            #将表信息和字段信息保存到Meta MySQL
            column_infos = await self._save_tables_to_meta_db(meta_config)
            logger.info("保存表信息和字段信息到Meta MySQL")
            #对字段信息建立向量索引
            await self._save_column_info_to_qdrant(column_infos)
            logger.info("为字段信息建立向量索引")
            #对指定的维度字段取值建立全文索引
            await self._save_value_info_to_es(meta_config,column_infos)
            logger.info("为字段取值建立全文索引")

        #根据配置文件同步指定的指标信息
        if meta_config.metrics:
            #将指标信息和字段依赖关系保存到Meta MySQL
            metric_infos = await self._save_metrics_to_meta_db(meta_config)
            logger.info("保存指标信息到数据库成功")

            #对指标信息建立向量索引
            await self._save_metrics_to_qdrant(metric_infos)
            logger.info("为指标信息建立向量索引成功")