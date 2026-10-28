import 'dart:io';

import 'package:server_box/core/ssh_bundle/bundle.dart';

/// Private, app-owned files. The member's private key stays at its original path.
class InstalledSshBundle {
  InstalledSshBundle(this.directory, this.configPath);
  final Directory directory;
  final String configPath;

  static Future<InstalledSshBundle> create(SshClientBundle bundle, String keyPath, Directory parent) async {
    if (!Platform.isMacOS) throw const FormatException('配置包导入目前支持 Mac');
    if (!bundle.matchesPrivateKey(await SshClientBundle.readPrivateKey(keyPath))) {
      throw const FormatException('私钥与配置包中的公钥不匹配');
    }
    await parent.create(recursive: true);
    final directory = await parent.createTemp('client-');
    try {
      await _chmod('700', directory.path);
      final knownPath = '${directory.path}/known_hosts';
      final configPath = '${directory.path}/config';
      await File(knownPath).writeAsString(bundle.hostKeys.entries.map((e) => '${e.key} ${e.value}\n').join(), flush: true);
      await File(configPath).writeAsString(bundle.config(key: keyPath, known: knownPath, config: configPath), flush: true);
      await _chmod('600', knownPath);
      await _chmod('600', configPath);
      return InstalledSshBundle(directory, configPath);
    } catch (_) {
      await directory.delete(recursive: true);
      rethrow;
    }
  }

  static Future<void> _chmod(String mode, String path) async {
    final result = await Process.run('/bin/chmod', [mode, path]);
    if (result.exitCode != 0) throw const FileSystemException('无法保护 SSH 配置文件');
  }
}
