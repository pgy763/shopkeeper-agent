# 已知限制

这个项目是**能跑通的完整链路**，不是生产系统。把边界写清楚，比在 README 里假装没有更有用 —— 下面每一条都对应仓库里的具体位置。

## 安全

**接口没有鉴权。** `/api/query` 对任何能访问端口的人开放，问了就有结果，包括业务数据。

**生成的 SQL 会直接执行。** 全链路只有 `validate_sql` 的 `explain` 做语法校验，它不限制：

- `SELECT *` 拉全表（没有自动加 `LIMIT`）
- 跨库查询（数仓账号有多少权限就能查多少）
- 复杂 JOIN 或笛卡尔积把数仓拖垮

实际防护完全依赖**数仓连接账号的权限**。上线前至少要做三件事：

```sql
-- 1. 只给只读权限
GRANT SELECT ON dw.* TO 'reader'@'%';

-- 2. 强制每条 SQL 带行数上限（应用层加，不是提示词层）
-- 3. 给查询设超时：MySQL 的 max_execution_time
```

**没有租户隔离、没有审计。** 谁问了什么问题，只在日志里，不在库里。

## 正确性

**纠错只有一轮。** `correct_sql` 之后直接进 `run_sql`，不回头再校验。第二轮还错就直接把错误抛给用户。这是刻意的取舍（延迟可预测），但意味着复杂方言问题可能救不回来。

**`校验SQL` 通过 ≠ SQL 正确。** `explain` 只看语法。字段名恰好同名、指标口径写错、时间范围理解错，全都通过。

**没有缓存。** 同一个问题问两次，两次都跑完整链路：关键词、三路召回、两次模型调用。相同问题的重复成本是 100%。

**单轮对话。** 每次请求 `DataAgentState(query=...)` 新建，不带历史。「再按品类拆一下」这种追问不支持。

## 工程

**重建知识库不幂等。**

| 存储 | 重复构建的后果 | 位置 |
| --- | --- | --- |
| Meta MySQL | 主键冲突，构建中途失败 | `meta_knowledge_service._save_tables_to_meta_db` |
| Qdrant | 点 id 是 `uuid.uuid4()`，旧点不删，越堆越多 | `_save_column_info_to_qdrant` |
| Elasticsearch | 文档 id 固定，覆盖，正常 | `_save_value_info_to_es` |

重建流程见 [元数据知识库](metadata.md#重建的正确姿势)。

**客户端断开后不取消上游。** `QueryService.query` 只是 `async for` 消费流，没有监听断连；用户关页面后模型照常跑完、照常计费。

**没有心跳。** 长时间没有事件时（模型首字慢），中间的 Nginx / 负载均衡可能按空闲超时断开。

**`request_id` 只进日志，不回写响应头。** 用户报障时拿不到 id，只能靠时间点翻日志。

**召回阈值硬编码在仓储层默认参数里**（Qdrant / ES 的 `score_threshold=0.6`、`limit=20`），调参要改代码，不能只改配置。

**没有自动化测试，也没有 CI。** 仓库里没有 `tests/`，没有 `.github/workflows/`。改任何一个节点都没有回归保护。

## 配置里值得复核的几处

这几条不是文档问题，是代码/配置的现状，列出来是因为它们会让人踩坑：

| 位置 | 现状 | 影响 |
| --- | --- | --- |
| `conf/app_config.yaml` 的 `es.index_name: data_agent` | 代码里硬编码 `index_name = "value_index"`，这个配置项**没被读取** | 改了不生效，容易误以为索引名可配 |
| `conf/meta_config.yaml` 里 `AOV` 的 `relevant_columns` | 指向 `fact_order.order_quantity`（订单数量） | AOV 应该是金额 ÷ 订单数，这个口径值得确认 |
| `pyproject.toml` 的 `description` | 还是模板占位 `Add your description here` | 打包/发布时显示为空描述 |
| `pyproject.toml` 依赖 `langchain-deepseek` | 实际用 `init_chat_model(model_provider="openai")` | 依赖冗余，容易让人以为默认走 DeepSeek |

按「不改代码」的约定，这些只记录，没有动。

## 如果要继续做，优先级

1. **SQL 安全**：只读账号 + 强制 `LIMIT` + 查询超时 —— 这是上线的前置条件，不是优化项
2. **重建幂等**：向量点 id 改成「字段 id + 别名哈希」，重建变纯 upsert
3. **接口鉴权与限流**：哪怕只是一个静态 token
4. **断连取消**：客户端断开时 `raise asyncio.CancelledError` 或取消 task，省钱
5. **测试**：至少覆盖「元数据构建 → 召回 → 生成 SQL」这条主链，用固定的假数据
6. **多轮**：State 里带 `messages`，`extract_keywords` 结合上一轮改写问题