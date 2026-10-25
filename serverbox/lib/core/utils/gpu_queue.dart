/// GPU Queue is reached through the owner's existing loopback SSH forward.
/// This link only opens the task page; it cannot grant execution approval.
abstract final class GpuQueue {
  static const address = String.fromEnvironment(
    'GPU_QUEUE_URL',
    defaultValue: 'http://127.0.0.1:8790/',
  );

  static Uri? parseAddress(String value) {
    final uri = Uri.tryParse(value);
    if (uri == null ||
        uri.scheme != 'http' ||
        !const ['127.0.0.1', 'localhost', '::1'].contains(uri.host) ||
        uri.userInfo.isNotEmpty ||
        uri.hasQuery ||
        uri.hasFragment ||
        uri.port < 1 ||
        uri.port > 65535 ||
        (uri.path.isNotEmpty && uri.path != '/')) {
      return null;
    }
    return uri;
  }

  static Uri get uri =>
      parseAddress(address) ?? Uri.parse('http://127.0.0.1:8790/');
}
