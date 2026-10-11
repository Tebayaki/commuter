# Commuter 通勤路线提醒

定时查询上班（家到公司）和下班（公司到家）的高德驾车路线。支持**常走路线A**和**备用路线B**，当B路线预计比A路线更快时，通过 Server 酱推送建议以避免拥堵。

## 配置和运行

复制 `.env.example` 为 `.env`，并填写配置项：  
| 配置项 | 说明 | 默认值 | 示例 |
|---|---|---|---|
| `AMAP_KEY` | 高德开放平台申请的KEY | 必填 | \ |
| `SERVERCHAN_KEY` | Server Chan3申请的KEY | 必填 | \ |
| `HOME_POINT` | 家的坐标 | 必填 | 116.397463,39.909187 |
| `WORK_POINT` | 公司坐标 | 必填 | 116.397463,39.909187 |
| `HOME_TO_WORK_WAYPOINTS_A` | 家到公司路线A（常走路线）的途径点坐标，可设多个，用分号分隔 | 必填 | 121.320081,31.193964;121.324443,31.194055 |
| `HOME_TO_WORK_WAYPOINTS_B` | 家到公司路线B（备用路线）的途径点坐标，可设多个，用分号分隔 | 必填 | 121.320081,31.193964;121.324443,31.194055 |
| `WORK_TO_HOME_WAYPOINTS_A` | 公司到家路线A（常走路线）的途径点坐标，可设多个，用分号分隔 | 必填 | 121.320081,31.193964;121.324443,31.194055 |
| `WORK_TO_HOME_WAYPOINTS_B` | 公司到家路线B（备用路线）的途径点坐标，可设多个，用分号分隔 | 必填 | 121.320081,31.193964;121.324443,31.194055 |
| `WORK_TIME` | 上班时间，该时间查询上班路线，格式为"HH:MM" | 选填 | 9:00 |
| `HOME_TIME` | 下班时间，该时间查询下班路线，格式为"HH:MM" | 选填 | 17:00 |
| `WORK_DAY` | 工作日，格式为逗号分隔的`1,2,3,4,5,6,7`，分别表示周一到周日 | 选填 | 1,2,3,4,5 |
| `TIMEZONE` | 调度器时区 | 选填 | Asia/Shanghai |

坐标可通过https://www.amap.com/ssr/coordinate-picker查询

```sh
cp .env.example .env
# 编辑 .env，填写你的配置

uv sync
uv run commuter
```

需要立即查询并推送上班、下班两方向的路线建议（不论 A 或 B 路线更快），运行：

```sh
uv run commuter-once
```

## Docker 部署

```sh
cp .env.example .env
# 编辑 .env，填写密钥、坐标、时间和工作日
docker compose up -d --build
```

容器内执行一次查询：

```sh
docker compose run --rm commuter commuter-once
```
