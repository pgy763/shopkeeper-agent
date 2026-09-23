import asyncio
from typing import Optional

from elasticsearch import AsyncElasticsearch
from watchfiles import awatch

from app.conf.app_config import ESConfig, app_config


class ESClientManager:
    def __init__(self,es_config: ESConfig):
        #保存ES配置对象，后面初始化客户端时会从这里读取host和post
        self.es_config = es_config
        #先把client声明出来
        self.client : Optional[AsyncElasticsearch] = None

    def _get_url(self):
        return f"http://{self.es_config.host}:{self.es_config.port}"

    def init(self):
        #创建异步ES客户端
        #hosts之所以是列表，是为了兼容ES常见的集群连接方式
        self.client=AsyncElasticsearch(hosts=[self._get_url()])

    async def close(self):
        await self.client.close()

#创建一个全局可复用的ES客户端管理对象
es_client_manager = ESClientManager(app_config.es)

if __name__=="__main__":
    #先初始化客户端
    es_client_manager.init()

    async def test():
        #取出真正的AsyncElasticsearch客户端
        client = es_client_manager.client

        #创建索引
        #这里同时显示定义了字段结构与
        #dynamic=False表示关闭动态映射，要求写入数据必须符合当前定义
        await client.indices.create(
            index="my-books",
            mappings={
                "dynamic": False,
                "properties": {
                    #书名和作者是合作全文检索，所以定义为text
                    "name": {"type":"text"},
                    "author": {"type":"text"},
                    #日期字段按日期类型处理
                    "release_date": {"type": "date","format":"yyyy-MM-dd"},
                    #页数字段按整数处理
                    "page_count": {"type": "integer"},
                },
            },
        )

        #插入数据
        #bulk采用“操作说明+数据本体”交替出现的格式
        #适合一次性写入多条文档
        await client.bulk(
            operations = [
                {"index":{"_index": "my-books"}},
                {
                    "name": "Revelation Space",
                    "author": "Alastair Reynolds",
                    "release_date": "2000-03-15",
                    "page_count": 585,
                },
                {"index":{"_index": "my-books"}},
                {
                    "name": "1984",
                    "author": "George Orwell",
                    "release_date": "1985-06-01",
                    "page_count": 328,
                },
                {"index":{"_index": "my-books"}},
                {
                    "name":"Fahrenheit 451",
                    "author": "Ray Bradbury",
                    "release_date": "1953-10-15",
                    "page_count": 227,
                },
                {"index": {"_index": "my-books"}},
                {
                    "name": "Brave New World",
                    "author": "Aldous Huxley",
                    "release_date": "1932-06-01",
                    "page_count": 268,
                },
                {"index": {"_index": "my-books"}},
                {
                    "name": "The Handmaids Tale",
                    "author": "Margaret Atwood",
                    "release_date": "1985-06-01",
                    "page_count": 311,
                },
            ],
        )

        #搜索
        #在name字段上执行match查询
        #这里演示的是最基础的全文检索能力
        resp = await client.search(
            index="my-books",
            query={"match": {"name":"brave"}},
        )

        #打印查询结果，便于观察hits和返回结构
        print(resp)

        #测试结束后关闭客户端连接
        await es_client_manager.close()

    #运行异步测试函数
    asyncio.run(test())
