import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from app.conf.app_config import DBConfig, app_config


class MySQLClientManager:
    def __init__(self,config: DBConfig):
        #Engine是数据库连接层核心对象，底层会维护连接池
        self.engine : AsyncEngine | None = None
        #session_factory用来按需创建新弄的AsyncSession
        self.session_factory = None
        #保存数据库配置，后面拼接链接地址要用
        self.config = config

    def _get_url(self):
        return f"mysql+asyncmy://{self.config.user}:{self.config.password}@{self.config.host}:{self.config.port}/{self.config.database}?charset=utf8mb4"

    def init(self):
        #创建异步Engine,相当于先把“数据库连接能力备好”
        self.engine = create_async_engine(
            self._get_url(),pool_size=10,pool_pre_ping=True
        )
        #基于Engine创建session工厂,后面真正查询数据库时再用session
        self.session_factory = async_sessionmaker(
            self.engine,autoflush=True,expire_on_commit=False
        )
    async def close(self):
        await self.engine.dispose()

#一套连源数据库，一套链接数仓模拟库
meta_mysql_client_manager = MySQLClientManager(app_config.db_meta)
dw_mysql_client_manager = MySQLClientManager(app_config.db_dw)

if __name__== '__main__':
    #这里演示数仓库查询
    dw_mysql_client_manager.init()

    async def test():
        #通过session_factory创建一次数据库绘画
        async with dw_mysql_client_manager.session_factory() as session:
            sql = "select * from fact_order limit 10"
            #text(sql)表示把原生SQL语句交给SQLAlchemy执行
            result = await session.execute(text(sql))


        #mappings().fetchall()会把结果转成“按列明访问”的行对象列表
        rows = result.mappings().fetchall()

        #下面三行只是为了帮助观察返回结果的结构
        print(type(rows))
        print(type(rows[0]))
        print(rows[0]["order_id"])

    asyncio.run(test())
