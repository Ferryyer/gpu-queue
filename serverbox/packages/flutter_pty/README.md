# flutter_pty

> **Fork.** The only difference from
> [TerminalStudio/flutter_pty](https://github.com/TerminalStudio/flutter_pty) is
> how the native library is built: `hook/build.dart` (a Dart build hook,
> `native_toolchain_c`) in place of a `.podspec` for iOS and macOS, a
> `CMakeLists.txt` for Linux, Windows and Android, and a gradle file. The Dart
> API is untouched.
>
> Upstream's last release is 0.4.2 (January 2025) and it has no `Package.swift`,
> so it holds a CocoaPods dependency open in every project that uses it —
> Flutter has defaulted to Swift Package Manager since 3.44, and the CocoaPods
> registry goes read-only on 2026-12-02. The one open PR for this
> ([#21](https://github.com/TerminalStudio/flutter_pty/pull/21), May 2026) adds
> a `Package.swift` for macOS only and has had no maintainer response. A build
> hook covers all five platforms instead, and is neither a pod nor a Swift
> package, so the question does not arise.

[![ci](https://github.com/TerminalStudio/flutter_pty/actions/workflows/ci.yml/badge.svg)](https://github.com/TerminalStudio/flutter_pty/actions/workflows/ci.yml)
[![pub points](https://badges.bar/flutter_pty/pub%20points)](https://pub.dev/packages/flutter_pty)


This is an experimental package to explore the possibilities of using native
code to implement PTY instead of pure FFI and blocking isolates. It's expected to be
more stable than the current implementation ([pty](https://pub.dev/packages/pty)).

## Platform


| Linux | macOS | Windows | Android |
| :---: | :---: | :-----: | :-----: |
|   ✔️   |   ✔️   |    ✔️    |    ✔️    |

## Quick start

```dart
import 'package:flutter_pty/flutter_pty.dart';

final pty = Pty.start('bash');

pty.output.listen((data) => ...);

pty.write(Utf8Encoder().convert('ls -al\n'));

pty.resize(30, 80);

pty.kill();
```

---

## Project stucture

This template uses the following structure:

* `src`: Contains the native source code, and a CmakeFile.txt file for building
  that source code into a dynamic library.

* `lib`: Contains the Dart code that defines the API of the plugin, and which
  calls into the native code using `dart:ffi`.

* platform folders (`android`, `ios`, `windows`, etc.): Contains the build files
  for building and bundling the native code library with the platform application.

## Buidling and bundling native code

The `pubspec.yaml` specifies FFI plugins as follows:

```yaml
  plugin:
    platforms:
      some_platform:
        ffiPlugin: true
```

This configuration invokes the native build for the various target platforms
and bundles the binaries in Flutter applications using these FFI plugins.

This can be combined with dartPluginClass, such as when FFI is used for the
implementation of one platform in a federated plugin:

```yaml
  plugin:
    implements: some_other_plugin
    platforms:
      some_platform:
        dartPluginClass: SomeClass
        ffiPlugin: true
```

A plugin can have both FFI and method channels:

```yaml
  plugin:
    platforms:
      some_platform:
        pluginClass: SomeName
        ffiPlugin: true
```

The native build systems that are invoked by FFI (and method channel) plugins are:

* For Android: Gradle, which invokes the Android NDK for native builds.
  * See the documentation in android/build.gradle.
* For iOS and MacOS: Xcode, via CocoaPods.
  * See the documentation in ios/flutter_pty.podspec.
  * See the documentation in macos/flutter_pty.podspec.
* For Linux and Windows: CMake.
  * See the documentation in linux/CMakeLists.txt.
  * See the documentation in windows/CMakeLists.txt.

## Binding to native code

To use the native code, bindings in Dart are needed.
To avoid writing these by hand, they are generated from the header file
(`src/flutter_pty.h`) by `package:ffigen`.
Regenerate the bindings by running `flutter pub run ffigen --config ffigen.yaml`.

## Invoking native code

Very short-running native functions can be directly invoked from any isolate.
For example, see `sum` in `lib/flutter_pty.dart`.

Longer-running functions should be invoked on a helper isolate to avoid
dropping frames in Flutter applications.
For example, see `sumAsync` in `lib/flutter_pty.dart`.

## Flutter help

For help getting started with Flutter, view our
[online documentation](https://flutter.dev/docs), which offers tutorials,
samples, guidance on mobile development, and a full API reference.

