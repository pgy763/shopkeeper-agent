"""
问数查询服务

负责把 API 层传入的自然语言问题转换成一次 LangGraph 工作流执行：
创建初始 State、组装 Runtime Context、消费 graph.astream 的流式输出，
并统一包装成 SSE 文本返回给路由层。
"""

import json

from langchain_huggingface import HuggingFaceEndpointEmbeddings

from app.agent.context import DataAgentContext
from app.agent.graph import graph
from app.agent.state import DataAgentState
from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository

class QueryService:
    """封装一次问数查询所需的业务编排逻辑"""

    def __init__(
            self,
            meta_mysql_repository: MetaMySQLRepository,
            embedding_client: HuggingFaceEndpointEmbeddings,
            dw_mysql_repository: DWMySQLRepository,
            column_qdrant_repository: ColumnQdrantRepository,
            metric_qdrant_repository: MetricQdrantRepository,
            value_es_repository: ValueESRepository,
    ):
        #MySQL仓储分别负责元数据补全和真实数仓环境信息读取
        self.meta_mysql_repository = meta_mysql_repository
        self.dw_mysql_repository = dw_mysql_repository

        #召回链路依赖的向量检索、Embedding和全文检索能力由以来曾注入
        self.embedding_client = embedding_client
        self.column_qdrant_repository = column_qdrant_repository
        self.metric_qdrant_repository = metric_qdrant_repository
        self.value_es_repository = value_es_repository

    async def query(self,query: str):
        """执行一次问数工作流，并逐段产出SSE消息"""

        #State 只放会被图节点读写和合并的业务数据，外部工具对象不塞进State
        state = DataAgentState(query=query)
        #Context保存本次图执行需要重复的外部依赖，节点通过runtime.context读取
        context = DataAgentContext(
            column_qdrant_repository=self.column_qdrant_repository,
            embedding_client=self.embedding_client,
            metric_qdrant_repository=self.metric_qdrant_repository,
            value_es_repository=self.value_es_repository,
            meta_mysql_repository=self.meta_mysql_repository,
            dw_mysql_repository=self.dw_mysql_repository,
        )

        try:
            #stream_mode="custom"对应节点内部writer(...)写出的进度消息
            async for chunk in graph.astream(
                input=state,context = context,stream_mode="custom"
            ):
                #SSE要求每条消息以data开头：以两个换行符结束
                # ensure_ascii=False 保留中文进度文案，default=str 兜底处理日期等非 JSON 类型
                yield f"data: {json.dumps(chunk,ensure_ascii=False,default=str)}\n\n"
        except Exception as e:
            error = {"type": "error","message": str(e)}
            yield f"data: {json.dumps(error,ensure_ascii=False,default=str)}\n\n"
