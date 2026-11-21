import 'package:flutter/services.dart';

/// Read the running bundle rather than trusting generated UI version data.
abstract final class MacUpdateBridge {
  static const channel = MethodChannel('work.gpuqueue/update');

  static Future<int> installedBuild() async {
    final value = await channel.invokeMethod<String>('installedBuild');
    final build = int.tryParse(value ?? '');
    if (build == null || build <= 0) {
      throw StateError('无法读取当前应用版本，请重新打开应用后重试。');
    }
    return build;
  }
}
