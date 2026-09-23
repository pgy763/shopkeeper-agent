"""
字段取值召回节点

负责从字段值全文索引中召回候选取值
当用户问题里出现店铺名 类目名 地区名等业务值时，这一步可以帮助定位真实字段和值
实现路径和字段/指标召回不同：关键词扩展 -> Elasticsearch 全文检索 -> ValueInfo 去重
"""

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.state import DataAgentState
from app.core.log import logger
from app.entities.value_info import ValueInfo
from app.prompt.prompt_loader import load_prompt

async def recall_value(state: DataAgentState,runtime: Runtime[DataAgentContext]):
    """召回和用户相关的字段取值"""
    writer = runtime.stream_writer
    step = "召回字段取值"
    writer({"type":"progress","step": step,"status":"running"})

    try:
        #query用于让LLM生成字段值层面的检索词，keywords来自上游通过关键词抽取
        query=state["query"]
        keywords=state["keywords"]
        #字段取值更关注真实文本命中，因此这里走ES，而不是向量检索
        value_es_repository = runtime.context["value_es_repository"]

        #用LLM扩展
        prompt = PromptTemplate(
            template=load_prompt("extend_keywords_for_value_recall"),
            input_variables=["query"],
        )
        output_parser = JsonOutputParser()
        chain = prompt|llm|output_parser

        result =await chain.ainvoke({"query":query})

        keywords = set(keywords+result)

        #用ValueInfo.id去重，避免多个关键词命中同意伊奥字段值记录
        value_infos_map: dict[str,ValueInfo] = {}
        for keyword in keywords:
            current_value_infos: list[ValueInfo] = await value_es_repository.search(
                keyword
            )
            for current_value_info in current_value_infos:
                if current_value_info.id not in value_infos_map:
                    value_infos_map[current_value_info.id] = current_value_info

        retrieved_value_infos: list[ValueInfo] = list(value_infos_map.values())
        logger.info(f"检索到字段取值：{list(value_infos_map.keys())}")
        writer({"type":"progress","step": step,"status":"success"})
        return {"retrieved_value_infos":retrieved_value_infos}
    except Exception as e:
        logger.error(f"{step} failed：{e}")
        writer({"type":"progress","step": step,"status":"error"})
        raise


