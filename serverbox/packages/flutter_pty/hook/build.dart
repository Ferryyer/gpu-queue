import 'package:code_assets/code_assets.dart';
import 'package:hooks/hooks.dart';
import 'package:native_toolchain_c/native_toolchain_c.dart';

/// Builds `src/flutter_pty.c` and hands the result to the Dart/Flutter SDK as
/// a code asset.
///
/// This replaces five per-platform build integrations — a `.podspec` each for
/// iOS and macOS, a `CMakeLists.txt` each for Linux and Windows, and a gradle
/// file plus a third `CMakeLists.txt` for Android — with one file.
///
/// The reason to bother: the CocoaPods registry goes read-only on 2026-12-08,
/// Swift Package Manager is Flutter's default since 3.44, and this plugin has
/// no `Package.swift`. Adding one would answer the question for two of the five
/// platforms and leave the other three on CMake. A build hook is neither a pod
/// nor a Swift package, so the question does not arise on any of them.
///
/// `src/flutter_pty.c` is the only translation unit: it `#include`s
/// `dart_api_dl.c`, `forkpty.c` and whichever of `flutter_pty_unix.c` /
/// `flutter_pty_win.c` applies. Listing the others here as well would define
/// every symbol twice.
void main(List<String> args) async {
  await build(args, (input, output) async {
    // Flutter also invokes the hook for non-code-asset phases. `config.code`
    // is intentionally unavailable then, so do not inspect the target or run
    // the C builder.
    if (!input.config.buildCodeAssets) return;

    await CBuilder.library(
      name: 'flutter_pty',
      assetName: 'flutter_pty',
      sources: ['src/flutter_pty.c'],
      includes: ['src'],
      // What the CMake build defined. `dart_api_dl.c` compiles to a different
      // linkage without it.
      defines: {'DART_SHARED_LIB': null},
      flags: [
        // Android 15 ships a 16 KB page size, and a library linked for 4 KB
        // will not load on it.
        if (input.config.code.targetOS == OS.android)
          '-Wl,-z,max-page-size=16384',
      ],
    ).run(input: input, output: output);
  });
}
