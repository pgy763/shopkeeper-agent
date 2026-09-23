"""
SQL 校验节点

负责在真正执行查询前，用数据库解析一次生成的 SQ
校验结果不在这里决定流程走向，而是通过 state["error"] 交给 graph.py 的条件边判断
"""

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.clients.mysql_client_manager import dw_mysql_client_manager
from app.core.log import logger
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository

async def validate_sql(state: DataAgentState,runtime: Runtime[DataAgentContext]):
    """校验SQL，并返回error字段控制后续条件分支"""
    writer = runtime.stream_writer
    step = "校验SQL"
    writer({"type":"progress","step":step,"status":"running"})

    try:
        #读取generate_sql或correct_sql写入状态的候选SQL
        sql = state["sql"]

        #SQL可用性必须交给真实数仓判断，这里从运行时上下文去DW Repository
        dw_mysql_repository: DWMySQLRepository = runtime.context["dw_mysql_repository"]

        try:
            await dw_mysql_repository.validate(sql)
            writer({"type":"progress","step":step,"status":"success"})
            logger.info("SQL语法正确")
            return {"error":None}
        except Exception as e:
            logger.error(f"SQL语法错误: {e}")
            writer({"type":"progress","step":step,"status":"success"})
            return {"error":str(e)}

    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer({"type":"progress","step":step,"status":"error"})
        raise

