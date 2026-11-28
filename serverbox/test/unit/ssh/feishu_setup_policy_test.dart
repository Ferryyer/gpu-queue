import 'package:flutter_test/flutter_test.dart';
import 'package:server_box/core/ssh_bundle/feishu_setup_policy.dart';
import 'package:server_box/data/model/server/custom.dart';
import 'package:server_box/data/model/server/geo.dart';
import 'package:server_box/data/model/server/server_private_info.dart';
import 'package:server_box/data/model/server/ssh_credential.dart';

const _host = 'cpu.example.test';
const _port = 2222;
const _username = 'test-member';

Spi _server(
  String id, {
  String host = _host,
  int port = _port,
  String username = _username,
}) => Spi(
  id: id,
  name: id,
  ssh: SshCredential(ip: host, port: port, user: username),
);

void main() {
  group('member server script directory', () {
    const homeDir = '~/.config/server_box';

    test('defaults new servers and existing servers without custom fields', () {
      final existing = _server('existing');

      expect(memberServerCustom().scriptDir, homeDir);
      expect(memberServerCustom(existing.custom).scriptDir, homeDir);
    });

    test('fills missing and blank directories while keeping other fields', () {
      for (final scriptDir in [null, '', '   ']) {
        final custom = ServerCustom(
          cmds: const {'example': 'true'},
          preferTempDev: 'sensor-example',
          tempIsCelsius: true,
          logoUrl: 'https://assets.example.test/icon.png',
          netDev: 'eth1',
          scriptDir: scriptDir,
          geo: GeoCoord.tryNew(0, 0),
          diskCountsNetwork: true,
        );

        expect(memberServerCustom(custom).toJson(), {
          ...custom.toJson(),
          'scriptDir': homeDir,
        });
      }
    });

    test('keeps an explicit directory', () {
      const custom = ServerCustom(
        scriptDir: '~/.local/share/example',
        netDev: 'eth1',
      );

      expect(memberServerCustom(custom), same(custom));
    });
  });

  group('existing Feishu server', () {
    final linked = _server('linked', host: 'old-cpu.example.test');
    final exact = _server('exact');
    final servers = [
      _server('wrong-user', username: 'another-member'),
      _server('wrong-port', port: 2200),
      linked,
      exact,
    ];

    Spi? find(Iterable<Spi> servers, List<Map<String, dynamic>> devices) =>
        findFeishuServer(
          servers: servers,
          devices: devices,
          username: _username,
          host: _host,
          port: _port,
        );

    test(
      'prefers a linked server even after the lease and SSH address change',
      () {
        expect(
          find(servers, [
            {'username': _username, 'server_id': 'deleted'},
            {
              'username': _username,
              'server_id': linked.id,
              'lease_expires_at': 1,
            },
          ]),
          same(linked),
        );
      },
    );

    test(
      'falls back to the full SSH tuple if no device links this account',
      () {
        expect(
          find(servers, [
            {'username': 'another-member', 'server_id': linked.id},
            {'username': _username, 'server_id': 'deleted'},
            {'username': _username, 'server_id': linked.id, 'revoked': true},
            {'username': _username},
          ]),
          same(exact),
        );
      },
    );

    test('returns no match if the SSH tuple also differs', () {
      expect(find(servers.where((server) => server != exact), []), isNull);
    });
  });

  group('default Feishu task service', () {
    final servers = [_server('saved'), _server('selected')];

    for (final (currentId, expectedId) in [
      ('', 'saved'),
      ('deleted', 'saved'),
      ('saved', 'saved'),
      ('selected', 'selected'),
    ]) {
      test(
        'resolves ${currentId.isEmpty ? 'empty selection' : currentId} to $expectedId',
        () {
          expect(
            feishuQueueServerId(
              currentId: currentId,
              savedId: 'saved',
              servers: servers,
            ),
            expectedId,
          );
        },
      );
    }
  });

  group('Feishu login button', () {
    final expiry = DateTime.utc(2030, 1, 1);
    final seconds = expiry.millisecondsSinceEpoch ~/ 1000;

    test('offers reauthorization while any unrevoked lease is active', () {
      final devices = [
        {'lease_expires_at': seconds - 1},
        {'lease_expires_at': seconds + 1, 'revoked': true},
        {'lease_expires_at': seconds},
      ];

      expect(
        feishuLoginButtonLabel(
          devices,
          now: expiry.subtract(const Duration(milliseconds: 1)),
        ),
        '重新授权连接',
      );
      expect(feishuLoginButtonLabel(devices, now: expiry), '飞书登录');
      expect(
        feishuLoginButtonLabel(
          devices,
          now: expiry.add(const Duration(milliseconds: 1)),
        ),
        '飞书登录',
      );
    });

    test(
      'offers login with missing, pending, malformed, or revoked records',
      () {
        expect(feishuLoginButtonLabel([], now: expiry), '飞书登录');
        expect(
          feishuLoginButtonLabel([
            {'expires_at': seconds + 1},
            {'lease_expires_at': '${seconds + 1}'},
            {'lease_expires_at': seconds + 1, 'revoked': true},
          ], now: expiry),
          '飞书登录',
        );
      },
    );
  });
}
