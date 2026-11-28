import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:fl_lib/fl_lib.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:server_box/core/ssh_bundle/bundle.dart';
import 'package:server_box/core/ssh_bundle/device_login.dart';
import 'package:server_box/core/ssh_bundle/feishu_setup_policy.dart';
import 'package:server_box/core/ssh_bundle/install.dart';
import 'package:server_box/core/utils/ssh_keygen.dart';
import 'package:server_box/data/model/server/server_private_info.dart';
import 'package:server_box/data/model/server/ssh_credential.dart';
import 'package:server_box/data/provider/server/all.dart';
import 'package:server_box/data/res/store.dart';
import 'package:url_launcher/url_launcher.dart';

class FeishuServerSetup extends ConsumerStatefulWidget {
  const FeishuServerSetup({super.key});

  static Future<void> open(BuildContext context) => Navigator.of(context).push<void>(
    MaterialPageRoute(builder: (_) => Scaffold(
      appBar: AppBar(title: const Text('飞书登录接入')),
      body: SingleChildScrollView(child: Center(child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 640),
        child: const Padding(padding: EdgeInsets.all(24), child: FeishuServerSetup()),
      ))),
    )),
  );

  @override
  ConsumerState<FeishuServerSetup> createState() => _FeishuServerSetupState();
}

class _FeishuServerSetupState extends ConsumerState<FeishuServerSetup> {
  // All entry points share one device authorization on this Mac.
  static bool _inProgress = false;
  final _client = DeviceLogin();
  DeviceLoginRequest? _request;
  Directory? _directory;
  bool _busy = false, _saved = false, _cancelled = false, _installing = false;
  String? _message, _error;
  List<({Directory directory, Map<String, dynamic> data})> _devices = [];
  Directory get _root => Directory('${Paths.doc}/ssh-client-bundles');

  @override
  void initState() {
    super.initState();
    unawaited(_loadDevices());
  }

  Future<void> _protect(String path, String mode) async {
    final result = await Process.run('/bin/chmod', [mode, path]);
    if (result.exitCode != 0) throw const FormatException('无法保护本机连接凭据');
  }

  Future<void> _writeRecord(Directory directory, Map<String, dynamic> data) async {
    final file = File('${directory.path}/session.json');
    await file.writeAsString(jsonEncode(data), flush: true);
    await _protect(file.path, '600');
  }

  Future<void> _loadDevices() async {
    final devices = <({Directory directory, Map<String, dynamic> data})>[];
    try {
      if (await _root.exists()) {
        await for (final entry in _root.list(followLinks: false)) {
          if (entry is! Directory || !entry.path.split('/').last.startsWith('device-')) continue;
          final file = File('${entry.path}/session.json');
          if (!await file.exists() || await file.length() > 8192) continue;
          try {
            final data = jsonDecode(await file.readAsString()) as Map<String, dynamic>;
            DeviceLoginRequest.fromJson(data);
            if (data['revoked'] != true) devices.add((directory: entry, data: data));
          } catch (_) { /* Unrelated or incomplete setup. */ }
        }
      }
      if (mounted) setState(() => _devices = devices);
    } catch (_) {
      if (mounted) setState(() => _error = '无法读取本机设备记录，请检查应用文件权限。');
    }
  }

  Future<void> _start() async {
    if (_busy) return;
    if (_inProgress) {
      setState(() => _error = '已有飞书登录正在进行，请先完成或取消。');
      return;
    }
    _inProgress = true;
    _cancelled = false;
    _request = null;
    _directory = null;
    setState(() { _busy = true; _saved = false; _error = null; _message = '正在准备此设备…'; });
    try {
      await _root.create(recursive: true);
      await _protect(_root.path, '700');
      final directory = await _root.createTemp('device-');
      _directory = directory;
      await _protect(directory.path, '700');
      final key = await generateSshKey(algorithm: SshKeyAlgorithm.ed25519, comment: '');
      if (_cancelled || !mounted) return;
      final keyFile = File('${directory.path}/identity');
      await keyFile.writeAsString(key.privatePem, flush: true);
      await _protect(keyFile.path, '600');
      final request = await _client.start(key.publicLine, DeviceLogin.verifier());
      _request = request;
      await _writeRecord(directory, request.toJson());
      if (_cancelled || !mounted) { await _client.revoke(request); return; }
      setState(() => _message = '在浏览器中用本人飞书登录，核对下方设备确认码。');
      if (!await launchUrl(request.uri, mode: LaunchMode.externalApplication)) {
        throw const FormatException('无法打开浏览器，请点击「打开授权网页」');
      }
      while (!_cancelled && mounted && DateTime.now().isBefore(request.expiresAt)) {
        Map<String, dynamic> result;
        try {
          result = await _client.poll(request);
        } catch (_) {
          if (mounted && !_cancelled) setState(() => _message = '连接登录服务失败，正在重试…');
          await Future<void>.delayed(Duration(seconds: request.interval));
          continue;
        }
        if (_cancelled || !mounted) return;
        switch (result['status']) {
          case 'ready':
            setState(() { _installing = true; _message = '正在保存个人服务器连接…'; });
            try {
              await _install(directory, keyFile.path, request, result);
            } finally {
              _installing = false;
            }
            return;
          case 'denied':
            throw const FormatException('设备授权已拒绝，可重新登录');
          case 'expired':
            throw const FormatException('授权已过期，请重新登录');
          case 'provisioning':
            setState(() => _message = '飞书身份已确认，正在准备个人服务器连接…');
          case 'unavailable':
            setState(() => _message = '个人服务器暂不可达，正在等待连接恢复…');
        }
        await Future<void>.delayed(Duration(seconds: request.interval));
      }
      if (!_cancelled && mounted) {
        throw const FormatException('授权已过期，请重新登录');
      }
    } catch (error) {
      if (mounted && !_cancelled) {
        setState(() => _error = error is FormatException
            ? error.message : '未能完成连接，请检查网络后重新登录。');
      }
    } finally {
      if (!_saved) await _cancelRequest();
      _inProgress = false;
      if (mounted) {
        setState(() => _busy = false);
        await _loadDevices();
      }
    }
  }

  Future<void> _install(Directory directory, String keyPath,
      DeviceLoginRequest request, Map<String, dynamic> result) async {
    final bundle = SshClientBundle.parse(base64Decode(result['bundle'] as String));
    if (!bundle.matchesPrivateKey(await SshClientBundle.readPrivateKey(keyPath))) {
      throw const FormatException('返回的设备公钥不匹配，请重新登录');
    }
    await _loadDevices();
    if (_cancelled || !mounted) return;
    final host = bundle.cpu['hostname']!;
    final port = int.parse(bundle.cpu['port']!);
    final existing = findFeishuServer(
      servers: Stores.server.fetch(),
      devices: _devices.map((device) => device.data),
      username: bundle.username,
      host: host,
      port: port,
    );
    if (existing != null) {
      final confirmed = await showDialog<bool>(context: context, builder: (context) => AlertDialog(
        title: const Text('更新现有服务器连接？'),
        content: Text('账号 ${bundle.username} 已配置为「${existing.name}」。确认后将使用本次飞书授权连接此服务器。'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('取消')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('更新连接')),
        ],
      ));
      if (confirmed != true) { _cancelled = true; return; }
    }
    if (_cancelled || !mounted) return;
    final installed = await InstalledSshBundle.create(bundle, keyPath, directory);
    final id = existing?.id ?? ShortId.generate();
    String? pinKey, previousPin, newPin;
    try {
      final proxy = await installed.resolveGateway(bundle, keyPath);
      if (_cancelled || !mounted) return;
      final hostKey = bundle.hostKeys['markflow-member-cpu']!;
      final known = Map<String, String>.from(Stores.setting.sshKnownHostFingerprints.fetch());
      pinKey = '$id::${hostKey.split(' ').first}';
      previousPin = known[pinKey];
      newPin = SshClientBundle.fingerprint(hostKey);
      known[pinKey] = newPin;
      await _writeRecord(directory, {...request.toJson(), 'server_id': id,
        'username': bundle.username, 'lease_expires_at': result['expires_at']});
      Stores.setting.sshKnownHostFingerprints.putSync(known);
      final credential = SshCredential(
        ip: host,
        port: port,
        user: bundle.username,
        keyPath: keyPath,
        proxyCommand: proxy,
      );
      final notifier = ref.read(serversProvider.notifier);
      final custom = memberServerCustom(existing?.custom);
      if (existing == null) {
        await notifier.addServer(Spi(
          id: id,
          name: '${bundle.username} · CPU',
          ssh: credential,
          custom: custom,
        ));
      } else {
        await notifier.updateServer(
          existing,
          existing.copyWith(ssh: credential, custom: custom),
        );
      }
      _saved = true;
      if (mounted) setState(() => _message = '${bundle.username} 的个人服务器已配置，正在连接。');
      try {
        final queueServer = Stores.setting.gpuQueueServer;
        final currentId = queueServer.fetch();
        final selectedId = feishuQueueServerId(
          currentId: currentId,
          savedId: id,
          servers: Stores.server.fetch(),
        );
        if (selectedId != currentId) queueServer.putSync(selectedId);
      } catch (_) {
        if (mounted) setState(() => _error = '服务器已保存。任务服务关联失败，请在任务页选择。');
      }
      await _retireReplacedDevices(id, directory);
    } catch (_) {
      final persisted = Stores.server.fetch().any((s) => s.id == id && s.ssh?.keyPath == keyPath);
      if (persisted) _saved = true;
      if (!persisted && pinKey != null) {
        final known = Map<String, String>.from(Stores.setting.sshKnownHostFingerprints.fetch());
        if (known[pinKey] == newPin) {
          if (previousPin == null) { known.remove(pinKey); }
          else { known[pinKey] = previousPin; }
          Stores.setting.sshKnownHostFingerprints.putSync(known);
        }
      }
      rethrow;
    }
  }

  Future<void> _retireReplacedDevices(String id, Directory current) async {
    await _loadDevices();
    for (final device in _devices.where((d) =>
        d.data['server_id'] == id && d.directory.path != current.path)) {
      try {
        await _client.revoke(DeviceLoginRequest.fromJson(device.data));
        await _writeRecord(device.directory, {...device.data, 'revoked': true});
      } catch (_) {
        if (mounted) setState(() => _error = '新连接已保存。旧设备退出尚未确认，可在设备列表重试退出。');
      }
    }
  }

  Future<void> _cancelRequest() async {
    final request = _request, directory = _directory;
    if (_saved || directory == null) return;
    try {
      if (request != null) await _client.revoke(request);
      if (await directory.exists()) await directory.delete(recursive: true);
      _request = null;
      _directory = null;
    } catch (_) {
      // A retained proof lets this screen retry revocation after a network failure.
      if (mounted) setState(() => _error = '退出尚未确认。请在下方设备列表重试退出。');
    }
  }

  Future<void> _logout(Directory directory, Map<String, dynamic> data) async {
    if (_busy) return;
    setState(() { _busy = true; _error = null; });
    try {
      await _client.revoke(DeviceLoginRequest.fromJson(data));
      final id = data['server_id'];
      final servers = Stores.server.fetch().where((s) => s.id == id &&
        s.ssh?.keyPath == '${directory.path}/identity');
      for (final server in servers) {
        ref.read(serversProvider.notifier).closeOneServer(server.id);
      }
      await _writeRecord(directory, {...data, 'revoked': true});
      await _loadDevices();
      if (mounted) setState(() { _saved = false; _message = '此设备的连接授权已退出。'; });
    } catch (_) {
      if (mounted) setState(() => _error = '退出未确认，请检查网络并重试。');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  void dispose() {
    _cancelled = true;
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (!Platform.isMacOS) return const SizedBox.shrink();
    final request = _request;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Text('用飞书连接个人服务器', style: Theme.of(context).textTheme.titleLarge),
      const SizedBox(height: 8),
      const Text('用本人飞书账号授权，自动配置服务器、终端和文件访问。'),
      const SizedBox(height: 16),
      FilledButton.icon(
        onPressed: _busy ? null : _start,
        icon: const Icon(Icons.login),
        label: Text(feishuLoginButtonLabel(
          _devices.map((device) => device.data),
          now: DateTime.now(),
        )),
      ),
      if (_busy) const Padding(padding: EdgeInsets.symmetric(vertical: 12), child: LinearProgressIndicator()),
      if (_message != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(_message!)),
      if (_busy && request != null) ...[
        const SizedBox(height: 12),
        SelectableText('设备确认码 ${request.userCode}', style: Theme.of(context).textTheme.titleMedium),
        Text('有效期至 ${request.expiresAt.toLocal().toString().split('.').first}'),
        Wrap(children: [
          TextButton(onPressed: () => launchUrl(request.uri, mode: LaunchMode.externalApplication), child: const Text('打开授权网页')),
          TextButton(onPressed: _installing ? null : () => setState(() { _cancelled = true; _message = '正在取消授权…'; }), child: const Text('取消')),
        ]),
      ],
      if (_error != null) Padding(padding: const EdgeInsets.only(top: 12),
          child: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error))),
      for (final device in _devices) ListTile(
        contentPadding: EdgeInsets.zero,
        title: Text(device.data['username'] as String? ?? '未完成的设备授权'),
        subtitle: device.data['lease_expires_at'] is int ? Text(
          (device.data['lease_expires_at'] as int) * 1000 <= DateTime.now().millisecondsSinceEpoch
              ? '授权已过期，请重新登录'
              : '授权至 ${DateTime.fromMillisecondsSinceEpoch((device.data['lease_expires_at'] as int) * 1000).toLocal().toString().split('.').first}') : null,
        trailing: TextButton(onPressed: _busy ? null : () => _logout(device.directory, device.data), child: const Text('退出此设备')),
      ),
    ]);
  }
}
