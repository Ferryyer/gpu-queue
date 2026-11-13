import 'dart:async';
import 'dart:convert';
import 'package:dartssh2/dartssh2.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:server_box/core/gpu_queue/protocol.dart';
import 'package:server_box/core/gpu_queue/session.dart';
import 'package:server_box/data/model/server/server_private_info.dart';
import 'package:server_box/data/provider/server/all.dart';
import 'package:server_box/data/provider/server/single.dart';
import 'package:server_box/data/res/store.dart';
export 'package:server_box/core/gpu_queue/session.dart';

final queueControllerProvider = Provider.autoDispose
    .family<QueueSession, String>((ref, id) {
      final session = QueueSession(
        auto: Stores.setting.gpuQueueAuto.fetch(),
        saveAuto: Stores.setting.gpuQueueAuto.put,
        identity: () {
          final ssh = ref.read(serverProvider(id)).spi.sshOn;
          return jsonEncode([
            ssh?.ip,
            ssh?.port,
            ssh?.user,
            ssh?.jumpIds,
            ssh?.proxyCommand,
          ]);
        },
        request: (path, body, connection) async {
          final current = ref.read(serverProvider(id));
          final client = current.client;
          if (client != null && !client.isClosed) {
            return queueSshRequest(client, path, body);
          }
          final interactive = connection == QueueConnection.interactive;
          final autoConnect = connection == QueueConnection.automatic &&
              current.spi.autoConnect &&
              !ref.read(serversProvider).manualDisconnectedIds.contains(id);
          if (!interactive && !autoConnect) {
            throw StateError('SSH 未连接，请点击连接 / 重试');
          }
          final ssh = await ref.read(serverProvider(id).notifier).ensureShellClient(
            interactive: interactive,
            resetRetries: interactive,
          );
          return queueSshRequest(ssh, path, body);
        },
      );
      ref.onDispose(session.dispose);
      return session;
    });

Future<Map<String, dynamic>> queueSshRequest(
  SSHClient ssh,
  String path,
  Map<String, dynamic>? body,
) async {
  final opening = ssh.execute(QueueProtocol.command(path, body));
  final channel = await opening.timeout(
    const Duration(seconds: 18),
    onTimeout: () {
      unawaited(opening.then<void>((lateChannel) => lateChannel.close(),
          onError: (_, _) {}));
      throw TimeoutException('SSH 任务通道打开超时');
    },
  );
  try {
    final output = StringBuffer();
    var size = 0;
    final out = channel.stdout
        .cast<List<int>>()
        .transform(utf8.decoder)
        .forEach((chunk) {
          size += chunk.length;
          if (size > 9 * 1024 * 1024) {
            channel.close();
            throw StateError('任务响应过大');
          }
          output.write(chunk);
        });
    final err = channel.stderr.drain<void>();
    await Future.wait([
      out,
      err,
      channel.done,
    ]).timeout(const Duration(seconds: 18));
    if (channel.exitCode != 0) {
      throw StateError(
        '任务服务需要远端 Python 3 与私有 socket；SSH 命令失败（${channel.exitCode}）',
      );
    }
    return QueueProtocol.decode(output.toString());
  } finally {
    channel.close(); // channel only; never close the borrowed transport
  }
}
