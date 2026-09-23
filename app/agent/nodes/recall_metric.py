"""
指标召回节点

负责根据用户问题从指标向量知识库中召回候选指标
它帮助 Agent 把“销售额 转化率 客单价”等业务表达映射到已定义指标
实现路径和字段召回类似：关键词扩展 -> Embedding -> Qdrant 相似度检索 -> MetricInfo 去重
"""

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.state import DataAgentState
from app.core.log import logger
from app.entities.metric_info import MetricInfo
from app.prompt.prompt_loader import load_prompt

async def recall_metric(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    """召回和用户问题语义相关的业务指标"""
    writer = runtime.stream_writer
    step = "召回指标信息"
    writer({"type": "progress","step":step,"status":"running"})

    try:
        #query用于让LLM生成指标层检索词，keywords来自上游的通用关键词抽取
        query = state["query"]
        keywords = state["keywords"]
        #指标找回使用向量检索，需要Embedding客户端和指标qdrant仓储配合
        embedding_client = runtime.context["embedding_client"]
        metric_qdrant_repository = runtime.context["metric_qdrant_repository"]

        #用LLM把扩展
        prompt = PromptTemplate(
            template = load_prompt("extend_keywords_for_metric_recall"),
            input_variables = ["query"],
        )
        output_parser = JsonOutputParser()
        chain = prompt | llm | output_parser

        result = await chain.ainvoke({"query":query})

        keywords = set(keywords+result)

        metric_info_map: dict[str,MetricInfo] = {}
        for keyword in keywords:
            #指标是向量集合，查询词必须先Embedding成query vector
            embedding = await embedding_client.aembed_query(keyword)
            current_metric_infos: list[
                MetricInfo
            ] = await metric_qdrant_repository.search(embedding)
            for metric_info in current_metric_infos:
                if metric_info.id not in metric_info_map:
                    metric_info_map[metric_info.id] = metric_info

        retrieved_metric_infos: list[MetricInfo] = list(metric_info_map.values())
        logger.info(f"检索到指标信息：{list(metric_info_map.keys())}")
        writer({"type": "progress","step":step,"status":"success"})
        return {"retrieved_metric_infos": retrieved_metric_infos}
    except Exception as e:
        logger.error(f"{step} failed：{e}")
        writer({"type": "progress","step":step,"status":"error"})
        raise
