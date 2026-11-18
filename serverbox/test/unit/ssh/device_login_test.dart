import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:server_box/core/ssh_bundle/device_login.dart';

void main() {
  final id = 'a' * 43;
  final verifier = 'v' * 43;
  Map<String, dynamic> startResponse() => {
    'request_id': id,
    'verification_uri': '${DeviceLogin.origin}/auth/queue/authorize?request=$id',
    'user_code': 'ABCD1234', 'expires_in': 300, 'interval': 5,
  };
  final request = DeviceLoginRequest(id, verifier, 'ABCD1234',
      DateTime.now().add(const Duration(minutes: 5)), 5);

  test('S256 matches the RFC 7636 public-client example', () {
    expect(DeviceLogin.challenge('dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk'),
        'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM');
  });

  test('device request carries public key and PKCE challenge only', () async {
    final client = DeviceLogin(post: (path, body) async {
      expect(path, '/auth/queue/device');
      expect(body, {'public_key': 'ssh-ed25519 public',
        'code_challenge': DeviceLogin.challenge(verifier),
        'device_name': 'Inspire Queue · Mac'});
      expect(jsonEncode(body), isNot(contains(verifier)));
      return startResponse();
    });
    final result = await client.start('ssh-ed25519 public', verifier);
    expect(result.id, id);
    expect(result.userCode, 'ABCD1234');
    expect(result.proof, {'request_id': id, 'code_verifier': verifier});
    expect(result.uri.origin, DeviceLogin.origin);
  });

  test('authorization navigation rejects alternate origins, params and codes', () async {
    for (final altered in [
      {'verification_uri': 'https://evil.example/auth/queue/authorize?request=$id'},
      {'verification_uri': '${DeviceLogin.origin}/auth/queue/authorize?request=$id&extra=1'},
      {'verification_uri': '${DeviceLogin.origin}@evil.example/auth/queue/authorize?request=$id'},
      {'expires_in': 999999}, {'interval': 0}, {'user_code': '<script>'},
      {'request_id': '$id\n'},
    ]) {
      final client = DeviceLogin(post: (_, _) async => {...startResponse(), ...altered});
      await expectLater(client.start('ssh-ed25519 public', verifier), throwsFormatException);
    }
  });

  test('poll preserves the same proof for lost-ack retries', () async {
    final calls = <Map<String, dynamic>>[];
    final client = DeviceLogin(post: (path, body) async {
      expect(path, '/auth/queue/token');
      calls.add(body);
      return {'status': 'provisioning'};
    });
    await client.poll(request);
    await client.poll(request);
    expect(calls, [request.proof, request.proof]);
  });

  test('ready needs a live, bounded lease and a bundle', () async {
    final now = DateTime.now().millisecondsSinceEpoch ~/ 1000;
    for (final response in [
      {'status': 'unknown'},
      {'status': 'ready', 'expires_at': now - 10, 'bundle': 'zip'},
      {'status': 'ready', 'expires_at': now + 90000, 'bundle': 'zip'},
      {'status': 'ready', 'expires_at': now + 3600, 'bundle': ''},
    ]) {
      final client = DeviceLogin(post: (_, _) async => response);
      await expectLater(client.poll(request), throwsFormatException);
    }
    final client = DeviceLogin(post: (_, _) async =>
      {'status': 'ready', 'expires_at': now + 180, 'bundle': 'zip'});
    expect((await client.poll(request))['status'], 'ready');
  });

  test('revocation requires explicit server acknowledgement', () async {
    final client = DeviceLogin(post: (path, body) async {
      expect(path, '/auth/queue/revoke');
      expect(body, request.proof);
      return {'status': 'revoked'};
    });
    await client.revoke(request);
    final unavailable = DeviceLogin(post: (_, _) async => {'status': 'unavailable'});
    await expectLater(unavailable.revoke(request), throwsFormatException);
  });

  test('saved proofs round-trip and reject malformed requests', () {
    expect(DeviceLoginRequest.fromJson(request.toJson()).proof, request.proof);
    expect(() => DeviceLoginRequest.fromJson({...request.toJson(), 'request_id': '../x'}), throwsFormatException);
    final first = DeviceLogin.verifier();
    expect(first.length, 43);
    expect(DeviceLogin.verifier(), isNot(first));
  });
}
