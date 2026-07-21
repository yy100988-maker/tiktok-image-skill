---
name: image
description: Vetech AI 团队打造的跨境电商与通用领域 AI 图片生成助手，集成 Image2 和 GPT 大模型能力，内置 23 类专业图片生成提示词，支持妙手 ERP 店铺产品清单、图像理解、单张生图、目录批量生图和 Excel/CSV 批量生图。支持 WorkBuddy、Codex、Claude Code 及其他支持 SKILL.md 的 agent。
metadata:
  requires:
    bins: [python]
    anyEnv: [IMG_API_KEY, API_KEY]
---

# 图像技能说明

由 Vetech AI 团队打造的面向跨境电商和通用领域的 AI 图片生成助手，集成 Image2 和 GPT 大模型能力，内置 23 类专业图片生成提示词，支持妙手 ERP 导出的店铺产品清单，并可按国家站点一键批量自动生成电商主图、场景图和详情图，一次性可生成 2000+ 张电商图片。

## 使用前提

- 适用环境：支持 `SKILL.md` 的主流 agent 工具，包括 WorkBuddy、Codex、Claude Code 等。
- 运行环境：Python 3.10+，可执行命令 `python`。
- 服务账号：用户需要自行注册 VTeTech 账号并准备 API key。注册地址：`https://vtetech.com/`
- 必填配置：`IMG_API_KEY` 或 `API_KEY`。不得使用示例 key。
- 默认模型：图像理解使用 `gpt-5.4`，图像生成使用 `gpt-image-2`。
- 配置方式：运行 `python <skill-base>/scripts/configure.py`，或使用环境变量、`--env-file`、`image-config.json`。
- 参考图默认使用 base64 传输，优先使用本地图片转为 base64 后提交。
- 目标国家语言：图片理解和生图会根据 `request.txt` 或 `--requirements` 中的目标国家自动选择图片文案语言；也可以直接写“使用法语/日语/葡萄牙语”等语言要求。
- 不在 提示词、日志、提交内容或 skill 包中暴露 API key 和内部服务地址。

## 多国家语言适配

- 在 `request.txt` 或 Excel/CSV 的 `--requirements` 中写明目标国家，例如“美国 TikTok Shop”“法国 TikTok Shop”“日本站点”或“巴西站点”。
- 图片理解阶段会按目标语言整理商品卖点、场景建议和风险说明，产品包装、品牌名和参考图中的原文按图片事实保留。
- 生图阶段会按目标语言生成画面内文案；没有明确要求文字时，默认不添加文字，避免生成错误语言或乱码。
- 如果只指定语言，也可以直接写“使用法语”“使用日语”“使用葡萄牙语”等，覆盖默认语言。
- 未指定国家或语言时，默认使用中文处理分析和生成提示词；跨境 TikTok Shop 任务应尽量明确目标国家。

支持的主要站点语言包括：

| 站点 | 图片文案语言 |
|---|---|
| 马来西亚 | Malay（马来语） |
| 越南 | Vietnamese（越南语） |
| 新加坡、菲律宾、英国、美国、加拿大、澳大利亚、新西兰、南非 | English（英语） |
| 泰国 | Thai（泰语） |
| 法国 | French（法语） |
| 西班牙、墨西哥、智利、哥伦比亚、秘鲁、阿根廷 | Spanish（西班牙语） |
| 德国 | German（德语） |
| 意大利 | Italian（意大利语） |
| 荷兰 | Dutch（荷兰语） |
| 波兰 | Polish（波兰语） |
| 日本 | Japanese（日语） |
| 韩国 | Korean（韩语） |
| 巴西、葡萄牙 | Portuguese（葡萄牙语） |
| 土耳其 | Turkish（土耳其语） |
| 沙特、阿联酋 | Arabic（阿拉伯语） |

## 使用流程

1. 识别任务：判断是图像理解、提示词生成、单张生图、目录批量，还是 Excel/CSV 批量。
2. 读取参考图：优先主图，再补 SKU 图或局部图；单个商品任务最多使用 10 张参考图。
3. 匹配模板：从 `references/templates/` 选择最匹配的模板，再参考 `references/style-library.md` 和 `references/template-guide-zh.md`。
4. 组装 提示词：只保留主体、构图、材质、光线、文字、比例和负面约束等有效信息。
5. 先 dry-run：检查输入文件、商品数量、参考图数量、输出目录和任务计划。
6. 调用脚本：由 agent 调用对应 Python 入口完成提交、轮询、下载和日志保存。
7. 结果检查：确认产品结构、SKU 一致性、文字可读性、比例和输出文件是否正确。

## GPT-Image2 提示词库

本提示词库用于根据用户的产品类型、使用场景和视觉目标选择模板，并生成简洁、可执行的中文生图提示词。先匹配图片类别，再匹配风格和场景，最后补充主体、构图、材质、光线、文字、比例及禁止项。

### 电商图片

| 用户意图 | 模板 |
|---|---|
| 白底主图、商品主图、packshot | `01-hero-image.json` |
| 生活方式、使用场景 | `02-lifestyle-scene.json` |
| 平铺、俯拍 | `03-flat-lay.json` |
| 细节、微距、材质特写 | `04-detail-macro.json` |
| 海报、Banner、促销图 | `05-poster-banner.json` |
| 社交媒体、种草图 | `06-social-media.json` |
| UGC、买家秀、真实使用 | `07-ugc-style.json` |
| 模特展示、人物佩戴 | `08-model-showcase.json` |
| 前后对比 | `09-before-after.json` |
| 包装、礼盒、开箱 | `10-packaging.json` |
| 信息图、A+、详情页 | `11-infographic.json` |
| 创意概念图 | `12-creative-concept.json` |
| 尺寸、规格、步骤 | `13-size-spec.json` |
| 套装、多产品组合 | `14-multi-product.json` |
| 直播画面 | `15-livestream.json` |
| 试穿、试用、融入场景 | `16-try-on-virtual.json` |
| 爆炸图、内部结构 | `17-exploded-view.json` |
| 隐形模特、服装展示 | `18-ghost-mannequin.json` |
| 多角度、多色网格 | `19-multi-angle-grid.json` |
| 杂志大片、封面 | `20-magazine-editorial.json` |
| 季节营销、营销活动 | `21-seasonal-campaign.json` |
| 奢华氛围、烟雾、质感 | `22-luxury-atmospherics.json` |
| 设备模型、App、软件服务、UI | `23-device-mockup.json` |
| 店铺、门面、实体空间 | `24-storefront.json` |
| 运动、健身、户外 | `25-sports-campaign.json` |

### 提示词必备字段

```text
目标：这张图用于什么渠道和任务
主体：产品、人物、场景或信息主题
参考图事实：必须保持的外形、颜色、材质、配件、比例和结构
构图：视角、景别、主体位置、背景和阅读顺序
风格：摄影、材质、光线、色彩和氛围
文字：必须出现的精确文字；没有文字写“无文字”
规格：比例、尺寸、格式和数量
禁止：乱码、虚构功能、改款、错误结构、collage、grid、multi-panel
```

### 提示词原则

- 参考图存在时，SKU 一致性高于风格创意。
- 用自然语言描述，不堆叠互相冲突的风格词。
- 商品卖点只能来自图像事实；无法确认的功能、材质、尺寸和认证标记为未知。
- 一张请求默认生成一张独立图片，不把整套图片合成拼图。
- UGC、直播和社交图要指定真实手机、自然光、轻微瑕疵和非棚拍构图。
- UI、海报、信息图和文档必须指定准确文字、模块数量和信息层级。

## 单张和小批量生成

单张生成使用：

```powershell
python <skill-base>/scripts/generate_image.py --prompt-file prompt.txt --image reference.jpg --size 1:1 --resolution 1k
```

`request.txt` 示例：

```text
任务：为美国站点生成 1 张女装连衣裙模特展示主图。
目标国家站点：美国，电商商品页。
参考图事实：严格保留参考图中的连衣裙颜色、面料纹理、领口、袖型、腰线和长度，不新增配饰，不改变服装结构。
画面：成年女性模特半身至膝上构图，正面站姿，浅灰色干净室内背景，柔和均匀的商业摄影光线，商品主体清晰，画面简洁高级。
构图：模特位于画面中央，服装完整可见，四周留白，1:1 比例，适合电商主图。
文字：不添加任何文字、Logo、水印或促销信息。
禁止：不要改变颜色和版型，不要生成额外服装，不要出现多余人物、拼图、分栏、畸形手臂、错误肢体或模糊细节。
生成数量：1 张独立图片。
```

小批量可以为每张图片写一段独立提示词，或使用 `pack.json` 的 `items[]` 分别提交。例如：

```text
图片 1：保留参考图中的产品外观，生成美国站 1:1 白底电商主图，正面居中，柔和棚拍光线，无文字无水印。
图片 2：保留参考图中的产品外观，生成美国站 1:1 生活方式场景图，放置在明亮现代客厅中，突出真实使用场景，不改变产品颜色、结构和比例。
图片 3：保留参考图中的产品外观，生成美国站 9:16 详情图，近距离展示面料纹理和做工，背景简洁，不添加无法从参考图确认的功能说明。
```

需要多张不同 提示词 时，使用 `pack.json`，每个 `items[]` 对应一次独立生成任务。参考图可以是本地路径或公开 URL，本地图片默认以 base64 传给服务。

## 目录批量生成

适用于一个主目录下包含多个商品子目录的任务：

```text
root/
  product-a/
    in/
      request.txt
      reference.jpg
```

运行：

```powershell
python <skill-base>/scripts/batch-directory-generate.py <root> --dry-run
python <skill-base>/scripts/batch-directory-generate.py <root>
```

每个一级子目录作为一个独立商品任务，流程为：读取需求 → 读取参考图 → 图像理解 → 生成 提示词 → 提交图片任务 → 轮询 → 下载 → 写入商品日志和 manifest。单个商品失败不应阻断其他商品。

## Excel/CSV 批量生成

支持妙手 ERP 店铺产品导出的 Excel/CSV 清单直接运行，减少人工收集、整理和处理图片的工作量。

适用输入：

- `.xlsx`、`.xlsm` 或 `.csv` 文件；
- 妙手 ERP 店铺产品导出清单；
- 可映射 `SKU ID`、产品主图 URL、SKU 图片 URL、产品 ID、产品名称、产品类目和规格等字段。

运行：

```powershell
python <skill-base>/scripts/batch-excel-generate.py <products.xlsx> --requirements "目标市场、图片类型、数量和比例" --dry-run
python <skill-base>/scripts/batch-excel-generate.py <products.xlsx> --requirements "目标市场、图片类型、数量和比例"
```

`--requirements` 示例提示词：

```text
目标国家站点：美国 TikTok Shop；每个商品生成 3 张图片：1 张 1:1 白底主图、1 张 1:1 模特或生活方式场景图、1 张 9:16 产品详情图。严格保留每个 SKU 的颜色、款式、材质、配件和包装差异；主图突出商品完整外观，场景图适合 TikTok 短视频封面或商品卡片，详情图展示可观察的材质和做工。所有图片不添加未经提供的功能、认证、尺寸、品牌承诺或促销文字；不生成拼图、分栏、重复商品和错误 SKU。参考图优先使用商品主图和 SKU 图，每个商品最多 10 张。
```

妙手 ERP 导出清单的批量示例：

```powershell
python <skill-base>/scripts/batch-excel-generate.py "妙手ERP产品导出.xlsx" --requirements "目标国家站点：英国；每个商品生成 2 张 1:1 图片：白底主图和真实居家场景图；保留 SKU 颜色、结构和配件；不加文字、不改产品事实、不生成拼图" --dry-run
python <skill-base>/scripts/batch-excel-generate.py "妙手ERP产品导出.xlsx" --requirements "目标国家站点：英国；每个商品生成 2 张 1:1 图片：白底主图和真实居家场景图；保留 SKU 颜色、结构和配件；不加文字、不改产品事实、不生成拼图"
```

批量流程：

1. 读取 Excel/CSV 并校验字段。
2. 按产品 ID 聚合，同一产品作为一个任务。
3. 主图优先，补充 SKU 图，最多 10 张参考图。
4. 用图像理解提取可观察事实、卖点、SKU 差异和生成约束。
5. 按模板生成每张图片的独立 提示词。
6. 分批提交生成任务，独立轮询和下载，失败任务可恢复。
7. 输出原始表格、批次日志、商品日志、manifest 和最终图片。

批量限制：

- 单批最多支持生成 2000 张图片（作者实测一次批量生成 2700+ 张无中断）。
- 2000 张任务必须拆成多个提交批次，不得合并成一次 API 请求。
- 每批保存进度和 manifest，支持中断后恢复，避免重复生成。
- 建议先使用 `--dry-run` 核对产品数量、图片数量、参考图和输出目录。
- 2000 张是任务上限，不代表单个商品必须生成 2000 张；实际数量由用户需求和额度决定。

## 重点说明

- 真实 API 配置由用户提供，agent 不展示、回显或写入 key。
- 核心服务地址不写入本说明，脚本内部负责调用配置的服务。
- 生成结果必须检查商品一致性，不能把概念图直接当作真实商品交付。
- 生成数量受用户账号额度、服务端限流、图片尺寸和任务复杂度影响。
- 批量任务必须保留日志和 manifest，确保可追踪、可恢复、可重试。
- 版权和商业授权要求见 `NOTICE.md`。
