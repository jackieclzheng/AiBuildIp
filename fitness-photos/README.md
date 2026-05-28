# 跑步照片上传目录

把每天跑完步后的照片上传到这个目录，会触发 GitHub Action：

`Generate Fitness Photo Copy`

它会读取新增的 JPG / PNG / WEBP 图片，调用视觉模型生成黑谷风健身朋友圈文案，并通过邮件发送。

## 手机上传建议

推荐用 iPhone 快捷指令或 GitHub 手机端上传到：

```text
fitness-photos/YYYY-MM-DD/HHMM.jpg
```

示例：

```text
fitness-photos/2026-05-28/1815.jpg
```

## iPhone 快捷指令思路

1. 选择照片。
2. 转换图像为 JPEG。
3. Base64 编码。
4. PUT 到 GitHub Contents API：

```text
https://api.github.com/repos/jackieclzheng/AiBuildIp/contents/fitness-photos/YYYY-MM-DD/HHMM.jpg
```

请求体：

```json
{
  "message": "upload fitness photo YYYY-MM-DD HHMM",
  "content": "<base64 image>",
  "branch": "master"
}
```

Headers：

```text
Authorization: Bearer <GitHub fine-grained token>
Accept: application/vnd.github+json
X-GitHub-Api-Version: 2022-11-28
```

GitHub token 只需要给这个仓库 `Contents: Read and write` 权限。

## 注意

- GitHub Actions 需要仓库里配置 `OPENAI_API_KEY`（或 `CODEX_OPENAI_API_KEY`）以及现有 SMTP 邮件 secrets。
- 不建议直接上传 HEIC；快捷指令里先转 JPEG。
- 一次上传 1-3 张最好，文案会更聚焦。
- 这个 workflow 是照片触发的即时文案，不影响每天 07:25 的固定健身日更。
