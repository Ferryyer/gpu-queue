import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:server_box/data/model/file/file_backend.dart';
import 'package:server_box/data/model/file/path_query.dart';
import 'package:server_box/data/model/file/path_resolver.dart';

const _root = '/fixtures';

ParsedPathQuery _parse(
  String input, {
  String current = _root,
  String root = _root,
  String? home,
}) => ParsedPathQuery.parse(
  input,
  currentDir: current,
  root: root,
  homePath: home,
);

FileEntry _file(String name) => FileEntry(name: name, kind: FileKind.file);
FileEntry _dir(String name) => FileEntry(name: name, kind: FileKind.dir);

class _Backend implements FileBackend {
  _Backend(this.tree, {bool symlinks = false})
    : traits = FileBackendTraits(symlinks: symlinks);

  final Map<String, List<FileEntry>> tree;
  final listed = <String>[];
  final checked = <String>[];
  Future<List<FileEntry>> Function(String)? onList;
  Future<FileEntry?> Function(String)? onStat;

  @override
  final FileBackendTraits traits;

  @override
  Future<List<FileEntry>> list(String path) async {
    listed.add(path);
    final hook = onList;
    if (hook != null) return hook(path);
    return tree[path] ?? (throw Exception('Directory unavailable'));
  }

  @override
  Future<FileEntry?> stat(String path) async {
    checked.add(path);
    final hook = onStat;
    if (hook != null) return hook(path);
    final slash = path.lastIndexOf('/');
    final parent = slash <= 0 ? '/' : path.substring(0, slash);
    final name = path.substring(slash + 1);
    for (final entry in tree[parent] ?? const <FileEntry>[]) {
      if (entry.name == name) return entry;
    }
    return tree.containsKey(path) ? _dir(name) : null;
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

void main() {
  group('pasted paths', () {
    test('unwraps clipboard text and recognizes all line suffix forms', () {
      for (final (input, line) in [
        ('  "\n/fixtures/code.py:42\n"  ', 42),
        ("  '/fixtures/code.py':42:10  ", 42),
        ('  `/fixtures/code.py#L42`  ', 42),
        ('  </fixtures/code.py#L42-L59>  ', 42),
        ('  /fixtures/code.py:notes  ', null),
      ]) {
        final query = _parse(input);
        expect(
          query.targetPath,
          line == null ? '/fixtures/code.py:notes' : '/fixtures/code.py',
          reason: input,
        );
        expect(query.line, line, reason: input);
        expect(query.isPathLike, isTrue, reason: input);
      }
    });

    test(
      'decodes file URIs and retains invalid percent encoding literally',
      () {
        expect(
          _parse('file:///fixtures/code%20sample.py#L9').targetPath,
          '/fixtures/code sample.py',
        );
        for (final name in ['bad%ZZ.py', 'bad%FF.py', 'bad%.py']) {
          expect(
            _parse('file:///fixtures/$name').targetPath,
            '/fixtures/$name',
          );
        }
        final escapedName = _parse('file://localhost/fixtures/report%3A42');
        expect(escapedName.targetPath, '/fixtures/report:42');
        expect(escapedName.line, isNull);
      },
    );

    test('handles SCP, Windows drive letters, and slash normalization', () {
      expect(
        _parse(r'person@compute.example:/fixtures\logs\output:42').targetPath,
        '/fixtures/logs/output',
      );
      expect(
        _parse('compute.example:~/logs', home: '/fixtures/home').targetPath,
        '/fixtures/home/logs',
      );
      expect(
        _parse(
          r'C:\Fixtures\logs\output:42',
          root: 'C:/Fixtures',
          current: 'C:/Fixtures',
        ).targetPath,
        'C:/Fixtures/logs/output',
      );
      expect(
        _parse('file:///C:/', root: 'C:/', current: 'C:/').targetPath,
        'C:/',
      );
    });

    test('distinguishes names, relative paths, and unexpanded home', () {
      expect(_parse('output.log').isPathLike, isFalse);
      expect(_parse('.env').isPathLike, isTrue);
      final relative = _parse(r'..\src\cfg.yml', current: '/fixtures/sub');
      expect(relative.isRelative, isTrue);
      expect(relative.targetPath, '/fixtures/src/cfg.yml');
      expect(_parse('~', home: '/fixtures/home').targetPath, '/fixtures/home');
      expect(
        _parse('~/src', home: '/fixtures/home').targetPath,
        '/fixtures/home/src',
      );
      expect(_parse('~/fixtures/src', home: '/').targetPath, '/fixtures/src');
      final unresolved = _parse('~/src');
      expect(unresolved.cleanedPath, '~/src');
      expect(unresolved.targetPath, isNull);
      expect(unresolved.isOutOfBounds, isFalse);
    });
  });

  test(
    'one listing finds an exact file, exact dir, and ranks siblings',
    () async {
      final backend = _Backend({
        _root: [
          _file('train.py.bak'),
          _file('train_v2.py'),
          _file('xtrain.py'),
          _file('TRAIN.PY'),
          _file('train.py'),
          _dir('TrainFiles'),
        ],
      });
      final resolver = PathResolver(backend);
      final files = await resolver.resolve(_parse('/fixtures/train.py'));
      expect(files.candidates.map((item) => item.entry.name), [
        'train.py',
        'TRAIN.PY',
        'train.py.bak',
        'xtrain.py',
        'train_v2.py',
      ]);
      final exact = files.candidates.first;
      expect(exact.fullPath, '/fixtures/train.py');
      expect(exact.parentDir, _root);
      expect(exact.matchKind, PathMatchKind.exactFile);
      expect(exact.score, 100);
      expect(files.nearestExistingDir, isNull);
      expect(backend.listed, [_root]);

      final directory = await resolver.resolve(_parse('/fixtures/TrainFiles'));
      expect(directory.candidates.first.matchKind, PathMatchKind.exactDir);
      final root = await resolver.resolve(_parse('/fixtures/'));
      expect(root.candidates.single.matchKind, PathMatchKind.exactDir);
      expect(root.candidates.single.parentDir, _root);
    },
  );

  test('matches misspellings, missing letters and subsequences', () async {
    final resolver = PathResolver(
      _Backend({
        _root: [
          _file('train.py'),
          _file('train_config.yml'),
          _dir('sample-dir'),
        ],
      }),
    );
    for (final (query, name, kind) in [
      ('trzin.py', 'train.py', PathMatchKind.fuzzyFile),
      ('tran.py', 'train.py', PathMatchKind.fuzzyFile),
      ('trn_cnf.yml', 'train_config.yml', PathMatchKind.fuzzyFile),
      ('sampl-di', 'sample-dir', PathMatchKind.fuzzyDir),
    ]) {
      final result = await resolver.resolve(_parse(query));
      expect(result.candidates.first.entry.name, name, reason: query);
      expect(result.candidates.first.matchKind, kind, reason: query);
    }
  });

  test(
    'probes a missing parent, then ranks paths from the nearest ancestor',
    () async {
      final backend = _Backend({
        '/fixtures/exp': [_dir('run_02'), _dir('run_010')],
        '/fixtures/exp/run_02': [_file('train_v2.py')],
        '/fixtures/exp/run_010': [_file('train.py')],
      });
      final result = await PathResolver(backend)
          .resolve(_parse('/fixtures/exp/run_01/train.py'));

      expect(backend.listed.take(2), ['/fixtures/exp/run_01', '/fixtures/exp']);
      expect(result.nearestExistingDir, '/fixtures/exp');
      expect(result.candidates.map((item) => item.fullPath), [
        '/fixtures/exp/run_010/train.py',
        '/fixtures/exp/run_02/train_v2.py',
        '/fixtures/exp',
      ]);
      expect(result.candidates.last.matchKind, PathMatchKind.nearestDir);
    },
  );

  test('can locate a target under one omitted directory', () async {
    final backend = _Backend({
      _root: [_dir('outputs')],
      '/fixtures/outputs': [_dir('generated')],
      '/fixtures/outputs/generated': [_file('report.json')],
    });
    final result = await PathResolver(backend)
        .resolve(_parse('outputs/report.json'));
    expect(
      result.candidates.first.fullPath,
      '/fixtures/outputs/generated/report.json',
    );
    expect(result.candidates.first.matchKind, PathMatchKind.fuzzyFile);
  });

  test(
    'reports the deepest confirmed ancestor and tolerates list errors',
    () async {
      final backend = _Backend({
        _root: [_dir('reports')],
        '/fixtures/reports': [],
      });
      backend.onList = (path) async => throw Exception('Directory unavailable');
      final result = await PathResolver(backend)
          .resolve(_parse('/fixtures/reports/missing/deep/private.txt'));
      expect(result.nearestExistingDir, '/fixtures/reports');
      expect(result.candidates.single.entry.name, 'reports');
      expect(backend.listed, [
        '/fixtures/reports/missing/deep',
        '/fixtures/reports/missing',
        '/fixtures/reports',
      ]);
    },
  );

  test('prefers the current directory, then tries up to three distinct history dirs', () async {
    final backend = _Backend({
      _root: [],
      '/fixtures/current': [_dir('src')],
      '/fixtures/current/src': [_file('here.yml')],
      '/fixtures/store3/src': [_file('config.yml')],
      '/fixtures/store4/src': [_file('absent.yml')],
    });
    final resolver = PathResolver(backend);
    const history = [
      '/unrelated',
      '/fixtures/current',
      '/fixtures/store1',
      '/fixtures/./store1/',
      '/fixtures/store2',
      '/fixtures/store3',
      '/fixtures/store4',
    ];
    final exact = await resolver.resolve(
      _parse('src/here.yml', current: '/fixtures/current'),
      historyDirs: history,
    );
    expect(exact.candidates.first.fullPath, '/fixtures/current/src/here.yml');
    expect(backend.listed, ['/fixtures/current/src']);

    backend.listed.clear();
    final rebased = await resolver.resolve(
      _parse('src/config.yml', current: '/fixtures/current'),
      historyDirs: history,
    );
    expect(
      rebased.candidates.first.fullPath,
      '/fixtures/store3/src/config.yml',
    );
    expect(rebased.candidates.first.matchKind, PathMatchKind.exactFile);
    expect(rebased.nearestExistingDir, isNull);
    expect(backend.listed, [
      '/fixtures/current/src',
      '/fixtures/store1/src',
      '/fixtures/store2/src',
      '/fixtures/store3/src',
    ]);

    backend.listed.clear();
    await resolver.resolve(
      _parse('src/absent.yml', current: '/fixtures/current'),
      historyDirs: history,
    );
    expect(backend.listed, isNot(contains('/fixtures/store4/src')));
  });

  test('rejects root escapes before any backend request', () async {
    final backend = _Backend({}, symlinks: true);
    final resolver = PathResolver(backend);
    for (final query in [
      _parse('/../../etc/passwd', root: '/', current: '/'),
      _parse('/fixtures/../../etc/passwd'),
      _parse('/fixtures/../fixtures/report'),
      _parse('/fixtures-copy/report'),
      _parse('../report'),
      _parse('file:///fixtures/%2e%2e/report'),
      _parse('~/report', home: '/outside'),
      _parse('report', current: '/outside'),
      _parse('C:/../C:/report', root: 'C:/', current: 'C:/'),
      _parse(
        'C:/Fixtures/.. /report',
        root: 'C:/Fixtures',
        current: 'C:/Fixtures',
      ),
    ]) {
      expect(query.isOutOfBounds, isTrue, reason: query.cleanedPath);
      final result = await resolver.resolve(query, historyDirs: [_root]);
      expect(result.candidates, isEmpty);
    }
    await resolver.resolve(_parse('~/report'));
    expect(backend.listed, isEmpty);
    expect(backend.checked, isEmpty);
  });

  test('preserves the absolute form of a Windows drive root', () async {
    final backend = _Backend({'C:/': []});
    final result = await PathResolver(backend)
        .resolve(_parse('C:/', root: 'C:/', current: 'C:/'));
    expect(result.candidates.single.fullPath, 'C:/');
    expect(backend.listed, ['C:/']);
  });

  test('filters untrusted entry names and applies hidden visibility after cache reads', () async {
    final backend = _Backend({});
    final resolver = PathResolver(
      backend,
      directoryCache: {
        _root: [
          _file(''),
          _dir('.'),
          _dir('..'),
          _file('../outside'),
          _file(r'..\outside'),
          _file('.env'),
          _dir('.config'),
          _file('env.txt'),
        ],
        '/fixtures/.config': [_file('app.ini')],
      },
    );
    final visible = await resolver.resolve(_parse('env'));
    expect(visible.candidates.map((item) => item.entry.name), [
      'env.txt',
      'fixtures',
    ]);
    final hidden = await resolver.resolve(_parse('env'), showHiddenFiles: true);
    expect(hidden.candidates.map((item) => item.entry.name), contains('.env'));

    final exact = await resolver.resolve(_parse('.env'));
    expect(exact.candidates.first.fullPath, '/fixtures/.env');
    final nested = await resolver.resolve(_parse('.config/app.ini'));
    expect(nested.candidates.first.fullPath, '/fixtures/.config/app.ini');
    final omitted = await resolver.resolve(_parse('app.ini'));
    expect(omitted.candidates.map((item) => item.entry.name), ['fixtures']);

    final bogus = await resolver.resolve(
      _parse('outside'),
      showHiddenFiles: true,
    );
    expect(bogus.candidates.map((item) => item.entry.name), ['fixtures']);
    expect(backend.listed, isEmpty);
  });

  test('cache keys are normalized and successful results are reused', () async {
    final backend = _Backend({
      '/fixtures/src': [_file('config.yml'), _file('../config.yml')],
    });
    final cache = <String, List<FileEntry>>{};
    final resolver = PathResolver(backend, directoryCache: cache);
    final first = await resolver.resolve(_parse('src//./config.yml'));
    final second = await resolver.resolve(_parse('/fixtures/src/config.yml'));
    expect(first.candidates.single.fullPath, second.candidates.single.fullPath);
    expect(cache.keys, ['/fixtures/src']);
    expect(cache['/fixtures/src']!.map((entry) => entry.name), ['config.yml']);
    expect(backend.listed, ['/fixtures/src']);
  });

  test('never descends into links in a direct path or fuzzy branch', () async {
    final backend = _Backend({
      _root: [const FileEntry(name: 'linked', kind: FileKind.link)],
      '/fixtures/linked/sub': [_file('private.txt')],
    }, symlinks: true);
    final resolver = PathResolver(backend);
    final result = await resolver.resolve(_parse('linked/sub/private.txt'));
    expect(result.nearestExistingDir, _root);
    expect(result.candidates.single.matchKind, PathMatchKind.nearestDir);
    expect(backend.checked, ['/fixtures/linked']);
    expect(backend.listed, [_root]);
    final direct = await resolver.resolve(_parse('linked'));
    expect(direct.candidates.single.matchKind, PathMatchKind.nearestDir);
  });

  test('enforces list, depth, and branch limits independently', () async {
    final backend = _Backend({
      _root: [
        _dir('run_00a'),
        _dir('run_00b'),
        _dir('run_00c'),
        _dir('run_00d'),
      ],
      '/fixtures/run_00a': [_dir('result')],
      '/fixtures/run_00b': [_dir('result')],
    });
    const input = 'run_00/result/train.py';
    final bounded = await PathResolver(
      backend,
      maxListCalls: 4,
    ).resolve(_parse(input));
    expect(backend.listed.length, 4);
    expect(bounded.truncated, isTrue);
    expect(bounded.budgetExhausted, isTrue);
    expect(bounded.nearestExistingDir, _root);

    backend.listed.clear();
    final narrow = await PathResolver(
      backend,
      maxBranch: 1,
      maxDepth: 0,
    ).resolve(_parse(input));
    expect(backend.listed, [
      '/fixtures/run_00/result',
      '/fixtures/run_00',
      _root,
    ]);
    expect(narrow.truncated, isTrue);
    expect(narrow.budgetExhausted, isFalse);

    backend.listed.clear();
    await PathResolver(
      backend,
      maxBranch: 1,
      maxDepth: 1,
    ).resolve(_parse(input));
    expect(backend.listed.last, '/fixtures/run_00a');
    expect(backend.listed, isNot(contains('/fixtures/run_00b')));
  });

  test(
    'cancellation before or during a list stops requests and cache writes',
    () async {
      final backend = _Backend({});
      final cache = <String, List<FileEntry>>{};
      final resolver = PathResolver(backend, directoryCache: cache);
      final query = _parse('src/train.py');
      final alreadyCancelled = await resolver.resolve(
        query,
        isCancelled: () => true,
      );
      expect(alreadyCancelled.cancelled, isTrue);
      expect(backend.listed, isEmpty);

      final request = Completer<List<FileEntry>>();
      final started = Completer<void>();
      backend.onList = (_) {
        started.complete();
        return request.future;
      };
      var cancel = false;
      final future = resolver.resolve(query, isCancelled: () => cancel);
      await started.future;
      cancel = true;
      request.complete([_file('train.py')]);
      final cancelled = await future;
      expect(cancelled.cancelled, isTrue);
      expect(cancelled.candidates, isEmpty);
      expect(cache, isEmpty);
      expect(backend.listed, ['/fixtures/src']);
      expect(backend.checked, isEmpty);
    },
  );

  test('cancellation after a stat prevents subsequent I/O', () async {
    var cancel = false;
    final backend = _Backend({}, symlinks: true);
    backend.onStat = (_) async {
      cancel = true;
      return _dir('src');
    };
    final result = await PathResolver(backend)
        .resolve(_parse('src/build/train.py'), isCancelled: () => cancel);
    expect(result.cancelled, isTrue);
    expect(backend.checked, ['/fixtures/src']);
    expect(backend.listed, isEmpty);
  });
}
