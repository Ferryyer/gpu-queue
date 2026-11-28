import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:path/path.dart' as p;
import 'package:server_box/core/ssh_bundle/device_lease.dart';

void main() {
  late Directory scratch;
  late String root;
  late Directory device;
  late File identity;
  late File session;
  final expiresAt = DateTime.utc(2030, 1, 2, 3, 4);
  final expiresAtSeconds = expiresAt.millisecondsSinceEpoch ~/ 1000;

  setUp(() {
    scratch = Directory.systemTemp.createTempSync('device-lease-');
    root = p.join(scratch.path, 'ssh-client-bundles');
    device = Directory(p.join(root, 'device-example'))
      ..createSync(recursive: true);
    identity = File(p.join(device.path, 'identity'))..createSync();
    session = File(p.join(device.path, 'session.json'));
  });

  tearDown(() => scratch.deleteSync(recursive: true));

  DeviceLease? read({String? keyPath, DateTime? now}) => DeviceLease.read(
    keyPath ?? identity.path,
    bundlesRoot: root,
    now: now ?? expiresAt,
  );

  test('lease exposes its expiration and expires at the exact boundary', () {
    session.writeAsStringSync(
      jsonEncode({
        'lease_expires_at': expiresAtSeconds,
        'server_id': 'server-example',
        'username': 'example-user',
        'code_verifier': 'synthetic-verifier',
      }),
    );
    final lease = read(
      now: expiresAt.subtract(const Duration(milliseconds: 1)),
    )!;

    expect(lease.state, DeviceLeaseState.valid);
    expect(lease.expiresAt!.toUtc(), expiresAt);
    expect(lease.toString(), isNot(contains('synthetic-verifier')));
    expect(read()!.state, DeviceLeaseState.expired);
    expect(
      read(now: expiresAt.add(const Duration(milliseconds: 1)))!.state,
      DeviceLeaseState.expired,
    );
  });

  test('explicit revocation takes precedence and can stand on its own', () {
    session.writeAsStringSync(
      jsonEncode({'lease_expires_at': expiresAtSeconds, 'revoked': true}),
    );
    final afterExpiry = read()!;
    expect(afterExpiry.state, DeviceLeaseState.revoked);
    expect(afterExpiry.expiresAt!.toUtc(), expiresAt);
    expect(
      read(now: expiresAt.subtract(const Duration(days: 1)))!.state,
      DeviceLeaseState.revoked,
    );

    session.writeAsStringSync('{"revoked":true}');
    expect(read()!.state, DeviceLeaseState.revoked);
    expect(read()!.expiresAt, isNull);
  });

  test('ordinary keys and paths outside the expected layout are ignored', () {
    session.writeAsStringSync('{"revoked":true}');
    final ordinary = Directory(p.join(root, 'ordinary-ssh'))..createSync();
    final nonDeviceKey = File(p.join(ordinary.path, 'identity'))..createSync();
    File(p.join(ordinary.path, 'session.json'))
        .writeAsStringSync('{"revoked":true}');

    final sibling = Directory(p.join('${root}-other', 'device-example'))
      ..createSync(recursive: true);
    final siblingKey = File(p.join(sibling.path, 'identity'))..createSync();
    File(p.join(sibling.path, 'session.json'))
        .writeAsStringSync('{"revoked":true}');
    final traversingKey = p.join(
      ordinary.path,
      '..',
      'device-example',
      'identity',
    );

    expect(read(keyPath: nonDeviceKey.path), isNull);
    expect(read(keyPath: siblingKey.path), isNull);
    expect(read(keyPath: traversingKey), isNull);
  });

  test('missing, malformed and unsafe lease records are ignored', () {
    expect(read(), isNull);
    for (final contents in [
      '{',
      '[]',
      '{"expires_at":$expiresAtSeconds}',
      '{"lease_expires_at":"$expiresAtSeconds"}',
      '{"lease_expires_at":9223372036854775807}',
      '{"lease_expires_at":$expiresAtSeconds,"revoked":"true"}',
    ]) {
      session.writeAsStringSync(contents);
      expect(read(), isNull, reason: contents);
    }
    session.writeAsBytesSync([0xff]);
    expect(read(), isNull);
  });

  test('files are limited to 8192 bytes', () {
    session.writeAsStringSync('{"revoked":true}'.padRight(8192));
    expect(read()!.state, DeviceLeaseState.revoked);
    session.writeAsStringSync('{"revoked":true}'.padRight(8193));
    expect(read(), isNull);

    session.writeAsStringSync('{"revoked":true}');
    identity.writeAsStringSync(' '.padRight(8193));
    expect(read(), isNull);
  });

  test(
    'links are ignored at every level of the bundle',
    () {
      session.writeAsStringSync('{"revoked":true}');
      final target = session.renameSync('${session.path}.other');
      final sessionLink = Link(session.path)..createSync(target.path);
      expect(read(), isNull);
      sessionLink.deleteSync();
      target.renameSync(session.path);

      final key = identity.renameSync('${identity.path}.other');
      final keyLink = Link(identity.path)..createSync(key.path);
      expect(read(), isNull);
      keyLink.deleteSync();
      key.renameSync(identity.path);

      final movedDevice = device.renameSync(
        p.join(scratch.path, 'device-other'),
      );
      final deviceLink = Link(device.path)..createSync(movedDevice.path);
      expect(read(), isNull);
      deviceLink.deleteSync();
      movedDevice.renameSync(device.path);

      final movedRoot = Directory(root).renameSync('${root}-other');
      Link(root).createSync(movedRoot.path);
      expect(read(), isNull);
    },
    skip: Platform.isWindows
        ? 'Windows link creation requires extra privileges'
        : false,
  );
}
