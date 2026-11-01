# 元数据知识库

整个系统最值钱的部分不是那 12 个节点，而是**模型凭什么知道你的表长什么样**。这篇把 `conf/meta_config.yaml` 到三个存储的映射讲清楚。

## 三层存储各存什么

| 存储 | 存什么 | 回答什么问题 | 检索方式 |
| --- | --- | --- | --- |
| Meta MySQL | 表、字段、指标、指标依赖字段 | 「有哪些表？这个字段什么类型？」 | 直接查 |
| Qdrant | 字段 / 指标的向量点 | 「用户说的『收入』最像哪个字段？」 | COSINE 相似度 |
| Elasticsearch | 维度字段的真实取值 | 「『华东』到底是哪个字段的哪个值？」 | IK 分词 + match |

三者的分工原则：**结构化事实查库，语义模糊走向量，取值精确对齐走全文**。

## 配置格式

`conf/meta_config.yaml` 是唯一数据源，改元数据不用改代码。

### 表

```yaml
tables:
  - name: dim_region          # 表名，同时作为 table_info.id
    role: dim                 # fact / dim
    description: 地区维度表，用于描述订单发生的地理区域信息。
    columns: [...]
```

### 字段

```yaml
    columns:
      - name: region_name     # 列名，id = 表名.列名 → dim_region.region_name
        role: dimension       # primary_key / foreign_key / measure / dimension
        description: 订单所属的大区名称，如华东、华南等。
        alias: [地区, 区域, 大区]
        sync: true            # true → 把真实取值写进 ES
```

| 字段 | 必填 | 作用 |
| --- | --- | --- |
| `name` | 是 | 列名，必须和数仓里的真实列名一致（构建时会 `show columns from` 校验） |
| `role` | 是 | 语义角色，写进元数据供提示词参考 |
| `description` | 是 | 会单独生成一个向量点，所以**写得越像人话，召回越好** |
| `alias` | 否 | 业务口语，每个别名一个向量点 |
| `sync` | 否 | 是否同步真实取值。主键、外键、金额这类高基数或敏感的列应为 `false` |

### 指标

```yaml
metrics:
  - name: GMV
    description: 全称 Gross Merchandise Value，表示所有订单的成交金额总和。
    relevant_columns:
      - fact_order.order_amount     # 用「表名.列名」引用
    alias: [成交总额, 订单总额]
```

指标比字段多一层：`relevant_columns` 声明口径依赖哪些列，落到 `column_metric` 表（`column_id` + `metric_id` 联合主键）。

## 构建做了什么

```bash
uv run python -m app.scripts.build_meta_knowledge -c conf/meta_config.yaml
```

`-c` 是必填参数，不传会直接报 argparse 错误。

### 第一步：写 Meta MySQL

`MetaKnowledgeService._save_tables_to_meta_db()`：

1. 表定义 → `table_info`（`id = name`）
2. 从数仓 `show columns from <表>` 取真实字段类型（**类型以数仓为准，不是配置里的**）
3. 从数仓取每个字段的 10 个样例值 → 填进 `column_info.examples`
4. 字段 → `column_info`（`id = 表名.列名`）

### 第二步：字段向量化

一个字段会裂成**多个向量点**：

```
dim_region.region_name        → 向量（精确英文字段名）
订单所属的大区名称，如华东...   → 向量（描述，语义入口）
地区 / 区域 / 大区             → 各一个向量（业务口语）
```

4 个点，payload 都是同一份字段元数据。检索命中任意一个，按 payload 里的 `id` 去重就回到同一个字段。

向量用 TEI + `bge-large-zh-v1.5`（1024 维），**每批 20 条**调一次 `/embed`，避免单次请求过大。

### 第三步：取值写 ES

只处理 `sync: true` 的列：

```sql
select distinct <列> from <表> limit 100000
```

- 上限 10 万条，超出的部分不会进索引
- 文档 id 是 `列id.取值`，例如 `dim_region.region_name.华东` —— 加上列 id 是为了避免两个表的同名列撞车
- 索引 mapping 固定：`value` 用 `ik_max_word` 分词，`column_id` 用 keyword
- 按 20 条一批 bulk 写入

## 检索参数

| 位置 | 参数 | 默认值 | 影响 |
| --- | --- | --- | --- |
| Qdrant 字段检索 | `limit` | 20 | 召回候选字段数 |
| Qdrant 指标检索 | `limit` / `score_threshold` | 20 / 0.6 | 低于 0.6 相似度直接丢弃 |
| ES 取值检索 | `size` / `min_score` | 20 / 0.6 | 同上 |

调参经验：

- **召回为空** → 先降 `score_threshold`（0.6 → 0.45）验证是不是阈值卡掉了，再决定改阈值还是补别名
- **召回太杂、提示词变长** → 降 `limit`，或者加强 `filter_table` / `filter_metric` 的提示词（它们本来就是干这个的）
- 阈值不是越低越好：低于 0.45 时，不相关字段会挤掉真正相关的，反而降低 SQL 正确率

## 重建的正确姿势

**直接重跑会失败，而且会污染向量库。** 按当前实现（`app/services/meta_knowledge_service.py`）：

| 存储 | 重复构建的结果 |
| --- | --- |
| Meta MySQL | `table_info` / `column_info` 主键固定（`表名` / `表名.列名`），第二次 INSERT **主键冲突报错** |
| Qdrant | 向量点 id 是 `uuid.uuid4()`，每次生成新的 → **旧点不会删除**，同一个字段有 N 份，召回结果出现大量重复 |
| Elasticsearch | 文档 id 固定（`列id.取值`）→ 覆盖，天然幂等 |

所以重建前要先清干净：

```bash
# 1. 元数据库：重建表结构（meta.sql 里有 DROP TABLE）
docker exec -i mysql mysql -uroot -pdili123 < docker/mysql/meta.sql

# 2. Qdrant：删掉两个 collection（下次构建会自动重建）
curl -X DELETE http://localhost:6333/collections/column_info_collection
curl -X DELETE http://localhost:6333/collections/metric_info_collection

# 3. ES 可以不清（按 id 覆盖），想清就：
curl -X DELETE http://localhost:9200/value_index
```

然后重新跑构建脚本。

> 这是当前实现的取舍，不是设计意图。更稳的做法是把向量点 id 改成「字段 id + 别名哈希」，这样重建就是纯 upsert。改动很小，但属于代码层，这里只记录现状。

## 怎么验证构建成功

```bash
# 元数据
docker exec -i mysql mysql -uroot -pdili123 -D meta -e "
  select count(*) tables from table_info;
  select count(*) columns_ from column_info;
  select count(*) metrics from metric_info;"

# 向量点数量：约等于「字段数 × (2 + 别名数)」+「指标数 × (2 + 别名数)」
curl -s http://localhost:6333/collections/column_info_collection | grep points_count

# 取值索引
curl -s "http://localhost:9200/value_index/_count"

# 语义召回是否真的能命中
curl -s -X POST http://localhost:8081/embed -H "Content-Type: application/json" \
  -d '{"inputs":"收入"}' | head -c 80
```

最直接的验证还是问一句：「帮我看看收入」，看 `召回字段信息` 之后能不能命中 `order_amount`。