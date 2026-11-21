import 'package:fl_lib/fl_lib.dart';
import 'package:flutter/services.dart';

/// Listen <kbd>Cmd+Key</kbd> event.
/// eg:
///   - macOS: <kbd>Cmd+Enter</kbd>
///   - Linux & Windows: <kbd>Ctrl+Enter</kbd>
final class KeyboardCtrlListener {
  final bool? Function() callback;
  late final Set<PhysicalKeyboardKey> ctrlKeys;
  final PhysicalKeyboardKey key;

  KeyboardCtrlListener({
    required this.callback,
    required this.key,
    Set<PhysicalKeyboardKey>? ctrlKeys,
  }) {
    this.ctrlKeys = ctrlKeys ?? (isMacOS ? macOSCtrlKeys : linuxWindowsCtrlKeys);
    HardwareKeyboard.instance.addHandler(_handler);
  }

  static final macOSCtrlKeys = {
    PhysicalKeyboardKey.metaLeft,
    PhysicalKeyboardKey.metaRight,
  };

  static final linuxWindowsCtrlKeys = {
    PhysicalKeyboardKey.controlLeft,
    PhysicalKeyboardKey.controlRight,
  };

  void dispose() {
    HardwareKeyboard.instance.removeHandler(_handler);
  }

  bool _isCtrlPressing = false;

  /// Returns `true` if handled, `false` otherwise.
  bool _handler(KeyEvent event) {
    if (event is KeyDownEvent) {
      final key = event.physicalKey;
      if (ctrlKeys.contains(key)) {
        _isCtrlPressing = true;
        return false;
      }

      final isSuffixPressed = key == this.key;
      if (_isCtrlPressing && isSuffixPressed) {
        return callback() ?? true;
      }
    } else if (event is KeyUpEvent) {
      final key = event.physicalKey;
      if (ctrlKeys.contains(key)) {
        _isCtrlPressing = false;
        return false;
      }
    }
    return false;
  }
}
