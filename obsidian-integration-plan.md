## Obsidian 集成方案说明

### 目标
- 让手机采集的媒体素材、AI 生成的文案以及手工补充的笔记，全部集中在 Obsidian Vault 中管理。
- 在 Obsidian 内即可浏览素材、查看 AI 生成的摘要、手动修改或添加标签，并与邮件自动化流程对接。
- 保持数据结构清晰，便于脚本读取与后续自动化扩展。

### 整体流程概览
1. **媒体上传**：手机端自动同步到云存储（OSS/COS/S3/NAS），生成可访问的 URL。
2. **元数据入库**：脚本/自动化将素材信息写入 Obsidian Vault 的 Markdown 文件（每日或每素材一份）。
3. **AI 摘要生成**：GitHub Actions 或本地脚本读取 Vault 中当日新增条目，调用大模型生成文案，并写回对应笔记。
4. **邮件发送**：现有 Python 邮件脚本读取整理好的 Markdown 内容，按计划发送。

### Vault 结构建议
```
vault/
  DailyMedia/
    2024/
      2024-11-02.md
      2024-11-03.md
  MediaLibrary/
    IMG_20241102_101010.md
    VID_20241102_103000.md
  Templates/
    media-daily-note.md
    media-record.md
  Automations/
    media-index.json
```
- `DailyMedia`：每日汇总笔记，按日期记录当天素材及 AI 文案，便于快速回顾。
- `MediaLibrary`：每个素材一份 Markdown，包含 front matter + 详情 + AI 输出。
- `Templates`：Obsidian 模板，供手动新增或脚本渲染。
- `Automations/media-index.json`：脚本维护的索引，记录已处理素材、对应的 Markdown 路径。

### Markdown 模板示例
**`Templates/media-record.md`**
```markdown
---
title: {{FILENAME}}
captured_at: {{CAPTURED_AT}}
type: image
tags: [{{TAGS}}]
media_url: {{MEDIA_URL}}
local_path: {{LOCAL_PATH}}
processed: {{PROCESSED}}
---

## 原始信息
- 拍摄设备：{{DEVICE}}
- 拍摄地点：{{LOCATION}}
- 上传时间：{{UPLOAD_TIME}}

## AI 生成文案
- 摘要：
{{SUMMARY}}

- 推荐配文：
{{COPY}}

## 个人笔记
>
```
脚本在填充模板时替换占位符，AI 生成的内容写到对应段落，留出“个人笔记”区供人工补充。

### 自动化实现方式
1. **同步 Vault 到 GitHub**
   - 将 Obsidian Vault（或其中自动化相关目录）同步到 Git 仓库，便于 Actions 访问。
   - 可使用 Obsidian Git 插件自动 commit & push，也可手动同步。
2. **脚本流程**
   - `scripts/update_vault.py`：读取 `Automations/media-index.json`，为新增素材生成 Markdown 并更新索引。
   - `scripts/generate_vault_copy.py`：扫描 `MediaLibrary` 中 `processed: false` 的条目，调用模型生成文案，写回 `AI 生成文案` 部分，并把 `processed` 标记为 `true`。
3. **GitHub Actions**
   - 夜间（例如 02:00 UTC）运行：
     1. `actions/checkout` 拉取 Vault 仓库。
     2. 安装 Python 依赖，运行上述两个脚本。
     3. 若有改动，使用 `create-pull-request` 或直接 push（视协作流程而定）。
   - 邮件工作流读取 `DailyMedia` 或 `MediaLibrary` 中最新条目，组合邮件内容。

### 在 Obsidian 中的使用
- 借助 Dataview/Calendar 插件，快速浏览每日媒体与 AI 文案。
- 通过 Obsidian Search、Canvas 构建素材关系、素材-文案对照。
- 手动修改 Markdown 后，下一次自动化运行会检测 `processed: false` 或 front matter 中的更新时间，决定是否重新生成文案。

### 结合媒体文件
- **本地同步**：如果 Vault 与 NAS 同步，可在 front matter 中记录 `local_path`，Obsidian 内直接预览原图。
- **远程引用**：若媒体存储在云端，使用 `![]({{MEDIA_URL}})` 在 Markdown 中嵌入图片；视频可用外链或辅助插件预览。
- 可在 Obsidian 中创建“媒体收集面板”，集中显示最近 7 天素材及配文。

### 注意事项
- 保持 Vault 与云存储路径的映射关系，脚本需要知道媒体对应的 URL。
+- 若 Vault 存在私密内容，使用私有仓库或加密同步工具，避免公开泄露。
- 注意 Git 仓库体积，避免直接存储未压缩视频；可通过 Git LFS 或只引用外部链接。
- Actions 自动生成内容时需考虑冲突：若用户在本地手动修改了同一文件，应在脚本中检测并创建 PR 而非强行 push。

### 后续扩展
- 在 Obsidian 中运行 Dataview JS 或自定义脚本，实现 AI 文案手动重生成、打分。
- 引入同步插件（如 Omnisearch、Media Extended）增强多媒体体验。
- 结合向量数据库，将 Obsidian 的内容同步到检索服务，为聊天机器人提供上下文。
