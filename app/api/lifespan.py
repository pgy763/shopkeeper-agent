from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.clients.embedding_client_manager import embedding_client_manager
from app.clients.es_client_manager import es_client_manager
from app.clients.mysql_client_manager import (
    dw_mysql_client_manager,
    meta_mysql_client_manager,
)
from app.clients.qdrant_client_manager import qdrant_client_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """管理应用启动和关闭两个阶段的外部资源"""

    #启动阶段，先建立各类外部服务客户端，后续依赖函数会从manager中取已初始化对象
    qdrant_client_manager.init()
    embedding_client_manager.init()
    es_client_manager.init()
    meta_mysql_client_manager.init()
    dw_mysql_client_manager.init()

    #yield之前是启动逻辑，yield之后是关闭逻辑，中间阶段由FastAPI正常处理请求
    yield

    #关闭阶段：统一释放外部链接，避免进程退出前留下未关闭的网络连接
    await qdrant_client_manager.close()
    await dw_mysql_client_manager.close()
    await es_client_manager.close()
    await meta_mysql_client_manager.close()