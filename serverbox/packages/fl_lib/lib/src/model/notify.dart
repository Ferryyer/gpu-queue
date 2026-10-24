import 'package:fl_lib/src/core/dio.dart';

final class AppNotify {
  final String title;
  final String msg;
  final List<AppNotifyVer> vers;
  final int level;

  const AppNotify({
    required this.title,
    required this.msg,
    required this.vers,
    required this.level,
  });

  static Future<List<AppNotify>?> fetch(
    String url, {
    void Function(Object e, StackTrace s)? onErr,
  }) async {
    try {
      final resp = await myDio.get(url);
      return AppNotify.fromJsonList(resp.data);
    } catch (e, s) {
      onErr?.call(e, s);
    }
    return null;
  }

  bool contains(int ver) {
    return vers.any((e) => ver >= e.min && ver <= e.max);
  }

  static AppNotify fromJson(Map<String, dynamic> json) {
    return AppNotify(
      title: json['title'],
      msg: json['msg'],
      vers: (json['vers'] as List)
          .cast<String>()
          .map(AppNotifyVer.parse)
          .toList(),
      level: json['level'],
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'title': title,
      'msg': msg,
      'vers': vers,
      'level': level,
    };
  }

  static List<AppNotify> fromJsonList(List<dynamic> list) {
    return list.map((e) => AppNotify.fromJson(e)).toList();
  }
}

final class AppNotifyVer {
  final int min;
  final int max;

  const AppNotifyVer(this.min, this.max);

  static AppNotifyVer parse(String ver) {
    final parts = ver.split('-');
    if (parts.length != 2) throw 'Invalid version format: $ver';
    final minV = int.tryParse(parts[0]);
    final maxV = int.tryParse(parts[1]);
    if (minV == null || maxV == null) throw 'Invalid version format: $ver';
    return AppNotifyVer(minV, maxV);
  }
}
