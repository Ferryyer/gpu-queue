import 'dart:async';
import 'dart:convert';
import 'package:dartssh2/dartssh2.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:server_box/core/gpu_queue/protocol.dart';
import 'package:server_box/core/gpu_queue/session.dart';
import 'package:server_box/data/model/server/server_private_info.dart';
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
        request: (path, body, connect) async {
          final current = ref.read(serverProvider(id));
          final SSHClient ssh;
          if (connect) {
            ssh = await ref
                .read(serverProvider(id).notifier)
                .ensureShellClient();
          } else {
            final client = current.client;
            if (client == null || client.isClosed) {
              throw StateError('SSH 未连接，请点击连接 / 重试');
            }
            ssh = client;
          }
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
  final channel = await ssh.execute(QueueProtocol.command(path, body));
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
