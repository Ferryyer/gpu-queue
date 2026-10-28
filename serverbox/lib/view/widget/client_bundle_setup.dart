import 'dart:io';

import 'package:desktop_drop/desktop_drop.dart';
import 'package:file_picker/file_picker.dart';
import 'package:fl_lib/fl_lib.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:server_box/core/ssh_bundle/bundle.dart';
import 'package:server_box/core/ssh_bundle/install.dart';
import 'package:server_box/data/model/server/server_private_info.dart';
import 'package:server_box/data/model/server/ssh_credential.dart';
import 'package:server_box/data/provider/server/all.dart';
import 'package:server_box/data/res/store.dart';

class ClientBundleSetup extends ConsumerStatefulWidget {
  const ClientBundleSetup({super.key});
  @override
  ConsumerState<ClientBundleSetup> createState() => _ClientBundleSetupState();
}

class _ClientBundleSetupState extends ConsumerState<ClientBundleSetup> {
  SshClientBundle? _bundle;
  String? _keyPath, _error;
  bool _busy = false, _dragging = false, _saved = false;

  Future<void> _read(String path) async {
    if (_busy || _saved) return;
    setState(() { _busy = true; _error = null; _bundle = null; _keyPath = null; });
    try {
      final bundle = await SshClientBundle.read(path);
      final home = Platform.environment['HOME'];
      final key = home == null ? null : await bundle.findKey(Directory('$home/.ssh'));
      if (mounted) setState(() { _bundle = bundle; _keyPath = key; });
    } catch (e) {
      if (mounted) setState(() => _error = _message(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  static String _message(Object e) => e is FormatException ? e.message : '无法读取或保存配置，请检查文件和访问权限后重试。';

  Future<void> _pick({bool privateKey = false}) async {
    if (_busy || _saved) return;
    // Lock the form during the native picker so a simultaneous drop cannot
    // replace the bundle while the selected key is being verified.
    setState(() { _busy = true; _error = null; });
    String? zip;
    try {
      final result = await FilePicker.pickFile(
        type: privateKey ? FileType.any : FileType.custom,
        allowedExtensions: privateKey ? null : ['zip'],
        dialogTitle: privateKey ? '选择与配置包匹配的 SSH 私钥' : '选择服务器配置包',
      );
      final path = result?.path;
      if (path == null || !mounted) return;
      if (!privateKey) {
        zip = path;
      } else {
        if (!_bundle!.matchesPrivateKey(await SshClientBundle.readPrivateKey(path))) {
          throw const FormatException('这个私钥与配置包中的公钥不匹配，请选择分配给你的私钥。');
        }
        if (mounted) setState(() => _keyPath = path);
      }
    } catch (e) {
      if (mounted) setState(() => _error = _message(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
    if (zip != null && mounted) await _read(zip);
  }

  Future<void> _save() async {
    final bundle = _bundle, key = _keyPath;
    if (bundle == null || key == null || _busy || _saved) return;
    setState(() { _busy = true; _error = null; });
    InstalledSshBundle? installed;
    String? id;
    try {
      final duplicates = Stores.server.fetch().where((s) => s.ssh?.ip == bundle.cpu['hostname'] &&
        s.ssh?.port == int.parse(bundle.cpu['port']!) && s.ssh?.user == bundle.username);
      if (duplicates.isNotEmpty) throw const FormatException('这个账号的服务器已经存在，请到“服务器”中打开；原连接未修改。');
      installed = await InstalledSshBundle.create(bundle, key, Directory('${Paths.doc}/ssh-client-bundles'));
      final proxy = await installed.resolveGateway(bundle, key);
      id = ShortId.generate();
      final hostKey = bundle.hostKeys['markflow-member-cpu']!;
      final known = Map<String, String>.from(Stores.setting.sshKnownHostFingerprints.fetch());
      known['$id::${hostKey.split(' ').first}'] = SshClientBundle.fingerprint(hostKey);
      // Fail closed: persist the bundled pin before addServer starts connecting.
      Stores.setting.sshKnownHostFingerprints.putSync(known);
      final server = Spi(id: id, name: '${bundle.username} · CPU', ssh: SshCredential(
        ip: bundle.cpu['hostname']!, port: int.parse(bundle.cpu['port']!), user: bundle.username,
        keyPath: key, proxyCommand: proxy,
      ));
      if (!mounted) { throw const FormatException('导入已取消，请重新打开配置页'); }
      await ref.read(serversProvider.notifier).addServer(server);
      if (mounted) setState(() => _saved = true);
    } catch (e) {
      // If the provider wrote the server before failing, retain the referenced
      // files and pin. Otherwise remove only this attempt's temporary files.
      final persisted = id != null && Stores.server.fetch().any((s) => s.id == id);
      if (!persisted) {
        if (installed != null) await installed.directory.delete(recursive: true);
        if (id != null) {
          final known = Map<String, String>.from(Stores.setting.sshKnownHostFingerprints.fetch())
            ..removeWhere((k, _) => k.startsWith('$id::'));
          Stores.setting.sshKnownHostFingerprints.putSync(known);
        }
      }
      if (mounted) setState(() => _error = _message(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final bundle = _bundle;
    if (!Platform.isMacOS) return const Text('配置包导入目前支持 Mac。其他平台可在服务器页面手动添加 SSH 连接。');
    if (_saved) { return const Padding(padding: EdgeInsets.all(24), child: Column(children: [
      Icon(Icons.check_circle_outline, size: 40), SizedBox(height: 16),
      Text('服务器已添加'), SizedBox(height: 8), Text('正在尝试连接。你可以在“服务器”和“终端”中查看连接状态。'),
    ])); }
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      DropTarget(
        onDragEntered: (_) { if (!_busy) setState(() => _dragging = true); },
        onDragExited: (_) => setState(() => _dragging = false),
        onDragDone: (details) {
          setState(() => _dragging = false);
          if (_busy) return;
          if (details.files.length != 1) {
            setState(() => _error = '每次请拖入一个 ZIP 配置包');
            return;
          }
          _read(details.files.single.path);
        },
        child: Container(
          padding: const EdgeInsets.all(24),
          decoration: BoxDecoration(color: _dragging ? colors.primaryContainer : colors.surfaceContainerLow,
            border: Border.all(color: _dragging ? colors.primary : colors.outlineVariant), borderRadius: BorderRadius.circular(16)),
          child: Column(children: [
            const Icon(Icons.folder_zip_outlined, size: 36), const SizedBox(height: 12),
            Text(_dragging ? '松开以读取配置' : '把 client.zip 拖到这里', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8), const Text('自动填写账号、服务器和网关信息', textAlign: TextAlign.center),
            const SizedBox(height: 16), OutlinedButton(onPressed: _busy ? null : () => _pick(), child: const Text('选择配置包')),
          ]),
        ),
      ),
      if (_busy) const Padding(padding: EdgeInsets.symmetric(vertical: 16), child: LinearProgressIndicator()),
      if (bundle != null) ...[
        const SizedBox(height: 20), Text('连接预览', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8), SelectableText('账号：${bundle.username}\n服务器：${bundle.cpu['hostname']}:${bundle.cpu['port']}\n网关：${bundle.gateway['hostname']}:${bundle.gateway['port']}'),
        const SizedBox(height: 16), Text(_keyPath == null ? '还需要你的 SSH 私钥' : '已找到匹配的私钥'),
        const SizedBox(height: 4), Text(_keyPath ?? '配置包只有公钥。请选择管理员为你登记的私钥文件。'),
        TextButton(onPressed: _busy ? null : () => _pick(privateKey: true), child: Text(_keyPath == null ? '选择私钥' : '更换私钥')),
        Text('公钥指纹：${SshClientBundle.fingerprint(bundle.memberKey)}', style: Theme.of(context).textTheme.bodySmall),
        const SizedBox(height: 8), const Text('私钥留在原位置。若私钥有密码，网关连接需先在 Mac 钥匙串或 ssh-agent 中解锁。'),
        const SizedBox(height: 20), FilledButton(onPressed: _busy || _keyPath == null ? null : _save, child: const Text('保存并连接')),
      ],
      if (_error != null) Padding(padding: const EdgeInsets.only(top: 16), child: Text(_error!, style: TextStyle(color: colors.error))),
    ]);
  }
}
