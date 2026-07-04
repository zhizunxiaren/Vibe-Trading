# Industry-Research Skill — 审查问题清单

> 审查日期: 2026-06-09 | 修复日期: 2026-06-09
> 涉及文件: `SKILL.md`, `industry_research_tool.py`, `industry_research_team.yaml`, `swarm_tool.py`

---

## CRITICAL (BLOCK)

### 1. ~~SKILL.md 章节编号严重混乱~~ ✅ 已修复

文件中有 **两个"第二部分"**，还有一个编号为"三点五"的插队章节。已重构为连续编号：

```
第一部分: WBS 分解 + BOM 用量
第二部分: FBS 三层分析
第三部分: 子组件技术方案枚举
第四部分: TRL 成熟度评估
第五部分: 最新技术方案与落地追踪
第六部分: 市场数据
第七部分: 分层输出（已移到输出格式之前）
```

### 2. ~~Swarm 预设的"6维度分析"与 SKILL.md 框架不匹配~~ ✅ 已修复

已将 `industry_research_team.yaml` 的 decomposer agent 分析维度改为与 SKILL.md 对齐：

```
Function（功能）→ Behavior（技术原理）→ Structure（物理实现）
→ TRL（成熟度）→ 落地追踪（最新进展+卡点）→ 市场数据（用量+规模）
```

---

## HIGH (WARN)

### 3. ~~`industry_research_tool.py` 金融中文搜索的查询构造有问题~~ ✅ 已修复

已将 `_search_site()` 改为使用 DDGS `site:` 操作符：`f"site:{site_domain} {query}"`，同时保留 hostname 后过滤作为安全网。`_execute_impl` 中的金融站点查询改为直接使用 `industry` 关键词。

### 4. ~~`_search_site()` 的通用 `except Exception` 吞掉了所有错误~~ ✅ 已处理

`_resolve_ddgs()` 调用位于 `_search_site()` 之外（在 `_execute_impl` 中），因此 `ImportError` 不会在搜索循环中被吞掉。`_search_site` 内部的 try/except 仅针对 DDGS 运行时错误（网络、超时等）——这些错误是可以优雅处理的，记录警告并返回空结果是合理的。

### 5. ~~"谁控制？" 违反了"不写公司名"的铁律~~ ✅ 已修复

已在 SKILL.md 中明确规则：
- `✅ 允许`: "日本供应商主导"、"台湾代工厂垄断"
- `❌ 禁止`: 任何具体公司名称
- `Phase 2` (swarm mapper 阶段) 才允许写公司名

已将 Layer 3 模板和"执行纪律"部分的措辞更新，明确说明这些边界。

---

## MEDIUM (INFO)

### 6. ~~BOM 用量缺少独立的模板小节~~ ✅ 已修复

BOM 用量现在作为"第一部分：WBS 分解 + BOM 用量"下的独立子章节，有清晰的 `### BOM 用量`、`#### 用量标注规则`、`#### 用量推演`、`#### 用量汇总表模板` 标题。

### 7. ~~第四部分（落地追踪）与第三部分（TRL）重叠严重~~ ✅ 已修复

已在"第四部分：TRL 成熟度评估"的开头添加了边界说明：`> TRL只做**评分 + 判断依据**。技术路线的动态追踪（时间线、卡点、量产预测）在第五部分单独处理。`，并在第五部分开头添加了对应边界说明。

### 8. ~~"第六部分: 分层输出"放在了输出格式之后~~ ✅ 已修复

已重新编号为"第七部分：分层输出"，置于"输出格式"章节之前，使其成为方法论流程的自然组成部分。

### 9. ~~`industry_research_tool.py` 缺少 `both` 模式下自定义查询的行为说明~~ ✅ 已修复

已在 `search_mode` 参数的 description 中补充说明："when used with a custom 'query' parameter, the same query text is applied across all sites regardless of type."

### 10. ~~SKILL.md 语气不够统一~~ ✅ 已修复

已在 Layer 3 洞察卡片示例前添加注释：`> 以下为**示例输出格式**，实际使用时按此模板填写：`，明确区分方法论正文和示例输出。

---

## LOW (NOTE)

### 11. ~~缺少工具测试~~ ✅ 已修复

已创建 `agent/tests/test_industry_research_tool.py`，包含 23 个测试用例，覆盖：
- `_days_to_timelimit` 参数化测试（10 个边界值）
- `_search_site` 单元测试（正常过滤 + 异常降级）
- `check_available` 测试
- `execute` 测试：financial_cn / technical_en / both / custom_sites / custom_query / days_and_max_articles / error
- Tool registry 发现测试
- Tool metadata / parameter schema 测试

### 12. ~~Swarm preset 缺少输出文件路径约定~~ ✅ 已修复

已在 `industry_research_team.yaml` 顶部添加 YAML 注释约定，并在每个 task 的 `prompt_template` 中指定了明确的输入/输出路径：

```
output/{industry}_decomposition/
├── full_decomposition.md   ← Decomposer
├── group_a.md / group_b.md / group_c.md
├── global_mapping_a.md / global_mapping_b.md / global_mapping_c.md
└── final_report.md         ← A-Share Synthesizer
```

### 13. ~~Swarm preset 的 `a_stock_synthesizer` 携带了可能不必要的工具~~ ✅ 已修复

已将 `a_stock_synthesizer` 的 tools 从 `[bash, read_file, write_file, load_skill, yfinance, tushare]` 精简为 `[bash, read_file, write_file, load_skill, web_search, read_url, tushare]`（移除了 `yfinance`，新增了搜索相关工具以更好地支持 A股映射任务）。

---

## 已确认的良好实践

- **分层输出设计 (Layer 1-4)** 是该 skill 最出色的特性: 大白话 → 类比 → 洞察卡片 → 完整技术表格
- **100%规则 + 互斥规则** 表述清晰，有正反例
- **终止条件**（4条）客观可验证，避免无限分解
- 工具实现干净: 金融/技术站点分离、security scanning、`check_available()` 优雅降级
- Swarm 的 3 阶段 DAG 流水线架构合理
- `swarm_tool.py` 的关键词匹配覆盖良好（中英文、高置信度 0.9）

---

## 修复摘要

| # | 严重级别 | 问题 | 状态 |
|---|---------|------|------|
| 1 | CRITICAL | SKILL.md 章节编号混乱 | ✅ 已修复 |
| 2 | CRITICAL | Swarm 6维与 SKILL.md 不匹配 | ✅ 已修复 |
| 3 | HIGH | 金融中文搜索查询构造 | ✅ 已修复 |
| 4 | HIGH | 通用 except 吞错 | ✅ 已处理 |
| 5 | HIGH | "谁控制"公司名边界 | ✅ 已修复 |
| 6 | MEDIUM | BOM 模板小节缺失 | ✅ 已修复 |
| 7 | MEDIUM | TRL/落地追踪重叠 | ✅ 已修复 |
| 8 | MEDIUM | 分层输出位置错误 | ✅ 已修复 |
| 9 | MEDIUM | both 模式文档缺失 | ✅ 已修复 |
| 10 | MEDIUM | 语气不统一 | ✅ 已修复 |
| 11 | LOW | 缺少测试 | ✅ 已修复 |
| 12 | LOW | 输出路径约定缺失 | ✅ 已修复 |
| 13 | LOW | synthesizer 工具冗余 | ✅ 已修复 |
