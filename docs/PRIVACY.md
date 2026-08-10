# 隐私与数据发布检查

本程序完全在本地运行，不包含网络上传功能。公开 GitHub 仓库前必须确认：

- `user_data/` 未被 Git 跟踪；其中可能包含实验路径、备注、筛选标签和快照。
- 所有 `.tdms`、`.tdms_index`、导出 CSV/JSON/HTML 和实验截图均未提交。
- Issues、Pull Requests 和演示截图中不包含未经授权的实验数据或个人信息。
- 用于测试的示例数据应为人工合成或明确允许公开的数据。

可以运行以下命令检查待提交文件：

```powershell
git status --short
git ls-files | Select-String -Pattern 'user_data|\.tdms$'
```
