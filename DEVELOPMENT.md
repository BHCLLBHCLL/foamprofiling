# 开发文档：Profiling 工具算法实现原理

本文说明 `pyqt_profiling_tool.py` 的核心算法设计与实现逻辑，重点解释：

- 如何在 `controlDict` 中稳定写入 profiling 配置
- 如何把“配置动作”和“运行后扫描”统一建模为历史快照
- 如何把历史快照映射为表格与曲线可视化

## 1. 设计目标与约束

### 1.1 目标

- 支持对“当前算例”快速配置 profiling 参数
- 不破坏 `controlDict` 现有内容和用户手工配置
- 运行后可回溯每次 profiling 配置状态
- 低耦合：即使没有 `matplotlib`，核心功能仍可用

### 1.2 约束

- OpenFOAM 配置文件是文本格式，不能依赖完整语法树解析器
- 算例目录可随时切换，历史记录必须按算例隔离
- 日志格式不完全固定，只能使用鲁棒的关键字扫描策略

## 2. 整体架构

工具采用“UI 层 + 领域模型层 + 文件适配层 + 可视化层”的轻量分层：

- `ProfilingConfig`：领域数据模型（一次配置快照）
- `ProfilingTool`：主窗口与业务协调器
- `controlDict` 读写逻辑：配置块提取、解析、插入/更新
- 历史持久化：`.foamprofiling_history.json`
- `PlotCanvas`：历史数据可视化（可选）

核心思路是把“配置状态”抽象成不可知来源的统一快照，来源由 `source` 区分：

- `manual`：用户点击应用配置
- `runtime-scan`：用户扫描最新运行日志

## 3. 数据模型算法

### 3.1 快照结构

`ProfilingConfig` 作为最小数据单元，包含：

- 参数域：`enabled`、`interval`、`detail_level`、`output_dir`
- 审计域：`source`、`timestamp`
- 运行关联域：`run_log`、`run_profile_line_count`

### 3.2 统一快照策略

所有操作都转换为同一种快照并追加到 `history`，其优势：

- UI 刷新逻辑统一（表格与曲线只依赖 `history`）
- 持久化格式稳定（JSON 数组，不区分动作类型）
- 后续可扩展（新增字段不会影响既有流程）

## 4. controlDict 写入算法

### 4.1 标记块机制

脚本定义固定边界标记：

- `MARKER_BEGIN`
- `MARKER_END`

写入时只管理标记块内部内容，不修改其他段落。该机制避免了“全文件重写”的风险，保证用户原有配置可保留。

### 4.2 提取算法：`_extract_block`

实现方法：

- 使用正则 `BEGIN(.*?)END`（DOTALL）捕获最小块内容
- 找到则返回块内部文本，找不到返回空串

复杂度：

- 时间复杂度 `O(n)`（`n` 为 `controlDict` 文本长度）
- 空间复杂度 `O(n)`（正则与文本缓存）

### 4.3 解析算法：`_parse_block`

对提取块再做字段级正则匹配：

- `profilingEnabled true|false;`
- `profilingInterval <int>;`
- `profilingDetailLevel "<str>";`
- `profilingOutputDir "<str>";`

策略是“尽力解析 + 默认回退”：

- 某字段匹配失败，不报错，保留 dataclass 默认值
- 可容忍部分字段缺失或手工修改

### 4.4 生成算法：`_build_block`

将 UI 当前状态标准化输出为固定顺序文本块，确保：

- 可读性一致（利于人工 diff）
- 后续解析稳定（字段命名固定）

### 4.5 更新算法：`_upsert_block`

`upsert` 是本工具最关键步骤：

1. 正则查找是否已有标记块
2. 若存在：整块替换（update）
3. 若不存在：追加到文件末尾（insert）

该算法保证了幂等性：同一配置反复应用不会产生重复块。

## 5. 运行后扫描算法

### 5.1 日志选择策略：`_scan_latest_run`

从算例目录匹配 `log*`，按修改时间降序，取最新一个：

- 不要求特定 solver 文件名
- 兼容 `log.simpleFoam`、`log.pimpleFoam` 等命名

### 5.2 关键字匹配策略

对日志全文做大小写不敏感匹配：`.*profil.*`

匹配结果数量作为 `run_profile_line_count`。此设计是“弱结构统计”：

- 优点：通用性强，不依赖版本细节
- 局限：可能把无关单词（含 `profil` 子串）计入

如果需要更精准，可升级为多模式词典或状态机匹配。

## 6. 历史持久化与可视化算法

### 6.1 持久化：`_save_history` / `_load_history`

历史文件路径：`<case_dir>/.foamprofiling_history.json`

保存时策略：

- 仅保留最近 200 条（滑动窗口）
- `dataclass -> dict -> JSON`，易读、易调试、易迁移

加载时策略：

- 全量读取并逐项恢复为 `ProfilingConfig`
- 异常容错：读取失败只记录日志，不中断 UI

### 6.2 表格映射：`_refresh_history_view`

把每条快照映射为一行，固定列：

- timestamp/source/enabled/interval/detail/output/run log

该映射是纯函数式展示，不包含业务计算，因此维护成本低。

### 6.3 曲线映射：`plot_history`

从历史中抽取两个序列：

- `interval` 连续曲线
- `enabled` 二值曲线（1/0）

横轴使用快照序号（而非时间戳）：

- 规避时间解析与时区问题
- 直观反映“第几次配置变更”

## 7. 关键鲁棒性设计

- **可选依赖降级**：无 `matplotlib` 时仅禁用图表，不影响设置与记录
- **文件缺失防护**：`controlDict` 或 `log*` 不存在时给出状态提示，不抛出致命异常
- **跨平台路径**：统一使用 `pathlib.Path`
- **编码容错**：文本读取使用 `errors="ignore"`，降低日志脏字符导致的失败概率

## 8. 可扩展方向

- 支持一键运行 solver 并实时追踪 profiling 指标
- 把日志扫描从关键字计数升级为结构化解析（阶段耗时、函数级耗时）
- 增加“历史对比”视图（任意两次快照字段 diff）
- 导出报告（CSV/HTML）用于批量算例性能回归

## 9. 开发调试建议

- 本地语法检查：`python -m py_compile pyqt_profiling_tool.py`
- 依赖安装：`pip install pyqt5 matplotlib`
- 在含有 `system/controlDict` 的算例目录下启动以验证完整流程
