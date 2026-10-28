import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:archive/archive.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:server_box/core/ssh_bundle/bundle.dart';
import 'package:server_box/core/ssh_bundle/install.dart';
import 'package:server_box/core/utils/ssh_keygen.dart';

const template = '''Host markflow-gateway
  HostName gateway.example.test
  Port 2222
  User gatewayuser
  HostKeyAlias markflow-member-gateway
  IdentityFile "@KEY@"
  IdentitiesOnly yes
  UserKnownHostsFile "@KNOWN@"
  StrictHostKeyChecking yes
  RequestTTY no
  ForwardAgent no
  ServerAliveInterval 30

Host markflow-cpu
  HostName personal-cpu
  Port 22223
  User @USER@
  HostKeyAlias markflow-member-cpu
  IdentityFile "@KEY@"
  IdentitiesOnly yes
  UserKnownHostsFile "@KNOWN@"
  StrictHostKeyChecking yes
  ForwardAgent no
  ServerAliveInterval 30
  ProxyCommand ssh -F "@CONFIG@" -T markflow-gateway
''';

void main() {
  late List<String> member, other, encrypted;
  setUpAll(() {
    member = generateSshKeyPair(['ed25519', 'synthetic-test-only', '']);
    other = generateSshKeyPair(['ed25519', 'synthetic-host-only', '']);
    encrypted = generateSshKeyPair(['ed25519', 'synthetic-encrypted', 'test-password']);
  });
  Uint8List zip({Map<String, String> overrides = const {}, String prefix = 'client/'}) {
    final files = {
      'config.template': template, 'username.txt': 'testuser', 'member.pub': member[1],
      'known_hosts': 'markflow-member-gateway ${other[1]}\nmarkflow-member-cpu ${other[1]}\n',
      'Setup.py': 'raise Exception("must never execute")', ...overrides,
    };
    final archive = Archive();
    for (final entry in files.entries) {
      final bytes = utf8.encode(entry.value);
      archive.addFile(ArchiveFile('$prefix${entry.key}', bytes.length, bytes));
    }
    return Uint8List.fromList(ZipEncoder().encode(archive));
  }

  test('reads standard bundle at root or client folder, ignores scripts', () {
    for (final prefix in ['', 'client/']) {
      final bundle = SshClientBundle.parse(zip(prefix: prefix));
      expect(bundle.username, 'testuser');
      expect(bundle.cpu['hostname'], 'personal-cpu');
      expect(bundle.hostKeys, hasLength(2));
    }
  });
  test('matches the assigned private key and rejects another account', () {
    final bundle = SshClientBundle.parse(zip());
    expect(bundle.matchesPrivateKey(member[0]), isTrue);
    expect(bundle.matchesPrivateKey(other[0]), isFalse);
    expect(bundle.matchesPrivateKey(member[1]), isFalse);
  });
  test('matches encrypted OpenSSH keys without collecting passphrases', () {
    final bundle = SshClientBundle.parse(zip(overrides: {'member.pub': encrypted[1]}));
    expect(bundle.matchesPrivateKey(encrypted[0]), isTrue);
  });
  test('rejects executable SSH directives and modified proxy commands', () {
    for (final config in [
      '$template  LocalCommand touch /tmp/should-not-exist\n',
      template.replaceAll('ssh -F "@CONFIG@" -T markflow-gateway', 'sh -c "echo unsafe"'),
      template.replaceAll('StrictHostKeyChecking yes', 'StrictHostKeyChecking no'),
      template.replaceAll('personal-cpu', 'cpu;echo unsafe'),
    ]) {
      expect(() => SshClientBundle.parse(zip(overrides: {'config.template': config})), throwsFormatException);
    }
  });
  test('rejects traversal paths, invalid accounts and excessive decompressed files', () {
    for (final overrides in [
      {'../escaped': 'bad'}, {'username.txt': 'user\nLocalCommand unsafe'},
      {'README.txt': 'a' * (65 * 1024)}, {'known_hosts': 'unknown ${other[1]}'},
      {'member.pub': 'ssh-ed25519 AAAA'},
    ]) {
      expect(() => SshClientBundle.parse(zip(overrides: overrides)), throwsA(isA<Exception>()));
    }
    expect(() => SshClientBundle.parse(Uint8List(SshClientBundle.maxZipBytes + 1)), throwsFormatException);
  });
  test('requires complete gateway, member, CPU and host pin data', () {
    final archive = Archive()..addFile(ArchiveFile('client/config.template', template.length, utf8.encode(template)));
    expect(() => SshClientBundle.parse(Uint8List.fromList(ZipEncoder().encode(archive))), throwsFormatException);
  });
  test('quotes generated paths and preserves strict gateway routing', () {
    final config = SshClientBundle.parse(zip()).config(key: '/tmp/a "key%file', known: '/tmp/known', config: "/tmp/a'b/config");
    expect(config, contains('StrictHostKeyChecking yes'));
    expect(config, contains('key%%file'));
    expect(config, contains("/usr/bin/ssh -F '/tmp/a'\\''b/config' -T markflow-gateway"));
    expect(config, isNot(contains('@USER@')));
    expect(() => SshClientBundle.parse(zip()).config(key: '/tmp/\nbad', known: '/tmp/k', config: '/tmp/c'), throwsFormatException);
  });
  test('finds a matching key without following symlinks or reading large files', () async {
    final directory = await Directory.systemTemp.createTemp('bundle-match-');
    addTearDown(() => directory.delete(recursive: true));
    await File('${directory.path}/wrong').writeAsString(other[0]);
    await File('${directory.path}/large').writeAsString('a' * 100000);
    final correct = File('${directory.path}/member');
    await correct.writeAsString(member[0]);
    expect(await SshClientBundle.parse(zip()).findKey(directory), correct.path);
  });
  test('installs private configuration, keeps original key and never executes scripts', () async {
    final directory = await Directory.systemTemp.createTemp('bundle-install-');
    addTearDown(() => directory.delete(recursive: true));
    final key = File('${directory.path}/member');
    await key.writeAsString(member[0]);
    final bundle = SshClientBundle.parse(zip());
    final installed = await InstalledSshBundle.create(bundle, key.path, Directory('${directory.path}/managed'));
    expect(await key.readAsString(), member[0]);
    expect((await installed.directory.list().toList()).length, 2);
    expect((await installed.directory.stat()).mode & 0x1ff, 0x1c0);
    expect((await File(installed.configPath).stat()).mode & 0x1ff, 0x180);
    final result = await Process.run('/usr/bin/ssh', ['-G', '-F', installed.configPath, 'markflow-cpu']);
    expect(result.exitCode, 0);
    expect(result.stdout, contains('user testuser'));
    expect(result.stdout, contains('hostname personal-cpu'));
    expect(result.stdout, contains('proxycommand /usr/bin/ssh -F'));
    final wrong = File('${directory.path}/wrong');
    await wrong.writeAsString(other[0]);
    await expectLater(InstalledSshBundle.create(bundle, wrong.path, Directory('${directory.path}/rejected')), throwsFormatException);
    expect(await Directory('${directory.path}/rejected').exists(), isFalse);
  }, skip: !Platform.isMacOS);
}
