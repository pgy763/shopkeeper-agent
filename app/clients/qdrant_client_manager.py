import asyncio
import random
from typing import Optional

from qdrant_client import AsyncQdrantClient, models

from app.conf.app_config import QdrantConfig, app_config


class QdrantClienntManager:
    def __init__(self,qdrant_config: QdrantConfig):
        # 保存配置对象。后面初始化客户端要从这里读取host和port
        self.qdrant_config = qdrant_config
        #先把client生命出来，真正初始化放到init
        self.client: Optional[AsyncQdrantClient] = None

    def _get_url(self):
        #根据配置文件拼出Qdrannt服务地址
        return f"http://{self.qdrant_config.host}:{self.qdrant_config.port}"

    def init(self):
        # 创建异步客户端
        # 这里不再__init__中直接初始化，是为了和项目的生命周期管理保持一致
        self.client = AsyncQdrantClient(url=self._get_url())


    async def close(self):
        # 项目关闭时同意关闭客户端连接
        await self.client.close()

#创建一个全局的管理器对象
#后续项目中的其它模块都通过它来获取同一套Qdrant客户端
qdrant_client_manager = QdrantClienntManager(app_config.qdrant)

if __name__=="__main__":
    # 先初始化客户端，后面的测试逻辑才能真正访问Qdrant
    qdrant_client_manager.init()

    async def test():
        #取出真正的Qdrant异步客户端
        client = qdrant_client_manager.client

        # 如果集合不存在，就先创建一个集合
        if not await client.collection_exists("my_collection"):
            await client.create_collection(
                collection_name = "my_collection",
                vectors_config = models.VectorParams(
                    #当前集合中的向量为度时10
                    size = 10,
                    #使用余弦相似度作为距离计算方式
                    distance=models.Distance.COSINE,
                ),
            )

        #向集合中写入100个随机point
        #每个point都有一个id和一个10维度向量
        await client.upsert(
            collection_name="my_collection",
            points=[
                models.PointStruct(
                    id=i,
                    vector=[random.random() for _ in range(10)],
                )
                for i in range(100)
            ],
        )

        #用一个随机生成的查询向量做相似度检索

        #limit=10表示最多返回10条结果
        #score_threshold=0.8表示只保留分数不低于0.8的结果
        res = await client.query_points(
            collection_name="my_collection",
            query=[random.random() for _ in range(10)],
            limit=10,
            score_threshold=0.8,
        )

        #打印查询结果，便于观察一个向量节点的一些东西
        print(res)

    asyncio.run(test())