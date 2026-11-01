# 接口说明

只有一个接口，但它同时是「普通请求」和「流式响应」，所以单独写一篇。

## 契约

| 项 | 值 |
| --- | --- |
| 方法 / 路径 | `POST /api/query` |
| 请求体 | `application/json`，模型 `QuerySchema` |
| 响应 | `text/event-stream`（SSE），**不会**返回 JSON 对象 |
| 鉴权 | 无 |
| 并发限制 | 无（本地演示项目，见 [已知限制](limitations.md)） |

请求体只有一个字段：

```json
{ "query": "统计 2025 年第一季度各大区的 GMV，并按 GMV 从高到低排序" }
```

字段没有长度校验 —— 传空字符串不会报 422，而是会让整条链路在「关键词为空」的状态下继续跑，最后大概率返回空结果或让模型瞎猜。客户端应该先拦一道。

## 事件格式

每一行 `data: {json}`，事件之间用**两个换行**分隔（SSE 规范）。JSON 由 `json.dumps(..., ensure_ascii=False, default=str)` 生成，所以中文进度文案不会被转义成 `\uXXXX`。

三种事件：

### `progress`

```json
{"type":"progress","step":"生成SQL","status":"running"}
```

`status` 只有三个值：`running` / `success` / `error`。

完整的步骤序列（按图的执行顺序，并行的三步会交错到达）：

```
抽取关键词
召回字段信息 · 召回字段取值 · 召回指标信息
合并召回信息
过滤表信息 · 过滤指标信息
添加额外上下文
生成SQL
校验SQL
校正SQL          ← 仅当校验失败时出现
执行SQL
```

### `result`

```json
{"type":"result","data":[{"region_name":"华东","gmv":"1234567.89"}]}
```

`data` 是 `list[dict]`，列名直接来自 SQL 结果。**金额等数值可能以字符串返回**（MySQL `DECIMAL` 经 `default=str` 序列化），前端渲染前要自己转。

### `error`

```json
{"type":"error","message":"..."}
```

`message` 是异常原文（`str(e)`）。这类事件之后流会结束，不会再出现 `result`。

## 一个容易误判的点

`校验SQL` 这个步骤**语法错误时也会上报 `success`**：

```python
# app/agent/nodes/validate_sql.py
try:
    await dw_mysql_repository.validate(sql)
    writer({"type":"progress","step":step,"status":"success"})
    return {"error": None}
except Exception as e:
    writer({"type":"progress","step":step,"status":"success"})   # ← 仍是 success
    return {"error": str(e)}
```

因为「校验这个动作」本身成功了，失败的是被校验的 SQL。流程会转去 `校正SQL`。

**所以前端不能把「校验SQL success」当作「SQL 正确」**，终态只看 `result` 或 `error`。

## 客户端示例

### curl

```bash
curl -N -X POST http://127.0.0.1:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"query":"统计 2025 年 3 月各商品品类的销量和销售额"}'
```

`-N` 关掉 curl 自己的输出缓冲，否则你会以为服务端在卡。

### TypeScript（fetch + ReadableStream）

```ts
const resp = await fetch("/api/query", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ query }),
});

const reader = resp.body!.getReader();
const decoder = new TextDecoder();
let buf = "";

for (;;) {
  const { done, value } = await reader.read();
  if (done) break;
  buf += decoder.decode(value, { stream: true });

  // 可能一次读到半个事件，也可能读到多个，所以按分隔符切、留尾巴
  const parts = buf.split("\n\n");
  buf = parts.pop() ?? "";
  for (const part of parts) {
    const line = part.trim();
    if (!line.startsWith("data:")) continue;
    try {
      const evt = JSON.parse(line.slice(5).trim());
      // 处理 evt.type
    } catch {
      // 半包/脏数据：丢弃这一条，别让整条链路崩
    }
  }
}
```

关键是三件事：`decoder.decode(value, {stream:true})`（多字节字符可能被切开）、按 `\n\n` 切分、**保留最后一段**。

### Python（httpx）

```python
import httpx, json

with httpx.stream("POST", "http://127.0.0.1:8000/api/query",
                  json={"query": "统计华东地区 2025 年销售额前 5 的商品"},
                  timeout=120) as r:
    for line in r.iter_lines():
        if not line.startswith("data:"):
            continue
        evt = json.loads(line[5:].strip())
        print(evt["type"], evt.get("step", ""))
```

## 超时与断连

- 服务端**没有心跳**。长时间没有 `progress` 事件时（比如模型迟迟不返回首字），中间代理可能认为连接空闲而断开
- 客户端超时建议设 **120 秒**起步：一次完整问数含模型生成 + 可能的纠错，正常在 5–20 秒
- 客户端断开后，服务端不会立刻停止 —— `astream` 还在跑，模型调用照常完成并计费。目前没有做「取消上游」的处理

## 错误速查

| 你看到的 | 说明 |
| --- | --- |
| HTTP 422 | 请求体不是合法 JSON，或缺 `query` 字段 |
| HTTP 500 | 应用启动或中间件异常，看服务端日志 |
| 流里出现 `error` 事件 | 节点抛异常，`message` 是原文 |
| 流正常结束但没有 `result` | 只可能是图跑完却没执行 `run_sql`，检查日志里的节点顺序 |
| 一直无输出 | 模型接口卡住或 key 无效，见 [排查手册](troubleshooting.md) |