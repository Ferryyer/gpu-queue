import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:server_box/core/update/release.dart';

void main() {
  const url = 'https://github.com/Ferryyer/gpu-queue/releases/download/v2.0.2004/GPU-Queue-macos-arm64-2004-unsigned.dmg';
  final asset = <String, dynamic>{'browser_download_url': url, 'state': 'uploaded', 'size': 54000000, 'digest': 'sha256:${'a' * 64}'};
  Map<String, dynamic> release() => {'draft': false, 'prerelease': false, 'tag_name': 'v2.0.2004', 'assets': [Map.of(asset)]};
  test('uses immutable project tag and published SHA-256 asset', () {
    final value = MacUpdateRelease.parse(jsonEncode(release()), url, 2004);
    expect(value.sha256, 'a' * 64);
    expect(value.bytes, 54000000);
    expect(MacUpdateRelease.apiFor(url, 2004).toString(), 'https://api.github.com/repos/Ferryyer/gpu-queue/releases/tags/v2.0.2004');
  });
  test('rejects foreign, unversioned, or inconsistent asset URLs', () {
    for (final invalid in [url.replaceFirst('https:', 'http:'), url.replaceFirst('github.com', 'evil.example'),
      url.replaceFirst('Ferryyer', 'another'), '$url?raw=1', '$url#x',
      url.replaceFirst('/v2.0.2004/', '/v2.0.2005/'), url.replaceFirst('-2004-', '-2005-'),
      url.replaceFirst('github.com', 'user@github.com'), url.replaceFirst('github.com', 'github.com:443')]) {
      expect(() => MacUpdateRelease.apiFor(invalid, 2004), throwsFormatException, reason: invalid);
    }
  });
  test('rejects draft, prerelease, wrong tag and duplicate assets', () {
    for (final override in [<String, dynamic>{'draft': true}, {'prerelease': true}, {'tag_name': 'v2.0.2003'}, {'assets': [asset, asset]}, {'assets': []}]) {
      expect(() => MacUpdateRelease.parse(jsonEncode(release()..addAll(override)), url, 2004), throwsFormatException);
    }
  });
  test('requires uploaded asset, bounded byte count and SHA-256', () {
    for (final override in [<String, dynamic>{'digest': null}, {'digest': 'sha256:abc'}, {'state': 'new'}, {'size': 0}, {'size': 600 * 1024 * 1024}]) {
      final data = release()..['assets'] = [Map.of(asset)..addAll(override)];
      expect(() => MacUpdateRelease.parse(jsonEncode(data), url, 2004), throwsFormatException);
    }
  });
}
