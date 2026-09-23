"""
电商问数Agent使用的大模型实例

集中初始化一个openai兼容地chatModel
"""

from langchain.chat_models import init_chat_model
from openai import base_url

from app.conf.app_config import app_config

llm = init_chat_model(
    model = app_config.llm.model_name,
    model_provider="openai",
    base_url=app_config.llm.base_url,
    api_key=app_config.llm.api_key,
    temperature=0,
)

if __name__=="__main__":
    print(llm.invoke("你好").content)