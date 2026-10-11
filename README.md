# Commuter 通勤路线提醒

定时查询上班（家到公司）和下班（公司到家）的高德驾车路线。支持**常走路线A**和**备用路线B**，当B路线预计比A路线更快时，通过 Server 酱推送建议以避免拥堵。

## 配置和运行

复制 `.env.example` 为 `.env`，并填写配置项：  
| 配置项 | 说明 | 属性 | 示例 |
|---|---|---|---|
| `AMAP_KEY` | 高德开放平台申请的KEY | 必填 | \ |
| `SERVERCHAN_KEY` | Server Chan3申请的KEY | 必填 | \ |
| `HOME_POINT` | 家的位置，填写经纬度坐标或地址 | 必填 | 116.397463,39.909187 或 北京市朝阳区阜通东大街6号 |
| `WORK_POINT` | 公司的位置，填写经纬度坐标或地址 | 必填 | 116.397463,39.909187 或 北京市朝阳区阜通东大街6号 |
| `HOME_TO_WORK_WAYPOINTS_A` | 家到公司路线A（常走路线）的途经点，坐标或地址，可设多个，用分号分隔 | 必填 | 121.320081,31.193964;上海@人民广场 |
| `HOME_TO_WORK_WAYPOINTS_B` | 家到公司路线B（备用路线）的途经点，坐标或地址，可设多个，用分号分隔 | 必填 | 121.320081,31.193964;上海@人民广场 |
| `WORK_TO_HOME_WAYPOINTS_A` | 公司到家路线A（常走路线）的途经点，坐标或地址，可设多个，用分号分隔 | 必填 | 121.320081,31.193964;上海@人民广场 |
| `WORK_TO_HOME_WAYPOINTS_B` | 公司到家路线B（备用路线）的途经点，坐标或地址，可设多个，用分号分隔 | 必填 | 121.320081,31.193964;上海@人民广场 |
| `WORK_TIME` | 上班时间，该时间查询上班路线，格式为"HH:MM" | 选填 | 9:00 |
| `HOME_TIME` | 下班时间，该时间查询下班路线，格式为"HH:MM" | 选填 | 17:00 |
| `WORKDAYS` | 工作日，格式为逗号分隔的`1,2,3,4,5,6,7`，分别表示周一到周日 | 选填 | 1,2,3,4,5 |
| `TIMEZONE` | 调度器时区 | 选填 | Asia/Shanghai |

> TIP: 坐标可通过[坐标拾取\_高德地图](https://www.amap.com/ssr/coordinate-picker)查询

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

### docker run

```sh
docker run -d --rm --env-file .env --name commuter tebayaki/commuter:latest
```

执行一次查询：

```sh
docker run --rm --env-file .env tebayaki/commuter:latest commuter-once
```

### docker compose

```yaml
services:
  commuter:
    image: tebayaki/commuter:latest
    container_name: commuter
    env_file:
      - .env
    restart: unless-stopped
```

或者clone该项目后自行构建:

```sh
docker compose up -d --build
```
