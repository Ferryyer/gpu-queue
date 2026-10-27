# Apple 公证发布准备

当前状态：尚未开通 Apple Developer Program；本机没有有效的代码签名身份，仓库没有配置发布密钥。2.0.2007 的内部包不是已公证包。

## 账号持有人需要完成

1. 由个人或公司加入 [Apple Developer Program](https://developer.apple.com/programs/enroll/)。公司分发建议使用公司主体，账号持有人自行完成身份验证、协议和付款。
2. 账号开通后，由账号持有人申请 **Developer ID Application** 证书，签名机器必须同时持有对应私钥。Apple Development、Mac App Distribution 或 ad-hoc 签名不能替代它。
3. 在发布机器安全配置 notarization 凭据，优先使用 `notarytool store-credentials` 存入钥匙串。只向发布人员提供钥匙串配置名称与 Team ID；不要将密码、p12、p8 或私钥写入源码、聊天或发布附件。

## 后续发布验收

- 使用完整 Xcode 的发布机器或受保护的 CI，保留当前 GPU Queue 的 bundle ID、数据目录和凭据兼容配置。
- 为 GPU Queue 准备独立的 Developer ID 签名配置。上游 ServerBox 的 iCloud entitlement 属于上游开发团队，不可直接复用；当前 `ReleaseDmg.entitlements` 也不能直接作为本产品的生产签名配置。
- 由内向外签署所有 Mach-O 库、框架、辅助更新器和应用；启用 hardened runtime 与安全时间戳，验证体系结构和签名。不能用 `codesign --deep --sign -` 代替 Developer ID 签名。
- 向 Apple 提交应用压缩包，等待 `notarytool` 明确返回 `Accepted`；将票据装订到应用，再制作并签署 DMG。提交 DMG，确认 Accepted，装订并验证 DMG 票据。
- 在启用 Gatekeeper 的 Mac 上检查签名、`spctl` 评估及票据；从真实下载包安装，验证首次打开、SSH、SFTP、钥匙串访问与应用内升级/回滚。
- 所有步骤通过后才生成 `notarized: true` 的发布清单、最终 SHA-256 和正式发布包。保留提交 ID 与验收结果；失败不得回退成“已公证”或关闭系统安全检查。

当前内部打包脚本显式输出 `notarized: false`。已有上游发布脚本面向 ServerBox，需在取得本产品开发团队信息后适配并实测；不能直接执行默认的上游发布目标。

官方依据：[Developer ID](https://developer.apple.com/developer-id/)、[Notarizing macOS software before distribution](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)、[Customizing the notarization workflow](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow)。
