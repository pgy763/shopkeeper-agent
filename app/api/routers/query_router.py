from typing import Annotated

from fastapi import APIRouter, Depends
from starlette.responses import StreamingResponse

from app.api.dependencies import get_query_service
from app.api.schemas.query_schema import QuerySchema
from app.services.query_service import QueryService

# 当前模块只负责查询相关接口，后续接口变多时可以继续拆其他router
query_router = APIRouter()


@query_router.post("/api/query")
async def query_handler(
        #FastAPI会把前端JSON请求体自动解析成QuerySchema
        query: QuerySchema,
        # FastAPI 会调用 get_query_service，递归组装它依赖的仓储和客户端
        query_service: Annotated[QueryService,Depends(get_query_service)],
):
        return StreamingResponse(
                # query.query 是用户问题字符串；QueryService.query 返回异步生成器
                query_service.query(query.query),
                media_type="text/event-stream",
        )