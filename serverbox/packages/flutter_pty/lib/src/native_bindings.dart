import 'dart:ffi';

import 'package:flutter_pty/src/flutter_pty_bindings_generated.dart';

/// Resolve the asset emitted by hook/build.dart. A bare dlopen filename does
/// not refer to Dart's code-asset map in Flutter tests or packaged apps.
abstract final class PtyNative {
  static const _asset = 'package:flutter_pty/flutter_pty';

  @Native<IntPtr Function(Pointer<Void>)>(assetId: _asset, symbol: 'Dart_InitializeApiDL')
  external static int initialize(Pointer<Void> data);

  @Native<Pointer<PtyHandle> Function(Pointer<PtyOptions>)>(assetId: _asset, symbol: 'pty_create')
  external static Pointer<PtyHandle> create(Pointer<PtyOptions> options);

  @Native<Void Function(Pointer<PtyHandle>, Pointer<Char>, Int)>(assetId: _asset, symbol: 'pty_write')
  external static void write(Pointer<PtyHandle> handle, Pointer<Char> buffer, int length);

  @Native<Void Function(Pointer<PtyHandle>)>(assetId: _asset, symbol: 'pty_ack_read')
  external static void ackRead(Pointer<PtyHandle> handle);

  @Native<Int Function(Pointer<PtyHandle>, Int, Int)>(assetId: _asset, symbol: 'pty_resize')
  external static int resize(Pointer<PtyHandle> handle, int rows, int columns);

  @Native<Int Function(Pointer<PtyHandle>)>(assetId: _asset, symbol: 'pty_getpid')
  external static int getpid(Pointer<PtyHandle> handle);

  @Native<Pointer<Char> Function()>(assetId: _asset, symbol: 'pty_error')
  external static Pointer<Char> error();
}
