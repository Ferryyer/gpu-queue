import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:archive/archive.dart';
import 'package:crypto/crypto.dart';
import 'package:dartssh2/dartssh2.dart';

/// Reads the company client bundle as data; never extracts or executes it.
class SshClientBundle {
  SshClientBundle._(this.username, this.gateway, this.cpu, this.memberKey, this.hostKeys);
  final String username;
  final Map<String, String> gateway, cpu;
  final String memberKey;
  final Map<String, String> hostKeys;
  static const maxZipBytes = 2 * 1024 * 1024;

  static Future<SshClientBundle> read(String path) async {
    final file = File(path);
    if (await file.length() > maxZipBytes) throw const FormatException('配置包不能超过 2 MB');
    return parse(await file.readAsBytes());
  }

  static SshClientBundle parse(Uint8List bytes) {
    if (bytes.length > maxZipBytes) throw const FormatException('配置包过大');
    final directory = ZipDirectory()..read(InputMemoryStream(bytes));
    if (directory.fileHeaders.isEmpty || directory.fileHeaders.length > 32) {
      throw const FormatException('无效的配置包或文件数量过多');
    }
    final entries = <String, ZipFileHeader>{};
    var total = 0;
    for (final entry in directory.fileHeaders) {
      final name = entry.filename;
      total += entry.uncompressedSize;
      if (name.startsWith('/') || name.contains('\\') || name.split('/').contains('..') ||
          name.contains('\x00') || entries.containsKey(name) ||
          (entry.externalFileAttributes >> 16 & 0xf000) == 0xa000 ||
          entry.generalPurposeBitFlag & 1 != 0 ||
          ![0, 8].contains(entry.compressionMethod) ||
          entry.uncompressedSize > 64 * 1024 || total > 256 * 1024 ||
          entry.file?.filename != name) {
        throw const FormatException('配置包含不支持的路径、重复文件或压缩内容');
      }
      entries[name] = entry;
    }
    final prefix = entries.containsKey('client/config.template') ? 'client/' : '';
    String text(String name) {
      final entry = entries['$prefix$name'];
      if (entry == null) throw FormatException('配置包缺少 $name');
      final output = _BoundedOutput();
      entry.file!.decompress(output);
      final data = output.getBytes();
      if (data.length != entry.uncompressedSize || getCrc32(data) != entry.crc32) {
        throw const FormatException('配置包校验失败，请重新下载');
      }
      return utf8.decode(data).trim();
    }
    final username = text('username.txt');
    if (!RegExp(r'^[a-zA-Z_][a-zA-Z0-9_.-]{0,63}$').hasMatch(username)) {
      throw const FormatException('配置包中的账号格式无效');
    }
    final blocks = <String, Map<String, String>>{};
    Map<String, String>? current;
    for (final raw in text('config.template').split('\n')) {
      final line = raw.trim();
      if (line.isEmpty || line.startsWith('#')) continue;
      final match = RegExp(r'^(\S+)\s+(.+)$').firstMatch(line);
      if (match == null) throw const FormatException('SSH 模板格式无效');
      final key = match[1]!.toLowerCase();
      var value = match[2]!.trim();
      if (key == 'host') {
        if (!['markflow-gateway', 'markflow-cpu'].contains(value) || blocks.containsKey(value)) {
          throw const FormatException('仅支持标准网关与个人 CPU 配置');
        }
        current = blocks[value] = {};
      } else {
        if (current == null || current.containsKey(key)) throw const FormatException('SSH 模板含重复配置');
        if (key != 'proxycommand' && value.startsWith('"') && value.endsWith('"')) {
          value = value.substring(1, value.length - 1);
        }
        current[key] = value;
      }
    }
    if (blocks.length != 2) throw const FormatException('配置包需要网关和个人 CPU 两项配置');
    final gateway = blocks['markflow-gateway']!, cpu = blocks['markflow-cpu']!;
    const allowed = {'hostname', 'port', 'user', 'hostkeyalias', 'identityfile', 'identitiesonly',
      'userknownhostsfile', 'stricthostkeychecking', 'requesttty', 'forwardagent', 'serveraliveinterval', 'proxycommand'};
    for (final block in blocks.entries) {
      final values = block.value;
      final port = int.tryParse(values['port'] ?? '');
      if (values.keys.any((k) => !allowed.contains(k)) ||
          !RegExp(r'^[a-zA-Z0-9][a-zA-Z0-9.:-]*$').hasMatch(values['hostname'] ?? '') ||
          port == null || port < 1 || port > 65535 ||
          values['identityfile'] != '@KEY@' || values['userknownhostsfile'] != '@KNOWN@' ||
          values['hostkeyalias'] != (block.key == 'markflow-cpu' ? 'markflow-member-cpu' : 'markflow-member-gateway') ||
          values['stricthostkeychecking'] != 'yes' || values['identitiesonly'] != 'yes' ||
          values['forwardagent'] != 'no' ||
          (values['requesttty'] != null && values['requesttty'] != 'no') ||
          (values['serveraliveinterval'] != null && int.tryParse(values['serveraliveinterval']!) == null)) {
        throw const FormatException('配置包不是受支持的标准 SSH 模板');
      }
    }
    if (cpu['user'] != '@USER@' ||
        !RegExp(r'^[a-zA-Z_][a-zA-Z0-9_.-]{0,63}$').hasMatch(gateway['user'] ?? '') ||
        gateway.containsKey('proxycommand') ||
        cpu['proxycommand'] != 'ssh -F "@CONFIG@" -T markflow-gateway') {
      throw const FormatException('配置包的网关连接方式不受支持');
    }
    final member = normalizeKey(text('member.pub'));
    final hosts = <String, String>{};
    for (final line in text('known_hosts').split('\n')) {
      if (line.trim().isEmpty || line.trim().startsWith('#')) continue;
      final fields = line.trim().split(RegExp(r'\s+'));
      if (fields.length < 3 || !['markflow-member-gateway', 'markflow-member-cpu'].contains(fields[0]) || hosts.containsKey(fields[0])) {
        throw const FormatException('配置包中的主机指纹格式无效');
      }
      hosts[fields[0]] = normalizeKey(fields.sublist(1).join(' '));
    }
    if (hosts.length != 2) throw const FormatException('缺少网关或 CPU 主机指纹');
    return SshClientBundle._(username, gateway, cpu, member, hosts);
  }

  static String normalizeKey(String line) {
    final fields = line.trim().split(RegExp(r'\s+'));
    if (fields.length < 2 || !['ssh-ed25519', 'ssh-rsa', 'ecdsa-sha2-nistp256'].contains(fields[0])) {
      throw const FormatException('不支持的 SSH 公钥');
    }
    final bytes = base64.decode(fields[1]);
    if (bytes.length < 8 || bytes.length > 8192 || SSHHostKey.getType(bytes) != fields[0]) {
      throw const FormatException('SSH 公钥格式无效');
    }
    var offset = 0;
    Uint8List field() {
      if (offset + 4 > bytes.length) throw const FormatException('SSH 公钥格式无效');
      final size = ByteData.sublistView(bytes, offset, offset + 4).getUint32(0);
      offset += 4;
      if (size == 0 || offset + size > bytes.length) throw const FormatException('SSH 公钥格式无效');
      final value = bytes.sublist(offset, offset + size);
      offset += size;
      return value;
    }
    field();
    final first = field();
    if (fields[0] == 'ssh-ed25519' && first.length != 32) throw const FormatException('SSH 公钥格式无效');
    if (fields[0] == 'ssh-rsa') field();
    if (fields[0] == 'ecdsa-sha2-nistp256') {
      if (utf8.decode(first) != 'nistp256' || field().length != 65) throw const FormatException('SSH 公钥格式无效');
    }
    if (offset != bytes.length) throw const FormatException('SSH 公钥含多余内容');
    return '${fields[0]} ${base64.encode(bytes)}';
  }

  static String fingerprint(String key) => 'SHA256:${base64.encode(sha256.convert(base64.decode(key.split(' ')[1])).bytes).replaceAll('=', '')}';

  /// Match the public portion, including encrypted OpenSSH keys, without
  /// unlocking or storing a passphrase during setup.
  bool matchesPrivateKey(String pem) {
    try {
      final decoded = SSHPem.decode(pem);
      final public = decoded.type == 'OPENSSH PRIVATE KEY'
        ? OpenSSHKeyPairs.decode(decoded.content).publicKeys
        : SSHKeyPair.fromPem(pem).map((key) => key.toPublicKey().encode()).toList();
      return public.any((bytes) => '${SSHHostKey.getType(bytes)} ${base64.encode(bytes)}' == memberKey);
    } catch (_) { return false; }
  }

  static Future<String> readPrivateKey(String path) async {
    final file = File(path);
    final size = await file.length();
    if (size < 32 || size > 64 * 1024) throw const FormatException('请选择有效的 SSH 私钥文件');
    return file.readAsString();
  }

  Future<String?> findKey(Directory directory) async {
    if (!await directory.exists()) return null;
    var count = 0;
    await for (final entry in directory.list(followLinks: false)) {
      if (++count > 128) break;
      if (entry is! File || entry.path.endsWith('.pub')) continue;
      try {
        if (matchesPrivateKey(await readPrivateKey(entry.path))) return entry.path;
      } catch (_) { /* Not a private key. */ }
    }
    return null;
  }

  String config({required String key, required String known, required String config}) {
    String quote(String value) {
      if (value.contains(RegExp(r'[\r\n\x00]'))) throw const FormatException('配置路径含非法字符');
      return '"${value.replaceAll('\\', '\\\\').replaceAll('"', '\\"').replaceAll('%', '%%')}"';
    }
    String host(String alias, Map<String, String> values, String user) =>
      'Host $alias\n  HostName ${values['hostname']}\n  Port ${values['port']}\n  User $user\n'
      '  HostKeyAlias ${values['hostkeyalias']}\n  IdentityFile ${quote(key)}\n'
      '  IdentitiesOnly yes\n  UserKnownHostsFile ${quote(known)}\n  StrictHostKeyChecking yes\n'
      '  ForwardAgent no\n  RequestTTY no\n  ServerAliveInterval 30\n';
    return '${host('markflow-gateway', gateway, gateway['user']!)}\n'
      '${host('markflow-cpu', cpu, username)}  ProxyCommand ${gatewayCommand(config)}\n';
  }

  static String gatewayCommand(String config) => '/usr/bin/ssh -F ${shellQuote(config.replaceAll('%', '%%'))} -T markflow-gateway';
  static String shellQuote(String value) => "'${value.replaceAll("'", "'\\''")}'";
}

class _BoundedOutput extends OutputMemoryStream {
  void check(int count) {
    if (length + count > 64 * 1024) throw const FormatException('配置文件解压后过大');
  }
  @override
  void writeByte(int value) { check(1); super.writeByte(value); }
  @override
  void writeBytes(List<int> bytes, {int? length}) { check(length ?? bytes.length); super.writeBytes(bytes, length: length); }
  @override
  void writeStream(InputStream stream) { check(stream.length); super.writeStream(stream); }
  @override
  void writeBackReference(int distance, int count) { check(count); super.writeBackReference(distance, count); }
}
