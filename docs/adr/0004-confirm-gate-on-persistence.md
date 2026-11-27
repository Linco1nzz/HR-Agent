# 0004. 确认闸门放在落库动作上

Status: Accepted (2026-11-24)

仓库现状是生成结果不落库（JD / 评分标准 / 面试方案只返回预览），只有简历评分落库。决定：
`generate_*` 与 `score_resume` 作为免确认工具执行并产出；新增 `save_resource` 把产物落库，
与 `edit_resource`、`delete_resource` 一起作为 `require_confirm` 工具，Worker 进入
`waiting_confirm` 后退出，确认后才真正写库。理由：把确认闸门放在真正的写库动作上，既符合
SPEC 的 `require_confirm` 规则，又不让 AI 产出在用户审阅前污染数据库。
