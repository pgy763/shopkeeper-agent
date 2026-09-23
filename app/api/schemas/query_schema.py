from pydantic import BaseModel

class QuerySchema(BaseModel):
    #前端请求体中的query字段
    query: str