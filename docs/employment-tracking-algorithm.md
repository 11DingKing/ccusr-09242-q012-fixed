# 就业成效追踪 — 统计算法分析说明

> 本文档以代码实际实现为准，梳理修读/未修读微专业毕业生的分组逻辑、三大核心指标的分子分母取数、跨届趋势聚合、以及三口径报表的一层层聚合过程。

---

## 一、分组对照数据流图

### 1.1 核心分组函数

分组逻辑集中在 [stats_calculator.py](file:///Users/huangding/Documents/SOLOCODE%203/0614/mbp/zj-00295-gradtrack-5/app/utils/stats_calculator.py) 的 `get_comparison_stats` 和 `get_follow_up_comparison` 两个函数中，分组规则完全一致。

### 1.2 数据流图

```
┌─────────────────────────────────────────────────────────────┐
│                    数据库 graduates 表                        │
│  字段: has_micro_major, micro_major_id,                     │
│        graduation_year, college_id,                         │
│        destination_status, destination_type,                │
│        is_aligned, salary_range ...                         │
└──────────────────────────┬──────────────────────────────────┘
                           │
                  SELECT * FROM graduates
                           │
              ┌────────────┴────────────┐
              │  可选过滤条件（AND 组合）  │
              │  · graduation_year = ?    │
              │  · college_id = ?         │
              └────────────┬────────────┘
                           │
                  全量毕业生集合 all_graduates
                           │
           ┌───────────────┴───────────────┐
           │         分组判断逻辑            │
           │                               │
           │  ┌─ 指定了 micro_major_id？──┐ │
           │  │                           │ │
           │  YES                         NO│
           │  │                           │ │
           ▼  ▼                           ▼ ▼
  ┌─────────────────┐          ┌──────────────────┐
  │  修读组 with_micro│          │  修读组 with_micro │
  │                 │          │                  │
  │  has_micro_major│          │  has_micro_major  │
  │    = True       │          │    = True         │
  │  AND            │          │                  │
  │  micro_major_id │          │  (不限具体微专业)   │
  │    = 指定ID      │          │                  │
  └────────┬────────┘          └────────┬─────────┘
           │                            │
           │                            │
  ┌────────┴────────┐          ┌────────┴─────────┐
  │ 未修读组         │          │ 未修读组           │
  │ without_micro   │          │ without_micro     │
  │                 │          │                  │
  │ has_micro_major │          │ has_micro_major   │
  │    = False      │          │    = False        │
  │                 │          │                  │
  │ (全部未修读过    │          │ (全部未修读过       │
  │  任何微专业的人)  │          │  任何微专业的人)    │
  └────────┬────────┘          └────────┬─────────┘
           │                            │
           └──────────┬─────────────────┘
                      │
                      ▼
          ┌───────────────────────┐
          │  calculate_group_stats │
          │  (分别对两组调用)       │
          │  返回 GroupStats       │
          └───────────┬───────────┘
                      │
                      ▼
          ┌───────────────────────┐
          │  ComparisonStats       │
          │  · with_micro          │
          │  · without_micro       │
          └───────────────────────┘
```

### 1.3 分组规则要点

| 场景 | 修读组 (with_micro) | 未修读组 (without_micro) |
|------|--------------------|-------------------------|
| **指定 micro_major_id** | `has_micro_major=True` **且** `micro_major_id=指定ID` | `has_micro_major=False`（所有未修读任何微专业的人） |
| **未指定 micro_major_id** | `has_micro_major=True`（修读过任意微专业的人） | `has_micro_major=False`（所有未修读任何微专业的人） |

**重要细节**：
- 未修读组的定义始终是 `has_micro_major=False`，即完全没有修读过任何微专业的毕业生
- 当指定了某个微专业ID时，修读组只包含修读了**该特定**微专业的人，而未修读组仍然是**所有**未修读过任何微专业的人——这意味着未修读组不会包含"修读了其他微专业但没修读指定微专业"的毕业生
- 跨届趋势接口（`/trend/{micro_major_id}`）中的分组与此一致，每年独立拆分

---

## 二、三大核心指标的分子分母

所有指标的计算入口均为 [calculate_group_stats](file:///Users/huangding/Documents/SOLOCODE%203/0614/mbp/zj-00295-gradtrack-5/app/utils/stats_calculator.py#L10-L91)，输入为一个毕业生列表，输出为 `GroupStats` 结构。

### 2.1 去向落实率 (`confirmed_rate`)

```
分子 = 毕业生中 destination_status ∈ {CONFIRMED("已落实"), VERIFIED("已核实")} 的人数
分母 = 该组全体毕业生总人数 (total_count)
公式 = (分子 / 分母) × 100，保留2位小数
```

**代码位置**：[stats_calculator.py L28-L33](file:///Users/huangding/Documents/SOLOCODE%203/0614/mbp/zj-00295-gradtrack-5/app/utils/stats_calculator.py#L28-L33)

| 字段 | 枚举值 | 含义 |
|------|--------|------|
| `destination_status` | `PENDING("待登记")` | 尚未登记去向 |
| `destination_status` | `CONFIRMED("已落实")` | ✅ 计入分子 |
| `destination_status` | `CHANGING("变动中")` | 不计入分子 |
| `destination_status` | `VERIFIED("已核实")` | ✅ 计入分子 |

**关键**：分母是该组的**全体毕业生**，不区分去向类型，`CHANGING("变动中")` 和 `PENDING("待登记")` 都在分母中但不计入分子。

### 2.2 对口就业率 (`aligned_rate`)

```
分子 = 毕业生中 destination_type=EMPLOYMENT("就业") 且 is_aligned=True 的人数
分母 = 毕业生中 destination_type=EMPLOYMENT("就业") 的人数
公式 = (分子 / 分母) × 100，保留2位小数（分母为0时返回0.0）
```

**代码位置**：[stats_calculator.py L35-L42](file:///Users/huangding/Documents/SOLOCODE%203/0614/mbp/zj-00295-gradtrack-5/app/utils/stats_calculator.py#L35-L42)

| 字段 | 枚举值 | 含义 |
|------|--------|------|
| `destination_type` | `FURTHER_STUDY("升学")` | 不在分母范围 |
| `destination_type` | `EMPLOYMENT("就业")` | 在分母范围 |
| `destination_type` | `UNDECIDED("待落实")` | 不在分母范围 |
| `is_aligned` | `True` | ✅ 计入分子（前提是 destination_type=EMPLOYMENT） |

**关键**：分母不是全体毕业生，而是**仅就业毕业生**。升学和待落实的人既不在分母也不在分子。

### 2.3 平均起薪 (`avg_salary`)

```
分子 = 所有 salary_range 非 None 的毕业生的薪资中位值之和
分母 = salary_range 非 None 的毕业生人数
公式 = 分子 / 分母，保留1位小数（单位：万元/年）
```

**代码位置**：[stats_calculator.py L44-L52](file:///Users/huangding/Documents/SOLOCODE%203/0614/mbp/zj-00295-gradtrack-5/app/utils/stats_calculator.py#L44-L52)

薪资区间→中位值映射定义在 [salary_utils.py](file:///Users/huangding/Documents/SOLOCODE%203/0614/mbp/zj-00295-gradtrack-5/app/utils/salary_utils.py#L4-L10)：

| salary_range 枚举 | 显示文本 | 中位值（万元/年） |
|-------------------|---------|-----------------|
| `BELOW_6` | 6万以下 | 5.0 |
| `RANGE_6_8` | 6-8万 | 7.0 |
| `RANGE_8_10` | 8-10万 | 9.0 |
| `RANGE_10_15` | 10-15万 | 12.5 |
| `ABOVE_15` | 15万以上 | 17.5 |

**关键**：
- 起薪是**区间数据**，计算时取各区间的中位值做近似
- `salary_range` 为 None 的毕业生**直接排除**，不纳入分母——所以平均起薪的分母可能小于 total_count
- "15万以上"取 17.5 是一个截断假设，实际可能更高

### 2.4 补充指标

除三大核心指标外，`calculate_group_stats` 还计算了三个来自**用人单位回访**表 (`employer_follow_ups`) 的指标：

#### 满意度 (`avg_satisfaction`)

```
分子 = 该组所有回访记录的 satisfaction_score 之和
分母 = 该组 satisfaction_score 非 None 的回访记录数
公式 = 分子 / 分母，保留2位小数
```

- 注意：分母是**回访记录数**而非毕业生人数，一个毕业生有多次回访则多次计入

#### 留任率 (`retention_rate`)

```
对每个毕业生取其最新一次回访记录（按 follow_up_date 最大）
分子 = 最新回访中 is_still_employed=True 的毕业生人数
分母 = 有至少一条回访记录的毕业生人数
公式 = (分子 / 分母) × 100，保留2位小数
```

- 代码位置：[stats_calculator.py L65-L76](file:///Users/huangding/Documents/SOLOCODE%203/0614/mbp/zj-00295-gradtrack-5/app/utils/stats_calculator.py#L65-L76)
- 每个毕业生只取最新一条回访，不会重复计数

#### 回访覆盖数 (`follow_up_count`)

```
值 = 该组所有回访记录的总条数
```

---

## 三、三口径报表指标计算图

三个报表接口定义在 [statistics.py](file:///Users/huangding/Documents/SOLOCODE%203/0614/mbp/zj-00295-gradtrack-5/app/api/statistics.py)，均调用同一个 `calculate_group_stats` 函数，区别在于**传入的毕业生集合不同**。

```
┌──────────────────────────────────────────────────────────────────┐
│                        graduates 表                               │
└───────┬──────────────────────────┬───────────────────────────────┘
        │                          │
        │  ┌───────────────────────┼───────────────────────┐
        │  │                       │                       │
        ▼  ▼                       ▼                       ▼
┌───────────────┐       ┌──────────────────┐      ┌─────────────────┐
│ 按学院口径     │       │ 按微专业口径       │      │ 按届次口径       │
│ /by-college   │       │ /by-micro-major  │      │ /by-year        │
├───────────────┤       ├──────────────────┤      ├─────────────────┤
│               │       │                  │      │                 │
│ 遍历 College  │       │ 第一行：          │      │ 遍历所有         │
│ 表的每个学院   │       │ has_micro_major  │      │ 不同的           │
│               │       │ = False 的       │      │ graduation_year  │
│ 每个学院：     │       │ 全体毕业生        │      │                 │
│ college_id    │       │                  │      │ 每个届次：        │
│ = 该学院ID    │       │ 后续每行：        │      │ graduation_year  │
│ 的全体毕业生   │       │ micro_major_id   │      │ = 该年份的        │
│               │       │ = 该微专业ID     │      │ 全体毕业生        │
│               │       │ AND              │      │                 │
│               │       │ has_micro_major  │      │                 │
│               │       │ = True           │      │                 │
│               │       │ 的毕业生          │      │                 │
└───────┬───────┘       └────────┬─────────┘      └────────┬────────┘
        │                        │                         │
        │                        │                         │
        ▼                        ▼                         ▼
  ┌─────────────────────────────────────────────────────────────┐
  │              calculate_group_stats(graduates)                │
  │                                                             │
  │  输入: 一组毕业生列表                                         │
  │  输出: GroupStats                                            │
  │                                                             │
  │  ┌─────────────────────────────────────────────────────┐    │
  │  │  去向落实率 confirmed_rate                            │    │
  │  │  分子: destination_status ∈ {CONFIRMED, VERIFIED}    │    │
  │  │  分母: 全体毕业生                                      │    │
  │  ├─────────────────────────────────────────────────────┤    │
  │  │  对口就业率 aligned_rate                              │    │
  │  │  分子: destination_type=EMPLOYMENT ∧ is_aligned=True │    │
  │  │  分母: destination_type=EMPLOYMENT                    │    │
  │  ├─────────────────────────────────────────────────────┤    │
  │  │  平均起薪 avg_salary                                  │    │
  │  │  分子: Σ salary_range中位值                           │    │
  │  │  分母: salary_range非None的毕业生数                    │    │
  │  ├─────────────────────────────────────────────────────┤    │
  │  │  满意度 avg_satisfaction                              │    │
  │  │  分子: Σ satisfaction_score                           │    │
  │  │  分母: satisfaction_score非None的回访记录数             │    │
  │  ├─────────────────────────────────────────────────────┤    │
  │  │  留任率 retention_rate                                │    │
  │  │  分子: 最新回访 is_still_employed=True 的毕业生数      │    │
  │  │  分母: 有回访记录的毕业生数                             │    │
  │  └─────────────────────────────────────────────────────┘    │
  └─────────────────────────┬───────────────────────────────────┘
                            │
                            ▼
              ┌─────────────────────────────┐
              │     ReportItem 各行数据       │
              │                             │
              │  · dimension  (口径维度名)    │
              │  · dimension_value (维度值)  │
              │  · total_count              │
              │  · confirmed_rate           │
              │  · aligned_rate             │
              │  · avg_salary_display       │
              │  · avg_satisfaction_display │
              │  · retention_rate_display   │
              │  · follow_up_count          │
              └─────────────────────────────┘
```

### 3.1 按学院口径 `/reports/by-college`

**代码位置**：[statistics.py L164-L192](file:///Users/huangding/Documents/SOLOCODE%203/0614/mbp/zj-00295-gradtrack-5/app/api/statistics.py#L164-L192)

| 步骤 | 操作 |
|------|------|
| 1 | 查询 `College` 表获取所有学院 |
| 2 | 对每个学院，查询 `college_id = 该学院ID` 的**全体毕业生**（含修读和未修读微专业） |
| 3 | 预加载回访记录 (`_eager_load_follow_ups`) |
| 4 | 调用 `calculate_group_stats` 计算该学院全体毕业生的统计指标 |
| 5 | 输出一行 `ReportItem`，`dimension="学院"`，`dimension_value=学院名称` |

**要点**：按学院口径不做修读/未修读分组，每个学院一行，统计对象是该学院所有毕业生。

### 3.2 按微专业口径 `/reports/by-micro-major`

**代码位置**：[statistics.py L195-L241](file:///Users/huangding/Documents/SOLOCODE%203/0614/mbp/zj-00295-gradtrack-5/app/api/statistics.py#L195-L241)

| 步骤 | 操作 |
|------|------|
| 1 | 查询 `has_micro_major=False` 的全体毕业生 → 第一行 "未修读微专业" |
| 2 | 查询 `MicroMajor` 表获取所有微专业 |
| 3 | 对每个微专业，查询 `micro_major_id=该微专业ID AND has_micro_major=True` 的毕业生 |
| 4 | 分别调用 `calculate_group_stats` |
| 5 | 输出行：`dimension="微专业"`，`dimension_value="未修读微专业"` 或 微专业名称 |

**要点**：
- 第一行是所有未修读过任何微专业的毕业生，作为基准对照行
- 后续每行是一个微专业的修读毕业生
- **不存在重叠**：每个毕业生要么在"未修读"行，要么在某个具体微专业行

### 3.3 按届次口径 `/reports/by-year`

**代码位置**：[statistics.py L244-L275](file:///Users/huangding/Documents/SOLOCODE%203/0614/mbp/zj-00295-gradtrack-5/app/api/statistics.py#L244-L275)

| 步骤 | 操作 |
|------|------|
| 1 | 查询 `graduation_year` 的去重值并排序 |
| 2 | 对每个年份，查询 `graduation_year=该年份` 的**全体毕业生** |
| 3 | 预加载回访记录 |
| 4 | 调用 `calculate_group_stats` |
| 5 | 输出行：`dimension="届次"`，`dimension_value="20XX届"` |

**要点**：按届次口径也不做修读/未修读分组，每个年份一行，统计对象是该届全体毕业生。

---

## 四、跨届趋势聚合逻辑

跨届趋势接口：`GET /statistics/trend/{micro_major_id}`

**代码位置**：[statistics.py L81-L161](file:///Users/huangding/Documents/SOLOCODE%203/0614/mbp/zj-00295-gradtrack-5/app/api/statistics.py#L81-L161)

### 4.1 聚合流程

```
┌─────────────────────────────────────────────────────────────┐
│  输入: micro_major_id (路径参数)                              │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 1: 查询所有去重的 graduation_year 并按升序排列           │
│  (来源: graduates 表)                                        │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼ (遍历每个年份)
┌─────────────────────────────────────────────────────────────┐
│  Step 2: 对每个年份，查询该届全体毕业生                        │
│  SELECT * FROM graduates WHERE graduation_year = {year}      │
└──────────────────────────┬──────────────────────────────────┘
                           │
               ┌───────────┴───────────┐
               ▼                       ▼
  ┌────────────────────┐  ┌─────────────────────┐
  │ with_micro         │  │ without_micro       │
  │ has_micro_major=T  │  │ has_micro_major=F   │
  │ AND                │  │                     │
  │ micro_major_id=指定 │  │                     │
  └────────┬───────────┘  └──────────┬──────────┘
           │                         │
           ▼                         ▼
  ┌────────────────────┐  ┌─────────────────────┐
  │ calc_confirmed_rate │  │ calc_confirmed_rate  │
  │ (行内函数，只算     │  │ (行内函数，只算      │
  │  去向落实率)        │  │  去向落实率)         │
  └────────┬───────────┘  └──────────┬──────────┘
           │                         │
           └───────────┬─────────────┘
                       │
                       ▼
  ┌────────────────────────────────────────────────────────────┐
  │  同时调用 calculate_yearly_indicators(db, "micro_major", id)│
  │  → 返回每年该微专业修读生的 confirmed_rate 和 aligned_rate  │
  └──────────────────────────┬─────────────────────────────────┘
                             │
                             ▼
  ┌────────────────────────────────────────────────────────────┐
  │  组装 YearlyTrendItem:                                      │
  │  · year                                                    │
  │  · with_micro_rate    ← 行内函数算出的修读组落实率            │
  │  · without_micro_rate ← 行内函数算出的未修读组落实率          │
  │  · with_micro_count   ← 修读组人数                         │
  │  · without_micro_count← 未修读组人数                        │
  │  · confirmed_rate     ← yearly_indicators 中的落实率        │
  │  · aligned_rate       ← yearly_indicators 中的对口率        │
  │  · has_warning        ← 该年份是否在预警区间内               │
  │  · warning_types      ← 命中的预警类型列表                   │
  └────────────────────────────────────────────────────────────┘
```

### 4.2 关键细节

1. **`with_micro_rate` 与 `confirmed_rate` 的区别**：
   - `with_micro_rate`：由趋势接口内的行内函数 `calc_confirmed_rate` 计算，只算**去向落实率**，只对该年份该微专业修读组
   - `confirmed_rate`：来自 `calculate_yearly_indicators`，该函数调用的是 `calculate_group_stats`，同样只针对该微专业修读组
   - **两者计算逻辑实质相同**（都是 CONFIRMED+VERIFIED 人数 / 总人数），是重复计算

2. **跨届趋势只看落实率和对口率**：不涉及平均起薪的跨届对比

3. **预警叠加**：趋势数据会叠加该微专业在该年份区间内的活跃预警信息

---

## 五、`calculate_yearly_indicators` 详解

**代码位置**：[warning_detector.py L31-L68](file:///Users/huangding/Documents/SOLOCODE%203/0614/mbp/zj-00295-gradtrack-5/app/utils/warning_detector.py#L31-L68)

此函数同时服务于**跨届趋势**和**预警检测**两个场景。

```
输入: target_type ∈ {"micro_major", "college"}, target_id

对每个年份:
  ├── target_type = "micro_major"
  │   → 查询 has_micro_major=True AND micro_major_id=target_id 的毕业生
  │
  ├── target_type = "college"
  │   → 查询 college_id=target_id 的毕业生
  │
  └── 调用 calculate_group_stats(graduates)

输出: [
  { year, confirmed_rate, aligned_rate, total_count, confirmed_count, aligned_count },
  ...
]
```

**与分组对照的区别**：
- 分组对照 (`get_comparison_stats`) 会拆出修读/未修读两组分别计算
- `calculate_yearly_indicators` 只看目标对象本身（微专业修读生或学院全体），不拆组

---

## 六、指标计算速查表

| 指标 | 分子 | 分母 | 数据来源表 | 备注 |
|------|------|------|-----------|------|
| 去向落实率 | `destination_status ∈ {CONFIRMED, VERIFIED}` 的人数 | 全体毕业生 | graduates | 含所有去向状态 |
| 对口就业率 | `destination_type=EMPLOYMENT ∧ is_aligned=True` 的人数 | `destination_type=EMPLOYMENT` 的人数 | graduates | 仅就业毕业生 |
| 平均起薪 | Σ `salary_range` 中位值 | `salary_range ≠ None` 的人数 | graduates | 区间中位值近似 |
| 满意度 | Σ `satisfaction_score` | `satisfaction_score ≠ None` 的回访记录数 | employer_follow_ups | 按记录数非人数 |
| 留任率 | 最新回访 `is_still_employed=True` 的毕业生数 | 有回访记录的毕业生数 | employer_follow_ups | 取每人最新回访 |
| 回访覆盖数 | — | — | employer_follow_ups | 回访记录总条数 |

---

## 七、实现要点与注意事项

1. **薪资是区间而非精确值**：系统存储的是 `SalaryRange` 枚举而非精确薪资，计算平均起薪时用各区间的中位值近似，"15万以上"取 17.5 万是人为设定上限，实际偏差可能较大。

2. **分组对照中"未修读组"始终是全局的**：即使指定了某个微专业ID，未修读组取的仍然是所有 `has_micro_major=False` 的毕业生，而非"修读了其他微专业但没修读指定微专业"的人。修读了其他微专业的人在指定微专业场景下**既不在修读组也不在未修读组**，被排除在对照之外。

3. **三口径报表不做修读/未修读拆分**：按学院和按届次的报表统计的是全体毕业生（含修读和未修读），只有按微专业口径才天然按微专业归属拆行。

4. **回访数据的预加载**：`_eager_load_follow_ups` 函数将回访记录批量查出后挂载到毕业生对象上，避免 N+1 查询，但这意味着计算依赖的是回访表的快照数据。

5. **跨届趋势中 `confirmed_rate` 和 `with_micro_rate` 重复计算**：趋势接口既在行内计算了修读组的落实率 (`with_micro_rate`)，又通过 `calculate_yearly_indicators` 算了一遍 (`confirmed_rate`)，逻辑完全一致，属于冗余。

6. **对口就业率分母可能远小于总人数**：由于分母仅统计 `destination_type=EMPLOYMENT` 的毕业生，升学和待落实的人被排除，在升学率高的学院/微专业中，对口率的分母可能只占总人数的较小比例。
