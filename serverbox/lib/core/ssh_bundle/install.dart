import 'dart:async';
import 'dart:convert';
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

  /// Check only the SSH greeting, without authenticating to the CPU or
  /// running a CPU command. Forced gateways are tried first; the fixed legacy
  /// entry is used only when the original template does not produce SSH.
  Future<String> resolveGateway(SshClientBundle bundle, String keyPath) async {
    for (final explicit in [false, true]) {
      if (!await _hasSshGreeting(bundle, explicit)) continue;
      await File(configPath).writeAsString(bundle.config(key: keyPath,
        known: '${directory.path}/known_hosts', config: configPath,
        explicitGateway: explicit), flush: true);
      return bundle.command(configPath, explicitGateway: explicit);
    }
    throw const FormatException('无法接通网关。请检查网络；加密私钥请先在 Mac 钥匙串或 ssh-agent 中解锁，然后重试。');
  }

  Future<bool> _hasSshGreeting(SshClientBundle bundle, bool explicit) async {
    final process = await Process.start('/usr/bin/ssh', ['-F', configPath, '-T',
      'markflow-gateway', if (explicit) ...bundle.gatewayEntry()]);
    final stderr = process.stderr.drain<void>();
    var received = '';
    try {
      await process.stdout.transform(utf8.decoder).firstWhere((chunk) {
        received += chunk;
        if (received.length > 8192) throw const FormatException('网关响应无效');
        return RegExp(r'(^|\n)SSH-2\.0-').hasMatch(received);
      }).timeout(const Duration(seconds: 8));
      return true;
    } catch (_) {
      return false;
    } finally {
      process.kill(ProcessSignal.sigkill);
      await process.exitCode;
      await stderr;
    }
  }

  static Future<void> _chmod(String mode, String path) async {
    final result = await Process.run('/bin/chmod', [mode, path]);
    if (result.exitCode != 0) throw const FileSystemException('无法保护 SSH 配置文件');
  }
}
