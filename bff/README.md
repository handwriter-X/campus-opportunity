# 小程序 BFF · 部署说明

给飞书小程序用的**无状态后端**。只做搬运：飞书开放接口 ↔ 小程序 JSON。

```
小程序 ──HTTPS──▶ 本服务（云端）──HTTPS──▶ 飞书开放平台 ──▶ 多维表格
```

> **它和 gateway 没有任何依赖。** gateway 继续待在校内网跑长连接和轮询；
> 本服务单独部署到云上，**你的电脑关机也不影响评委点链接**。

---

## 1. 本地跑一遍（验证用）

```bash
set -a && . ./.env && set +a
.venv/bin/python -m uvicorn bff.app:app --host 127.0.0.1 --port 8100
```

```bash
curl -s -X POST http://127.0.0.1:8100/v1/activities/list -H 'Content-Type: application/json' -d '{}'
curl -s -X POST http://127.0.0.1:8100/v1/teams/list      -H 'Content-Type: application/json' -d '{}'
```

## 2. 环境变量

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | ✅ | 自建应用，**和小程序同一个 appid**（`cli_aa4ede6a1fb8dbb5`）|
| `BITABLE_APP_TOKEN` | ✅ | 多维表格 base |
| `BITABLE_OPPORTUNITY_TABLE_ID` | ✅ | 【机会汇总】 |
| `BITABLE_REQUEST_TABLE_ID` | ✅ | 【组队需求】 |
| `BITABLE_INVITE_TABLE_ID` | ✅ | 【邀请】 |
| `BFF_AGENT_ID` / `BFF_API_KEY` | 建议 | 小程序请求头里带的一对。**不设就是裸奔** |
| `PORT` | | 云平台一般会注入 |

> ⚠️ **`FEISHU_APP_SECRET` 是最高权限凭据。** 部署到云上等于把它交给那个平台，
> 这是必须自己做的取舍。至少：单独建一个只有多维表格权限的应用来跑 BFF 会更干净。

## 3. 部署到云（三选一）

| 平台 | 免费额度 | 国内访问 | 说明 |
| --- | --- | --- | --- |
| **腾讯云 CloudBase 云托管** | 有 | ✅ | 直接传 Dockerfile，最省事 |
| **阿里云函数计算 FC** | 有免费额度 | ✅ | 选「自定义容器」，镜像同上 |
| 任意轻量云服务器 + Docker | ❌（~¥5/月） | ✅ | 最可控 |

```bash
docker build -t campus-bff ./bff
docker run -d -p 8100:8100 --env-file ./bff/.env campus-bff
```

> **不建议 Vercel / Cloudflare Workers** —— 免费、稳定，但**国内经常打不开**。
> 评委点开转圈，比没有还糟。

## 4. 部署完必须做的两件事

### ① 飞书开放平台加白名单

小程序 → 开发配置 → **服务器域名** → 把 BFF 的域名加到 **request 合法域名**。
（必须是 HTTPS，不能是 IP。改完重新打开小程序生效。）

### ② 小程序指向 BFF

`mini/.env.production`：

```bash
TARO_APP_AGENT_BASE_URL=https://你的域名
TARO_APP_AGENT_API_ID=<BFF_AGENT_ID>
TARO_APP_AGENT_API_KEY=<BFF_API_KEY>
```

然后 `npm run build:tt`，在飞书开发者工具里上传并**发布**。

## 5. 接口

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/health` | 健康检查（云平台探活用） |
| POST | `/v1/activities/list` | 【机会汇总】→ 活动列表 |
| POST | `/v1/opportunities/detail` | `{id}` → 单条机会 |
| POST | `/v1/teams/list` | 【组队需求】→ 需求池 |
| POST | `/v1/teams/detail` | `{id}` → 单条需求 |
| POST | `/v1/teams/apply` | `{teamId, message, userCode}` → 写【邀请】表 |

返回统一是 `{"code": 0, "data": …}`；出错是 `{"code": 1, "message": …}`。

`/v1/teams/apply` 里的 `userCode` 是 `Taro.login()` 拿到的 code，
BFF 调 `mina/v2/tokenLoginValidate` 换成 `open_id` —— **和 gateway 用同一套 open_id**，
所以能和【队友画像】里的 `飞书账号` 直接对上。

## 6. 已知限制

- **没有缓存**：每次请求全量读表。几十条数据没问题，上千条要加缓存。
- **申请是"写邀请表"**，发起人还得在飞书里处理。小程序里看不到处理结果。
- **`deadline` 可能为 `null`**：组队需求没有截止时间字段。前端已改成"缺了不丢卡片"。
