# 计算接口

以下资料均为虚构的接口示例，使用时替换为本人确认的输入。

## 单人星盘

```json
{"year":1990,"month":6,"day":10,"hour":12,"minute":0,"birth_place":"北京","gender":"F","time_known":true,"house_system":"placidus","include_minor_aspects":false}
```

## 双人关系盘

```json
{
  "person_a":{"name":"示例A","year":1990,"month":6,"day":10,"hour":12,"minute":0,"birth_place":"北京","gender":"F","time_known":true,"house_system":"placidus"},
  "person_b":{"name":"示例B","year":1992,"month":11,"day":5,"hour":9,"minute":30,"birth_place":"上海","gender":"M","time_known":true,"house_system":"placidus"},
  "event":{"datetime":"2030-06-01 10:00","timezone":"Asia/Shanghai"}
}
```

`event` 可省略。提供时，脚本计算事件时刻七大传统行星与双方本命点之间 2° 内的主要相位。

新疆、西藏出生时间必须确认是北京时间还是当地时间，并通过单人参数中的 `timezone` 明确指定。

## 单人指定事件行运

```json
{
  "person":{"name":"示例A","year":1990,"month":6,"day":10,"hour":12,"minute":0,"birth_place":"北京","gender":"F","time_known":true,"house_system":"placidus"},
  "events":[
    {"label":"事件一","datetime":"2030-06-01 10:00","place":"北京","timezone":"Asia/Shanghai"},
    {"label":"事件二","datetime":"2030-06-02 15:00","place":"上海","timezone":"Asia/Shanghai"}
  ],
  "max_orb":2.0
}
```

`events` 中每个事件必须给当地钟表时间和地点；`timezone` 可省略，由地点解析。脚本输出当时天体位置、事件四轴、天体落入本命宫位，以及行运对本命点的主要相位。该接口只接受一个 `person`，不得用来偷偷做关系分析。
