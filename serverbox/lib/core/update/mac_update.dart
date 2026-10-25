import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:crypto/crypto.dart';
import 'package:fl_lib/fl_lib.dart';
import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';
import 'package:server_box/core/update/release.dart';

abstract final class MacAutoUpdate {
  static const _channel = MethodChannel('work.gpuqueue/update');
  static bool _active = false;

  static void configure() {
    if (!Platform.isMacOS) return;
    AppUpdateIface.installer = install;
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      try {
        await _channel.invokeMethod<void>('confirmLaunch');
        final status = await _channel.invokeMapMethod<String, dynamic>('lastResult');
        if (status == null) return;
        Toast.show(status['phase'] == 'complete'
            ? '已完成应用更新'
            : '更新未完成，已恢复上一版。${status['message'] ?? ''}');
      } catch (error) {
        Loggers.app.warning('Update result unavailable', error);
      }
    });
  }

  static Future<String> _metadata(HttpClient client, Uri uri) async {
    final req = await client.getUrl(uri).timeout(const Duration(seconds: 30));
    req.headers.set(HttpHeaders.acceptHeader, 'application/vnd.github+json');
    final response = await req.close().timeout(const Duration(seconds: 30));
    if (response.statusCode != 200) throw HttpException('更新服务返回 ${response.statusCode}');
    final bytes = <int>[];
    await for (final part in response.timeout(const Duration(seconds: 30))) {
      bytes.addAll(part);
      if (bytes.length > 4 * 1024 * 1024) throw const FormatException('更新信息过大');
    }
    return utf8.decode(bytes);
  }

  static Future<void> install(BuildContext context, String url, int build) async {
    if (_active) return;
    _active = true;
    final progress = ValueNotifier<(String, double?)>(('正在读取更新信息…', null));
    final client = HttpClient()..userAgent = 'GPU-Queue-Updater'..connectionTimeout = const Duration(seconds: 30);
    Directory? work;
    var handedOff = false;
    var nativeStarted = false;
    var dialogOpen = true;
    unawaited(context.showRoundDialog(
      title: '下载并安装更新', barrierDismiss: false,
      child: ValueListenableBuilder<(String, double?)>(
        valueListenable: progress,
        builder: (_, value, _) => SizedBox(width: 360, child: Column(mainAxisSize: MainAxisSize.min, children: [
          LinearProgressIndicator(value: value.$2), const SizedBox(height: 16),
          Text(value.$1), const SizedBox(height: 8),
          const Text('准备完成后会退出并重启应用，远端任务继续运行。'),
        ])),
      ),
    ).whenComplete(() => dialogOpen = false));
    try {
      final release = MacUpdateRelease.parse(await _metadata(client, MacUpdateRelease.apiFor(url, build)), url, build);
      work = await Directory.systemTemp.createTemp('gpuq-update-');
      final file = File('${work.path}/update.dmg');
      final req = await client.getUrl(release.url).timeout(const Duration(seconds: 30));
      final response = await req.close().timeout(const Duration(seconds: 30));
      if (response.statusCode != 200) throw HttpException('安装包下载返回 ${response.statusCode}');
      final sink = file.openWrite();
      var count = 0;
      try {
        await for (final part in response.timeout(const Duration(seconds: 45))) {
          count += part.length;
          if (count > release.bytes) throw const FormatException('安装包超过发布大小');
          sink.add(part);
          progress.value = ('正在下载 ${(count / release.bytes * 100).floor()}%', count / release.bytes);
        }
      } finally { await sink.close(); }
      if (count != release.bytes) throw const FormatException('安装包下载不完整，请重试');
      progress.value = ('正在校验安装包…', null);
      final digest = await sha256.bind(file.openRead()).first;
      if (digest.toString() != release.sha256) throw const FormatException('安装包 SHA-256 校验失败');
      progress.value = ('正在检查并准备安装…', null);
      nativeStarted = true;
      await _channel.invokeMethod<void>('install', {
        'dmg': file.path, 'sha256': release.sha256, 'build': build,
      });
      handedOff = true;
      progress.value = ('准备完成，正在重启应用…', null);
      // Normally the process exits in half a second. If a close/save prompt
      // prevents quitting, surface the helper's timeout instead of a stuck dialog.
      final quitDeadline = DateTime.now().add(const Duration(seconds: 75));
      while (DateTime.now().isBefore(quitDeadline)) {
        await Future<void>.delayed(const Duration(seconds: 1));
        final status = await _channel.invokeMapMethod<String, dynamic>('installStatus');
        if (status?['phase'] == 'failed') throw StateError(status?['message']?.toString() ?? '安装未完成');
      }
      await _channel.invokeMethod<void>('cancelInstall');
      throw StateError('应用未能退出，已取消更新。请关闭待保存窗口后重试。');
    } catch (error) {
      handedOff = false;
      if (context.mounted && dialogOpen) { context.popDialog(); dialogOpen = false; }
      if (context.mounted) {
        await context.showRoundDialog(title: '更新未完成', child: Text('$error\n当前应用仍保留，可重新检查更新后重试。'), actions: [Btn.ok()]);
      }
    } finally {
      client.close(force: true);
      if (!handedOff) {
        // Once started, the helper owns its workspace (including slow copies
        // that outlive a channel timeout). Never delete beneath that process.
        if (!nativeStarted && work != null && await work.exists()) await work.delete(recursive: true);
        if (context.mounted && dialogOpen) context.popDialog();
        // The progress dialog is removed before its notifier is disposed.
        await Future<void>.delayed(Duration.zero);
        progress.dispose();
      }
      if (!handedOff) _active = false;
    }
  }
}
