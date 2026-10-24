import 'dart:convert';

/// No address, credential or shell text is supplied by a task document.
abstract final class QueueProtocol {
  static String quote(String value) => "'${value.replaceAll("'", "'\\''")}'";

  static String command(String path, [Map<String, dynamic>? body]) {
    if (!RegExp(
      r'^/api/(state|health|queue/reorder|tasks/GQ-[a-f0-9]{16}/(start|stop))$',
    ).hasMatch(path)) {
      throw ArgumentError.value(path, 'path');
    }
    final payload = base64.encode(
      utf8.encode(jsonEncode({'path': path, 'body': body})),
    );
    return 'python3 -c ${quote(script)} $payload';
  }

  /// HTTP over the existing owner's private socket. It has exactly the same
  /// digest/revision checks and explicit Start authority as the web client.
  static const script = r'''
import base64,http.client,json,os,socket,sys
request=json.loads(base64.b64decode(sys.argv[1]))
class UnixHTTP(http.client.HTTPConnection):
 def connect(self):
  self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
  self.sock.settimeout(12)
  self.sock.connect('/tmp/gpuq-%d/web.sock'%os.getuid())
connection=UnixHTTP('127.0.0.1',8790,timeout=12)
try:
 body=request.get('body')
 headers={'Host':'127.0.0.1:8790','Origin':'http://127.0.0.1:8790','X-GPUQ-Action':'1','Content-Type':'application/json'}
 connection.request('GET' if body is None else 'POST',request['path'],None if body is None else json.dumps(body),headers)
 response=connection.getresponse()
 raw=response.read(8*1024*1024+1)
 if len(raw)>8*1024*1024: raise ValueError('Task response exceeds 8 MiB')
 print(json.dumps({'status':response.status,'body':json.loads(raw)}))
except Exception as error:
 print(json.dumps({'status':503,'body':{'error':'Task service unavailable: '+type(error).__name__}}))
finally:
 connection.close()
''';

  static Map<String, dynamic> decode(String output) {
    final envelope = jsonDecode(output) as Map<String, dynamic>;
    final body = envelope['body'] as Map<String, dynamic>;
    if (envelope['status'] != 200) {
      throw StateError(body['error']?.toString() ?? '任务服务请求失败');
    }
    return body;
  }
}

/// An association is scoped to the service, instance and both SSH destinations.
/// Editing a saved server's address invalidates it; name/host guessing is never
/// used to resolve a task's terminal or file browser.
abstract final class QueueTarget {
  static String? instance(Map<String, dynamic> task) {
    final value = task['execution']?['instance_id'] ?? task['request_uuid'];
    return value is String && value.isNotEmpty ? value : null;
  }

  static bool bindingMatches(Map binding, String identity, String origin) =>
      binding['identity'] == identity && binding['origin'] == origin;
  static String key(String service, String instance) =>
      jsonEncode([service, instance]);
  static bool fresh(
    Map<String, dynamic> resource,
    DateTime now, {
    required bool connected,
  }) {
    final at = resource['telemetry']?['at'];
    if (!connected || resource['status'] != 'online' || at is! num) {
      return false;
    }
    final age = now.millisecondsSinceEpoch / 1000 - at;
    return age >= -5 && age < 90;
  }

  static String? directory(Map<String, dynamic> task) {
    final value = task['execution']?['workspace'];
    return value is String && value.startsWith('/') && !value.contains('\x00')
        ? value
        : null;
  }
}
