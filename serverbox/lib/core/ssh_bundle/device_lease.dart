import 'dart:convert';
import 'dart:io';

import 'package:path/path.dart' as p;

enum DeviceLeaseState { valid, expired, revoked }

/// The displayable part of a locally installed Feishu device record.
class DeviceLease {
  const DeviceLease._(this.state, this.expiresAt);

  final DeviceLeaseState state;
  final DateTime? expiresAt;

  static const _maxFileBytes = 8192;
  static const _maxEpochSeconds = 8640000000000; // DateTime's range.

  /// Returns null when the SSH key has no recognizable device lease.
  static DeviceLease? read(
    String keyPath, {
    required String bundlesRoot,
    DateTime? now,
  }) {
    final root = p.normalize(bundlesRoot);
    final device = p.dirname(keyPath);
    final name = p.basename(device);
    if (!p.isAbsolute(root) ||
        keyPath.contains('\u0000') ||
        !name.startsWith('device-') ||
        name == 'device-' ||
        keyPath != p.join(root, name, 'identity')) {
      return null;
    }
    final session = p.join(device, 'session.json');
    try {
      if (FileSystemEntity.typeSync(root, followLinks: false) !=
              FileSystemEntityType.directory ||
          FileSystemEntity.typeSync(device, followLinks: false) !=
              FileSystemEntityType.directory ||
          FileSystemEntity.typeSync(keyPath, followLinks: false) !=
              FileSystemEntityType.file ||
          FileSystemEntity.typeSync(session, followLinks: false) !=
              FileSystemEntityType.file ||
          File(keyPath).lengthSync() > _maxFileBytes) {
        return null;
      }

      final record = File(session).openSync();
      try {
        if (record.lengthSync() > _maxFileBytes) return null;
        final bytes = record.readSync(_maxFileBytes + 1);
        if (bytes.length > _maxFileBytes) return null;
        final data = jsonDecode(utf8.decode(bytes));
        if (data is! Map<String, dynamic>) return null;

        final seconds = data['lease_expires_at'];
        final expiresAt =
            seconds is int &&
                seconds >= -_maxEpochSeconds &&
                seconds <= _maxEpochSeconds
            ? DateTime.fromMillisecondsSinceEpoch(seconds * 1000)
            : null;
        final revoked = data['revoked'];
        if (revoked == true) {
          return DeviceLease._(DeviceLeaseState.revoked, expiresAt);
        }
        if (expiresAt == null || (revoked != null && revoked is! bool)) {
          return null;
        }

        final state = expiresAt.isAfter(now ?? DateTime.now())
            ? DeviceLeaseState.valid
            : DeviceLeaseState.expired;
        return DeviceLease._(state, expiresAt);
      } finally {
        record.closeSync();
      }
    } on FileSystemException {
      return null;
    } on FormatException {
      return null;
    }
  }
}
