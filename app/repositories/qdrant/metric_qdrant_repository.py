"""
指标向量仓储

管理指标向量集合，并把Service层准备好的指标point批量写入Qdrant

字段和指标虽然都用向量检索，但他们是两类不同对象
所以指标单独使用metric_info_collection，避免后续找回是和字段结果混在一起
"""

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance,PointStruct,VectorParams

from app.conf.app_config import app_config
from app.entities.metric_info import MetricInfo

class MetricQdrantRepository:
    """负责指标向量集合的创建 写入和基础检索"""

    collection_name = "metric_info_collection"

    def __init__(self,client: AsyncQdrantClient):
        self.client=client

    async def ensure_collection(self):
        """确保指标向量集合存在，并按照当前Embedding维度初始化"""

        if not await self.client.collection_exists(self.collection_name):
            await self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    #向量为度必须和Embedding模型输出一致,否则写入时会失效
                    size=app_config.qdrant.embedding_size,
                    distance=Distance.COSINE
                ),
            )


    async def upsert(
            self,
            ids: list[str],
            embeddings: list[list[float]],
            payloads: list[dict],
            batch_size: int=10,
    ):
        """分批upsert指标向量点，避免一次提交过多point"""
        #ids embeddings payloads 三个列表按相同下标组成一条完整的Qdrant point
        points: list[PointStruct] = [
            PointStruct(id=id,vector=embeddings,payload=payloads)
            for id,embeddings,payloads in zip(ids,embeddings,payloads)
        ]
        for i in range(0,len(points),batch_size):
            await self.client.upsert(
                collection_name=self.collection_name,points=points[i: i+batch_size]
            )

    async def search(
            self,embedding: list[float],score_threshold: float=0.6,limit: int=20
    )->list[MetricInfo]:
        """按向量相似度检索之表元数据，并还原为MetricInfo对象"""

        result = await self.client.query_points(
            collection_name=self.collection_name,
            query=embedding,
            limit=limit,
            score_threshold=score_threshold,
        )
        return [MetricInfo(**point.payload) for point in result.points]