import 'dart:async';
import 'package:flutter/foundation.dart';

typedef QueueRequest =
    Future<Map<String, dynamic>> Function(
      String path,
      Map<String, dynamic>? body,
      bool connect,
    );

/// Owns polling and explicit actions, independently of the borrowed SSH client.
/// There is no action queue to replay when transport comes back.
class QueueSession extends ChangeNotifier {
  QueueSession({
    required this.request,
    required this.identity,
    this.auto = false,
    required this.saveAuto,
    bool poll = true,
  }) {
    if (poll) {
      _timer = Timer.periodic(const Duration(seconds: 5), (_) => refresh());
      scheduleMicrotask(refresh);
    }
  }
  final QueueRequest request;
  final String Function() identity;
  final void Function(bool) saveAuto;
  Timer? _timer;
  String? _snapshotIdentity;
  bool _disposed = false;
  bool loading = false, acting = false, connected = false, auto;
  String? error;
  DateTime? sampledAt;
  Map<String, dynamic> snapshot = {};
  List<Map<String, dynamic>> get tasks =>
      (snapshot['tasks'] as List? ?? []).cast<Map<String, dynamic>>();
  List<Map<String, dynamic>> get resources =>
      (snapshot['heartbeat']?['resources'] as List? ?? [])
          .cast<Map<String, dynamic>>();
  int get revision => snapshot['revision'] as int? ?? 0;
  void _notify() {
    if (!_disposed) notifyListeners();
  }

  void setAuto(bool value) {
    auto = value;
    saveAuto(value);
    _notify();
  }

  Future<Map<String, dynamic>> _request(
    String path,
    Map<String, dynamic>? body,
    bool connect,
  ) async {
    final destination = identity();
    final data = await request(path, body, connect);
    if (destination != identity()) throw StateError('服务器配置已变化，请重新同步');
    return data;
  }

  Future<void> refresh({bool connect = false}) async {
    if (_disposed || loading || acting) return;
    loading = true;
    _notify();
    try {
      final data = await _request('/api/state', null, connect);
      if (_disposed) return;
      snapshot = data;
      _snapshotIdentity = identity();
      connected = true;
      error = null;
      sampledAt = DateTime.now();
    } catch (e) {
      if (_disposed) return;
      connected = false;
      error = e.toString();
    } finally {
      loading = false;
      _notify();
    }
  }

  Future<void> action(String path, Map<String, dynamic> body) async {
    if (_disposed) throw StateError('任务页已关闭');
    if (acting || loading) throw StateError('正在同步，请稍后重试');
    if (auto && (path.endsWith('/start') || path.endsWith('/reorder'))) {
      throw StateError('请先切换到 Edit mode');
    }
    if (!connected || _snapshotIdentity != identity()) {
      throw StateError('任务服务未连接或配置已变化，请先重试');
    }
    acting = true;
    _notify();
    try {
      final data = await _request(path, body, false);
      if (_disposed) return;
      snapshot = data;
      sampledAt = DateTime.now();
      error = null;
    } catch (e) {
      connected = false;
      error = '$e；请刷新核对操作结果，不会自动重试';
      rethrow;
    } finally {
      acting = false;
      _notify();
    }
  }

  @override
  void dispose() {
    _disposed = true;
    _timer?.cancel();
    super.dispose();
  }
}
