# S2 实验：GeniOS 工作流内能力探测

> **给 [人]**：每个实验都给了「复制这段 → 粘到哪 → 看什么 → 怎么判」。
> 做完把**实际输出原文**贴回来（截图或复制文字都行），我写进 `docs/findings.md`。
>
> 前提：S1 的最小工作流已经能跑通。三个实验可以**放在同一个工作流里**，用不同的分支或依次替换节点，不必建三个。
>
> ⚠️ 以下对 GeniOS 节点界面的描述是**推测**，我没有任何官方文档。界面和你看到的不一样时，**以你看到的为准，截图给我**。

---

## 实验 A · 大模型节点能否约束 JSON 输出（关闭 Q2）

**为什么重要**：整个抽取链路的成败取决于大模型能不能稳定吐 JSON。如果不能，阶段 3 的全部方案要重写（改成让模型输出标记文本再解析）。

### A-1 基础测试

加一个**大模型节点**，系统提示词粘贴：

```
你是一个严格的 JSON 生成器。只输出 JSON，不要输出任何解释、不要用 markdown 代码块包裹。

输出格式：
{"is_opportunity": true, "confidence": 0.9, "reason": "一句话理由"}

判断下面这段文字是否在描述一个学生可以报名参加的机会（竞赛、讲座、志愿、文体活动等）。
```

用户提示词粘贴：

```
关于举办南开大学第十五届程序设计竞赛的通知

为培养学生算法设计与编程能力，现举办第十五届程序设计竞赛。全校本科生均可报名。
报名时间：10月8日至10月20日。比赛时间：11月2日 9:00-14:00，地点：计算机学院A305。
设一等奖5名、二等奖10名。请登录 https://example.nankai.edu.cn/signup 报名。
```

**看什么**：

1. 输出是不是**纯 JSON**（没有被 ```json 包裹、没有前后废话）？
2. 温度参数在哪里设？能不能设到 0 或最低？
3. 有哪些模型可选？名称分别是什么？

### A-2 加约束（逐个试，试到稳定为止）

按顺序试这几种写法，记录哪种有效：

| 写法 | 内容 |
| --- | --- |
| ① 提示词约束 | 如上（「只输出 JSON」） |
| ② 节点自带开关 | 找找大模型节点配置里有没有「输出格式」「JSON 模式」「结构化输出」之类的开关 |
| ③ 预填开头 | 在**助手消息**或输出前缀里填 `{`，逼模型接着写 |
| ④ few-shot | 在提示词里塞 1 个完整的输入→JSON 例子 |

> 📌 **贴回来**：节点配置界面的截图（尤其是模型选择、温度、输出格式这几项）。

### A-3 复杂结构测试

换一段更长的提示词，要求输出**数组嵌套**结构（阶段 3 大模型 1 的真实形状）：

```
只输出 JSON。判断下面文章里包含几个学生可参与的机会，逐个列出。

格式：
{"is_opportunity": true, "confidence": 0.9, "items": [{"title": "机会名称", "type": "竞赛|学术与学习交流|志愿活动与社会实践|校园文体活动"}]}

文章：
【汇总】本周校园活动一览
1. 数学建模校内选拔赛，10月15日截止报名，全校学生均可参加。
2. 王教授学术讲座《人工智能前沿》，10月9日 19:00，学生活动中心报告厅。
3. 校运动会志愿者招募，需20人，10月12日前报名。
```

**判定**：输出是否严格是 `{"is_opportunity":..., "items":[...]}` 结构、`items` 是数组、`type` 只在 4 个枚举值里选。

### A-4 长度与超时

找一篇**长**的公众号文章（3000 字以上）塞进提示词，看：

- 会不会被截断？
- 有没有报错（超长 / 超时）？
- 单次大概耗时多久？

**Q2 关闭条件**：明确了 ①能否约束 JSON 及**哪种写法可靠**、②可选模型、③长度上限、④超时。

---

## 实验 B · 代码节点能力（关闭 Q3）

**为什么重要**：阶段 3 的三层校验准备放在代码节点里。若它不支持 `datetime`/`re`/`json`，校验就得搬到 gateway 的 `POST /validate`。

### B-1 语言判定

加一个**代码节点**，看它默认让你写什么语言（Python？JavaScript？）。把代码编辑器的**第一行和默认内容**截图给我。

### B-2 库可用性（最关键）

**如果是 Python**，粘贴：

```python
import json
import re
import datetime

src = "报名截止时间：2026年10月20日 17:00，名额：30人，网址 https://a.b/c?d=1"

# json
d = json.loads('{"a": 1, "b": [2, 3]}')

# re
m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", src)
date_ok = m is not None

# datetime
now = datetime.datetime.now()
iso = (now + datetime.timedelta(days=1)).isoformat()
tz = str(getattr(datetime, "timezone", "NO_TIMEZONE"))
has_zoneinfo = True
try:
    from zoneinfo import ZoneInfo
    sh = datetime.datetime.now(ZoneInfo("Asia/Shanghai"))
except Exception as e:
    has_zoneinfo = False
    sh = str(e)

# 正则回退解析（不依赖 dateutil）
if m:
    y, mo, da = int(m.group(1)), int(m.group(2)), int(m.group(3))
    parsed = datetime.date(y, mo, da).isoformat()
else:
    parsed = None

result = {
    "json": d,
    "date_ok": date_ok,
    "iso": iso,
    "tz": tz,
    "has_zoneinfo": has_zoneinfo,
    "shanghai": str(sh),
    "parsed": parsed,
}
print(json.dumps(result, ensure_ascii=False))
```

**如果是 JavaScript**，告诉我，我改写成 JS 版本再给你。

**看什么**：逐个 import 是否报错；`has_zoneinfo` 是 True 还是 False；输出里有没有 `parsed` 和 ISO 时间。

> 📌 **贴回来**：**完整的控制台输出或报错原文**。这是判断校验放哪里的唯一依据。

### B-3 出网能力

在代码节点里试：

```python
try:
    import urllib.request
    with urllib.request.urlopen("https://open.feishu.cn/", timeout=5) as r:
        net = r.status
except Exception as e:
    net = f"FAILED: {type(e).__name__}: {e}"
print(net)
```

**判定**：能出网 → 代码节点可做后备推送；不能 → 推送只能靠 HTTP 节点或插件（**不影响校验**，校验是纯计算）。

### B-4 超时与输入输出

- 代码节点能不能同时**接收上游变量**、**输出多个字段**给下游？（截图配置界面）
- 给个 `time.sleep(30)` 试试，看多久超时。

**Q3 关闭条件**：明确 ①语言 ②可用库（重点是 `json`/`re`/`datetime`/`zoneinfo`）③超时 ④能否出网 ⑤输入输出变量怎么配。

**分岔**：
- `json`+`re`+`datetime` 都有 → 三层校验放在代码节点（方案 A）
- 缺 `zoneinfo` → 时区用固定 `+08:00` 偏移手算（中国无夏令时，安全）
- 连 `re`/`datetime` 都没有 → 校验搬到 gateway `POST /validate`（方案 B，我来写）

---

## 实验 C · HTTP 请求节点出网（关闭 Q4）

与 S5 步骤 5.4 重叠，做一次即可。

### C-1 打我们的 gateway

```
POST <你的公网URL>/_debug/echo
Content-Type: application/json
{"from":"genios","ts":"test"}
```

### C-2 打飞书

```
POST https://open.feishu.cn/open-apis/bot/v2/hook/aaaaaaaa-0000-0000-0000-000000000000
Content-Type: application/json
{"msg_type":"text","content":{"text":"genios http node test"}}
```

（这是**假路径**，只为测连通性。）

**判定矩阵**：

| gateway | 飞书 | 结论 |
| --- | --- | --- |
| 通 | 通 | 🎉 最理想：回写 + 推送都走 HTTP 节点 |
| 通 | 不通 | 回写走 HTTP，推送走飞书插件 |
| 不通 | 通 | HTTP 节点有域名白名单/有限出网 → 深挖原因 |
| 不通 | 不通 | **关键分岔**：HTTP 节点没出网能力，架构要重做 |

### C-3 其他要点

- 能不能读**上游变量**填进 URL / Header / Body？（截图配置界面）
- 能不能设**超时**和**重试**？
- 响应体能被下游节点读到吗？

> 📌 **贴回来**：HTTP 节点配置界面截图 + 两次请求的实际结果。

---

## 做完之后

把三份结果贴回来，我会：

1. 写进 `docs/findings.md`，关闭 Q2/Q3/Q4
2. 据 Q3 决定三层校验放代码节点还是 gateway `POST /validate`
3. 据 Q4 决定回写与推送走哪条路
4. 开始写 `genios/schemas/` 与 `genios/prompts/`（**前提是两份 .docx 已放入 `docs/`**）
