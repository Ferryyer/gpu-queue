import 'package:server_box/data/model/app/scripts/script_consts.dart';
import 'package:server_box/data/model/server/custom.dart';
import 'package:server_box/data/model/server/server_private_info.dart';

ServerCustom memberServerCustom([ServerCustom? custom]) {
  const scriptDir = ScriptConstants.scriptDirHome;
  if (custom == null) return const ServerCustom(scriptDir: scriptDir);
  if (custom.scriptDir?.trim().isNotEmpty == true) return custom;

  return ServerCustom(
    cmds: custom.cmds,
    preferTempDev: custom.preferTempDev,
    tempIsCelsius: custom.tempIsCelsius,
    logoUrl: custom.logoUrl,
    netDev: custom.netDev,
    scriptDir: scriptDir,
    geo: custom.geo,
    diskCountsNetwork: custom.diskCountsNetwork,
  );
}

Spi? findFeishuServer({
  required Iterable<Spi> servers,
  required Iterable<Map<String, dynamic>> devices,
  required String username,
  required String host,
  required int port,
}) {
  final serversById = {for (final server in servers) server.id: server};
  // An expired lease can still identify the server that should be reauthorized.
  for (final device in devices) {
    final id = device['server_id'];
    if (device['revoked'] == true ||
        device['username'] != username ||
        id is! String ||
        id.isEmpty) {
      continue;
    }
    final server = serversById[id];
    if (server != null) return server;
  }

  return servers.where((server) {
    final ssh = server.ssh;
    return ssh != null &&
        ssh.ip == host &&
        ssh.port == port &&
        ssh.user == username;
  }).firstOrNull;
}

String feishuQueueServerId({
  required String currentId,
  required String savedId,
  required Iterable<Spi> servers,
}) {
  if (currentId.isEmpty || !servers.any((server) => server.id == currentId)) {
    return savedId;
  }
  return currentId;
}

String feishuLoginButtonLabel(
  Iterable<Map<String, dynamic>> devices, {
  required DateTime now,
}) {
  final hasActiveLease = devices.any((device) {
    final expiresAt = device['lease_expires_at'];
    return device['revoked'] != true &&
        expiresAt is int &&
        expiresAt > now.millisecondsSinceEpoch ~/ 1000;
  });
  return hasActiveLease ? '重新授权连接' : '飞书登录';
}
