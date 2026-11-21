# RustDesk 自编译版

在 **GitHub Actions** 上编译的 [RustDesk](https://github.com/rustdesk/rustdesk) 分支：把自有的 ID/API 服务器配置在编译时写入二进制，产出可直接分发的安装包，不依赖官方公共服务器。

> 定制改动、维护流程、每次升级的冲突处理记录见 [CUSTOM.md](CUSTOM.md)。

## 项目定位

- **只在 GitHub Actions 编译**：不提供本地编译流程，也不承诺与上游一致的开发/调试体验。
- **服务器配置内置且不可见**：编译时通过 Secrets 注入 `RENDEZVOUS_SERVER`、`RS_PUB_KEY`，可选注入 `API_SERVER`；客户端不提供切换/查看服务器配置的入口。
- **产物私有发布**：默认发布到独立的私有 Release 仓库，避免公开泄露 ID 服务器信息。
- **双形态**：普通版保留完整窗口与托盘；Windows x64 额外提供 `-ui-invisible` 无感版。
- 本项目是个人/团队自用的定制分支，**与 RustDesk 官方无关**，不提供官方支持。

## 与上游版本的主要差异

| 维度 | 本版本 | 上游 |
| --- | --- | --- |
| ID/API 服务器 | 编译时内置，客户端不可见、不可切换 | 默认官方服务器，可在设置中修改 |
| 连接认证 | 未设固定密码时免密直连；设密码后校验 | 默认需要密码或点击同意 |
| CM 窗口 | 启动即最小化，不抢焦点、不置顶；用户可从任务栏恢复 | 连接时弹出并置顶，3 秒后最小化 |
| 无感版 | Windows x64 提供 `-ui-invisible`：无托盘、连接不显示 CM 窗口 | 无此形态 |
| 首帧鼠标同步 | 跳过初始 `(0,0)`，不会把远端光标拉到左上角 | 首帧可能把远端光标定位到左上角 |
| 其他 | 跳过 `secure_tcp` 以兼容 rustdesk-api；Android 包名等定制 | 原生行为 |

更细的改动与回归记录见 [CUSTOM.md](CUSTOM.md)。

## 连接认证行为

实现见 `src/server/connection.rs` 与 `src/client.rs`：

| 被控端设置 | 发起端连接时 |
| --- | --- |
| 未设置固定密码（接受方式为默认） | 直接连上，无需密码，也无需被控端确认 |
| 已设置固定密码 | 校验固定密码；未输入密码时等待被控端手动同意 |

注意事项：

- **未设置固定密码时，界面显示的一次性密码不再作为访问凭证**，任何知道 ID 的人都能连入。需要恢复点击确认时，把「接受方式」改为「仅点击同意」即可。
- 已设置固定密码后想恢复免密直连，清除固定密码即可。
- 已开启 2FA 时仍需输入验证码；IP 白名单等策略仍然生效。

## 窗口行为与无感版

### 普通版

- 被控端的 CM 窗口在连接时**最小化出现**，不抢焦点、不置顶。
- 用户仍可从任务栏或 Alt+Tab 恢复，权限、聊天、语音、提权、断开等功能保持原样。
- 标题栏 X 仍是“断开所有会话并退出 CM 进程”；只想保留会话时请使用最小化。

### Windows x64 无感版（`-ui-invisible`）

- 无托盘图标；连接时 CM 窗口不显示；安装完成和手动启动仍可打开主窗口查看 ID/设置。
- 与普通版同 app name、同版本，MSI 已启用 `AllowSameVersionUpgrades`，两个安装包可以互相覆盖。
- 仅支持 Windows x64，不构建 ARM64，也不影响其他平台。
- 限制：
  - 不适用于 `approve-mode=click`（点击审批）。无感版没有 CM 窗口可点 Accept，连接会挂起；请使用默认免密直连或固定密码。
  - 聊天/语音主动拉起时仍可能显示 CM 窗口，这是显式使用功能。
  - 与普通版同产品身份，自动更新可能把无感版覆盖成普通版；部署时建议关闭自动更新或固定使用 `-ui-invisible` 资产。

产物命名：

- 普通版：`rustdesk-<version>-x86_64.msi` / `.exe`
- 无感版：`rustdesk-<version>-x86_64-ui-invisible.msi` / `.exe`

## 构建与发布

### 1. 配置 GitHub Secrets

在仓库 **Settings → Secrets and variables → actions → Repository secrets** 中添加：

| Secret 名称 | 说明 | 必填 |
| --- | --- | --- |
| `RENDEZVOUS_SERVER` | ID 服务器地址（含端口，如 `your-server.com:21116`） | ✅ |
| `RS_PUB_KEY` | 服务器公钥（Base64 编码，位于服务器 `id_ed25519.pub`） | ✅ |
| `API_SERVER` | API 服务器地址（如 `https://api.your-server.com`） | 可选 |
| `ANDROID_SIGNING_KEY` | Base64 编码的 keystore 文件 | 可选 |
| `ANDROID_ALIAS` | keystore 别名 | 可选 |
| `ANDROID_KEY_STORE_PASSWORD` | keystore 密码 | 可选 |
| `ANDROID_KEY_PASSWORD` | key 密码 | 可选 |
| `RELEASE_REPO` | 私有仓库名（如 `inkss/rustdesk-releases`） | 可选 |
| `RELEASE_PAT` | Fine-grained PAT，对私有仓库有 Contents 读写权限 | 可选 |
| `SYNC_PAT` | Classic PAT（`repo` + `workflow`），用于同步后推送变更并触发编译 | 可选 |

> ID 和 Key 必须同时填写，否则会出现 key 不匹配。都不填则等同于官方客户端。
>
> 未配置私有仓库时，产物发布到当前仓库的 Releases。

### 2. 触发编译

- **自动触发**：每天 UTC 03:23（北京时间 11:23）检查上游新版本，有更新则自动合并并编译。
- **手动触发**：Actions → Sync Upstream Release → Run workflow（或直接触发 Build RustDesk）。
- **PR 合并触发**：解决冲突后合并 PR 时，commit 消息包含 `[build]` 即可自动编译。

命令行手动触发（`platforms` 可选 `all` / `windows` / `linux` / `android`）：

```bash
gh workflow run build.yml -R inkss/rustdesk --ref custom-build -f platforms=all
```

只补跑 Windows（包含普通版与无感版）：

```bash
gh workflow run build.yml -R inkss/rustdesk --ref custom-build -f platforms=windows
```

### 3. 下载产物

从 Releases 页面下载安装包（配置了私有仓库则去私有仓库的 Releases）：

- Windows：MSI + EXE（x86_64）；额外提供 `-ui-invisible` MSI + EXE
- Linux：DEB（x86_64 / aarch64）、RPM（x86_64 / aarch64）、Arch 包
- Android：APK（aarch64）

```bash
gh release download <version> -R inkss/rustdesk-releases -p "rustdesk-<version>-x86_64.deb"
```

## 编译平台配置

编辑 `.build-config.yml` 控制编译哪些平台：

```yaml
platforms:
  windows: true        # Windows x86_64（普通版 + 无感版，MSI + EXE）
  windows_arm64: false # Windows ARM64（需要 Flutter 3.44；无感版不构建 ARM64）
  linux: true          # Linux x86_64 + aarch64（DEB + RPM）
  android: true        # Android aarch64（APK）
```

## 工作流说明

| 工作流 | 触发方式 | 功能 |
| --- | --- | --- |
| `sync-upstream.yml` | 每天自动 / 手动 | 检查上游新版本，按需合并代码，触发编译 |
| `build.yml` | tag 推送 / 手动 dispatch / sync 调用 | 获取版本号，编译并发布到 Releases |
| `flutter-build.yml` | 被 `build.yml` 调用 | 实际编译逻辑（不直接触发） |

另有 `bridge.yml`（bridge 代码生成）与 `third-party-RustDeskTempTopMostWindow.yml`（Windows 置顶窗口组件）两个辅助工作流，详见 [CUSTOM.md](CUSTOM.md)。

## 上游同步与 PR 评审

每天自动检查上游仓库（[rustdesk/rustdesk](https://github.com/rustdesk/rustdesk)）的新版本：

- 无冲突 → 自动合并，触发编译。
- 已是最新 → 跳过，不触发编译。
- 有差异/冲突 → **自动创建 PR**，不会直接合入。

由于本仓库存在编译期服务器配置、连接认证、窗口行为、无感版等定制，上游每次发版**几乎必然存在差异**，需要逐项评审后再合并：

- 确认上游改动是否影响现有定制；
- 重新施加被覆盖的定制补丁；
- 检查 Android 包名、bridge、CI 配置等易冲突文件；
- 合并 commit 带 `[build]` 才会触发编译。

本仓库的实际 PR 评审与合并**由 AI 执行**，但流程仍然是“先评审、后合并”，不会无条件跟随上游。

## 参考内容

### 1. 生成 Android 签名密钥

```bash
# 1. 生成 keystore（只需执行一次）
keytool -genkey -v -keystore release.keystore \
  -keyalg RSA -keysize 2048 -validity 10000 \
  -alias rustdesk -storepass 你的密码 -keypass 你的密码 \
  -dname "CN=RustDesk, OU=Dev, O=RustDesk, L=Unknown, ST=Unknown, C=US"

# 2. 编码为 Base64
base64 -w 0 release.keystore   # Linux
# base64 release.keystore      # macOS
```

将输出的 Base64 字符串填入 `ANDROID_SIGNING_KEY`，别名填 `rustdesk`，密码填你设的值。

### 2. 私有 Release 仓库

公开仓库享受免费 Actions 额度，但 Releases 对所有人可见，存在泄露风险。

1\. 创建私有仓库

GitHub 上新建一个 private 仓库（如 `rustdesk-releases`），创建时勾选 **Initialize this repository with a README**[^1]。

[^1]: 仓库不能为空，否则 Release 创建会失败。

2\. 生成 PAT

GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token：

- Token name：随意（如 `rustdesk-release`）
- Expiration：选 1 年
- Repository access：选 `Only select repositories` → 选刚建的私有仓库
- Permissions → Repository permissions → **Contents**：`Read and write`

3\. 配置 Secret

在公开仓库 Settings → Secrets → Repository secrets 中添加：

| Secret 名称 | 值 |
| --- | --- |
| `RELEASE_REPO` | 私有仓库名（如 `inkss/rustdesk-releases`） |
| `RELEASE_PAT` | 上一步复制的 token |

配置后，编译产物会推送到私有仓库的 Releases，当前仓库不再有产物。

### 3. PAT 汇总

本项目需要两个 PAT，创建方式相同（GitHub → Settings → Developer settings → Personal access tokens）：

| Secret | 用途 | 推荐类型 | 权限 | 必填 |
| --- | --- | --- | --- | --- |
| `RELEASE_PAT` | 推送编译产物到私有仓库 | Fine-grained | 选私有仓库 → Contents: `Read and write` | 配置私有仓库时必填 |
| `SYNC_PAT` | 上游同步时推送变更、创建 PR 并触发编译 | Classic | 勾选 `repo` + `workflow` scope | 可选；未配置时回退 `GITHUB_TOKEN`，但自动触发编译会失效（`REPO_TOKEN` 作为历史 fallback 仍受支持） |

### 4. rustdesk-api 兼容

本版本兼容 [lejianwen/rustdesk-api](https://github.com/lejianwen/rustdesk-api)，跳过了 `secure_tcp` 与 `secure_tcp_required` 握手，登录 API 账户后不会出现连接超时。

## 安全与限制

- 未设置固定密码时，任何知道 ID 的人都能直接连接；公网部署请设置固定密码、开启 2FA 或配置 IP 白名单。
- 无感版没有托盘和连接窗口，本地用户无法从界面看到当前会话；仅建议用于自有/受管设备，并保留服务管理、卸载和审计手段。
- 普通版关闭 CM 窗口仍会结束所有会话；只想让远控继续时请使用最小化。
- 本项目依赖上游代码与第三方组件，使用前请自行评估合规与安全风险。
