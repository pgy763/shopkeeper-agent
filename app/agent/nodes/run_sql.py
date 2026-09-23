"""
SQL 执行节点

负责执行最终 SQL，并记录查询结果。
它是当前 SQL 闭环的结束节点，执行完成后流程进入 END。
"""

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.clients.mysql_client_manager import dw_mysql_client_manager
from app.core.log import logger


async def run_sql(state: DataAgentState,runtime: Runtime[DataAgentContext]):
    """执行SQL并产出最终问数结果"""
    writer = runtime.stream_writer
    step = "执行SQL"
    writer({"type": "progress","step": step,"status":"running"})

    try:
        #这里拿到的可能是generate_sql直接通过校验的SQL，也可能是correct_sql覆盖后的SQL
        sql = state["sql"]
        dw_mysql_repository = runtime.context["dw_mysql_repository"]

        result = await dw_mysql_repository.run(sql)
        logger.info(f"SQL执行结果：{result}")
        writer({"type": "progress","step": step,"status":"success"})
        writer({"type":"result","data":result})
    except Exception as e:
        logger.error(f"{step} failed：{e}")
        writer({"type": "progress","step": step,"status":"error"})
        raise
