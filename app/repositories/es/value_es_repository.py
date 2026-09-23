"""
字段取值ES仓储

把字段真实取值组织成Elasticsearch全文索引，并提供索引创建 批量写入和关键词检索能力

service层负责觉电工哪些字段需要同步
Repository只关心索引是否存在ValueInfo 如何写进ES以及如何按关键词召回

"""

from dataclasses import asdict

from elasticsearch import AsyncElasticsearch

from app.entities.value_info import ValueInfo

class ValueESRepository:
    """负责字段取值全文索引的创建  写入和基础检索"""
    index_name = "value_index"
    #value字段使用IK分词，这样地区 会员等级 品类等中文值才能按全文方式检索
    index_mappings = {
        "dynamic": False,
        "properties": {
            "id": {"type":"keyword"},
            "value": {
                "type": "text",
                "analyzer": "ik_max_word",
                "search_analyzer": "ik_max_word",
            },
            "column_id": {"type":"keyword"},
        },
    }

    def __init__(self,client: AsyncElasticsearch):
        self.client = client

    async def ensure_index(self):
        """确保字段取值索引已经创建好"""
        if not await self.client.indices.exists(index=self.index_name):
            await self.client.indices.create(
                index=self.index_name,mappings = self.index_mappings
            )

    async def index(self,value_infos: list[ValueInfo],batch_size=20):
        """分批写入字段取值，避免一次bulk过大"""
        if not value_infos:
            return

        for i in range(0,len(value_infos),batch_size):
            batch_value_infos = value_infos[i: i+batch_size]
            batch_operations = []
            for value_info in batch_value_infos:
                #使用ValueInfo.id作为文档id，这样重复构建时会覆盖同一条值记录
                batch_operations.append(
                    {"index": {"_index": self.index_name,"_id": value_info.id}}
                )
                batch_operations.append(asdict(value_info))
            await self.client.bulk(operations=batch_operations)

    async def search(self,keyword: str,score_threshold: float=0.6,limit: int = 20)->list[ValueInfo]:
        """按关键词全文检索字段取值，并还原为ValueInfo实体"""

        resp = await self.client.search(
            index=self.index_name,
            #value字段启用了IK分词，match查询可以处理中文短语和枚举值匹配
            query={"match": {"value": keyword}},
            size=limit,
            #过滤掉相关度过低的命中，避免把明显无关的取值带入后续上下文
            min_score=score_threshold

        )

        #ES文档_score中保存的是ValueInfo的字段结构，业务层继续使用实体对象
        return [ValueInfo(**hit["_source"]) for hit in resp["hits"]["hits"]]