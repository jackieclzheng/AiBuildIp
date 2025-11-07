## 自动更新文案方案草案

### 目标
- 定期为 `pyq-duhougan.md` 和 `fitness-poetic.md` 自动追加新的段落，保持内容持续更新。
- 过程完全在 GitHub Actions 内完成，可审计、可回滚。
- 避免覆盖已有文案，确保邮件发送脚本能无缝读取新增内容。

### 文案来源与管理
1. **素材存储**：在仓库新增 `content_pool/` 目录，按日期或主题维护 JSON/Markdown 素材文件，字段包含 `title`、`body`、`tags` 等。
2. **状态跟踪**：使用 `content_pool/state.json` 记录每条素材的使用状态（未使用/已使用/忽略）。
3. **人工审核**：所有新素材通过 PR 进入 `content_pool`，便于多人协作与历史追溯。

### 自动化流程
1. **准备脚本**
   - 新建 `scripts/inject_content.py`，职责：
     - 读取 `state.json`，挑选未使用的素材。
     - 将素材渲染为目标 Markdown 段落（使用模板，自动添加 `## Day X` 或 `## 序号`）。
     - 追加到对应 Markdown 文件尾部，并更新 `state.json`。
   - 保证幂等性：如果当日运行失败或重复执行，不会重复插入同一素材。
2. **GitHub Actions 工作流**
   - 触发条件：每日凌晨（或与邮件发送错开）跑一次。
   - 步骤：
     1. checkout 仓库。
     2. `actions/setup-python` 安装 Python 环境。
     3. 运行 `python scripts/inject_content.py --slot daily`。
     4. 若有改动，执行 `git config`, `git commit -am "Add daily content"`，并 `git push` 到一个自动分支。
     5. 使用 `peter-evans/create-pull-request` 创建 PR，标题形如 `chore: add content for 2024-11-XX`，由人工 Merge。
3. **冲突处理**：若 PR 无人合并导致后续自动 PR 冲突，可在脚本中检测已有同名分支，自动在 CI 中中止并提醒维护者。

### 邮件发送协同
- 邮件脚本继续依赖 `.pyq_snippet_state` 与 `.fitness_snippet_state`（Actions 版用 `--index`），不需要调整。
- 若内容追加量大，可在 `inject_content.py` 中同步维护一个 `entries_count` 文件，供邮件脚本读取总数。

### 测试与监控
1. 本地测试：手动运行 `python scripts/inject_content.py --dry-run`，确认输出与文件变更符合预期。
2. CI 校验：在工作流中新增一步运行 `python -m unittest` 或 `pytest`（可编写基础测试，验证 Markdown 模板生成）。
3. 日志监控：PR 描述里自动附加本次追加的标题列表，便于审核。

### 后续改进
- 支持外部接口（如自建内容服务）拉取素材，通过 GitHub Secrets 存储 API Token。
- 根据邮件反馈（打开率、点击率）为文案打分，写回 `state.json` 形成闭环。
