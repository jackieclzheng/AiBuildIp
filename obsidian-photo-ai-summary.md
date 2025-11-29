# 手机照片 + Obsidian + AI 自动文案方案综述

本摘要整理了近期讨论的全部要点，涵盖图片同步、自动化方案、GitHub Actions 运行细节以及实时触发需求的技术选型，便于后续统一规划。

## 1. 图片同步路径
1. **Obsidian Sync（已订阅）**  
   - 手机（Android/Vivo）与 Mac 端登录同一账号，启用 Remote Vault 并确保 `Attachments/Binary files` 同步开启。  
   - Selective Sync 中保留 `attachments` 目录，即可让手机新增照片自动落地到 Mac Vault，本地脚本立即可用。  
2. **跨平台云盘**  
   - 若不依赖官方 Sync，可将 Vault/attachments 放到坚果云、Dropbox、OneDrive 等同步盘。手机端 App 自动上传，Mac 端客户端拉取。  
3. **点对点同步/第三方 App**  
   - Syncthing、Resilio Sync 等工具适合不想走云端的场景，需要多端常驻。  
4. **云存储直传**  
   - 手机或 Obsidian 通过自动化上传到 OSS/S3/七牛等，供云端脚本访问（GitHub Actions/Serverless）。

## 2. AI 文案生成与分发方案
| 方案 | 描述 | 触发方式 | 适用场景 |
| --- | --- | --- | --- |
| 本地 Python 脚本 + 公有多模态 API | Mac 上 Watchdog 监听 `attachments/photos`，调用 GPT-4o/Qwen-VL/LLaVA，生成朋友圈/小红书文案，复用现有 SMTP 脚本 | 依赖电脑在线 | 想完全掌控流程、已有 Send 脚本基础 |
| Coze Workflow/Bot | 在 Coze 平台搭建流程，接收图片链接 → 调模型 → 调用邮件 API | 需把图片上传到 Coze 可访问的 URL，触发通常靠 Webhook | 喜欢低代码搭建、接受上传到第三方 |
| n8n/Zapier/Make | 监听 Dropbox/Drive 新文件 → 调用 LLM → 邮件/飞书推送 | 云端平台实时触发 | 想图形化并管理多条自动化 |
| Serverless （OSS/S3 事件 + 云函数） | 上传到云存储即触发云函数，函数内下载图片、生成文案并发送邮件 | 实时事件 | 追求“手机上传立刻推送”，且可维护云函数 |
| GitHub Actions 轮询 | 定时 job 从云存储拉取图片 → 生成文案 → 邮件 | 定时（非实时） | 能容忍时间延迟，已有 Actions 基建 |

## 3. 使用 GitHub Actions 的注意事项
1. Action 运行目录为 `$GITHUB_WORKSPACE`，`curl`/`wget``aws s3 sync` 等命令会把图片下载到此临时目录。  
2. 官方托管 runner 有约 14 GB 可用磁盘，job 完成后会清空；如需长期保存需上传到对象存储或使用 `actions/upload-artifact`。  
3. 要访问云端图片需提供凭证（OSS AccessKey、S3 IAM、Dropbox Token），可以放在 `secrets` 中。  
4. Actions 本身无法做到“实时触发”，只能定时或手动，所以对“手机上传即触发”的需求并不合适。

## 4. 实时触发大模型 + 邮件的实现思路
1. **云存储事件驱动**：  
   - 手机或 Obsidian 直接把图片同步到支持事件的存储桶（S3、OSS、七牛）。  
   - 配置上传事件触发云函数（Lambda、阿里函数计算等），函数中完成：下载图片 → 调大模型 → 发送邮件。  
   - 延迟低、无需本地设备在线，是最推荐的实时方案。  
2. **低代码自动化平台**：  
   - 使用 n8n/Zapier/Make 等提供的 “New File in Dropbox/Drive” 触发器，即时执行后续节点（LLM、邮件/推送）。  
   - 适用于不想写云函数但接受平台月费的场景。  
3. **本地守护脚本**：  
   - 若 Mac 常在线，可用 `watchdog` 监听 Obsidian Sync 下的附件目录，发现新文件立即调用模型并发邮件。  
   - 适合对隐私要求高、希望本地处理的场景。

## 5. Coze 访问 Obsidian 图片的限制
- Coze 无法直接读取 Obsidian Sync/iCloud/本地 Vault 的附件，需要把图片上传或同步到 Coze 可访问的 URL/云存储，再传给 Workflow/Bot。常见做法：
  1. 脚本监听 Vault 中的新增附件，通过 Coze API（或前端）把文件上传到 Coze 素材库，并记录返回的素材 ID。  
  2. 使用 n8n/Zapier 监控 Dropbox/Drive 等同步目录，一旦有新文件就调用 Coze API 上传。  
  3. 若 Coze 不提供上传接口，可把图片发到 S3/OSS/图床并在 Workflow 中引用外链，间接实现“同步知识库”。  
- 目前没有官方“一键 Vault→Coze”的插件，必须借助脚本或自动化桥接。

## 6. 典型实施路线
1. **最少维护（本地）**：Obsidian Sync → Mac watchdog 脚本 → 多模态 API → 复用现有邮件脚本。  
2. **云端实时**：手机 App → OSS/S3 → 事件触发云函数 → 模型 API → SMTP。  
3. **低代码**：手机 → Dropbox/Drive → Zapier/n8n → OpenAI/其他模型 → 邮件/飞书/企业微信。  
4. **排程备份**：若容忍延迟，可让 GitHub Actions 定时拉取云存储图片，生成文案并发送。

## 7. 关键问题 FAQ
1. **需要把图片同步到 Mac 吗？** 仅当要用本地脚本时需要；若计划用 GitHub Actions/云函数，就把图片同步到云端即可。  
2. **Actions 下载的图片存在哪里？** 在 runner 的 `$GITHUB_WORKSPACE`（约 14 GB 可用），job 结束即销毁。  
3. **如何立即触发文案生成？** 用云存储事件或自动化平台的 “New File” 触发器，不建议靠定时 Actions。  
4. **Coze 能直接访问 Obsidian 附件吗？** 不能，需要先上传到 Coze 可访问的位置。  
5. **手机是 Android/vivo 怎么同步？** 使用 Obsidian Sync 或跨平台云盘（坚果云、Dropbox 等），选择支持 Android + macOS 的方案即可。

> 以上总结可作为“手机拍照→Obsidian→AI 文案→邮件推送”系统的总体设计参考，可按自身资源选择本地、云端或低代码路径。
