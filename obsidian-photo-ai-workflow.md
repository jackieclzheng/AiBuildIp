# Obsidian + 手机照片 + AI文案自动化流程方案

## 1. 业务目标
1. 手机拍照后自动同步到 Obsidian（或其附件库），无需手动导入。  
2. 调用大模型读取照片（或照片元数据/描述）生成配套文案。  
3. 将图片+文案组合成邮件内容，通过定时脚本自动推送。

## 2. 端到端流程概览
1. **手机端 → Obsidian**：使用 iCloud Drive、坚果云、Dropshare 等具备自动上传功能的 App，把指定相册同步到仓库中的 `/attachments/daily-photos/` 等目录。  
2. **Obsidian 监听器**：在电脑端运行脚本，检测到新图片时记录到任务队列（如 JSON/SQLite）。  
3. **AI 文案生成**：脚本读取图片路径，调用大模型完成图像理解 + 文案生成。  
4. **内容入库**：脚本把图片、生成的 Markdown 摘要写入新的 md 文件或 YAML 数据文件，方便复用。  
5. **定时推送**：GitHub Actions / 本地 cron 读取最新的若干条，构建邮件正文并发送。

## 3. 大模型调用方案比较
| 方案 | 优点 | 缺点 | 适用场景 |
| --- | --- | --- | --- |
| **自写脚本 + 公有 API（OpenAI、Moonshot、阿里灵积）** | 完整掌控输入输出，易集成到现有 Python automation；便于图像+文字混合 prompt，和邮件脚本共用依赖 | 需自行写 prompt/重试逻辑，token 费用直接与调用量相关 | 需要高度可控、易调试、与现有脚本共存 |
| **Coze Workflow / Bot** | 图形化搭建流程，支持多模型；可在手机端直接触发或 Webhook 触发 | 需要维护 Coze 平台状态；图片上传到第三方，需注意隐私；触发调度要额外 glue code | 喜欢在平台上拖拽流程、文案需求主要面向社媒 |
| **本地/自托管 n8n + LLM 节点** | 可配置化强，拖拽式流程 + Webhook + Cron；可连接 Obsidian API、邮件、云存储 | 自建服务需要持续运行（VPS/树莓派）；图像→LLM 仍需 API 支持；初期搭建较耗时 | 希望统一管理多条自动化管道，并偏好可视化流程 |
| **完全本地模型（如 LLaVA、Qwen2-VL）** | 不依赖云端，隐私更强；可借助 GPU 批量处理 | 部署/维护成本高，生成质量需打磨 prompt+fine-tune；推理速度慢 | 有 GPU 资源且对隐私要求极高 |

推荐优先使用 **Python 自研脚本 + 公有多模态 API**：就地复用 `send_hot_topics_digest.py` 的邮件封装，易于自定义模板；后续若想托管到 n8n，可把脚本封装为 Webhook 节点调用。

## 4. 技术选型建议
1. **脚本语言**：Python，方便复用现有邮件发送逻辑并处理图像。  
2. **存储**：  
   - 图片：沿用 Obsidian 附件目录。  
   - 任务队列：`photo-tasks.jsonl` 或 SQLite（字段含 `path`, `timestamp`, `caption`, `status`）。  
   - 文案：生成 Markdown（`pyq-photo-copywriting.md`）或 Frontmatter。  
3. **模型**：选支持图像输入的 API，如 `gpt-4o-mini`, `qwen-vl-plus`, `moonshot-vl`；prompt 模板示例：  
   ```
   你是短内容文案助手。输入是一次拍摄的照片,请生成朋友圈文案和小红书标题+正文，包含场景亮点、镜头感。输出 JSON。
   ```  
4. **调度**：  
   - 本地：`cron` 或 `launchd` 每小时检查图片目录。  
   - GitHub Actions：利用仓库触发（需先把图片同步到仓库，或使用外部存储 + API）。  
5. **邮件推送**：在 `send_hot_topics_digest.py` 基础上提取通用函数，例如 `send_email(message)`，然后新增 `send_photo_copy_digest.py` 处理图片和文案（带 HTML/内联图片或外链）。

## 5. 实施步骤
1. **配置手机同步**：创建 `Photos/For-Obsidian` 相册 → 通过 iCloud 同步到电脑上的 `obsidian-vault/attachments/photos`.  
2. **写一个 `watch_photos.py`**：  
   - 扫描目录获取新文件。  
   - 调用模型 API 生成文案（含错误重试）。  
   - 写入 `photo-copywriting.md`（Markdown 表格或分节）。  
3. **集成邮件脚本**：  
   - 新建 `send_photo_digest.py`，读取最新 N 条文案 + 图片链接，构建邮件。  
   - 在 `.github/workflows/send-photo-email.yml` 或本地 cron 中调用。  
4. **可选：n8n/Coze 接入**：  
   - n8n：搭建一个工作流，Webhook 接受图片路径 → 调模型 → 调 SMTP 节点。  
   - Coze：创建 Bot，上传图片并生成文案，使用 Coze API 从脚本触发。  
5. **日志与回退**：每次生成后记录模型响应与提示词，方便日后改进；必要时在仓库中保存备份。

### 5.1 已订阅 Obsidian Sync 的推荐做法
1. 在手机端（Android/Vivo）和 Mac 端的 Obsidian 中登录同一个账号。  
2. 进入 `Settings → Sync`，选择需要同步的 Remote Vault，确保 `Attachments/Binary files` 选项保持开启。  
3. 完成首轮同步后，手机里新增的图片会自动落地到 Mac 本地 Vault；脚本直接读取本地文件即可，不必额外配置云盘。  
4. 如需限制流量，可在 `Selective Sync` 中排除无关文件夹，但必须保留存放图片的 `attachments` 目录。

## 6. 风险与注意事项
1. **隐私/版权**：上传到云端模型需确认是否包含敏感信息，可能需要模糊处理或局部裁剪。  
2. **模型稳定性**：API 限流时要实现重试和告警。  
3. **图片体积**：可在脚本内做等比压缩，防止邮件过大；或邮件正文使用外链（Obsidian Publish/图床）。  
4. **触发频率**：若拍照频繁，建议设置任务状态（如「待审核」→「已发送」），防止重复发送。  
5. **多端协作**：若多人使用同一 vault，需要锁机制（如基于文件锁或 Git 分支）避免冲突。

## 7. 后续扩展
1. 在文案中自动生成标签、话题、发布时间建议。  
2. 结合 `send_copywriting_digest.py`，让邮件内容混合「热点选题 + 图文战报」。  
3. 将最终文案推送到飞书/企业微信机器人，实现多渠道分发。  
4. 给 Obsidian 模板新增「照片速记」按钮，一键插入生成的文案和图片引用。

> 结论：先以「手机同步 + Python 脚本 + 云端多模态 API + GitHub Actions 邮件推送」作为 MVP，实现端到端闭环；后续如需低代码可再迁移到 Coze Workflow 或 n8n。
