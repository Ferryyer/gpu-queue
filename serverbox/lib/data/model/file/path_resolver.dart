import 'dart:math' as math;

import 'package:server_box/data/model/file/browse_path.dart';
import 'package:server_box/data/model/file/file_backend.dart';
import 'package:server_box/data/model/file/path_query.dart';

enum PathMatchKind { exactFile, exactDir, fuzzyFile, fuzzyDir, nearestDir }

final class PathMatchCandidate {
  const PathMatchCandidate({
    required this.fullPath,
    required this.parentDir,
    required this.entry,
    required this.matchKind,
    required this.score,
  });

  final String fullPath;
  final String parentDir;
  final FileEntry entry;
  final PathMatchKind matchKind;

  /// 100 for exact paths, 0 for the nearest ancestor, and 1–99 otherwise.
  final int score;
}

final class PathResolveResult {
  PathResolveResult._({
    Iterable<PathMatchCandidate> candidates = const [],
    this.nearestExistingDir,
    this.truncated = false,
    this.budgetExhausted = false,
    this.cancelled = false,
  }) : candidates = List.unmodifiable(candidates);

  final List<PathMatchCandidate> candidates;
  final String? nearestExistingDir;

  /// The search skipped work due to a depth, branch, or backend call limit.
  final bool truncated;

  /// The search attempted to exceed a backend call limit.
  final bool budgetExhausted;
  final bool cancelled;
}

/// Searches through the browser's backend using per-request limits and state.
final class PathResolver {
  PathResolver(
    this.backend, {
    this.maxListCalls = 8,
    this.maxBranch = 3,
    this.maxDepth = 3,
    this.maxStatCalls = 32,
    this.directoryCache,
  }) {
    if (maxListCalls < 0 || maxBranch < 1 || maxDepth < 0 || maxStatCalls < 0) {
      throw ArgumentError('Invalid path search limits');
    }
  }

  final FileBackend backend;
  final int maxListCalls;
  final int maxBranch;
  final int maxDepth;
  final int maxStatCalls;

  /// Optional writable cache of successful listings, owned by the caller.
  /// Scope it to one backend and invalidate it when directory contents change.
  final Map<String, List<FileEntry>>? directoryCache;

  Future<PathResolveResult> resolve(
    ParsedPathQuery query, {
    bool showHiddenFiles = false,
    Iterable<String> historyDirs = const [],
    bool Function()? isCancelled,
  }) async {
    final search = _PathSearch(this, query, showHiddenFiles, isCancelled);
    try {
      search.checkCancellation();
      final target = query.targetPath;
      if (target == null) return PathResolveResult._();
      return await search.resolve(target, historyDirs);
    } on _SearchCancelled {
      return PathResolveResult._(cancelled: true);
    }
  }
}

typedef _Branch = ({String dir, int offset, int points, bool usedGap});

final class _PathSearch {
  _PathSearch(this.options, this.query, this.showHiddenFiles, this.isCancelled);

  final PathResolver options;
  final ParsedPathQuery query;
  final bool showHiddenFiles;
  final bool Function()? isCancelled;

  final _listings = <String, List<FileEntry>?>{};
  final _directories = <String, bool>{};
  final _candidates = <String, PathMatchCandidate>{};
  var _listCalls = 0;
  var _statCalls = 0;
  var _budgetExhausted = false;
  var _truncated = false;

  Future<PathResolveResult> resolve(
    String target,
    Iterable<String> historyDirs,
  ) async {
    final parent = _parentOf(target);
    String? nearest;
    if (target == query.root) {
      if (await _list(target) != null ||
          await _existsAfterListFailure(target)) {
        _add(_directoryCandidate(target, PathMatchKind.exactDir, 100));
      }
    } else {
      var dir = parent;
      while (true) {
        final entries = await _list(dir);
        checkCancellation();
        if (entries != null) {
          nearest = dir;
          await _expand(dir, target, entries);
          break;
        }
        if (await _existsAfterListFailure(dir)) {
          nearest = dir;
          break;
        }
        if (dir == query.root) break;
        dir = _parentOf(dir);
      }
    }

    var exact = _candidates[target]?.score == 100;
    if (!exact && query.isRelative) {
      exact = await _searchHistory(target, historyDirs);
    }
    checkCancellation();
    if (exact) nearest = null;
    if (nearest != null && !_candidates.containsKey(nearest)) {
      _add(_directoryCandidate(nearest, PathMatchKind.nearestDir, 0));
    }
    final ranked = _candidates.values.toList()
      ..sort((a, b) {
        final score = b.score.compareTo(a.score);
        return score == 0 ? a.fullPath.compareTo(b.fullPath) : score;
      });
    return PathResolveResult._(
      candidates: ranked,
      nearestExistingDir: nearest,
      truncated: _truncated || _budgetExhausted,
      budgetExhausted: _budgetExhausted,
    );
  }

  /// Walks the literal suffix one component at a time. If a component has no
  /// match, try one omitted, visible directory on a lower-scoring branch.
  Future<void> _expand(
    String ancestor,
    String target,
    List<FileEntry> initialEntries,
  ) async {
    final base = query.basePath;
    if (base != null && ancestor != base) {
      final prefix = BrowsePath.join(base, '');
      if (target.startsWith(prefix) && !ancestor.startsWith(prefix)) return;
    }
    final prefixLength = ancestor.length + (ancestor.endsWith('/') ? 0 : 1);
    final segments = target.substring(prefixLength).split('/');
    var layer = <_Branch>[
      (dir: ancestor, offset: 0, points: 0, usedGap: false),
    ];
    for (var depth = 0; layer.isNotEmpty; depth++) {
      final next = <_Branch>[];
      for (final branch in layer) {
        final entries = depth == 0 ? initialEntries : await _list(branch.dir);
        checkCancellation();
        if (entries == null) continue;
        final segment = segments[branch.offset];
        final isLeaf = branch.offset == segments.length - 1;
        var matched = false;
        for (final entry in entries) {
          if (!entry.isDir && (!isLeaf || entry.kind != FileKind.file))
            continue;
          if (!_visible(entry.name, segment)) continue;

          final score = _score(segment, entry.name);
          if (score == 0) continue;
          matched = true;
          final path = BrowsePath.join(branch.dir, entry.name);
          final points = branch.points + score;
          if (isLeaf) {
            final matchesTarget = path == target;
            _add(
              _candidate(
                path,
                entry,
                exact: matchesTarget,
                score: points ~/ (segments.length + (branch.usedGap ? 1 : 0)),
              ),
            );
          } else {
            next.add((
              dir: path,
              offset: branch.offset + 1,
              points: points,
              usedGap: branch.usedGap,
            ));
          }
        }

        if (!matched && !branch.usedGap) {
          for (final entry in entries) {
            // The user supplied no component which could opt into a dot dir.
            if (!entry.isDir || !_visible(entry.name, '')) continue;
            next.add((
              dir: BrowsePath.join(branch.dir, entry.name),
              offset: branch.offset,
              points: branch.points + 20,
              usedGap: true,
            ));
          }
        }
      }
      if (next.isEmpty) break;
      if (depth == options.maxDepth) {
        _truncated = true;
        break;
      }
      next.sort((a, b) {
        final score = b.points.compareTo(a.points);
        return score == 0 ? a.dir.compareTo(b.dir) : score;
      });
      if (next.length > options.maxBranch) _truncated = true;
      layer = next.take(options.maxBranch).toList();
    }
  }

  Future<bool> _searchHistory(
    String target,
    Iterable<String> historyDirs,
  ) async {
    final searchedTargets = <String>{target};
    for (final previous in historyDirs) {
      checkCancellation();
      final dir = query.resolveDirectory(previous);
      if (dir == null) continue;
      final rebased = query.resolveDirectory(
        BrowsePath.join(dir, query.cleanedPath),
      );
      if (rebased == null || !searchedTargets.add(rebased)) continue;
      if (rebased == query.root) {
        if (await _list(rebased) != null ||
            await _existsAfterListFailure(rebased)) {
          _add(_directoryCandidate(rebased, PathMatchKind.exactDir, 100));
          return true;
        }
      } else {
        final name = _basename(rebased);
        final entries = await _list(_parentOf(rebased));
        for (final entry in entries ?? const <FileEntry>[]) {
          if (entry.name == name &&
              (entry.isDir || entry.kind == FileKind.file)) {
            _add(_candidate(rebased, entry, exact: true, score: 100));
            return true;
          }
        }
      }
      if (searchedTargets.length == 4) break;
    }
    return false;
  }

  Future<List<FileEntry>?> _list(String dir) async {
    checkCancellation();
    if (_listings.containsKey(dir)) return _listings[dir];
    final shared = options.directoryCache?[dir];
    if (shared == null && _listCalls >= options.maxListCalls) {
      _budgetExhausted = true;
      return null;
    }
    if (options.backend.traits.symlinks && !await _confirmDirectory(dir)) {
      _listings[dir] = null;
      return null;
    }
    checkCancellation();
    if (shared != null) {
      return _listings[dir] = _safeEntries(shared);
    }

    _listCalls++;
    final entries = await _request(() => options.backend.list(dir));
    if (entries == null) {
      _listings[dir] = null;
      return null;
    }

    checkCancellation();
    final safe = _safeEntries(entries);
    _directories[dir] = true;
    options.directoryCache?.putIfAbsent(dir, () => safe);
    return _listings[dir] = safe;
  }

  /// On link-capable backends, a listing can follow intermediate symlinks.
  /// Check components below the caller's root from top to bottom first.
  Future<bool> _confirmDirectory(String dir) async {
    final unverified = <String>[];
    var ancestor = dir;
    while (ancestor != query.root && !_directories.containsKey(ancestor)) {
      unverified.add(ancestor);
      ancestor = _parentOf(ancestor);
    }

    var exists = ancestor == query.root || _directories[ancestor] == true;
    for (final path in unverified.reversed) {
      exists = exists && await _statDirectory(path);
      _directories[path] = exists;
    }
    return exists;
  }

  Future<bool> _existsAfterListFailure(String dir) async {
    if (!_listings.containsKey(dir)) return false;
    return _directories[dir] ??= await _statDirectory(dir);
  }

  Future<bool> _statDirectory(String dir) async {
    checkCancellation();
    if (_statCalls >= options.maxStatCalls) {
      _budgetExhausted = true;
      return false;
    }
    _statCalls++;
    final entry = await _request(() => options.backend.stat(dir));
    return entry?.isDir ?? false;
  }

  Future<T?> _request<T>(Future<T?> Function() request) async {
    checkCancellation();
    try {
      return await request();
    } on Exception {
      // Backends can report absent and unreadable directories as list errors.
      // Stat can verify an existing ancestor before it is offered as a result.
      return null;
    } finally {
      checkCancellation();
    }
  }

  void checkCancellation() {
    if (isCancelled?.call() == true) throw const _SearchCancelled();
  }

  bool _visible(String name, String segment) =>
      showHiddenFiles || !name.startsWith('.') || segment.startsWith('.');

  String _parentOf(String path) {
    if (path == query.root) return path;
    final slash = path.lastIndexOf('/');
    final bareParent = slash <= 0 ? '/' : path.substring(0, slash);
    return query.root == '$bareParent/' ? query.root : bareParent;
  }

  String _basename(String path) {
    if (path == '/') return path;
    final end = path.endsWith('/') ? path.length - 1 : path.length;
    return path.substring(path.lastIndexOf('/', end - 1) + 1, end);
  }

  PathMatchCandidate _candidate(
    String path,
    FileEntry entry, {
    required bool exact,
    required int score,
  }) => PathMatchCandidate(
    fullPath: path,
    parentDir: _parentOf(path),
    entry: entry,
    matchKind: entry.isDir
        ? (exact ? PathMatchKind.exactDir : PathMatchKind.fuzzyDir)
        : (exact ? PathMatchKind.exactFile : PathMatchKind.fuzzyFile),
    score: exact ? 100 : math.min(score, 99),
  );

  PathMatchCandidate _directoryCandidate(
    String dir,
    PathMatchKind kind,
    int score,
  ) => PathMatchCandidate(
    fullPath: dir,
    parentDir: _parentOf(dir),
    entry: FileEntry(name: _basename(dir), kind: FileKind.dir),
    matchKind: kind,
    score: score,
  );

  void _add(PathMatchCandidate candidate) {
    final previous = _candidates[candidate.fullPath];
    if (previous == null || candidate.score > previous.score) {
      _candidates[candidate.fullPath] = candidate;
    }
  }

  List<FileEntry> _safeEntries(List<FileEntry> entries) => List.unmodifiable(
    entries.where((entry) => query.isSafeEntryName(entry.name)),
  );
}

final class _SearchCancelled implements Exception {
  const _SearchCancelled();
}

int _score(String query, String name) {
  if (query == name) return 100;
  final needle = query.toLowerCase();
  final haystack = name.toLowerCase();
  if (needle == haystack) return 90;
  if (haystack.startsWith(needle)) return 78;
  if (haystack.contains(needle)) return 66;
  if (needle.length >= 3 && _isSubsequence(needle, haystack)) return 50;

  if (needle.length < 3 || needle.length > 64 || haystack.length > 64) return 0;
  final limit = needle.length <= 5 ? 1 : 2;
  final edits = _editDistance(needle, haystack, limit);
  return edits <= limit ? 40 - edits * 4 : 0;
}

bool _isSubsequence(String needle, String haystack) {
  var matched = 0;
  for (var i = 0; i < haystack.length; i++) {
    if (haystack.codeUnitAt(i) == needle.codeUnitAt(matched)) {
      if (++matched == needle.length) return true;
    }
  }
  return false;
}

int _editDistance(String a, String b, int limit) {
  if ((a.length - b.length).abs() > limit) return limit + 1;
  var row = List.generate(b.length + 1, (i) => i);
  var next = List.filled(row.length, 0);
  for (var i = 1; i <= a.length; i++) {
    next[0] = i;
    var best = i;
    for (var j = 1; j <= b.length; j++) {
      final cost = a.codeUnitAt(i - 1) == b.codeUnitAt(j - 1) ? 0 : 1;
      next[j] = math.min(
        row[j - 1] + cost,
        math.min(next[j - 1] + 1, row[j] + 1),
      );
      best = math.min(best, next[j]);
    }
    if (best > limit) return limit + 1;
    (row, next) = (next, row);
  }
  return row.last;
}
