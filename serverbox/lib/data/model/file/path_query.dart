import 'package:server_box/data/model/file/browse_path.dart';

/// A pasted search query, with a backend path only when it can be resolved
/// within the browser root. Paths use forward slashes on every backend.
final class ParsedPathQuery {
  const ParsedPathQuery._({
    required this.cleanedPath,
    required this.root,
    required this.targetPath,
    required this.basePath,
    required this.isPathLike,
    required this.isRelative,
    required this.isOutOfBounds,
    required this.line,
  });

  /// Input after removing paste artifacts, before expanding home or resolving.
  final String cleanedPath;
  final String root;
  final String? targetPath;

  /// The already selected directory for relative and home paths.
  final String? basePath;
  final bool isPathLike;

  /// Eligible for rebasing against recently visited directories.
  final bool isRelative;
  final bool isOutOfBounds;
  final int? line;

  static ParsedPathQuery parse(
    String raw, {
    required String currentDir,
    required String root,
    String? homePath,
  }) {
    var path = _unwrap(raw);
    final suffix = _lineSuffix.firstMatch(path);
    final line = int.tryParse(suffix?.group(1) ?? suffix?.group(2) ?? '');
    if (suffix != null) path = _unwrap(path.substring(0, suffix.start));

    final isFileUri = path.toLowerCase().startsWith('file://');
    if (isFileUri) {
      path = path.substring('file://'.length);
      if (path.toLowerCase().startsWith('localhost/')) {
        path = path.substring('localhost'.length);
      }
      try {
        path = Uri.decodeComponent(path);
      } on ArgumentError {
        // Keep malformed escapes literal.
      } on FormatException {
        // The escapes can also decode to invalid UTF-8.
      }
    }
    path = path.replaceAll(r'\', '/');
    if (isFileUri &&
        path.startsWith('/') &&
        _drivePath.hasMatch(path.substring(1))) {
      path = path.substring(1);
    }

    final scp = isFileUri ? null : _scpPrefix.firstMatch(path);
    if (scp != null) path = path.substring(scp.end);

    final isPathLike =
        isFileUri ||
        scp != null ||
        path.contains('/') ||
        path.startsWith('~') ||
        path.startsWith('.');
    final usesHome = path == '~' || path.startsWith('~/');
    final isAbsolute = path.startsWith('/') || _drivePath.hasMatch(path);
    final isRelative =
        path.isNotEmpty &&
        !usesHome &&
        !isAbsolute &&
        !isFileUri &&
        scp == null &&
        !path.startsWith('~');
    final browser = BrowsePath(root: root);
    final normalizedRoot = _withDriveRootSlash(browser.root);

    String? requestedPath;
    String? basePath;
    if (usesHome && homePath != null && homePath.isNotEmpty) {
      final home = homePath.replaceAll(r'\', '/');
      basePath = _resolveWithin(browser, home);
      requestedPath = path == '~'
          ? home
          : BrowsePath.join(home, path.substring(2));
    } else if (isAbsolute) {
      requestedPath = path;
    } else if (isRelative) {
      basePath = _resolveWithin(browser, currentDir);
      if (basePath != null) requestedPath = BrowsePath.join(basePath, path);
    }

    final target = requestedPath == null
        ? null
        : _resolveWithin(browser, requestedPath);
    final missingHome = usesHome && (homePath == null || homePath.isEmpty);
    return ParsedPathQuery._(
      cleanedPath: path,
      root: normalizedRoot,
      targetPath: target,
      basePath: basePath,
      isPathLike: isPathLike,
      isRelative: isRelative,
      isOutOfBounds:
          target == null &&
          !missingHome &&
          (isAbsolute || isRelative || usesHome),
      line: line,
    );
  }

  /// Resolves a trusted browser location such as a history directory against
  /// this query's root, rejecting traversal at the root boundary.
  String? resolveDirectory(String directory) =>
      _resolveWithin(BrowsePath(root: root), directory);

  /// Validates one untrusted listing component before it is joined to a path.
  bool isSafeEntryName(String name) =>
      name.isNotEmpty &&
      name != '.' &&
      name != '..' &&
      !name.contains('/') &&
      !name.contains(r'\') &&
      !name.contains('\x00') &&
      (root.startsWith('/') || _isWindowsFileName(name));

  static bool _isWindowsFileName(String name) =>
      !name.contains(':') && !name.endsWith('.') && !name.endsWith(' ');

  static final _lineSuffix = RegExp(
    r':([0-9]+)(?::[0-9]+)?$|#L([0-9]+)(?:-L[0-9]+)?$',
  );
  static final _scpPrefix = RegExp(
    r'^([^/\s:]{2,}|\[[0-9A-Fa-f:]+\]):(?=/|~/)',
  );
  static final _drivePath = RegExp(r'^[A-Za-z]:/');
  static final _driveRoot = RegExp(r'^[A-Za-z]:$');

  static String _unwrap(String input) {
    var text = input.trim();
    while (text.length >= 2) {
      final first = text[0];
      final end = first == '<' ? '>' : first;
      if (!const {'<', "'", '"', '`'}.contains(first) || !text.endsWith(end))
        break;
      text = text.substring(1, text.length - 1).trim();
    }
    return text;
  }

  static String? _resolveWithin(BrowsePath browser, String rawPath) {
    final path = rawPath.replaceAll(r'\', '/');
    final windows = _driveRoot.hasMatch(browser.root.split('/').first);
    if (path.contains('\x00') ||
        (windows && !_drivePath.hasMatch(path) && !_driveRoot.hasMatch(path)) ||
        (!windows && !path.startsWith('/'))) {
      return null;
    }
    final rootDepth = browser.root
        .split('/')
        .where((part) => part.isNotEmpty)
        .length;
    var depth = 0;
    for (final part in path.split('/')) {
      if (part.isEmpty || part == '.') continue;
      // Reject traversal at the browser root before BrowsePath normalizes it.
      if (part == '..') {
        if (depth <= rootDepth) return null;
        depth--;
        continue;
      }
      // Win32 can reinterpret trailing spaces, trailing dots and stream
      // specifiers before accessing a component.
      if (windows && depth > 0 && !_isWindowsFileName(part)) {
        return null;
      }
      depth++;
    }

    final resolved = browser.resolve(path);
    return resolved == null ? null : _withDriveRootSlash(resolved);
  }

  // A bare drive letter and colon would be drive-relative on Windows.
  static String _withDriveRootSlash(String path) =>
      _driveRoot.hasMatch(path) ? '$path/' : path;
}
