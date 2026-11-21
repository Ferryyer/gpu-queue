import 'dart:convert';

/// The installer accepts only this project's immutable, versioned DMG asset.
class MacUpdateRelease {
  final Uri url;
  final int build;
  final int bytes;
  final String sha256;
  final String version;

  const MacUpdateRelease(this.url, this.build, this.bytes, this.sha256, this.version);

  static Uri apiFor(String raw, int build) {
    final uri = Uri.parse(raw);
    final match = RegExp(r'^/Ferryyer/gpu-queue/releases/download/(v(2\.0\.(\d+)))/(?:Inspire-Queue|GPU-Queue)-macos-(arm64|x86_64)-(\d+)-unsigned\.dmg$').firstMatch(uri.path);
    if (raw != 'https://github.com${uri.path}' || uri.scheme != 'https' || uri.host != 'github.com' || uri.hasPort ||
        uri.userInfo.isNotEmpty || uri.hasQuery || uri.hasFragment || match == null ||
        int.parse(match.group(3)!) != build || int.parse(match.group(5)!) != build) {
      throw const FormatException('更新下载地址或版本不匹配');
    }
    return Uri.https('api.github.com', '/repos/Ferryyer/gpu-queue/releases/tags/${match.group(1)}');
  }

  factory MacUpdateRelease.parse(String raw, String url, int build) {
    apiFor(url, build);
    final data = jsonDecode(raw) as Map<String, dynamic>;
    final version = '2.0.$build';
    if (data['draft'] != false || data['prerelease'] != false || data['tag_name'] != 'v$version') {
      throw const FormatException('更新版本尚未正式发布');
    }
    final assets = (data['assets'] as List).whereType<Map<String, dynamic>>().where((a) => a['browser_download_url'] == url).toList();
    if (assets.length != 1) throw const FormatException('找不到唯一的更新安装包');
    final asset = assets.single;
    final digest = asset['digest']?.toString() ?? '';
    final bytes = asset['size'];
    if (asset['state'] != 'uploaded' || bytes is! int || bytes <= 0 || bytes > 512 * 1024 * 1024 ||
        !RegExp(r'^sha256:[a-f0-9]{64}$').hasMatch(digest)) {
      throw const FormatException('安装包大小或 SHA-256 校验信息不完整');
    }
    return MacUpdateRelease(Uri.parse(url), build, bytes, digest.substring(7), version);
  }
}
