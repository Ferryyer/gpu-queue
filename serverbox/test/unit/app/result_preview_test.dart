import 'package:flutter_test/flutter_test.dart';
import 'package:server_box/core/utils/result_preview.dart';

void main() {
  test('keeps result paths, escaped names, query and fragments intact', () {
    const url = 'http://127.0.0.1:8780/f/cccagUFvFH84/T04-biology-cropping-20261030/index.html?name=a%2Fb#figure';
    expect(parseResultPreviewUrl('  $url  ').toString(), url);
    expect(parseResultPreviewUrl('https://localhost:8780/').scheme, 'https');
  });

  test('does not open another origin or credentials through the shortcut', () {
    for (final url in ['http://127.0.0.1:8790/', 'http://localhost/',
      'http://localhost.example:8780/', 'http://example.com:8780/',
      'http://user:secret@localhost:8780/', 'file:///etc/passwd',
      'javascript:alert(1)', '//localhost:8780/', 'not a link']) {
      expect(() => parseResultPreviewUrl(url), throwsFormatException, reason: url);
    }
  });
}
