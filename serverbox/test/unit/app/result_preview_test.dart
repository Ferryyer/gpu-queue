import 'package:flutter_test/flutter_test.dart';
import 'package:server_box/core/utils/result_preview.dart';

void main() {
  test('keeps result paths, escaped names, query and fragments intact', () {
    const url = 'http://127.0.0.1:8780/f/example-token/project-a/index.html?name=a%2Fb#figure';
    expect(parseResultPreviewUrl('  $url  ').toString(), url);
    expect(parseResultPreviewUrl('http://localhost:8780/').host, 'localhost');
  });

  test('does not open another origin or credentials through the shortcut', () {
    for (final url in ['https://localhost:8780/', 'http://127.0.0.1:8790/', 'http://localhost/',
      'http://localhost.example:8780/', 'http://example.com:8780/',
      'http://user:secret@localhost:8780/', 'file:///etc/passwd',
      'javascript:alert(1)', '//localhost:8780/', 'not a link']) {
      expect(() => parseResultPreviewUrl(url), throwsFormatException, reason: url);
    }
  });
}
