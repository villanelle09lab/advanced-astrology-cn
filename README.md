# advanced-astrology-cn

八字排盘 + 西洋星盘，一套可落地的 Agent Skill。本地 Python 真算，Agent 负责读盘与解读；增强版额外支持**个人事件盘**与**双人关系盘**，并输出带度数、容许度、作用方向的详细中文证据链。

不是"会说八字的提示词壳子"，而是「先算准，再解读」的完整链路。适用 Claude Code，以及其他能读取 `SKILL.md` 并执行本地命令的 Agent 框架。

---

## 它能做什么

- **八字排盘**：历法转换、真太阳时校正、五行十神、大运流年，终端彩色排盘。
- **西洋星盘**：Swiss Ephemeris 计算行星黄经、宫位、相位、庙旺陷落、格局，以及行运 / 二次推运 / 年度小限三条时机线。
- **个人事件盘**：指定日期与地点的精确行运（旅行、考试、求职、搬迁等）。
- **双人关系盘**：跨盘相位、双向宫位叠盘、指定事件行运。
- **本地档案**：命盘存本地 `~/.bazi_skill/profiles/`，可反复追问、长期复盘。

核心原则：**模型不手算四柱、不手估行星度数**。所有数学与历法交给 Python，从根上消灭排盘幻觉。

---

## 安装

推荐路径（与 `SKILL.md` 内部约定一致）：

```bash
git clone https://github.com/villanelle09lab/advanced-astrology-cn.git \
  ~/.claude/skills/advanced-astrology-cn
```

依赖由 skill 首次使用时按 `requirements.txt` 自动安装；也可手动安装：

```bash
pip install -r ~/.claude/skills/advanced-astrology-cn/requirements.txt
```

> 无需下载星历文件：十大行星、月亮交点、莉莉丝、四轴与宫位都用内置解析星历，开箱即用。只有凯龙星需要额外的小行星星历（`seas_18.se1`），缺失时照常出盘并注明。

---

## 使用

直接对 Agent 说"帮我算个八字""看看我的星盘"即可，Agent 会：

1. 收集出生日期、时分、出生地（八字走真太阳时，星盘走钟表时间转 UTC）。
2. 调用脚本算盘，终端展示排盘。
3. 基于 JSON 数据解读，每个结论给证据链。
4. 需要时询问是否存档，建立本地私人档案。

八字与星盘是两套独立体系，术语不混用；用户没指明时 Agent 会先问清要哪套。

---

## 目录结构

```
advanced-astrology-cn/
├── SKILL.md                 # Agent 行为规范与调用约定
├── calculate_bazi.py        # 八字排盘（--json / --pretty）
├── calculate_astro.py       # 西洋星盘（--json / --pretty）
├── store_bazi.py            # 命盘本地存档（save / load / list / delete）
├── scripts/
│   ├── calculate_personal_event.py   # 个人事件行运
│   └── calculate_relationship.py     # 双人关系盘 + 关系事件
├── references/              # 解读协议、计算接口、人物档案模板
├── agents/openai.yaml       # OpenAI / Codex 兼容的 skill 元信息
├── requirements.txt
└── LICENSE
```

---

## 隐私说明

- 命盘只存在**你自己的机器** `~/.bazi_skill/profiles/`，不上传任何服务器。
- `references/known-profiles.md` 是**空模板**，供你本地填写常算的人物；请勿把真实出生资料提交回公开仓库。
- 本仓库不含任何作者或他人的真实命盘数据。

---

## 许可证

**非商用个人使用许可**，详见 [LICENSE](./LICENSE)。

简言之：自己学习、研究、娱乐随意，**禁止任何商业用途**。未经明确授权不得商用、收费分发或商用部署。

---

## 免责声明

本项目仅供技术研究、传统文化学习与娱乐参考，命运掌握在自己手中。星盘不能证明现实动机，占星判断不替代现实决策。
