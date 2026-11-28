import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:path/path.dart' as p;
import 'package:server_box/core/extension/context/locale.dart';
import 'package:server_box/data/model/app/error.dart';
import 'package:server_box/data/model/server/server.dart';
import 'package:server_box/data/provider/server/single.dart';
import 'package:server_box/data/res/status.dart';
import 'package:server_box/view/page/server/card/notices.dart';

import '../../helpers/spi_fixture.dart';

void main() {
  late Directory scratch;
  late File identity;
  late File session;
  const authError = SSHErr(
    type: SSHErrType.auth,
    message: 'Synthetic SSH authentication error',
  );
  const connectError = SSHErr(
    type: SSHErrType.connect,
    message: 'Synthetic SSH connection error',
  );

  setUp(() {
    scratch = Directory.systemTemp.createTempSync('server-notice-');
    final device = Directory(p.join(scratch.path, 'device-example'))
      ..createSync();
    identity = File(p.join(device.path, 'identity'))..createSync();
    session = File(p.join(device.path, 'session.json'));
  });

  tearDown(() => scratch.deleteSync(recursive: true));

  void writeLease(DateTime expiresAt, {bool revoked = false}) {
    session.writeAsStringSync(
      jsonEncode({
        'lease_expires_at': expiresAt.millisecondsSinceEpoch ~/ 1000,
        'revoked': revoked,
      }),
    );
  }

  ServerState server({
    String? keyPath,
    SSHErr? err,
    ServerConn conn = ServerConn.disconnected,
    bool sshEnabled = true,
  }) => ServerState(
    spi: spiFixture(
      name: 'Example Server',
      ip: 'server.example.test',
      user: 'example-user',
      keyPath: keyPath ?? identity.path,
    ).copyWith(sshEnabled: sshEnabled),
    status: InitStatus.status..err = err,
    conn: conn,
  );

  test('expired device notice explains recovery and keeps SSH diagnostics', () {
    writeLease(DateTime.utc(2000));
    final srv = server(err: connectError, conn: ServerConn.failed);
    final notice = ServerNotice.of(srv, deviceBundlesRoot: scratch.path);
    final card = ServerNotice.onCard(srv, deviceBundlesRoot: scratch.path);

    expect(notice.kind, ServerNoticeKind.feishuLease);
    expect(notice.title, '飞书登录授权已过期');
    expect(notice.text, contains('授权到期时间'));
    expect(notice.text, contains('重新通过飞书登录可恢复服务器状态监控'));
    expect(notice.mono, connectError.message);
    expect(card?.title, notice.title);
    expect(notice.canReloginFeishu(onMacOS: true), isTrue);
    expect(notice.canReloginFeishu(onMacOS: false), isFalse);
  });

  test('device logout is visible on the card even before an SSH error', () {
    writeLease(DateTime.utc(2100), revoked: true);
    final srv = server();
    final notice = ServerNotice.of(srv, deviceBundlesRoot: scratch.path);
    final card = ServerNotice.onCard(srv, deviceBundlesRoot: scratch.path);

    expect(notice.title, '此设备的飞书授权已退出');
    expect(notice.mono, isEmpty);
    expect(card?.title, notice.title);
    expect(notice.canReloginFeishu(onMacOS: true), isTrue);
  });

  test('still-authorized devices offer sign-in only for SSH auth errors', () {
    writeLease(DateTime.utc(2100));
    final authFailure = ServerNotice.of(
      server(err: authError),
      deviceBundlesRoot: scratch.path,
    );
    final connectionFailure = ServerNotice.of(
      server(err: connectError),
      deviceBundlesRoot: scratch.path,
    );

    expect(authFailure.kind, ServerNoticeKind.failed);
    expect(authFailure.title, l10n.authFailTip);
    expect(authFailure.canReloginFeishu(onMacOS: true), isTrue);
    expect(authFailure.canReloginFeishu(onMacOS: false), isFalse);
    expect(connectionFailure.canReloginFeishu(onMacOS: true), isFalse);
  });

  test('ordinary SSH auth errors keep their existing text and diagnostics', () {
    final ordinary = p.join(scratch.path, 'id_example');
    final notice = ServerNotice.onCard(
      server(keyPath: ordinary, err: authError),
      deviceBundlesRoot: scratch.path,
    )!;

    expect(notice.kind, ServerNoticeKind.failed);
    expect(notice.title, l10n.authFailTip);
    expect(notice.mono, authError.message);
    expect(notice.canReloginFeishu(onMacOS: true), isFalse);
  });

  test(
    'a ready connection or disabled SSH does not report lease expiration',
    () {
      writeLease(DateTime.utc(2000));
      expect(
        ServerNotice.onCard(
          server(conn: ServerConn.finished),
          deviceBundlesRoot: scratch.path,
        ),
        isNull,
      );
      final disabled = ServerNotice.of(
        server(err: connectError, sshEnabled: false),
        deviceBundlesRoot: scratch.path,
      );
      expect(disabled.kind, ServerNoticeKind.failed);
      expect(disabled.canReloginFeishu(onMacOS: true), isFalse);
    },
  );
}
