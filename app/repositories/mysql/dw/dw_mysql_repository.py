"""
数仓MYSQL仓储

这一层对应文档里的DW Repository，职责是到真实数仓中补齐配置文件里
没有显示维护的信息，例如字段类型和字段示例值，
Service层只关心“需要哪些信息”，具体怎样查数仓由仓储层统一封装
SQL生成闭环中的数据库环境读取SQL校验和最终哈寻执行也集合放在这里
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

class DWMySQLRepository:
    """负责查询数仓真是表结构和字段样例值"""

    def __init__(self,session: AsyncSession):
        self.session = session

    async def get_column_types(self,table_name: str)->dict[str,str]:
        """查询整张表的字段类型，作为ColumnInfo。type的真是来源"""
        sql = f"show columns from {table_name}"
        result = await self.session.execute(text(sql))
        result_dict = result.mappings().fetchall()
        return {row["Field"]: row["Type"] for row in result_dict}

    async def get_column_values(
            self,table_name: str,column_name: str, limit: int=10
    )->list:
        """抽样查询字段示例值，供元数据入库和后续检索链路复用"""
        sql = f"select distinct {column_name} from {table_name} limit {limit}"
        result = await self.session.execute(text(sql))
        return [row[0] for row in result.fetchall()]

    async def get_db_info(self):
        """读取当前数仓数据库的方言和版本，供SQL生成提示词使用"""
        sql = "select version()"
        result = await self.session.execute(text(sql))
        version = result.scalar()

        #dialect来自SQLAlchemy当前绑定的数据库方言，例如mysql
        dialect = self.session.bind.dialect.name
        return {"dialect": dialect,"version":version}

    async def validate(self,sql: str):
        """校验SQL语法"""
        sql = f"explain {sql}"
        await self.session.execute(text(sql))

    async def run(self,sql:str)->list[dict]:
        """执行SQL语句，并把SQLAchemy的行对象转换成前端更容易消费的字典列表"""
        result= await self.session.execute(text(sql))
        return [dict(row) for row in result.mappings().fetchall()]