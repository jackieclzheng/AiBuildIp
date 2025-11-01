# 每日朋友圈文案自动化指南

## 1. 准备模板
- 每天 10 条文案写在 `templates/YYYY-MM-DD.json`。
- 结构示例：

```json
{
  "email_subject": "2025-10-30 朋友圈文案",
  "email_intro": "今日主题简述，可选。",
  "entries": [
    "第一条内容……",
    "第二条内容……",
    "……共 10 条"
  ]
}
```

## 2. 生成并追加到 `pyq-copywriting.md`
- 手动执行：`python3 generate_pyq.py --date 2025-10-30`
- 不加 `--date` 会默认使用当天日期。
- 若 `pyq-copywriting.md` 已存在对应日期章节，脚本会自动跳过，避免重复。

## 3. 邮件发送配置
- 复制 `email_config.example.json` 为 `email_config.json`，填入真实 SMTP 信息（建议使用 App Password）。
- 必填字段：`smtp_server`、`from_addr`、`to_addrs`、`password`（或与 `from_addr` 不同的 `username`）。
- 如果暂时不需要发邮件，可删除或重命名 `email_config.json`，或执行时加 `--skip-email`。

## 4. 定时任务
- **macOS（推荐 launchd）**  
  1. 编辑 `~/Library/LaunchAgents/com.pyq.generator.plist`：  
     ```xml
     <?xml version="1.0" encoding="UTF-8"?>
     <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
     <plist version="1.0">
       <dict>
         <key>Label</key>
         <string>com.pyq.generator</string>
         <key>ProgramArguments</key>
         <array>
           <string>/usr/bin/env</string>
           <string>python3</string>
           <string>/Users/jackiezheng/AIBuildIP/generate_pyq.py</string>
         </array>
         <key>WorkingDirectory</key>
         <string>/Users/jackiezheng/AIBuildIP</string>
         <key>StartCalendarInterval</key>
         <dict>
           <key>Hour</key>
           <integer>8</integer>
           <key>Minute</key>
           <integer>0</integer>
         </dict>
         <key>StandardOutPath</key>
         <string>/Users/jackiezheng/Library/Logs/pyq-generator.log</string>
         <key>StandardErrorPath</key>
         <string>/Users/jackiezheng/Library/Logs/pyq-generator.err</string>
       </dict>
     </plist>
     ```
  2. 加载：`launchctl load ~/Library/LaunchAgents/com.pyq.generator.plist`
  3. 修改后可用 `launchctl unload ...` 再次 `load`。

- **Linux / 兼容 cron**  
  1. `crontab -e`
  2. 添加：`0 8 * * * cd /Users/jackiezheng/AIBuildIP && /usr/bin/env python3 generate_pyq.py`

## 5. 故障排查
- 模板缺失：脚本会提示找不到模板，请确认文件名与日期一致。
- 邮件相关错误：检查 SMTP 端口、TLS/SSL 设置及授权信息。
- 日志：使用 launchd/cron 时，将标准输出和错误重定向到日志文件更易排查问题。
