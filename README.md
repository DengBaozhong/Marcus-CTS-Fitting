# Marcus CT 态拟合 WebUI

这是一个给课题组内部使用的 Marcus 电荷转移态（charge-transfer state, CT state）拟合工具。程序根据外量子效率（EQE）光谱和电致发光（EL）光谱，在 Marcus 电荷转移理论框架下拟合 CT 态能量 `E_CT` 和重组能 `lambda`。

程序提供网页界面，可以上传或读取 CSV 光谱文件，选择拟合区间，设置参数初值和边界，并导出拟合后的数据表。

## 理论基础

在有机光伏、光电探测等体系中，低能区 EQE 尾态和 EL 光谱通常可以反映 CT 态的吸收与辐射复合过程。Marcus 理论将电荷转移过程描述为两个近似谐振势能面之间的跃迁。若 CT 态能量为 `E_CT`，重组能为 `lambda`，温度为 `T`，则吸收和发射对应的 reduced spectra 可写成以能量 `E` 为变量的高斯型表达式。

本程序使用如下能量转换：

```text
E (eV) = 1239.841984 / wavelength (nm)
```

其中 `E` 是光子能量，`wavelength` 是波长。

## 拟合公式

标准 Marcus CT 拟合通常写成如下形式：

```text
EQE(E) * E = A_CT * exp[-(E_CT + lambda - E)^2 / (4 * lambda * k_B * T)]

EL(E) / E  = A_CT * exp[-(E_CT - lambda - E)^2 / (4 * lambda * k_B * T)]
```

其中：

- `E`：光子能量，单位 eV。
- `EQE(E)`：绝对 EQE。
- `EL(E)`：归一化 EL 强度。
- `E_CT`：CT 态能量，单位 eV。
- `lambda`：重组能，单位 eV。
- `A_CT`：强度因子。不同文献中可能会把前因子、归一化常数或跃迁强度写成不同形式，本程序将这些强度相关项统一吸收到 `A_CT` 中。
- `k_B`：玻尔兹曼常数，`8.617333262145e-5 eV/K`。
- `T`：温度，默认 `300 K`。

因此，本程序不直接拟合原始 EQE 和 EL 强度，而是先转换为 reduced spectra：

```text
reduced EQE = EQE_abs(E) * E
reduced EL  = EL_norm(E) / E
```

也就是说，`reduced EQE` 和 `reduced EL` 分别对应上面两个 Marcus 拟合公式的等号左边。程序实际拟合的是：

- `EQE_abs * E` 与吸收 Marcus 高斯项；
- `EL_norm / E` 与发射 Marcus 高斯项。

这里 `EQE_abs` 是绝对 EQE。如果输入 EQE 最大值大于 1，程序会认为数据单位是百分比，并自动除以 100。`EL_norm` 是归一化 EL 强度，程序会自动除以 EL 最大值，使其最大值为 1。

吸收峰中心约位于 `E_CT + lambda`，发射峰中心约位于 `E_CT - lambda`。因此，同时拟合 EQE 和 EL 时，两个谱之间的能量偏移可以帮助约束 `E_CT` 和 `lambda`。

## 拟合参数含义

### `E_CT_eV`

CT 态能量，单位 eV。它是最核心的拟合参数之一，通常用于描述给体/受体界面 CT 态的有效能量位置。

设置建议：

- 初值可以根据 EQE 低能尾或 EL 发射区的大致位置估计。
- 下限和上限应覆盖预期 CT 能量，但不要设置得过宽。
- 常见有机半导体体系中可先尝试 `0.6-1.8 eV`。

### `lambda_eV`

重组能，单位 eV。它描述电荷转移过程中分子和环境构型弛豫带来的能量代价。

设置建议：

- 初值可先使用 `0.1-0.3 eV`。
- 下限必须大于 0。
- 如果拟合得到的 `lambda` 贴近上下限，通常说明拟合区间、数据质量或边界设置需要重新检查。

### `A_CT`

CT 谱带振幅因子，无固定物理单位，主要用于匹配 reduced spectra 的强度尺度。

设置建议：

- 通常不直接解读为材料本征物理量。
- 如果曲线形状合理但强度不匹配，可以检查 `A_CT` 初值和边界。
- 程序会用同一个 `A_CT` 同时描述 EQE 和 EL 的 reduced spectra。

### `temperature_K`

温度，单位 K，默认 `300 K`。温度进入高斯展宽项 `4 * lambda * k_B * T`。

设置建议：

- 室温测试通常使用 `300 K`。
- 如果光谱是在变温条件下测量，应填写实际测试温度。

### `fit_ranges_nm`

拟合波长范围，单位 nm。程序只使用该范围内的数据点计算残差。

设置建议：

- EQE 拟合区间应选取 CT 吸收尾或低能吸收区域，避开主吸收峰、仪器噪声和明显异常点。
- EL 拟合区间应覆盖主要 EL 发射区，避开噪声底部和截断区域。
- 每个拟合区间内至少需要 5 个有效数据点。

### `residual`

残差计算方式：

- `Log`：对数残差，适合跨越多个数量级的 EQE 尾态数据，也是默认设置。
- `Linear`：线性归一化残差，对强信号区域权重更高。

对数残差的形式为：

```text
residual = log10(fit + floor) - log10(data + floor)
```

线性残差的形式为：

```text
residual = (fit - data) / max(abs(data))
```

## 数据格式

输入文件必须是 CSV 文件，至少包含两列。程序只读取前两列：

```text
第一列：波长，单位 nm
第二列：光谱强度
```

示例 EQE 文件：

```csv
Wavelength (nm),EQE (%)
600,84.19
610,83.63
620,83.00
```

示例 EL 文件：

```csv
Wavelength (nm),Normalized EL (a.u.)
700,0.01
710,0.02
720,0.05
```

注意事项：

- 第一列必须是正数波长，单位为 nm。
- 第二列可以有表头，但必须能转换为数字。
- 空值、非数字值和非正波长会被自动忽略。
- EQE 可以输入百分比，例如 `84` 表示 `84%`；也可以输入绝对值，例如 `0.84`。程序会根据最大值是否大于 1 自动判断。
- EL 不需要提前归一化，程序会自动按最大值归一化。
- 建议只保留物理上可信的光谱区域，明显噪声、仪器截断或杂散光区域应避免纳入拟合区间。

## 运行方法

本项目部署在 Render 等支持 Python 后端的网站上运行。打开网页后即可使用，不需要在个人电脑上安装 Python。

### Local Run

普通 Windows 用户可以直接下载 Release 中的便携版压缩包：

1. 打开仓库的 Releases 页面。
2. 下载 `MarcusCT_WebUI_Portable.zip`。
3. 解压压缩包。
4. 双击运行 `start_webui.bat`。
5. 程序会启动本地 WebUI，然后在浏览器中打开使用。

维护者如果需要从源码本地调试，可以在项目目录中运行：

```powershell
python -m pip install -r requirements.txt
python marcus_ct_webui.py
```

然后在浏览器中打开：

```text
http://localhost:8502
```

## 项目结构

当前代码已经从单文件 WebUI 拆分为轻量入口、后端模块和前端静态文件。日常运行命令仍然是：

```powershell
python marcus_ct_webui.py
```

主要文件结构如下：

```text
marcus_ct_webui.py       # 程序入口：解析参数并启动 WebUI 服务

marcus_ct/
  config.py              # 常量、默认设置、路径配置
  settings.py            # 设置读取、保存、迁移和参数清洗
  spectra.py             # CSV 光谱读取、上传文件处理、文件名清洗
  model.py               # Marcus CT 模型、光谱转换和预测曲线
  fitting.py             # least_squares 拟合和残差计算
  payload.py             # Web API 返回给前端的数据结构
  export.py              # 拟合结果表格和 CSV 导出
  server.py              # HTTP Handler、API 路由和静态文件服务

frontend/
  index.html             # WebUI 页面结构
  style.css              # WebUI 样式
  app.js                 # 前端交互、绘图和 API 调用
```

这种拆分的目标是让计算核心、后端接口和前端界面各自独立维护。后续如果需要修改 Marcus 公式或拟合策略，优先查看 `marcus_ct/model.py` 和 `marcus_ct/fitting.py`；如果需要调整界面和交互，优先查看 `frontend/`。

### Deploy As A Persistent Web App

GitHub Pages 只能托管静态网页，不能运行本程序所需的 Python 后端和 `scipy` 拟合过程。因此，本项目需要部署到支持 Python Web Service 的平台，例如 Render、Railway、Fly.io 或 Hugging Face Spaces。

#### Render

1. 将本文件夹推送到 GitHub 仓库。
2. 在 Render 中从该 GitHub 仓库创建一个新的 Web Service。
3. 使用以下配置：
   - Build command: `pip install -r requirements.txt`
   - Start command: `python marcus_ct_webui.py --host 0.0.0.0 --no-browser`
4. 部署完成后，Render 会提供一个可以长期访问的网页链接。

仓库中包含的 `render.yaml` 也可以作为 Render Blueprint 使用。

## 使用流程

1. 打开网页界面。
2. 上传 EQE CSV 文件。
3. 如果选择 `EQE + EL` 模式，同时上传 EL CSV 文件。
4. 选择拟合模式：
   - `EQE`：只拟合 EQE 光谱。
   - `EQE + EL`：同时拟合 EQE 和 EL 光谱，推荐在有可靠 EL 数据时使用。
5. 设置 EQE 和 EL 的拟合波长范围。
6. 设置参数初值、下限和上限。
7. 点击 `Fit` 进行拟合。
8. 检查 reduced spectra 图中的数据点和拟合曲线。
9. 导出 CSV 结果，用于后续作图或记录。

## 导出结果

导出的 CSV 包含：

- 原始 EQE/EL 数据。
- 转换后的能量坐标。
- reduced spectra。
- 拟合曲线。
- 最终拟合参数。

导出结果可用于 Origin、Python、Excel 等软件中重新作图。

## 常见问题

### 为什么 EQE 数据会自动除以 100？

如果 EQE 第二列最大值大于 1，程序会认为输入是百分比，例如 `84` 表示 `84%`，并自动转换为绝对值 `0.84`。

### 为什么 EL 强度和原文件不同？

程序拟合前会将 EL 除以最大值进行归一化，因此图中的 EL 是归一化后的强度。

### 为什么拟合失败或结果贴近边界？

常见原因包括：

- 拟合波长范围内有效点数太少。
- 初值离合理结果太远。
- 参数上下限过窄或过宽。
- 数据中包含主吸收峰、噪声底部、截断区域或异常点。
- EQE 与 EL 数据不是同一器件、同一测试条件或不满足相同 CT 态假设。

### 什么时候只拟合 EQE？

当没有可靠 EL 光谱，或者 EL 光谱明显受其他发光态、噪声或仪器响应影响时，可以选择只拟合 EQE。只拟合 EQE 时，`E_CT` 和 `lambda` 的约束会更弱，结果需要更谨慎解读。

## 附录：便携 Windows 文件夹

如果需要生成一个带独立 Python 运行环境的 Windows 便携版文件夹，可以在维护者电脑上运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_portable_webui.ps1
```

运行完成后，将生成的 `dist\MarcusCT_WebUI_Portable` 文件夹发给同学即可。这个方式适合不能访问网页版本，或者需要在离线电脑上使用程序的情况。

## 附录：设计规范

项目根目录中的 `DESIGN_SPEC.md` 记录了当前 WebUI 的统一设计规范。后续如果基于本项目衍生其它科研拟合、光谱分析或数据导出工具，建议优先复用其中定义的暗色科研面板风格、颜色语义、布局结构、组件规则和图表规范。

核心原则包括：

- 保持左侧控制栏 + 右侧图表工作区的工具型布局。
- 使用暗色分析工作台风格，避免营销式页面和大面积装饰。
- 固定数据颜色语义，例如 EQE 使用蓝色、EL 使用橙色、主操作使用红色。
- 图表、参数、结果和导出操作应服务于同一条拟合工作流。

## 附录：Render 部署配置

本项目已经包含 Render Blueprint 配置文件 `render.yaml`，可用于在 Render 上创建 Python Web Service。

当前线上 WebUI 地址：

```text
https://marcus-cts-fitting.onrender.com/
```

`render.yaml` 中的主要配置如下：

```yaml
services:
  - type: web
    name: marcus-ct-webui
    env: python
    plan: free
    buildCommand: pip install -r requirements.txt
    startCommand: python marcus_ct_webui.py --host 0.0.0.0 --no-browser
```

如果在 Render 控制台中手动创建服务，可以使用同样的配置：

- Service type: `Web Service`
- Environment: `Python`
- Build command: `pip install -r requirements.txt`
- Start command: `python marcus_ct_webui.py --host 0.0.0.0 --no-browser`
- Plan: 可使用 `Free`，也可按访问需求升级。

部署时需要将仓库连接到 Render。Render 会根据 `render.yaml` 或控制台中的设置安装依赖，并运行 `marcus_ct_webui.py` 启动 WebUI。

## License

This project is released under the MIT License. See `LICENSE` for details.
