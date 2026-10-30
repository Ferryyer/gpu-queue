const resultPreviewDestination = 'inspire-results://fileshare';

/// A single loopback service can serve any number of result paths. Keeping
/// the original origin also preserves absolute assets, redirects and sockets.
Uri parseResultPreviewUrl(String input) {
  final uri = Uri.tryParse(input.trim());
  if (uri == null ||
      uri.scheme != 'http' ||
      !const ['127.0.0.1', 'localhost'].contains(uri.host) ||
      uri.userInfo.isNotEmpty ||
      uri.port != 8780) {
    throw const FormatException('请粘贴以 http://127.0.0.1:8780/ 或 http://localhost:8780/ 开头的成果链接。');
  }
  return uri;
}
