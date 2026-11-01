# 排查手册

按「你现在看到什么」组织，不按组件组织 —— 出问题时你手上是现象，不是模块名。

## 一、服务起不来

### `docker compose up` 后 elasticsearch 反复重启

```bash
docker logs elasticsearch --tail 50
```

看到插件加载失败或 `FileNotFoundException`，多半是 IK 插件 zip 没放进去：

- 路径必须是 `docker/elasticsearch/plugins/elasticsearch-analysis-ik-8.19.10.zip`
- **版本号必须和 ES 镜像一致**（compose 里是 8.19.10）
- 放好后要 `docker compose up -d --build`，只 `restart` 不会重新构建镜像

### embedding 容器起来就退出

```bash
docker logs embedding --tail 30
```

`MODEL_ID: /models/bge-large-zh-v1.5` 指向 `docker/embedding/bge-large-zh-v1.5/`，这个目录没入库（约 1.3G）。下载后目录里应该能看到：

```
config.json  model.safetensors  tokenizer.json  ...
```

如果只有 `bge-large-zh-v1.5/` 一层套一层（`bge-large-zh-v1.5/bge-large-zh-v1.5/...`），把内层挪出来。

### 后端启动报连不上 MySQL

两个检查点：

1. compose 把 MySQL 映射到宿主机的 **3307**，不是 3306
2. `conf/app_config.yaml` 里 `db_meta.port` 和 `db_dw.port` 都要跟着改

```bash
docker exec -it mysql mysql -udidilili -pdili123 -e "show databases;"
# 应该看到 meta 和 dw
```

没有 `meta` 库说明 `meta.sql` 没执行 —— 它只在数据卷**首次创建**时跑。重建：

```bash
docker compose down -v && docker compose up -d
```

`-v` 会删数据卷，确保你不需要里面的数据。

## 二、问数跑不动

### 一直停在某个步骤，没有任何后续事件

先看服务端日志里 `request_id` 对应的最后一条：

```bash
tail -f logs/*.log | grep <request_id>
```

| 卡在哪 | 大概率原因 |
| --- | --- |
| `抽取关键词` | jieba 首次加载词典（几秒，之后正常）；或 ES/向量库连接超时 |
| `召回字段信息` | TEI 服务不可用 —— `curl localhost:8081/health` |
| `召回字段取值` | ES 不可用或索引不存在 —— `curl localhost:9200/_cat/indices` |
| `生成SQL` | 模型接口慢、key 无效、`base_url` 不通 |
| `执行SQL` | 数仓锁表或 SQL 太慢 |

### 日志里 `LLM_API_KEY` 读成了空

`.env` 必须在**项目根目录**（和 `main.py` 同级）。`python-dotenv` 默认从当前工作目录找，所以用 `uv run uvicorn main:app` 从根目录启动是一次性解决的办法。

验证：

```bash
uv run python -c "from app.conf.app_config import app_config; print(app_config.llm.model_name, len(app_config.llm.api_key or ''))"
```

第二项是 0，就是没读到。

### 报模型调用失败

按顺序排查：

1. `model_name` 和 `base_url` 是否同一家（GLM 的 key 配 DeepSeek 的地址必然 401）
2. 额度是否还在（GLM 的额度耗尽也会报 401，不是 429）
3. 公司网络是否需要代理 —— 这类报错长这样：`SSLHandshakeException: PKIX path building failed`

## 三、结果不对

这是最难的一类，因为没有异常。**按链路顺序逐段确认**，不要一上来就调提示词。

### 第一步：关键词抽对了吗

```bash
uv run python -c "
from app.agent.nodes.extract_keywords import *  # 或临时打日志
"
```

更简单的办法是把日志级别调到 DEBUG，看 `抽取关键词` 节点输出的词表。如果「销售额」被抽成了「销售」「额」，说明 jieba 分词粒度不对 —— 词表里加自定义词，或丰富 `meta_config.yaml` 里的别名。

### 第二步：召回命中了吗

直接打 Qdrant 和 ES 看：

```bash
# 语义召回：先向量化，再检索
curl -s -X POST http://localhost:8081/embed -H "Content-Type: application/json" \
  -d '{"inputs":"收入"}' > /tmp/e.json
# 取值召回
curl -s "http://localhost:9200/value_index/_search" -H "Content-Type: application/json" \
  -d '{"query":{"match":{"value":"华东"}},"size":5}'
```

| 现象 | 判断 |
| --- | --- |
| ES 里搜不到「华东」 | 这个字段 `sync: false`，或取值没同步（重建过但没跑构建脚本） |
| Qdrant 里搜「收入」命中不到 `order_amount` | 别名不够，或 `description` 写得太技术化 |
| 召回命中一堆无关字段 | 阈值太低或 `limit` 太大 |

### 第三步：过滤是不是把对的表删了

`filter_table` / `filter_metric` 都是让模型做二次筛选，**它们也会犯错**。如果召回里有正确字段但最终 SQL 没用上，很可能是被这两步筛掉了。

临时验证办法：把 `app/agent/nodes/filter_table.py` 里的过滤结果打进日志（只改日志，不改逻辑），对比过滤前后。

### 第四步：SQL 本身对不对

`校验SQL` 通过不代表对。`explain` 只校验语法，不校验语义：

- 字段名写错但恰好同名 → 语法通过，结果错
- 指标口径算错（比如把 `sum` 写成 `avg`）→ 语法通过，结果错
- 时间范围理解错（「第一季度」被理解成「2025-01-01 到 2025-03-31」还是「2025 财年 Q1」）→ 语法通过，结果错

把 `generate_sql` 的提示词和最终 SQL 一起打出来看，比读日志猜快得多。

## 四、性能

| 症状 | 定位 | 优化方向 |
| --- | --- | --- |
| 单次问数 > 30 秒 | 看各步骤耗时（日志时间戳相减） | 召回/过滤步骤调 `limit`；模型换更快的小模型 |
| 并发上来就超时 | 模型 API 的 RPM 限制 | 加队列或限流；本地不做并发控制 |
| 第一个请求特别慢 | jieba 加载词典 + TEI 首次推理 | 预热：启动后跑一次空问 |
| ES 检索慢 | 索引没建好或数据量过大 | 检查 `value_index` 的 mapping 是否真的是 IK |

## 五、重建知识库后行为变了

回到 [元数据知识库](metadata.md#重建的正确姿势)：当前实现下，**重复构建不会覆盖旧数据** —— MySQL 会主键冲突、Qdrant 会堆重复点。如果重建后召回出现大量重复字段，就是这个原因。