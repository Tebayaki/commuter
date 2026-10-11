# Commuter 通勤路线提醒

通过高德API定时查询上下班驾车路线耗时，通过 Server 酱推送建议，避免拥堵。

## 配置和运行

创建`config.yaml`配置文件。配置中支持使用 `${VAR}` 引用环境变量。

```sh
cp config.example.yaml config.yaml
# 编辑 config.yaml

uv sync
uv run commuter
```

### YAML 配置

`home_point`、`work_point` 和每个途经点都可以用坐标或地址表示。坐标使用 `coordinate: "经度,纬度"`；地址使用 `address`，可选填写 `city` 以提高地址解析准确度。

每个方向可分别配置多条路线。路线耗时相同时，配置列表中靠前的路线胜出。默认只有非第一条路线胜出时推送；设置 `push_when_first_route_win: true` 后，第一条路线胜出也会推送。

```yaml
amap_key: "your-amap-key"
serverchan_key: "your-server-chan-key"
work_time: "09:00"
home_time: "17:00"
workdays: "1,2,3,4,5" # 周一到周五
timezone: Asia/Shanghai

home_point:
  city: 北京
  address: 春明西路(公交站)
work_point:
  city: 北京
  address: 辟才胡同(公交站)

home_to_work_routes:
  - name: 朗清园西站-西单路口东方向
    waypoints:
      - coordinate: 116.742773,39.892519
      - city: 北京
        address: 西单路口东(公交站)
  - name: 胡各庄新村-民族文化宫方向
    waypoints:
      - coordinate: 116.735235,39.910376
      - coordinate: 116.364479,39.907269

work_to_home_routes:
  - name: 春明西路方向
    waypoints:
      - coordinate: 116.752105,39.894796
  - name: 金融街购物中心-通州北关方向
    waypoints:
      - coordinate: 116.361563,39.915619
      - city: 北京
        address: 通州北关(地铁站)

push_when_first_route_win: false
```

## Docker 部署
```sh
docker run -d --rm --env-file .env \
  -v "$PWD/config.yaml:/app/config.yaml:ro" \
  --name commuter tebayaki/commuter:latest
```

执行一次查询：

```sh
docker run --rm --env-file .env \
  -v "$PWD/config.yaml:/app/config.yaml:ro" \
  tebayaki/commuter:latest commuter-once
```

### docker compose

```yaml
services:
  commuter:
    image: tebayaki/commuter:latest
    container_name: commuter
    volumes:
      - ./config.yaml:/app/config.yaml:ro
    restart: unless-stopped
```

也可以在克隆项目后自行构建：

```sh
docker compose up -d --build
```
