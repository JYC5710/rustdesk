# RustDesk 自定义编译版 — 改动记录与维护手册

本文件记录本 fork 自 [rustdesk/rustdesk](https://github.com/rustdesk/rustdesk) 的所有自定义改动，并说明构建发布、上游同步与版本升级的维护流程。

- 只想编译或下载安装包 → 看 [README.md](README.md)
- 想改代码、合并上游、排查 CI → 看本文

> 仓库：`inkss/rustdesk`（fork）｜上游：`rustdesk/rustdesk`｜当前基线：**v1.5.3**｜长期分支：`custom-build`

## 目录

1. 概览（定位、术语、快速索引）
2. 改动清单（源码、认证、Android、工作流、平台开关）
3. 构建与发布（触发、流水线、补跑、产物、环境限制）
4. 上游同步（自动化流程、冲突判定、静默问题）
5. 版本升级实操（前置条件、步骤、验证、回滚）
6. 排错手册
7. 维护记录

---

## 1. 概览

### 1.1 项目定位

编译内置自建 ID/API 服务器配置的 RustDesk 客户端，覆盖 Windows / Linux / Android，跟随上游版本自动同步。

| 项 | 值 |
| --- | --- |
| 上游 | [rustdesk/rustdesk](https://github.com/rustdesk/rustdesk) |
| 长期分支 | `custom-build` |
| 版本号来源 | 上游 tag（`workflow_dispatch` 时取最新 tag，去掉 `v` 前缀） |
| 构建 | GitHub Actions，本机不参与 |
| 产物 | 配置 `RELEASE_REPO` 时发到私有仓库 Releases，否则发到当前仓库 |

### 1.2 术语

| 术语 | 含义 |
| --- | --- |
| upstream | 上游仓库 `rustdesk/rustdesk` |
| hbbs | RustDesk 的 ID / 中继服务器 |
| bridge | `flutter_rust_bridge` 生成的 Dart ↔ Rust 胶水层，产物为 `src/bridge_generated*.rs` 与 `flutter/lib/generated_bridge.dart`，**被 gitignore，只在 CI 生成** |
| vcpkg | Windows / Android 的 C/C++ 依赖包管理器，版本由 `VCPKG_COMMIT_ID` 固定 |

### 1.3 快速索引

| 我要…… | 看 |
| --- | --- |
| 打一个包 / 发布版本 | [3.1](#31-触发方式) |
| 只补跑失败平台 | [3.3](#33-补跑与重跑) |
| 合并上游新版本 | [5](#5-版本升级实操) |
| 判断某个冲突该保留谁 | [4.2](#42-冲突判定) |
| 合并后编译失败但没冲突 | [4.3](#43-合并后必查的静默问题) |
| 排查某次 CI 失败 | [6](#6-排错手册) |
| 查某天改了什么 | [7](#7-维护记录) |

---

## 2. 改动清单

### 2.1 编译期注入（`src/common.rs`，6 处）

均通过 `option_env!` 在编译期读取环境变量，值来自 GitHub Secrets（见 README）。

| 位置 | 环境变量 | 行为 | 作用 |
| --- | --- | --- | --- |
| `global_init()` | `RENDEZVOUS_SERVER` | 写入 `PROD_RENDEZVOUS_SERVER` | 内置 ID 服务器地址（用户可在设置中覆盖） |
| `get_key()` | `RS_PUB_KEY` | 返回内置公钥 | 内置服务器公钥 |
| `get_api_server_()` | `API_SERVER` | 返回内置地址 | 内置 API 地址 |
| `check_software_update()` | — | 直接 `return` | 禁用官方更新检测 |
| `secure_tcp()` | — | 返回 `Ok(())` | 跳过可选握手，兼容 rustdesk-api |
| `secure_tcp_required()` | — | 返回 `Ok(())` | 跳过强制握手；上游 1.5.3 在注册/心跳/中继路径启用，自建 hbbs 不支持，不跳过会连不上 |

两个 `secure_tcp*` 只影响客户端与服务器之间的传输层加密，**不影响**客户端之间的端到端加密。

### 2.2 连接认证（`src/server/connection.rs`、`src/client.rs`）

被控端未设置固定密码时免认证放行，一次性密码不再作为访问凭证。

| 位置 | 改动 | 作用 |
| --- | --- | --- |
| `src/server/connection.rs`（`on_message` 登录分支，`allow_logon_screen_password` 之后） | 接受方式为默认（`ApproveMode::Both`）且 `Config::has_permanent_password()` 为 false 时，直接 `send_logon_response_and_keep_alive()` 授权并 `return true`，跳过 CM 确认 | 无固定密码时发起端直接连入 |
| `src/server/connection.rs`（`lr.password.is_empty()` 分支） | 仅密码模式收到空密码时回 `LOGIN_MSG_PASSWORD_EMPTY`，不再挂到 180s 超时 | 发起端能弹出密码框重试 |
| `src/client.rs`（`handle_hash`） | 对端 `Hash.salt` 为空（即对端无固定密码）时不弹 `input-password` | 发起端不再做无意义的密码输入 |

语义边界：

- 设置了固定密码 → 仍走原有 `validate_password` / CM 同意两条路径，行为不变；
- 用户把接受方式显式改为「仅点击同意」或「仅密码」时，新分支不生效（仅 `Both` 时生效）；
- 2FA、ID 白名单、隐私模式等既有策略仍然生效。

### 2.3 Android

- **包名**：`com.carriez.flutter_hbb` → `com.rustdesk.app`，可与原版共存。
- **Kotlin 正文跟随上游**：只改 `package` 声明与 `namespace`，文件内容一律取上游同版本，不做本地改写（原因见 [4.3](#43-合并后必查的静默问题)）。
- **JNI 符号同步**：包名改动后，Rust 侧 `Java_*` 导出符号必须同步改包名段，否则运行时闪退。
- **签名**：使用 `apksigner` 直接签名，keystore 由 Secrets 提供。
- **防诈骗弹窗**：移除 `ScamWarningDialog` 的触发。

### 2.4 GitHub Actions 工作流

上游自带的 workflow 已全部移除，只保留以下 5 个：

| 文件 | 作用 |
| --- | --- |
| `sync-upstream.yml` | 检查上游新版本，按需合并，触发编译 |
| `build.yml` | 编译入口，解析版本并调用 `flutter-build.yml` |
| `flutter-build.yml` | 实际编译逻辑 |
| `bridge.yml` | `flutter_rust_bridge` 代码生成（辅助） |
| `third-party-RustDeskTempTopMostWindow.yml` | Windows 置顶窗口组件（辅助） |

设计原则：

- 平台开关：`.build-config.yml`
- 是否发布：`PUBLISH_RELEASE`（默认 `true`）
- 产物去向：配置 `RELEASE_REPO` + `RELEASE_PAT` → 私有仓库；否则 → 当前仓库
- Actions Artifacts：不上传（仅 `bridge-artifact` 保留，各平台编译依赖）

### 2.5 编译平台开关

`.build-config.yml` 控制参与编译的平台，默认只开 Windows / Linux / Android：

```yaml
platforms:
  windows: true
  windows_arm64: false   # 需 Flutter 3.44
  linux: true
  android: true
  macos: false
  ios: false
  windows_sciter: false
  linux_sciter: false
  appimage: false
  flatpak: false
```

---

## 3. 构建与发布

### 3.1 触发方式

| 方式 | 条件 | 版本号来源 |
| --- | --- | --- |
| 手动 | `workflow_dispatch`（可选 `platforms`） | 上游最新 tag |
| 打 tag | push `v1.2.3` 或 `1.2.3` | tag 名 |
| PR 合并 | 合入 `custom-build` 且 commit 含 `[build]` | 分支名 `upstream-merge-<version>` |

```bash
# 全平台
gh workflow run build.yml -R inkss/rustdesk --ref custom-build -f platforms=all

# 只编 android
gh workflow run build.yml -R inkss/rustdesk --ref custom-build -f platforms=android
```

> `gh` 必须显式带 `-R inkss/rustdesk`：本仓库配置了 upstream 远程，`gh` 默认会解析到上游。

### 3.2 流水线阶段

`build.yml` → `prepare`：

1. 解析版本号（`workflow_dispatch` 会先 `git fetch upstream --tags`）
2. Preflight：扫描 `flutter/android/**/*.kt` 的 `package` 声明与 Rust 侧 `fn Java_*` 符号，命中 `carriez` / `flutter_hbb` 立即失败
3. 清理旧 Release（**仅 `platforms=all` 时执行**）

随后 `flutter-build.yml`：

1. `read-config`：用 `platforms` 覆盖 `.build-config.yml`
2. `generate-bridge`：分别生成 Flutter 3.22.3 与 3.44.0 两套 bridge
3. 各平台编译（Windows / Linux x86_64 / Linux aarch64 / Android）
4. 发布到 Releases

### 3.3 补跑与重跑

- **只补跑某平台**：`platforms=windows|linux|android`。非 `all` 会跳过「清理旧 Release」，避免删掉其他平台已发布的资产。
- **代码未变、只是偶发失败**：优先重跑失败 job，成功 job 的状态与产物保留。

```bash
gh run rerun <run-id> -R inkss/rustdesk --failed
```

### 3.4 产物与发布

- Release tag 与版本号同名（如 `1.5.3`），**同名资产直接覆盖**，不保留历史构建。
- 典型资产：`rustdesk-<ver>-x86_64.msi/.exe`、`rustdesk-<ver>-x86_64/-aarch64.deb`、`rustdesk-<ver>-0.x86_64/-aarch64.rpm`、`rustdesk-<ver>-aarch64.apk`、Arch 包。
- 配置了 `RELEASE_REPO` 时，「清理旧 Release」只作用于**当前公开仓库**（`GITHUB_TOKEN` 的权限范围）；发布仓库既不删旧 release 也不改 `publishedAt`，靠同名资产覆盖。

```bash
gh release view 1.5.3 -R inkss/rustdesk-releases --json assets --jq '.assets[].name'
```

### 3.5 环境限制（易踩）

| 限制 | 后果 | 应对 |
| --- | --- | --- |
| `GITHUB_TOKEN` 无 `workflows` 权限 | 推送含 workflow 变更的 ref 会被拒 | sync 流程提交前清空 `.github/workflows/`，提交后还原本地备份；日常合并不要手动带 workflow 变更 |
| `GITHUB_TOKEN` 发起的 API 调用不创建 run | `workflow_dispatch` 触发编译无效 | 配置 `SYNC_PAT`（Classic PAT，`repo` + `workflow`） |
| `GITHUB_TOKEN` 推送的 commit 不触发 push 事件 | 自动编译断链 | 同上，用 `SYNC_PAT` |
| `actions/github-script` 入参名是 `github-token` | 写成 `token:` 被静默忽略，PAT 不生效 | 统一用 `github-token` |
| 本地缺 `src/bridge_generated.rs` | 本地无法完整编译 Flutter 包 | 不要本地编译，走 CI；也不要手动跑 `flutter_rust_bridge_codegen` |

---

## 4. 上游同步

### 4.1 自动化流程（`sync-upstream.yml`）

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

每天 UTC 03:23 自动执行，也可手动触发。

### 4.2 冲突判定

| 对象 | 策略 |
| --- | --- |
| `src/common.rs` 的 6 处注入 | 保留本地（见 [2.1](#21-编译期注入srccommonrs6-处)）；改动都在函数体内，上游重构这些函数时需手动重新施加 |
| `src/server/connection.rs`、`src/client.rs` 的连接认证改动 | 保留本地（见 [2.2](#22-连接认证srcserverconnectionrssrcclientrs)），合并后逐段核对 |
| `README.md` / `CLAUDE.md` / `CUSTOM.md` | 保留本地 |
| `src/lang/*.rs` | 采用上游译文（上游删掉的条目不复活） |
| `.gitignore` | 合并两侧 |
| `libs/hbb_common` 子模块 gitlink | 采用上游（前向更新） |
| `.github/workflows/` | **整体丢弃上游改动**，只保留本地 5 个 |
| Android Kotlin 文件 | 采用上游，只保留包名 `com.rustdesk.app` |
| core 其余文件（`rendezvous_mediator.rs`、`server.rs`…） | 采用上游 |

### 4.3 合并后必查的静默问题

git 不报冲突、但会导致编译失败或运行时崩溃。合并后逐项过一遍：

| 检查项 | 症状 | 处理 |
| --- | --- | --- |
| **重复声明** | `already declared in this scope` / 同名 `fn` 冲突 | 上游 tag 位于与 master 分叉的发布分支，git 可能把「上游移动过的代码块」与「fork 保留的旧副本」同时留下。以上游同版本文件为准做差集，多出的删掉 |
| **Kotlin 包名** | 编译报 `Unresolved reference`，或运行弹 `No such method` | 上游新增的 `Document*.kt` 等文件 `package` 仍是 `com.carriez.flutter_hbb`，改为 `com.rustdesk.app`。Preflight 已覆盖 |
| **JNI 符号** | 运行即闪退：`UnsatisfiedLinkError: No implementation found for ...` | Kotlin 包名改了但 Rust 侧 `Java_*` 符号没改。Preflight 已覆盖 |
| **vcpkg 版本** | 端口版本在版本库中不存在 | `vcpkg.json` 升版后同步 `flutter-build.yml` 的 `VCPKG_COMMIT_ID` |
| **CMake 版本** | 新版 vcpkg 的 SPDX 脚本报错 | 同步 `VCPKG_CMAKE_VERSION`（当前 `4.3.0`，与上游一致） |
| **子模块指针** | 编译缺符号 | 采用上游 gitlink 后，本地执行 `git submodule sync --recursive && git submodule update --init --recursive` |
| **Flutter 版本** | bridge 生成失败或引擎不匹配 | 同步 `FLUTTER_VERSION` / `ANDROID_FLUTTER_VERSION`（当前 `3.24.5`） |
| **gitignore 误伤** | 新增的二进制或脚本没有被 git 跟踪 | `.gitignore` 的 `rustdesk` 规则已改为 `/rustdesk`（只忽略根目录产物）；合并后确认新文件没被误忽略 |

当前工具链常量集中在 `.github/workflows/flutter-build.yml` 顶部（`FLUTTER_VERSION`、`VCPKG_COMMIT_ID`、`VCPKG_CMAKE_VERSION`）。

---

## 5. 版本升级实操

### 5.1 前置条件

- `gh` 已登录，具备 `repo` + `workflow` 权限
- 本地已配置 `upstream` 远程并能 `git fetch upstream --tags`
- 子模块已初始化（`git submodule update --init --recursive`）
- 已读 [4.2](#42-冲突判定) 与 [4.3](#43-合并后必查的静默问题)

### 5.2 步骤

1. **求真实合并基点**

   ```bash
   gh api "repos/rustdesk/rustdesk/compare/<新tag>...inkss:custom-build" -q '.merge_base_commit.sha'
   ```

   不要拿「上次合并的 tag 提交」当基点（v1.5.0 的真实基点是 `0c86d461`，不是 1.4.9 的 `59e044ff`）。基点错了会得到大面积假冲突（曾出现 84/86 全冲突）。

2. **批量三方合并**

   对每个冲突文件用 contents API 取 base / ours / theirs 三份，`git merge-file -p` 合并。单侧无改动直接采纳另一侧；两侧都有改动按 [4.2](#42-冲突判定) 判定。先验证一个文件，再批量执行。

3. **逐项核对静默问题**

   按 [4.3](#43-合并后必查的静默问题) 过一遍，重点是与上游同版本文件做差集找重复。

4. **提交并推送**

   ```bash
   git push origin custom-build
   ```

5. **触发编译**

   ```bash
   gh workflow run build.yml -R inkss/rustdesk --ref custom-build -f platforms=all
   ```

6. **按失败日志逐支修复**

   单平台失败用 `platforms=<平台>` 补跑；纯偶发失败用 `gh run rerun --failed`。

### 5.3 验证闭环

```bash
gh run list  -R inkss/rustdesk --workflow build.yml --limit 3
gh run view  <run-id> -R inkss/rustdesk
gh release view <version> -R inkss/rustdesk-releases --json assets --jq '.assets[].name'
```

验收标准：四个编译 job 全绿 + Release 资产齐全（Windows / Linux x86_64 / Linux aarch64 / Android）。

### 5.4 回滚

| 场景 | 处理 |
| --- | --- |
| 编译失败但已合入 | 从上一个良好 commit 重新 dispatch，不要用 revert 上游提交的方式回退 |
| 已发布产物有问题 | 旧资产已被覆盖，只能取历史版本的 Release，或从旧 commit 重编 |
| tag / Release 需要重建 | 删除 tag 与 Release 后重新 dispatch；配置了 `RELEASE_REPO` 时需到私有仓库手动删 |

---

## 6. 排错手册

| 症状 | 根因 | 处理 |
| --- | --- | --- |
| Android 启动即闪退，`UnsatisfiedLinkError` | JNI 符号包名未跟随 | 按 Preflight 提示把 `Java_*` 的包名段改为 `com_rustdesk_app` |
| 启动服务弹 `No such method` | Kotlin 文件被整文件保留旧版，丢了上游 MethodChannel 分支 | 整文件对齐上游，只改包名 |
| 合并时 `git commit` 退出 128 | `hbb_common` 子模块 gitlink 冲突且 CI 未检出子模块 | 采用上游 gitlink，并用「逐个暂存遗留未合并项」兜底 |
| push 被拒，提示 workflow 权限 | `GITHUB_TOKEN` 无 `workflows` 权限 | 提交前清空 `.github/workflows/`，或用 `SYNC_PAT` |
| dispatch 后没有新 run | `GITHUB_TOKEN` 发起的 API 调用不创建 run | 用 `SYNC_PAT` 触发；失败时看 job summary 告警 |
| `vcpkg` 报端口版本不存在 | `VCPKG_COMMIT_ID` 未随 `vcpkg.json` 升级 | 同步为上游同版本值 |
| Linux ARM64 vcpkg 报 CMake 版本 | SPDX 脚本要求 CMake 4.3+ | 同步 `VCPKG_CMAKE_VERSION` 并 `pip install cmake==<ver>` |
| bridge 生成失败 / 引擎不匹配 | Flutter 版本不一致 | 同步 `FLUTTER_VERSION`；Windows ARM64 用 3.44 分支 |
| Preflight 误报 `package hbb` | 上游历史遗留，Kotlin 不强制 package 匹配目录 | 属正常现象，检查脚本只拦 `carriez` / `flutter_hbb` |

---

## 7. 维护记录

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
