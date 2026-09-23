"""
字段召回节点

负责根据关键词从字段向量知识库中召回候选字段
他解决的时”用户问题可能对应哪些数据库字段“地问题
本章的主线是：关键词扩展->Embedding->Qdrant相似度检索->ColumnInfo去重
"""

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.llm import llm
import asyncio
from app.agent.state import DataAgentState
from app.core.log import logger
from app.entities.column_info import ColumnInfo
from app.prompt.prompt_loader import load_prompt

async def recall_column(state: DataAgentState,runtime: Runtime[DataAgentContext]):
    """召回和用户问题语义相关的字段元数据"""

    writer = runtime.stream_writer
    step = "召回字段信息"
    writer({"type":"progress","step":step,"status":"running"})

    try:
        #state保存部内业务中间结果：原始问题河上游抽取出的关键词
        keywords = state["keywords"]
        query = state["query"]
        #context保存外部运行时工具：向量仓储和Embedding客户端
        column_qdrant_repository = runtime.context["column_qdrant_repository"]
        embedding_client = runtime.context["embedding_client"]

        #用LLM把用户问题扩展成“语义字段”列表，例如“销售总额”可扩展出“销售金额”
        prompt = PromptTemplate(
            template=load_prompt("extend_keywords_for_column_recall"),
            input_variables = ["query"],
        )
        #提示词要求模型只输出JSON数组，解析后result就是list[str]
        output_parser = JsonOutputParser()
        chain = prompt | llm | output_parser

        result = await chain.ainvoke({"query": query})

        #原始关键词和LLM扩展词一起参与找回，set去重，避免重复请求同一关键词
        keywords = set(keywords+result)

        #用字段id做唯一键，因为多个关键词，统一字段的多个向量点都可能命中同一个字段
        column_info_map: dict[str,ColumnInfo] = {}
        for keyword in keywords:
            #查询词必须先转成向量，才能和第9章写入qDrant的字段向量做相似度检索
            embedding = await embedding_client.aembed_query(keyword)
            current_column_infos: list[
                ColumnInfo
            ] = await column_qdrant_repository.search(embedding)
            for column_info in current_column_infos:
                if column_info.id not in column_info_map:
                    column_info_map[column_info.id] = column_info

        #写回state的是去重后的ColumnInfo列表，不暴露Qdrant原始point结构
        retrieved_column_infos: list[ColumnInfo] = list(column_info_map.values())
        logger.info(f"检索到字段信息：{list(column_info_map.keys())}")
        writer({"type":"progress","step":step,"status":"success"})
        return {"retrieved_column_infos": retrieved_column_infos}
    except Exception as e:
        logger.error(f"{step}failed: {e}")
        writer({"type":"progress","step":step,"status":"error"})
        raise



