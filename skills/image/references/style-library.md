# GPT-Image2 风格与提示词库

Generated from `data/style-library.json`. Use this file as the detailed index for choosing GPT-Image2 prompt templates, visual styles, categories, and scene tags.

## 选择规则

- Match explicit product types to template categories first, such as product, poster, UI, infographic, brand, photography, character, or document.
- Match visual words to style tags next, such as realistic, 3D, illustration, classical, brand, poster, or UI.
- Match context words to scene tags next, such as commerce, education, social, food, travel, story, history, tech, or creative.
- If a request is vague, offer 2-3 strong template directions and ask the user to choose before writing the final prompt.
- Final output should include the selected template name, a copyable GPT-Image2 prompt, and concise constraints for text, aspect ratio, layout, and negative details.

## 模板索引

### UI 截图系统

- ID: `ui-screenshot-system`
- 类别： UI & Interfaces
- 风格： UI
- 场景： Tech, Social
- 标签： UI, Dashboard, Screenshot
- 示例图： `/images/case17.jpg`
- 示例案例： case 17, case 2, case 4

适用场景：
- 说明： Use for app screens, dashboards, social screenshots, and live interface mockups.
- ZH: 用于 App 截图、仪表盘、社媒截图和直播界面。

编写要点：
  - Lock platform, aspect ratio, layout hierarchy, and exact visible text.
  - Specify UI chrome such as status bars, tabs, action rows, or comment layers.
  - 锁定平台、比例、层级和画面文字。
  - 明确状态栏、Tab、操作区、评论层等 UI 元素。

注意事项：
  - Avoid vague platform names and generic app mockups.
  - Constrain text readability and platform-specific details.
  - 避免平台描述过泛。
  - 约束文字可读性和平台特征。

### 信息图引擎

- ID: `infographic-engine`
- 类别： Charts & Infographics
- 风格： Infographic, Charts
- 场景： Education, Tech
- 标签： Infographic, Chart, Education
- 示例图： `/images/case334.png`
- 示例案例： case 334, case 1, case 8

适用场景：
- 说明： Use for explainer graphics, technical diagrams, timelines, and knowledge cards.
- ZH: 用于解释图、技术图解、时间线和知识卡片。

编写要点：
  - Define 3-5 modules, information flow, visual hierarchy, and short labels.
  - Use color groups, arrows, icons, and clean spacing to reduce clutter.
  - 定义 3-5 个模块、信息流、层级和短标签。
  - 用色块、箭头、图标和留白控制复杂度。

注意事项：
  - Avoid long paragraphs inside the image.
  - Limit module count before adding visual detail.
  - 避免把长段正文塞进画面。
  - 先限制模块数量，再补视觉细节。

### 科学尺度示意图

- ID: `scientific-scale-diagram`
- 类别： Charts & Infographics
- 风格： Infographic, Charts, Realistic
- 场景： Education, Tech
- 标签： Infographic, Chart, Education
- 示例图： `/images/case341.jpg`
- 示例案例： case 341

适用场景：
- 说明： Use when the topic needs micro-to-macro scale comparison and labeled detail windows.
- ZH: 用于需要从微观到宏观展示尺度变化的科普主题。

编写要点：
  - Use 6-8 scale frames and keep each label short.
  - Show units, magnification, and distinct scale detail.
  - 使用 6-8 个尺度框，每个标签保持短句。
  - 展示单位、倍率和不同尺度的细节。

注意事项：
  - Avoid making every scale frame visually identical.
  - Avoid generic magnifying glass icon layouts.
  - 避免所有尺度框长得一样。
  - 避免通用放大镜式布局。

### 海报排版系统

- ID: `poster-layout-system`
- 类别： Posters & Typography
- 风格： Poster
- 场景： Commerce, Social
- 标签： Poster, Typography, 营销活动
- 示例图： `/images/case345.jpg`
- 示例案例： case 345, case 5, case 10

适用场景：
- 说明： Use for event posters, movie posters, covers, and social campaign visuals.
- ZH: 用于活动海报、电影海报、封面和社媒传播视觉。

编写要点：
  - Lock subject, headline, layout, palette, and aspect ratio.
  - Make the title hierarchy and primary visual clear.
  - 锁定主体、标题、版式、配色和比例。
  - 突出标题层级和主视觉。

注意事项：
  - Avoid mixed 灵感板s or process sheets when asking for one finished poster.
  - Constrain extra text and decorative symbols.
  - 需要成品海报时，避免生成拼贴展示板。
  - 约束多余文字和装饰符号。

### 运动商业海报

- ID: `sports-campaign-poster`
- 类别： Posters & Typography
- 风格： Poster, Realistic
- 场景： Commerce, Fashion
- 标签： Poster, 营销活动, Typography
- 示例图： `/images/case350.jpg`
- 示例案例： case 350, case 3

适用场景：
- 说明： Use for sports brand campaigns, athlete posters, and product-led sport visuals.
- ZH: 用于运动品牌 营销活动、运动员海报和运动产品视觉。

编写要点：
  - Define sport, athlete pose, hero prop, title, and brand palette.
  - Use dramatic light, clean composition, and readable data overlays.
  - 定义运动项目、姿态、核心道具、标题和品牌色。
  - 使用强光影、干净构图和可读数据层。

注意事项：
  - Avoid wrong equipment and noisy collage.
  - Keep the athlete and hero prop visually dominant.
  - 避免错误运动器材和杂乱拼贴。
  - 让运动员和核心道具占据主导。

### 概念字体海报

- ID: `conceptual-typography-poster`
- 类别： Posters & Typography
- 风格： Poster
- 场景： Creative, Social
- 标签： Typography, Poster, Style
- 示例图： `/images/case355.jpg`
- 示例案例： case 355

适用场景：
- 说明： Use when the exact title must become the main visual structure.
- ZH: 用于标题文字需要成为主视觉结构的海报。

编写要点：
  - Make typography the hero and spell the title exactly.
  - Tie human figures, objects, or landscapes to the title meaning.
  - 让字体成为画面主角，并保证标题拼写准确。
  - 人物、物体或风景需要服务标题含义。

注意事项：
  - Avoid default word art, unrelated icons, and misspelled title text.
  - Limit the color system to a restrained palette.
  - 避免默认字效、无关图标和标题错字。
  - 控制配色数量，保持克制。

### 水墨双重曝光海报

- ID: `ink-double-exposure-poster`
- 类别： Posters & Typography
- 风格： Poster, Illustration, Classical
- 场景： Story, History
- 标签： Poster, Classical, Style
- 示例图： `/images/case359.jpg`
- 示例案例： case 359

适用场景：
- 说明： Use for poetic portrait posters, ink atmospheres, and layered cultural visuals.
- ZH: 用于诗意人像海报、水墨氛围和文化主题视觉。

编写要点：
  - Blend portrait silhouette, ink texture, atmosphere, and negative space.
  - Keep composition quiet, premium, and readable.
  - 融合人像剪影、水墨质感、氛围和留白。
  - 保持构图克制、高级、可读。

注意事项：
  - Avoid cheap fantasy collage and overloaded scenery.
  - Use subtle text or no text unless required.
  - 避免廉价奇幻拼贴和景物堆叠。
  - 非必要时减少文字。

### 自然科普海报

- ID: `nature-science-poster`
- 类别： Posters & Typography
- 风格： Poster, Infographic
- 场景： Education
- 标签： Poster, Education, Style
- 示例图： `/images/case339.jpg`
- 示例案例： case 339

适用场景：
- 说明： Use for natural subjects that need a premium, clean science poster feel.
- ZH: 用于自然主题的高级、干净科普海报。

编写要点：
  - Use a clear subject, minimal copy, soft shadows, and disciplined whitespace.
  - Keep the scientific label short and visible.
  - 使用清晰主体、少量文案、柔和阴影和充足留白。
  - 让科普标签短而清楚。

注意事项：
  - Avoid heavy advertising language.
  - Avoid dense encyclopedia blocks.
  - 避免广告感太重。
  - 避免密集百科正文。

### 商品商业视觉

- ID: `product-commerce-visual`
- 类别： Products & E-commerce
- 风格： Product, Realistic
- 场景： Commerce, Food
- 标签： Product, Commerce, Packaging
- 示例图： `/images/case373.jpg`
- 示例案例： case 373, case 358

适用场景：
- 说明： Use for product hero shots, packaging visuals, detail pages, and sales layouts.
- ZH: 用于商品主图、包装视觉、详情页和销售卖点排版。

编写要点：
  - Define product, selling points, material, scene, lighting, and layout blocks.
  - Separate hero product, benefit labels, and supporting props.
  - 定义商品、卖点、材质、场景、光线和版块。
  - 区分主商品、卖点标签和辅助道具。

注意事项：
  - Avoid random props that weaken product recognition.
  - Constrain packaging text and claim wording.
  - 避免无关道具削弱商品识别。
  - 约束包装文字和卖点表达。

### 个性化美妆报告

- ID: `personalized-beauty-report`
- 类别： Products & E-commerce
- 风格： Product, UI
- 场景： Commerce, Fashion
- 标签： Product, Layout, Style
- 示例图： `/images/case353.jpg`
- 示例案例： case 353

适用场景：
- 说明： Use for beauty recommendations, skin reports, shopping assistants, and lifestyle product cards.
- ZH: 用于美妆推荐、肤质报告、导购助手和生活方式商品卡片。

编写要点：
  - Use a report-like hierarchy with diagnosis, recommendation, and product cards.
  - Keep product images, labels, and ratings aligned.
  - 使用诊断、推荐和商品卡片的报告层级。
  - 对齐商品图、标签和评分。

注意事项：
  - Avoid medical claims and unreadable dense notes.
  - Keep recommendation logic simple.
  - 避免医疗化结论和难读小字。
  - 保持推荐逻辑清楚。

### 品牌识别包

- ID: `brand-identity-package`
- 类别： Brand & Logos
- 风格： Brand
- 场景： Commerce
- 标签： Brand, Logo, Identity
- 示例图： `/images/case354.jpg`
- 示例案例： case 354

适用场景：
- 说明： Use for logo systems, brand boards, visual identity kits, and application mockups.
- ZH: 用于 Logo 系统、品牌板、VI 套件和应用样机。

编写要点：
  - Define brand name, positioning, palette, typography, logo usage, and touchpoints.
  - Ask for a coherent board with aligned applications.
  - 定义品牌名、定位、配色、字体、Logo 用法和触点。
  - 要求视觉板中的应用统一对齐。

注意事项：
  - Avoid unrelated logo variants and inconsistent palettes.
  - Keep brand text accurate.
  - 避免无关 Logo 变体和混乱配色。
  - 保持品牌文字准确。

### 品牌触点视觉板

- ID: `brand-touchpoint-board`
- 类别： Brand & Logos
- 风格： Brand, Product
- 场景： Commerce, Social
- 标签： Brand, Identity, 营销活动
- 示例图： `/images/case362.jpg`
- 示例案例： case 362

适用场景：
- 说明： Use for multi-touchpoint campaign boards and brand rollout previews.
- ZH: 用于多触点 营销活动 展示和品牌落地预览。

编写要点：
  - Specify touchpoint list, shared visual rules, and mockup arrangement.
  - Use one palette and one typography logic across all panels.
  - 指定触点清单、统一视觉规则和样机排列。
  - 让所有面板共享配色和字体逻辑。

注意事项：
  - Avoid mixing many unrelated campaign styles.
  - Limit touchpoints if readability drops.
  - 避免混入多个无关 营销活动 风格。
  - 可读性下降时减少触点数量。

### 建筑与空间

- ID: `architecture-space`
- 类别： Architecture & Spaces
- 风格： Architecture
- 场景： Travel, Commerce
- 标签： Architecture, Interior, Map
- 示例图： `/images/case331.png`
- 示例案例： case 331, case 11

适用场景：
- 说明： Use for interiors, architecture renders, city maps, spatial plans, and environment concepts.
- ZH: 用于室内、建筑表现、城市地图、空间规划和环境概念图。

编写要点：
  - Define viewpoint, scale, material, lighting, and spatial function.
  - For maps, specify landmarks, labels, border decoration, and visual accuracy level.
  - 定义视角、尺度、材质、光线和空间功能。
  - 地图需要指定地标、标签、边框装饰和准确度。

注意事项：
  - Avoid impossible perspectives unless the output is conceptual.
  - Lock map label language and relative placement.
  - 概念图之外要避免不合理透视。
  - 锁定地图标签语言和相对位置。

### 写实摄影

- ID: `realistic-photography`
- 类别： Photography & Realism
- 风格： Photography, Realistic
- 场景： Fashion, Commerce
- 标签： Photography, Realistic, Lens
- 示例图： `/images/case377.jpg`
- 示例案例： case 377

适用场景：
- 说明： Use for portraits, street photos, product photography, and cinematic realism.
- ZH: 用于人像、街拍、商品摄影和电影感写实。

编写要点：
  - Specify camera distance, lens, light source, texture, background, and motion.
  - Use believable imperfections for documentary realism.
  - 指定机位、镜头、光源、质感、背景和动作。
  - 加入可信的小瑕疵增强纪实感。

注意事项：
  - Avoid over-polished plastic skin unless commercial beauty is required.
  - Add negative constraints for hands, text, and anatomy when needed.
  - 商业美妆之外，避免过度磨皮。
  - 需要时加入手部、文字、结构类负面约束。

### 街头纪实瞬间

- ID: `street-accident-moment`
- 类别： Photography & Realism
- 风格： Photography, Realistic
- 场景： Travel, Social
- 标签： Photography, Realistic, Scene
- 示例图： `/images/case376.jpg`
- 示例案例： case 376

适用场景：
- 说明： Use for candid street moments, accidental spills, documentary phone shots, and fast action.
- ZH: 用于街头抓拍、意外泼洒、手机纪实和快速动作。

编写要点：
  - Describe the exact moment, camera height, motion blur, and street context.
  - Add negative constraints for staged poses and fake ad lighting.
  - 描述具体瞬间、机位高度、运动模糊和街景。
  - 加入避免摆拍和广告棚拍感的限制。

注意事项：
  - Avoid too-clean compositions.
  - Keep the event plausible and grounded.
  - 避免画面过于干净。
  - 让事件看起来可信。

### 插画与艺术风格

- ID: `illustration-art-style`
- 类别： Illustration & Art
- 风格： Illustration
- 场景： Story, Creative
- 标签： Illustration, Art, Style
- 示例图： `/images/case346.jpg`
- 示例案例： case 346, case 6

适用场景：
- 说明： Use for anime, watercolor, ink, decorative art, and style experiments.
- ZH: 用于动漫、水彩、水墨、装饰画和风格实验。

编写要点：
  - Define composition, subject, palette, brush material, mood, and rendering depth.
  - For reference images, state what must be preserved.
  - 定义构图、主体、配色、笔触材质、情绪和完成度。
  - 参考图任务需要说明保留哪些特征。

注意事项：
  - Avoid style-only prompts without composition.
  - Lock character identity when using references.
  - 避免只写风格，不写构图。
  - 使用参考图时锁定角色识别。

### 角色设定表

- ID: `character-design-sheet`
- 类别： Characters & People
- 风格： Character, Illustration
- 场景： Story
- 标签： Character, Pose, Style
- 示例图： `/images/case347.jpg`
- 示例案例： case 347

适用场景：
- 说明： Use for character sheets, pose grids, action breakdowns, and identity references.
- ZH: 用于角色设定表、动作网格、动作拆解和一致性参考。

编写要点：
  - Define identity anchors, outfit, proportions, pose count, and sheet layout.
  - Keep face, hairstyle, and costume details consistent.
  - 定义身份锚点、服装、比例、动作数量和版式。
  - 保持脸、发型和服装细节一致。

注意事项：
  - Avoid changing costume details between poses.
  - Limit pose count if the sheet becomes crowded.
  - 避免不同动作里服装细节变化。
  - 画面拥挤时减少动作数量。

### 3D 收藏玩具

- ID: `3d-collectible-toy`
- 类别： Characters & People
- 风格： 3D, Character
- 场景： Commerce, Creative
- 标签： Character, 3D, Style
- 示例图： `/images/case378.jpg`
- 示例案例： case 378

适用场景：
- 说明： Use for premium collectible figures, avatar toys, blind-box characters, and 3D display renders.
- ZH: 用于高级收藏玩具、头像公仔、潮玩角色和 3D 展示图。

编写要点：
  - Preserve face and outfit anchors from the reference.
  - Specify material, packaging, base, lighting, and collectible scale.
  - 保留参考图中的脸和服装锚点。
  - 指定材质、包装、底座、光线和收藏比例。

注意事项：
  - Avoid generic toy bodies without identity details.
  - Keep packaging text minimal and accurate.
  - 避免没有身份细节的通用玩具。
  - 包装文字保持少量且准确。

### 场景叙事

- ID: `scene-storytelling`
- 类别： Scenes & Storytelling
- 风格： Scenes, Illustration
- 场景： Story, Social
- 标签： Scene, Story, Storyboard
- 示例图： `/images/case330.png`
- 示例案例： case 330

适用场景：
- 说明： Use for storyboards, worldbuilding, live scenes, and emotional narrative frames.
- ZH: 用于分镜、世界观、直播场景和情绪叙事画面。

编写要点：
  - Define who, where, when, conflict, emotion, and camera framing.
  - Use scene details to support narrative rather than decoration.
  - 定义人物、地点、时间、冲突、情绪和机位。
  - 让场景细节服务故事。

注意事项：
  - Avoid generic fantasy backgrounds.
  - Keep narrative cues visible in the frame.
  - 避免通用幻想背景。
  - 让故事线索在画面里可见。

### 历史与古风题材

- ID: `history-classical-themes`
- 类别： History & Classical Themes
- 风格： History, Classical, Illustration
- 场景： History, Story
- 标签： History, Classical, Scroll
- 示例图： `/images/case375.jpg`
- 示例案例： case 375, case 338

适用场景：
- 说明： Use for ancient Chinese themes, scrolls, dynasty clothing, poetry visuals, and historical scenes.
- ZH: 用于古风题材、长卷、朝代服饰、诗词视觉和历史场景。

编写要点：
  - Specify dynasty, clothing system, object references, layout format, and cultural mood.
  - Use scroll, album page, or poster format deliberately.
  - 指定朝代、服饰制度、器物参考、版式和文化气质。
  - 明确长卷、册页或海报形式。

注意事项：
  - Avoid mixing dynasties when historical accuracy matters.
  - Constrain random modern props.
  - 需要历史准确时，避免朝代混搭。
  - 约束随机现代物件。

### 文档与出版物

- ID: `document-publishing`
- 类别： Documents & Publishing
- 风格： Documents, Infographic
- 场景： Education, Tech
- 标签： Document, Publishing, Layout
- 示例图： `/images/case360.jpg`
- 示例案例： case 360

适用场景：
- 说明： Use for white papers, manuals, encyclopedic plates, report pages, and publication systems.
- ZH: 用于白皮书、手册、百科图鉴、报告页面和出版系统。

编写要点：
  - Define page size, columns, table of contents, figure system, and typography hierarchy.
  - Use readable headings, tables, labels, and page rhythm.
  - 定义页面尺寸、分栏、目录、图表系统和字体层级。
  - 使用可读标题、表格、标签和页面节奏。

注意事项：
  - Avoid tiny dense text.
  - Keep charts and captions aligned to the page grid.
  - 避免密集小字。
  - 让图表和说明对齐页面网格。

### 概念产品拆解

- ID: `concept-product-breakdown`
- 类别： Other Use Cases
- 风格： Other Use Cases, Product
- 场景： Creative, Tech
- 标签： Creative, R&D, Special
- 示例图： `/images/case370.jpg`
- 示例案例： case 370, case 361

适用场景：
- 说明： Use for experimental prompt tasks, R&D boards, exploded diagrams, and unusual visual systems.
- ZH: 用于实验型任务、研发视觉板、拆解图和特殊视觉系统。

编写要点：
  - Define the artifact type, components, labels, material logic, and final presentation format.
  - Use clear callouts and a controlled technical style.
  - 定义产物类型、组件、标签、材质逻辑和展示格式。
  - 使用清晰标注和受控技术风格。

注意事项：
  - Avoid unspecified mixed tasks.
  - Keep labels short and component relationships visible.
  - 避免任务边界过泛。
  - 标签要短，组件关系要清楚。

## 分类

- UI & Interfaces: UI 与界面 | Apps, websites, dashboards, social screenshots, and product interfaces.
- Charts & Infographics: 图表与信息可视化 | Infographics, knowledge maps, technical explainers, and structured diagrams.
- Posters & Typography: 海报与排版 | Event posters, covers, type-driven visuals, and strong layout compositions.
- Products & E-commerce: 商品与电商 | Product shots, detail pages, packaging, selling points, and ads.
- Brand & Logos: 品牌与标志 | Logos, identity systems, brand touchpoints, and campaign visuals.
- Architecture & Spaces: 建筑与空间 | Architecture renders, interiors, city maps, and spatial concepts.
- Photography & Realism: 摄影与写实 | Portraits, phone photography, film texture, and commercial photography.
- Illustration & Art: 插画与艺术 | Illustration, art styles, material experiments, and decorative images.
- Characters & People: 人物与角色 | Character design, pose references, cards, and 3D toys.
- Scenes & Storytelling: 场景与叙事 | Storyboards, narrative scenes, livestream frames, and worldbuilding.
- History & Classical Themes: 历史与古风题材 | Classical scrolls, historical figures, traditional themes, and poetry visuals.
- Documents & Publishing: 文档与出版物 | White papers, manuals, encyclopedic plates, and publishing layouts.
- Other Use Cases: 其他应用场景 | Creative experiments, special tasks, mixed workflows, and practical cases.

## 风格标签

- 3D: 3D | Keywords: 3d, toy, render, 玩具
- Architecture: 建筑 | Keywords: None
- Brand: 品牌 | Keywords: brand, logo, identity, 品牌, 标志
- Character: 角色 | Keywords: character, avatar, pose, 角色, 人物
- Characters: 人物 | Keywords: None
- Charts: 图表 | Keywords: None
- Classical: 古典 | Keywords: classical, dynasty, history, 古风, 历史
- Documents: 文档 | Keywords: None
- History: 历史 | Keywords: None
- Illustration: 插画 | Keywords: illustration, painting, watercolor, 插画, 绘画
- Infographic: 信息图 | Keywords: infographic, diagram, 信息图, 图解
- Other Use Cases: 其他应用场景 | Keywords: None
- Photography: 摄影 | Keywords: None
- Poster: 海报 | Keywords: poster, cover, typography, 海报, 封面
- Product: 商品 | Keywords: product, packaging, 商品, 包装
- Products: 商品 | Keywords: None
- Realistic: 写实 | Keywords: photo, realistic, camera, 写真, 写实
- 场景： 场景 | Keywords: None
- UI: 界面 | Keywords: ui, interface, dashboard, 界面, 截图

## 场景标签

- Creative: 创意 | Keywords: None
- Tech: 科技 | Keywords: ai, rag, tech, data, 技术, 数据
- Commerce: 商业 | Keywords: product, brand, ad, campaign, 商品, 商业, 广告
- Education: 教育 | Keywords: guide, atlas, science, learning, 学习, 科普
- Social: 社媒 | Keywords: social, x , wechat, 朋友圈, 社媒
- Fashion: 时尚 | Keywords: fashion, clothing, portrait, 服饰, 写真
- Food: 食品饮品 | Keywords: food, drink, coffee, tea, 餐厅, 咖啡, 茶
- Travel: 旅行 | Keywords: city, map, street, 城市, 地图, 街头
- Story: 叙事 | Keywords: story, scene, world, 故事, 场景
- History: 历史 | Keywords: history, dynasty, ancient, 历史, 古希腊, 唐
