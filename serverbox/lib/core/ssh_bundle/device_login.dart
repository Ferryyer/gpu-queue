import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:crypto/crypto.dart';

typedef DeviceLoginPost = Future<Map<String, dynamic>> Function(
  String path, Map<String, dynamic> body);

/// Public-client proof stays on this device and is sent only to the fixed issuer.
class DeviceLogin {
  DeviceLogin({DeviceLoginPost? post}) : _post = post ?? _httpsPost;
  static const origin = 'https://inspire.markflow.work';
  final DeviceLoginPost _post;
  static final _value = RegExp(r'^[A-Za-z0-9_-]{43}$');

  static String verifier() {
    final random = Random.secure();
    return base64Url.encode(List.generate(32, (_) => random.nextInt(256)))
        .replaceAll('=', '');
  }

  static String challenge(String verifier) => base64Url
      .encode(sha256.convert(utf8.encode(verifier)).bytes).replaceAll('=', '');

  Future<DeviceLoginRequest> start(String publicKey, String verifier) async {
    if (!_value.hasMatch(verifier)) throw const FormatException('登录校验信息无效');
    final data = await _post('/auth/queue/device', {
      'public_key': publicKey,
      'code_challenge': challenge(verifier),
      'device_name': 'Inspire Queue · Mac',
    });
    final id = data['request_id'];
    final code = data['user_code'];
    final expires = data['expires_in'];
    final interval = data['interval'];
    if (id is! String || !_value.hasMatch(id) || code is! String ||
        !RegExp(r'^[A-Z0-9]{8}$').hasMatch(code) || expires is! int ||
        expires < 1 || expires > 600 || interval is! int || interval < 2 || interval > 30 ||
        data['verification_uri'] != '$origin/auth/queue/authorize?request=$id') {
      throw const FormatException('登录服务返回的信息无效，请重试');
    }
    return DeviceLoginRequest(id, verifier, code,
        DateTime.now().add(Duration(seconds: expires)), interval);
  }

  Future<Map<String, dynamic>> poll(DeviceLoginRequest request) async {
    final result = await _post('/auth/queue/token', request.proof);
    if (!const {'pending', 'provisioning', 'denied', 'expired', 'ready', 'unavailable'}
        .contains(result['status'])) {
      throw const FormatException('登录状态无效，请重试');
    }
    if (result['status'] == 'ready') {
      final expires = result['expires_at'];
      final bundle = result['bundle'];
      final now = DateTime.now().millisecondsSinceEpoch ~/ 1000;
      if (expires is! int || expires <= now || expires > now + 28860 ||
          bundle is! String || bundle.isEmpty || bundle.length > 3 * 1024 * 1024) {
        throw const FormatException('服务器访问许可无效，请重新登录');
      }
    }
    return result;
  }

  Future<void> revoke(DeviceLoginRequest request) async {
    final result = await _post('/auth/queue/revoke', request.proof);
    if (result['status'] != 'revoked') {
      throw const FormatException('未确认此设备退出，请重试');
    }
  }

  static Future<Map<String, dynamic>> _httpsPost(
      String path, Map<String, dynamic> body) async {
    if (!const {'/auth/queue/device', '/auth/queue/token', '/auth/queue/revoke'}.contains(path)) {
      throw ArgumentError.value(path, 'path');
    }
    final client = HttpClient()..connectionTimeout = const Duration(seconds: 12);
    try {
      return await (() async {
        final request = await client.postUrl(Uri.parse('$origin$path'));
        request.followRedirects = false;
        request.headers.set('Origin', origin);
        request.headers.contentType = ContentType.json;
        final payload = utf8.encode(jsonEncode(body));
        request.contentLength = payload.length;
        request.add(payload);
        final response = await request.close();
        if (response.statusCode != HttpStatus.ok) {
          await response.drain<void>();
          throw const FormatException('飞书登录服务暂不可用，请稍后重试');
        }
        final bytes = <int>[];
        await for (final chunk in response) {
          if (bytes.length + chunk.length > 3 * 1024 * 1024) {
            throw const FormatException('登录服务响应过大');
          }
          bytes.addAll(chunk);
        }
        final value = jsonDecode(utf8.decode(bytes));
        if (value is! Map<String, dynamic>) {
          throw const FormatException('登录服务响应无效');
        }
        return value;
      })().timeout(const Duration(seconds: 18));
    } on SocketException {
      throw const FormatException('无法连接登录服务，请检查网络后重试');
    } on TimeoutException {
      throw const FormatException('登录服务响应超时，请重试');
    } finally {
      client.close(force: true);
    }
  }
}

class DeviceLoginRequest {
  const DeviceLoginRequest(this.id, this.verifier, this.userCode, this.expiresAt, this.interval);
  final String id, verifier, userCode;
  final DateTime expiresAt;
  final int interval;
  Uri get uri => Uri.parse('${DeviceLogin.origin}/auth/queue/authorize?request=$id');
  Map<String, dynamic> get proof => {'request_id': id, 'code_verifier': verifier};

  Map<String, dynamic> toJson() => {...proof, 'user_code': userCode,
    'expires_at': expiresAt.millisecondsSinceEpoch ~/ 1000, 'interval': interval};

  factory DeviceLoginRequest.fromJson(Map<String, dynamic> value) {
    final id = value['request_id'], verifier = value['code_verifier'];
    if (id is! String || !DeviceLogin._value.hasMatch(id) || verifier is! String ||
        !DeviceLogin._value.hasMatch(verifier)) {
      throw const FormatException('本机登录记录无效');
    }
    return DeviceLoginRequest(id, verifier, value['user_code'] as String,
        DateTime.fromMillisecondsSinceEpoch((value['expires_at'] as int) * 1000),
        value['interval'] as int);
  }
}
