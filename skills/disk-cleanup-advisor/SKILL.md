# Disk Cleanup Advisor Skill

## Description
分析磁盘占用，识别大文件及垃圾日志，提供清理建议。

## Tools
- `disk-usage-scan`: 扫描指定挂载点。
- `disk-find-largest`: 查找前 10 个大文件。
- `disk-cleanup-suggest`: 提供删除建议。

## Triggers
- "磁盘空间不足了"
- "哪里占用了最多的空间"
- "清理建议"
- "扫描磁盘 [路径]"

## Logic
1. 调用 `du -sh`。
2. 识别超过 1GB 的文件。
3. 过滤出日志、缓存等可清理项。
