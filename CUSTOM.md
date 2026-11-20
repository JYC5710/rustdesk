# RustDesk 自定义编译版 — 改动说明

本文件记录 fork 自 [rustdesk/rustdesk](https://github.com/rustdesk/rustdesk) 的所有自定义改动。

---

## 项目目标

编译内置自定义 ID 服务器配置的 RustDesk 客户端，支持全平台，自动同步上游新版本。

## 改动清单

### 1. 源码修改（`src/common.rs`）

| 位置 | 改动 | 作用 |
| --- | --- | --- |
| `global_init()` | 从 `RENDEZVOUS_SERVER` 环境变量写入 `PROD_RENDEZVOUS_SERVER` | 内置 ID 服务器地址 |
| `get_key()` | 从 `RS_PUB_KEY` 环境变量读取公钥 | 内置服务器公钥 |
| `get_api_server_()` | 从 `API_SERVER` 环境变量读取地址 | 内置 API 地址 |
| `check_software_update()` | 直接 return | 禁用官方更新检测 |
| `secure_tcp()` | 直接返回 `Ok(())` | 跳过握手，兼容 rustdesk-api |

使用 Rust `option_env!()` 宏在编译时读取环境变量，值来自 GitHub Secrets。

### 2. Android 修改

- **包名**：`com.carriez.flutter_hbb` → `com.rustdesk.app`（可与原版共存）
- **Kotlin 内容跟随上游**：只改 `package` 声明与 `namespace`，文件正文一律取上游同版本，不做本地改写
- **签名**：使用 `apksigner` 直接签名，支持自定义 keystore
- **防诈骗弹窗**：移除 `ScamWarningDialog` 的触发（自用版本不需要）

### 3. GitHub Actions 工作流

删除原有 11 个 workflow，新建 3 个 + 2 个辅助：

| 文件 | 作用 |
| --- | --- |
| `sync-upstream.yml` | 检查上游新版本，按需合并，触发编译 |
| `build.yml` | 编译入口，调用 flutter-build.yml |
| `flutter-build.yml` | 实际编译逻辑 |
| `bridge.yml` | flutter-rust-bridge 代码生成（辅助） |
| `third-party-RustDeskTempTopMostWindow.yml` | Windows 置顶窗口组件（辅助） |

**设计原则**：

- 平台控制：`.build-config.yml`
- Release 发布：`PUBLISH_RELEASE` 控制（默认 true）
- 产物去向：配置 `RELEASE_REPO` + `RELEASE_PAT` → 私有仓库；否则 → 当前仓库
- Actions Artifacts：不上传（仅 bridge-artifact 保留，编译依赖）

**sync-upstream 流程**：

```text
fetch upstream tags
       │
  上游 tag 的提交已在 HEAD 中？
      ╱              ╲
    是                否
     │                 │
  跳过           尝试合并到 custom-build
                    ╱          ╲
               成功             冲突
                │                │
         push + 触发 build    创建 upstream-merge-* 分支
                              自动解决部分冲突
                              创建 PR（含冲突详情）
```

**build.yml 流程**：

- `workflow_dispatch`：fetch upstream tags → 获取版本号 → Preflight 检查 → 清理旧 Release → 编译
- tag push：从 tag 名解析版本号 → 编译

**只编译指定平台（补跑用）**

`workflow_dispatch` 提供 `platforms` 入参（`all` / `windows` / `linux` / `android`，默认 `all`），
透传给 `flutter-build.yml` 后在 `read-config` 中覆盖 `.build-config.yml` 的平台开关。
非 `all` 时会**跳过「清理旧 Release」**，避免补跑时删掉其他平台已发布的资产：

```bash
gh workflow run build.yml -R inkss/rustdesk --ref custom-build -f platforms=android
```

若只是某支偶发失败、代码未变，优先用 `gh run rerun <run-id> -R inkss/rustdesk --failed`
（成功 job 的状态与产物保留，只重跑失败的那支）。

**Preflight 检查**

`prepare` job 中扫描 `flutter/android/` 下所有 `.kt` 文件的 `package` 声明，
命中 `carriez` / `flutter_hbb` 即失败并给出 file/line 注解，1 分钟内暴露必然失败的情况。
只检查 package 声明、不要求 package 与目录一致 —— 上游存在 `package hbb` 这类历史
遗留（Kotlin 不强制 package 匹配目录），它们能正常编译，不应被误报为错误。

**私有 Release 仓库**：公开仓库享受免费 Actions 额度，产物推送到私有仓库。配置 `RELEASE_REPO` + `RELEASE_PAT` 即可。

### 4. 编译平台配置

`.build-config.yml` 控制编译哪些平台，默认精简为 Windows / Linux / Android。

### 5. 连接认证逻辑

被控端未设置固定密码时免认证放行，一次性密码不再作为访问凭证。

| 位置 | 改动 | 作用 |
| --- | --- | --- |
| `src/server/connection.rs`（`on_message` 登录分支，`allow_logon_screen_password` 之后） | 新增分支：接受方式为默认（`ApproveMode::Both`）且 `Config::has_permanent_password()` 为 false 时，直接 `send_logon_response_and_keep_alive()` 授权并 `return true`，跳过 CM 确认 | 无固定密码时发起端直接连入 |
| `src/server/connection.rs`（`lr.password.is_empty()` 分支） | 仅密码模式收到空密码时回 `LOGIN_MSG_PASSWORD_EMPTY`，不再挂到 180s 超时 | 发起端能弹出密码框重试 |
| `src/client.rs`（`handle_hash`） | 对端 `Hash.salt` 为空（即对端无固定密码）时不弹 `input-password` | 发起端不再做无意义的密码输入 |

语义边界：

- 设置了固定密码 → 仍走原有 `validate_password` / CM 同意两条路径，行为不变；
- 用户把接受方式显式改为「仅点击同意」或「仅密码」时，新分支不生效（仅 `Both` 时生效）；
- 2FA、ID 白名单、隐私模式等既有策略仍然生效。

---

## 上游合并注意事项

1. `src/common.rs` 的改动在函数内部，上游重构时可能需要手动合并
2. `.github/workflows/` 完全重写，上游 CI 变更不影响本 fork
3. `.gitignore` 中 `rustdesk` 已改为 `/rustdesk`，注意新增文件是否被误忽略
4. Kotlin 版本需与 AGP 兼容（跟随上游配套版本，1.5.0 为 AGP 8.10.1 + Kotlin 2.1.21）
5. **上游 release tag 位于与 master 分叉的发布分支**（1.4.9 与 1.5.0 都是 master 的祖先，但 1.5.0 并不包含 1.4.9 之后的 master 提交）。因此合并 tag 时，git 可能把「上游移动过的代码块」与「fork 仍保留的旧位置副本」同时留下却不报冲突（v1.5.0 的 `login.dart` 就因此重复声明）。合并后需留意这类静默重复：以「与上游 1.x 文件对比」为准，重复块直接删掉（v1.5.1 又出现三处：`src/common.rs` 的 tests 模块整段重复、`libs/enigo/src/linux/nix_impl.rs` 同名测试函数、`libs/scrap/src/common/aom.rs` 重复 `mod tests`）。排查方法：对每个 `.rs`/`.dart` 文件统计「同名 `fn`/成员出现次数」，与上游同版本文件做差集，多出来的即为重复
6. 上游升级 vcpkg 版本后，需同步 `flutter-build.yml` 的 `VCPKG_COMMIT_ID`，否则 `vcpkg.json` 里的端口版本在旧版本库中找不到
7. **`GITHUB_TOKEN`（GitHub App 令牌）有三条限制**：① 无 `workflows` 权限（`permissions` 里不存在该键）→ 推送含 workflow 文件变更的 ref 会被拒绝，靠 sync 流程"提交前清空 `.github/workflows/` 并只还原本地备份"规避；② 由它发起的 API 调用不会创建新的 workflow run → `workflow_dispatch` 触发编译不会生效；③ 由它推送的 commit 不触发 push 事件的工作流。**需要在仓库 Secrets 配置 `SYNC_PAT`（Classic PAT，勾选 `repo` + `workflow`）**，才能让"无冲突自动合并 → 自动编译"真正闭环；未配置时 sync 仍可完成合并与建 PR，但自动触发编译会失败并输出告警（不会静默）
8. `actions/github-script` 的输入名是 `github-token`，写成 `token:` 会被静默忽略（不报错），导致 PAT 实际未生效
9. **Android Kotlin 文件不要保留旧版本**：合并时若把 `MainActivity.kt` 之类的文件当成"本地定制"整体保留旧内容，会静默丢失上游新增的 MethodChannel 分支（v1.5.1 就因此丢了 `DocumentPicker` 接入，见维护记录 2026-11-19），表现为 Dart 调用某个原生方法时收到 `No such method`。判定方法：把每个 `.kt` 文件与上游同版本文件（仅替换包名）逐字节对比，有差异就取上游
10. **改包名会连带 JNI 符号**：Kotlin 的 `external fun` 由 JVM 按 `Java_<包名>_<类名>_<方法名>` 查找，Rust 侧 `#[no_mangle] pub extern "system" fn Java_...` 必须同步改包名段（`_` 在符号里编码成 `_1`）。这类错误**编译期完全不报**，只在运行时抛 `UnsatisfiedLinkError` 立即闪退。`check_android_package.py` 已覆盖此类检查

---

## 上游版本升级实操清单（v1.5.0 经验）

按顺序执行，可覆盖一次完整升级：

1. **求真实合并基点**
   ```bash
   gh api "repos/rustdesk/rustdesk/compare/<新tag>...inkss:custom-build" -q '.merge_base_commit.sha'
   ```
   不要拿"上次合并的 tag 提交"当基点（v1.5.0 的真实基点是 `0c86d461`，不是 1.4.9 的 `59e044ff`）。基点错了，三方合并会把几乎所有文件都报成冲突（曾得到 84/86 全冲突的假象）。
2. **批量三方合并**：对每个冲突文件用 contents API 取 base / ours / theirs 三份，用 `git merge-file -p` 合并。单侧无改动直接采纳另一侧；两侧都有改动的按下面第 3 条逐条判定。先拿 1 个文件验证结果正确，再批量跑。
3. **冲突判定原则**
   | 对象 | 策略 |
   | --- | --- |
   | `src/common.rs` 编译期注入、Android 包名 `com.rustdesk.app` | 保留本地 |
   | `src/server/connection.rs`、`src/client.rs` 的连接认证改动 | 保留本地（见改动清单第 5 条），合并后逐段核对 |
   | `README.md` / `CLAUDE.md` / `CUSTOM.md` | 保留本地 |
   | `src/lang/*.rs` | 采用上游译文（上游删掉的条目不复活） |
   | `.gitignore` | 合并两侧 |
   | `libs/hbb_common` 子模块 gitlink | 采用上游（前向更新） |
   | `.github/workflows/` | **整体丢弃上游改动**，只保留本地备份集 |
   | core 其余文件（`rendezvous_mediator.rs`、`server.rs`…） | 采用上游 |
4. **合并后必查的"静默问题"**（git 不报冲突但会导致编译失败）
   - 重复声明：合并结果与上游同版本文件逐段对比。v1.5.0 的 `login.dart` 因上游移动代码块，两份都被留下，报 `already declared in this scope`
   - `vcpkg.json` 升版 → 必须同步 `flutter-build.yml` 的 `VCPKG_COMMIT_ID`（1.5.0 用上游的 2026.07.29 / `9e593bb1`）
   - 新版 vcpkg 的 SPDX 脚本要求 CMake 4.3+ → Linux ARM64 需 pip 装 `cmake==4.3.0`（`VCPKG_CMAKE_VERSION`，与上游一致）
   - 子模块指针更新后，本地也要 `git submodule sync --recursive && git submodule update --init --recursive`
5. **验证闭环**：`gh run list -R inkss/rustdesk --workflow build.yml` 看各平台 job，逐个按失败日志修 → 重跑；最后确认私有仓库 Release 的 assets 齐全。

---

## 维护记录

| 日期 | 改动 |
| --- | --- |
| 2026-06-07 | 初始版本：基于 v1.4.7 创建，实现编译时注入、自动同步、全平台编译 |
| 2026-06-08 | workflow 定型：sync 按提交历史判断、build 自动取版本号、tag 统一上游格式<br>支持私有 Release 仓库，移除 Actions Artifacts 上传<br>修复 Android 签名（改用 apksigner）与 Kotlin 兼容性<br>跳过 secure_tcp 握手以兼容 rustdesk-api；移除防诈骗弹窗 |
| 2026-06-09 | 重构 workflow：移除 UPLOAD_ARTIFACT/android-only，简化条件判断 |
| 2026-06-21 | sync-upstream 冲突按 UD/DU/UU 分类处理，PR 描述动态生成冲突详情 |
| 2026-06-23 | sync-upstream 保留本地 workflow 文件、PR 描述含上游 diff、改用 SYNC_PAT 创建 PR<br>修复 version 输出与版本解析，改为精确 git add，避免重复触发 |
| 2026-06-24 | 修复 Windows ARM64 编译：artifact 加平台后缀、补 Flutter 3.44 bridge、升级临时置顶窗口组件<br>Release 描述全平台统一<br>清理 workflow 的 --vram 传递、bridge cache key、模板注入与重复下载<br>新增 windows_arm64 开关（默认关闭） |
| 2026-07-09 | 合并 v1.4.9 时 commit 退出 128：根因是 hbb_common 子模块 gitlink 冲突且 CI 未检出子模块，补 gitlink 自动处理与索引兜底<br>随后编译失败：src 已升 1.4.9 而子模块指针未跟进，前移到 7e1c392c 后重编成功 |
| 2026-09-27 | 升级 v1.5.0（PR #7，86 冲突文件）：沿用「本地定制保留 + 其余采用上游」，修三处编译问题（VCPKG_COMMIT_ID、Linux ARM64 的 CMake 4.3、login.dart 重复声明），全平台成功<br>修复 sync-upstream：上游新 workflow 被带入导致 push 被拒（GITHUB_TOKEN 无 workflow 权限），改为提交前清空、提交后还原；github-script 入参应为 github-token，且 dispatch 需显式 PAT，已改为失败告警 |
| 2026-10-30 | 升级 v1.5.1（PR #8，163 冲突文件）：删除三处静默重复，子模块前移 fae47e02；Windows/Linux 成功，Android 失败（见下）<br>Android 失败：上游新增 5 个 Document*.kt 的 package 仍为 com.carriez.flutter_hbb，改为 com.rustdesk.app 后通过<br>编译反馈优化：dispatch 增加 platforms 入参、旧 Release 仅在 all 时清理、concurrency 分组细化、Linux 补 rust-cache、prepare 增加 Kotlin 包名检查 |
| 2026-11-19 | 升级 v1.5.3（113 冲突文件）：src/common.rs 重新施加 6 处定制（新增跳过 secure_tcp_required，否则自建 hbbs 连不上）；Android Kotlin 整文件对齐上游、仅保留包名；删除上游已移除文件与本地孤儿测试<br>Android 启动服务弹 No such method：整文件保留 MainActivity.kt 丢了上游 DocumentPicker 三处接入，document_require_log_folder 落到 else 分支；对齐上游后恢复 |
| 2026-11-20 | Android 启动闪退：DocumentLogs.setEnabled 的 JNI 符号仍带 carriez，包名改为 com.rustdesk.app 后 JVM 找不到；改正符号并给 check_android_package.py 增加 Rust 侧 JNI 扫描<br>新增免密直连：被控端未设固定密码时直接放行（一次性密码不再作凭证），设密码后仍校验或等待同意；改动 connection.rs 与 client.rs |
