import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:dartssh2/dartssh2.dart';
import 'package:fl_lib/fl_lib.dart';
import 'package:flutter/scheduler.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:server_box/core/utils/proxy_command_socket.dart';
import 'package:server_box/core/utils/server.dart';
import 'package:server_box/data/model/app/error.dart';
import 'package:server_box/data/model/server/server.dart';
import 'package:server_box/data/model/server/server_private_info.dart';
import 'package:server_box/data/model/server/ssh_credential.dart';
import 'package:server_box/data/model/server/try_limiter.dart';
import 'package:server_box/data/provider/server/all.dart';
import 'package:server_box/data/provider/server/single.dart';
import 'package:server_box/data/res/store.dart';

const _denial = r"printf 'Permission denied (publickey).\n' >&2; exit 23";
const _authError = 'ProxyCommand: Permission denied (publickey).';

Spi _server(String command, {String id = 'proxy-fixture'}) => Spi(
  id: id,
  name: id,
  autoConnect: true,
  ssh: SshCredential(
    ip: 'target.example',
    user: 'fixture',
    proxyCommand: command,
  ),
);

Matcher _sshError(SSHErrType type, Matcher message) => isA<SSHErr>()
    .having((err) => err.type, 'type', type)
    .having((err) => err.message, 'message', message);

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('process-backed ProxyCommand', () {
    Future<SSHClient> connect(String command) =>
        genClient(_server(command), knownHostFingerprints: {});

    test(
      'reports a sanitized gateway denial and no success breadcrumb',
      () async {
        final sink = _ConnectionDiagnostics();
        Diag.install(sink);
        addTearDown(Diag.uninstall);

        await expectLater(
          connect(r"""
            exec 1>&-
          printf '%4096s\n' '' >&2
          printf 'Could not open config file /synthetic/config: Permission denied\n' >&2
          printf 'fixture@gateway.example: Permission den' >&2
          printf 'ied (publickey).\r\n' >&2
          exit 23
        """),
          throwsA(_sshError(SSHErrType.auth, equals(_authError))),
        );
        expect(sink.events, ['ssh connect', 'ssh connect failed']);
      },
    );

    test('reports a nonzero exit without exposing local stderr', () async {
      await expectLater(
        connect(r"""
          printf 'Could not open config file /synthetic/config: Permission denied\n' >&2
          exit 17
        """),
        throwsA(
          _sshError(
            SSHErrType.connect,
            allOf(
              startsWith('ProxyCommand exited with code 17.'),
              isNot(contains('/synthetic/config')),
            ),
          ),
        ),
      );
    });

    test(
      'a clean EOF before the banner still reports a transport abort',
      () async {
        await expectLater(
          connect('exit 0'),
          throwsA(
            isA<SSHAuthAbortError>().having(
              (err) => err.reason,
              'reason',
              isNull,
            ),
          ),
        );
      },
    );

    test('forwards input and output unchanged', () async {
      final socket = await ProxyCommandSocket.connect(
        command: 'exec cat',
        host: 'target.example',
        port: 22,
        user: 'fixture',
        originalHost: 'proxy-fixture',
        jump: '',
      );
      addTearDown(socket.close);
      final echo = socket.stream.first;
      socket.sink.add(utf8.encode('synthetic payload\n'));
      await socket.flush();
      expect(utf8.decode(await echo), 'synthetic payload\n');
    });
  }, skip: !(Platform.isLinux || Platform.isMacOS));

  group('proxy connection retries', () {
    late Directory directory;
    late ProviderContainer container;

    setUpAll(() async {
      directory = await Directory.systemTemp.createTemp('proxy-auth-fixture-');
      Paths.doc = directory.path;
    });

    tearDownAll(() => directory.delete(recursive: true));

    setUp(() async {
      SqliteDb.openInMemory();
      await Stores.init();
      container = ProviderContainer();
    });

    tearDown(() async {
      container.dispose();
      TryLimiter.clear();
      await getIt.reset();
      await SqliteDb.close();
    });

    test(
      'polling pauses on auth while manual refresh and edits dial again',
      () async {
        final attempts = File('${directory.path}/attempts');
        final quotedPath = "'${attempts.path.replaceAll("'", "'\"'\"'")}'";
        final spi = _server('printf x >> $quotedPath; $_denial');
        Stores.server.put(spi);
        final servers = container.read(serversProvider.notifier);
        final provider = serverProvider(spi.id);
        SSHErr statusError() => container.read(provider).status.err! as SSHErr;

        Stores.setting.maxRetryCount.put(0);
        await servers.refresh();
        expect(container.read(provider).conn, ServerConn.failed);
        expect(statusError(), _sshError(SSHErrType.auth, equals(_authError)));
        await servers.refresh();
        await servers.refresh();
        expect(await attempts.readAsString(), 'x');

        Stores.setting.maxRetryCount.put(1);
        expect(TryLimiter.canTry(spi.id), isFalse);
        await servers.refresh(onlyFailed: true);
        expect(await attempts.readAsString(), 'xx');

        final manual = servers.refresh(spi: spi);
        _drawFrame();
        await manual;
        expect(await attempts.readAsString(), 'xxx');

        final retry = Completer<void>();
        final subscription = container.listen(provider, (_, next) {
          if (next.conn == ServerConn.failed &&
              (next.status.err as SSHErr?)?.type == SSHErrType.connect &&
              !retry.isCompleted) {
            retry.complete();
          }
        });
        addTearDown(subscription.close);
        await servers.updateServer(
          spi,
          _server('printf y >> $quotedPath; exit 0'),
        );
        _drawFrame();
        await retry.future.timeout(const Duration(seconds: 5));
        expect(await attempts.readAsString(), 'xxxy');

        Stores.setting.maxRetryCount.put(0);
        await servers.refresh();
        expect(await attempts.readAsString(), 'xxxyy');
      },
    );

    test('only transient shell errors retry after the cooldown', () async {
      Stores.setting.maxRetryCount.put(1);
      final rejected = _server(_denial);
      final dropped = _server('exit 0', id: 'transport-fixture');
      Stores.server.put(rejected);
      Stores.server.put(dropped);
      var rejectedDials = 0;
      var droppedDials = 0;
      final rejectedNotifier = container.read(
        serverProvider(rejected.id).notifier,
      );
      final droppedNotifier = container.read(
        serverProvider(dropped.id).notifier,
      );
      Future<void> checkRejected() => expectLater(
        rejectedNotifier.ensureShellClient(
          interactive: false,
          onDial: () => rejectedDials++,
        ),
        throwsA(_sshError(SSHErrType.auth, equals(_authError))),
      );
      Future<void> checkDropped() => expectLater(
        droppedNotifier.ensureShellClient(
          interactive: false,
          onDial: () => droppedDials++,
        ),
        throwsA(isA<SSHAuthAbortError>()),
      );

      await checkRejected();
      await checkDropped();
      await Future<void>.delayed(const Duration(seconds: 31));
      await checkRejected();
      await checkDropped();
      expect(rejectedDials, 1);
      expect(droppedDials, 2);
    }, timeout: const Timeout(Duration(minutes: 1)));
  }, skip: !(Platform.isLinux || Platform.isMacOS));
}

void _drawFrame() {
  SchedulerBinding.instance.handleBeginFrame(null);
  SchedulerBinding.instance.handleDrawFrame();
}

class _ConnectionDiagnostics extends DiagnosticsSink {
  final events = <String>[];

  @override
  void breadcrumb(Breadcrumb crumb) {
    if (crumb.message.startsWith('ssh connect')) events.add(crumb.message);
  }
}
