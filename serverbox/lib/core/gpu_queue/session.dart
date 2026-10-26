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
  Map<String, dynamic>? health;
  bool diagnosing = false;
  String? diagnosticError;
  bool get hasSnapshot => _snapshotIdentity == identity();
  List<Map<String, dynamic>> get tasks =>
      hasSnapshot ? (snapshot['tasks'] as List? ?? []).cast<Map<String, dynamic>>() : [];
  List<Map<String, dynamic>> get resources =>
      hasSnapshot ? (snapshot['heartbeat']?['resources'] as List? ?? [])
          .cast<Map<String, dynamic>>() : [];
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
      _validateSnapshot(data);
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

  static void _validateSnapshot(Map<String, dynamic> data) {
    final tasks = data['tasks'];
    final heartbeat = data['heartbeat'];
    if (tasks is! List || tasks.any((t) => t is! Map<String, dynamic>) ||
        (heartbeat != null && heartbeat is! Map) ||
        (data['revision'] != null && data['revision'] is! int)) {
      throw StateError('任务服务数据格式不兼容，请更新个人任务服务');
    }
    final resources = heartbeat is Map ? heartbeat['resources'] : null;
    if (resources != null && (resources is! List ||
        resources.any((r) => r is! Map<String, dynamic>))) {
      throw StateError('GPU 资源数据格式不兼容，请更新个人任务服务');
    }
  }

  Future<void> diagnose() async {
    if (_disposed || diagnosing) return;
    diagnosing = true;
    health = null;
    diagnosticError = null;
    _notify();
    try {
      final data = await _request('/api/health', null, false);
      if (_disposed) return;
      if (data['service'] != 'gpuq' || data['owner'] is! String || data['uid'] is! int) {
        throw StateError('未识别到个人 GPU Queue 服务，请核对服务器');
      }
      health = data;
    } catch (e) {
      if (!_disposed) diagnosticError = e.toString();
    } finally {
      diagnosing = false;
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
      _validateSnapshot(data);
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
