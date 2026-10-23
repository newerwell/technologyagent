# 每阶段 GitHub 交付规则

用户已指定仓库：https://github.com/newerwell/technologyagent.git，并授权每阶段完成后上传。正常开发分支为main，远程为origin；当前空仓库的首次提交为工程规划基线，不计作P00。

## 1. 什么才算阶段完成

阶段任务完成 → 相称检查和必要交互验收完成 → 更新说明与证据 → 审查diff → 明确路径暂存 → commit → push → 远程SHA核对 → 创建并推送阶段标签 → 报告交付。

禁止把“本地提交”“已注册工具”“已生成计划”写成阶段上传成功。必要外部验收未执行时如实保留not_run，按阶段spec判断能否完成本地交付。

阶段代码和文档都进入同一次阶段交付；可以有中间本地提交，但不能将未通过检查的提交推成已完成阶段。默认每阶段至少一个汇总提交，例如`feat(p04): complete approved procurement order flow`。

## 2. 每阶段必须包含

- 本阶段新增/修改源码、必要锁文件、相称测试。
- 新增/修改模块的中文README：职责、公开接口、例子、错误/限制、验证命令。
- 阶段spec任务状态、共享接口/布局变化、`evidence/Pxx.md`。
- `docs/delivery/STATUS.md`中的阶段状态、实际检查和已知缺口。

evidence与STATUS在提交前写实际测试输出和`delivery_state=ready_to_push`。提交本身不尝试包含自己的SHA。上传成功的证据以远程分支、标签和向用户报告的链接为准；后续提交可在STATUS记录上一阶段SHA。

## 3. 推送与核对

以下为实施阶段的操作约定，不表示当前已执行：

```powershell
git status --short
git diff --check
# 查看完整diff，并按阶段显式列出要暂存的文件/目录
git add -- <reviewed-path-1> <reviewed-path-2>
git diff --cached --stat
git diff --cached --check
git commit -m "feat(p00): complete foundation and verification"
git push origin main
git rev-parse HEAD
git ls-remote origin refs/heads/main
git tag -a phase-p00 -m "P00 accepted and delivered"
git push origin refs/tags/phase-p00
git ls-remote origin refs/tags/phase-p00 'refs/tags/phase-p00^{}'
```

核对规则：默认远程main等于本地交付HEAD；若已出现后续远程提交，fetch后验证交付SHA仍为origin/main祖先，不能盲目覆盖。annotated tag必须核对解引用后的commit SHA，不把tag对象SHA当commit SHA。P01–P09依次使用phase-p01至phase-p09；标签已存在则核对，不移动或重写标签。

阶段交付完成需要分支和阶段标签均在远程存在。初始规划提交直接推main，不创建phase-p00标签，避免把文档当可运行工程。

## 4. 失败与混合工作区

- 推送失败：保留本地commit，报告准确原因和SHA；恢复后重新推送同一提交，不伪造远程链接。
- 远程领先：先fetch并检查变更，按实际情况rebase/merge，重新执行受影响检查；绝不force push。
- 工作区有无关改动：只暂存本阶段明确文件；不reset、clean或覆盖用户改动。
- 远程分支保护拒绝直接推送：保留提交并说明平台限制；采用仓库允许的分支/PR路径，不通过关闭保护绕过，阶段仍要等到相应远程交付完成。
- 密钥、.env、运行库、日志、未经处理的用户数据不得入库。合成fixtures、无敏感信息的验收摘要及必要截图可入库；大体积产物按需给样例或外部存储链接。

## 5. 每阶段向用户报告

说明完成了什么、实际执行了哪些检查、还有哪些未验证；附GitHub commit链接、阶段tag链接和下一阶段。上传是用户已明确要求的交付动作，无需每阶段重新问是否push。
