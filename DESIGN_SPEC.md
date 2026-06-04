# Marcus Scientific WebUI Design Specification

本文件定义 Marcus CT 拟合工具及其衍生应用的统一设计规范。目标是让后续的光谱分析、参数拟合、数据导出或课题组内部工具保持一致的视觉气质、交互方式和信息组织。

## 1. Design Positioning

### 1.1 Product Character

本项目属于科研数据处理与拟合工具，而不是营销页面或展示型网站。界面应当呈现以下特征：

- 精准、克制、可信，优先服务于读数、比较、拟合和导出。
- 布局密度适中，避免大面积装饰、夸张插画和不必要的说明区块。
- 操作路径短，用户打开页面后应直接进入工具本身。
- 图表是核心工作区，参数面板和结果卡片服务于图表判断。

### 1.2 Design Keywords

- Scientific
- Instrument-like
- Dark analytical workspace
- Compact controls
- Clear fitting feedback
- Data-first

## 2. Visual Tokens

### 2.1 Color Palette

当前项目使用暗色科研面板风格。后续应用应优先复用以下色彩变量。

```css
:root {
  color-scheme: dark;
  --bg: #0b0f14;
  --panel: #111821;
  --panel-2: #151d28;
  --sidebar: #0f141b;
  --input: #171d27;
  --control: #151b24;
  --line: #2b3545;
  --grid-line: #303846;
  --zero-line: #3b4658;
  --text: #e8edf5;
  --text-strong: #f8fafc;
  --muted: #9aa8bb;
  --muted-blue: #bdd0ea;
  --primary: #ff4d4f;
  --eqe: #3b82f6;
  --el: #d65a31;
  --success: #a7f3d0;
  --danger: #fecaca;
}
```

Usage rules:

- `--primary` 用于主要动作、激活状态和最重要的操作按钮，例如 `Fit`。
- `--eqe` 固定表示 EQE 数据、区间线和图中 EQE 相关辅助色。
- `--el` 固定表示 EL 数据、区间线和图中 EL 相关辅助色。
- `--success` 只用于成功或中性完成消息。
- `--danger` 只用于错误、失败和需要用户修正的问题。
- 避免为每个模块创建新的主色。衍生应用如有新数据类型，应在 `--eqe` / `--el` 之外增加少量语义色，而不是重建整套色板。

### 2.2 Backgrounds

全局背景使用轻微纵向暗色渐变，保持工作台深度但不形成强装饰。

```css
body {
  background: linear-gradient(180deg, #0b0f14 0%, #101720 42%, #0c1118 100%);
}
```

Panel backgrounds:

- Sidebar: `#0f141b`
- Normal panel: `rgba(17, 24, 33, 0.8)`
- Cards and controls: `#151b24`
- Plot area: `#0f141b`

### 2.3 Typography

字体栈：

```css
font-family: Inter, Segoe UI, Arial, sans-serif;
```

Type scale:

- Page title: `38px`, weight inherited or semibold, letter spacing `0`
- Section title: `18px`, strong text color
- Body/control text: `15-16px`
- Label text: `14px`, muted color
- Helper text: `13-15px`, muted color, line-height `1.55`
- Result values: `21px`, strong color

Rules:

- 不使用负字距。
- 不按视口宽度缩放字体。
- 科学符号、参数名、单位和代码式变量可用 monospace 或 HTML sub/sup 表达，但不要让变量样式压过可读性。

## 3. Layout System

### 3.1 Page Structure

默认使用左侧控制栏 + 右侧主工作区的双栏结构。

```css
.app {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  min-height: 100vh;
}

aside {
  max-height: 100vh;
  overflow: auto;
}

main {
  min-width: 0;
}
```

Recommended spacing:

- Sidebar padding: `18px`
- Main padding: `24px 28px 32px`
- Section vertical rhythm: section title margin `24px 0 12px`
- Control gap: `10-12px`
- Panel padding: `14px`

### 3.2 Information Hierarchy

页面顺序应遵循用户实际工作流：

1. Data: 上传或选择输入数据。
2. View / Mode: 选择拟合模式或视图模式。
3. Ranges: 选择拟合区间。
4. Optimizer / Parameters: 设置物理参数、残差和计算限制。
5. Actions: 执行拟合、保存、刷新。
6. Results: 显示关键拟合参数和诊断结果。
7. Plot: 展示数据点、拟合曲线和可拖拽区间。

### 3.3 Responsive Behavior

衍生应用应至少支持桌面和常见笔记本宽度。若增加移动支持：

- 双栏在窄屏下应折叠为单栏，控制区在图表前。
- 图表高度可以降低，但不得小于 `420px`。
- 按钮和输入控件保持稳定高度，不因文案变长而跳动。

## 4. Component Guidelines

### 4.1 Buttons

Base button:

```css
button {
  height: 38px;
  border-radius: 7px;
  border: 1px solid var(--line);
  background: var(--control);
  color: var(--text);
  font-weight: 650;
  font-size: 15px;
}

button.primary {
  background: var(--primary);
  border-color: var(--primary);
  color: white;
}
```

Rules:

- 页面只保留一个最突出的主按钮，通常是 `Fit`、`Run`、`Analyze` 或 `Calculate`。
- 次要按钮保持暗色描边样式，例如 `Save CSV`、`Refresh`。
- 按钮文案使用短命令式英文；中文应用可使用短动词，例如“拟合”“导出”“刷新”。

### 4.2 Segmented Controls

用于少量互斥模式选择，例如 `EQE` / `EQE + EL`。

Rules:

- 只用于 2-4 个选项。
- 激活态使用 `--primary`。
- 不要用 segmented control 表示普通动作。

### 4.3 Inputs and Selects

Base input:

```css
input,
select {
  height: 42px;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--input);
  color: var(--text);
  padding: 0 10px;
  font-size: 15px;
}
```

Rules:

- 数值输入必须在 label 中带单位，例如 `Temperature T (K)`、`EQE min (nm)`。
- 参数边界使用成组表格布局：参数名、初值、下限、上限、小数位。
- 默认值应来自物理上合理的初始范围，而不是空白。

### 4.4 Dropzones

文件上传区应保持可拖拽、可点击，并用短文本说明当前文件状态。

Rules:

- Dropzone 边框使用虚线， hover 时边框和背景略微变亮。
- 第一行使用强文本说明动作，例如 `Choose or drop EQE CSV`。
- 第二行显示文件状态，例如 `No file loaded` 或文件名。

### 4.5 Panels and Cards

Panel 用于包裹参数编辑器或一组紧密相关控件。Card 仅用于结果摘要。

Rules:

- Border radius 固定在 `8px` 或以下。
- 不要把 card 放进另一个 card。
- 不要把整个页面 section 做成漂浮大卡片。
- 结果卡片应显示一个短标签和一个高对比数值。

### 4.6 Messages

消息区域放在主工作区底部或操作按钮附近。

Rules:

- 成功或普通反馈使用 `--success`。
- 错误反馈使用 `--danger`。
- 错误消息要说明用户下一步可做什么，例如上传文件、调整范围、检查参数边界。

## 5. Plot and Data Visualization

### 5.1 Plot Theme

Plotly 图表应与页面背景一致。

```js
const layout = {
  template: "plotly_dark",
  paper_bgcolor: "#0f141b",
  plot_bgcolor: "#0f141b",
  font: { color: "#e8edf5", size: 15 },
  gridcolor: "#303846"
};
```

Rules:

- 图表区域是主视觉，不要被装饰性元素抢占。
- 图表边框使用 `--line`，圆角不超过 `8px`。
- 默认高度桌面端约 `680px`。
- Hover mode 优先使用 `x unified`，便于同一横坐标比较多个谱线。

### 5.2 Data Colors

Semantic colors:

- EQE data and fit: blue `#3b82f6`
- EL data and fit: orange `#d65a31`
- Fit range bands: 使用对应颜色的低透明度填充，例如 `rgba(59,130,246,0.10)`
- Range boundary lines: 使用对应颜色，`3px` dashed line

Rules:

- 同一物理量在页面、图表、提示文案和导出说明中必须保持同一颜色。
- 新数据通道应先定义语义含义，再定义颜色。

### 5.3 Axis and Labels

Rules:

- 坐标轴标题必须包含单位，例如 `Energy (eV)`、`Wavelength (nm)`。
- 对跨数量级数据使用 log y-axis。
- 对 scientific notation 使用一致格式，例如 `.1e`。
- 图例放在图表上方横向排列，避免遮挡数据。

## 6. Interaction Patterns

### 6.1 Direct Manipulation

拟合区间允许在图中直接拖拽调整，同时同步侧栏数值输入。

Rules:

- 可拖拽线必须有足够强的颜色和线宽。
- 侧栏输入和图中形状必须互相同步。
- 拖拽后的数值应自动 clamp 到有效数据范围。

### 6.2 State Persistence

衍生应用可保存用户设置，但应避免保存临时导出文件名等一次性输入。

Recommended persisted state:

- 输入文件路径或最近上传数据。
- 拟合模式。
- 拟合区间。
- 参数初值和边界。
- 残差类型、最大迭代次数、温度。

Do not persist by default:

- 临时导出文件名前缀。
- 上一次错误消息。
- 未完成上传状态。

### 6.3 Validation

Rules:

- 上传文件后立即验证格式。
- 拟合前验证数据是否存在、范围内点数是否足够、参数边界是否有效。
- 对用户输入做容错清洗，但不能静默产生物理上荒谬的结果。

## 7. Content Style

### 7.1 UI Copy

界面文案应短、直接、任务导向。

Preferred:

- `Fit`
- `Save CSV`
- `Refresh`
- `EQE min (nm)`
- `Max function evaluations`
- `Choose or drop EQE CSV`

Avoid:

- 长段功能介绍放在界面里。
- 营销式标题。
- 含糊按钮，例如 `Submit`、`OK`、`Go`。

### 7.2 Language

当前应用界面使用英文，README 使用中文。后续可以继续采用：

- UI: 英文，便于变量、图表和论文术语一致。
- Documentation: 中文，便于课题组内部使用和维护。

如果衍生应用改为中文 UI，应保持术语一致，不要中英文频繁混排，变量名除外。

## 8. Implementation Checklist

创建新衍生应用或新增页面时，检查以下项目：

- 是否直接进入工具界面，而不是 landing page。
- 是否复用本文件的色彩变量和字体栈。
- 是否保留左侧控制栏 + 右侧图表工作区的主结构。
- 主要动作是否只有一个高强调按钮。
- 数据类型颜色是否有稳定语义。
- 所有数值输入是否有单位。
- 图表背景、网格、字体是否与页面主题一致。
- 结果是否用紧凑卡片展示，而不是长文本解释。
- 错误消息是否明确指出用户可以修正什么。
- 移动或窄屏下是否没有文本溢出、控件重叠或图表不可用。

## 9. Starter CSS Snippet

后续项目可以从以下 CSS 开始，再按具体功能扩展。

```css
:root {
  color-scheme: dark;
  --bg: #0b0f14;
  --panel: #111821;
  --panel-2: #151d28;
  --sidebar: #0f141b;
  --input: #171d27;
  --control: #151b24;
  --line: #2b3545;
  --text: #e8edf5;
  --text-strong: #f8fafc;
  --muted: #9aa8bb;
  --primary: #ff4d4f;
  --eqe: #3b82f6;
  --el: #d65a31;
  --success: #a7f3d0;
  --danger: #fecaca;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  font-family: Inter, Segoe UI, Arial, sans-serif;
  background: linear-gradient(180deg, #0b0f14 0%, #101720 42%, #0c1118 100%);
  color: var(--text);
  font-size: 16px;
}

.app {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  min-height: 100vh;
}

aside {
  border-right: 1px solid var(--line);
  background: var(--sidebar);
  padding: 18px;
  overflow: auto;
  max-height: 100vh;
}

main {
  padding: 24px 28px 32px;
  min-width: 0;
}

button,
input,
select {
  font: inherit;
}

button {
  height: 38px;
  border-radius: 7px;
  border: 1px solid var(--line);
  background: var(--control);
  color: var(--text);
  cursor: pointer;
  font-weight: 650;
  font-size: 15px;
}

button.primary {
  background: var(--primary);
  border-color: var(--primary);
  color: #fff;
}

input,
select {
  width: 100%;
  height: 42px;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--input);
  color: var(--text);
  padding: 0 10px;
  outline: none;
  font-size: 15px;
}
```
