import 'package:fl_lib/fl_lib.dart';
import 'package:flutter_test/flutter_test.dart';

extension on MockStore {
  Future<void> setWithTimestamp(String key, Object value, int timestamp) async {
    set(key, value);
    updateLastUpdateTs(ts: timestamp, key: key);
  }
}

void main() {
  group('Mergeable.mergeStore', () {
    late MockStore store;
    
    setUp(() {
      store = MockStore();
    });
    
    test('合并空备份到空 store', () async {
      final backupData = <String, Object?>{};
      
      await Mergeable.mergeStore(
        backupData: backupData,
        store: store,
        force: false,
      );
      
      expect(store.keys(), <String>{});
    });
    
    test('备份有但当前没有 - 备份时间戳更新', () async {
      final backupData = <String, Object?>{
        'key1': 'value1',
        'key2': 42,
        store.lastUpdateTsKey: {
          'key1': 2000,
          'key2': 2000,
        },
      };
      
      await Mergeable.mergeStore(
        backupData: backupData,
        store: store,
        force: false,
      );
      
      expect(store.get('key1'), 'value1');
      expect(store.get('key2'), 42);
      expect(store.lastUpdateTs?['key1'], 2000);
      expect(store.lastUpdateTs?['key2'], 2000);
    });
    
    test('备份有但当前没有 - 备份时间戳旧（应忽略）', () async {
      // 先设置当前 store 的时间戳
      store.updateLastUpdateTs(ts: 3000, key: 'key1');
      
      final backupData = <String, Object?>{
        'key1': 'old_value',
        store.lastUpdateTsKey: {
          'key1': 1000,
        },
      };
      
      await Mergeable.mergeStore(
        backupData: backupData,
        store: store,
        force: false,
      );
      
      expect(store.get('key1'), null); // 不应该添加旧数据
    });
    
    test('当前有但备份没有 - 备份时间戳更新（应删除）', () async {
      // 设置当前数据
      await store.setWithTimestamp('key1', 'current_value', 1000);
      
      final backupData = <String, Object?>{
        store.lastUpdateTsKey: {
          'key1': 2000, // 备份的时间戳更新，表示已删除
        },
      };
      
      await Mergeable.mergeStore(
        backupData: backupData,
        store: store,
        force: false,
      );
      
      expect(store.get('key1'), null); // 应该被删除
    });
    
    test('当前有但备份没有 - 当前时间戳更新（应保留）', () async {
      // 设置当前数据
      await store.setWithTimestamp('key1', 'current_value', 3000);
      
      final backupData = <String, Object?>{
        store.lastUpdateTsKey: {
          'key1': 1000, // 备份的时间戳旧
        },
      };
      
      await Mergeable.mergeStore(
        backupData: backupData,
        store: store,
        force: false,
      );
      
      expect(store.get('key1'), 'current_value'); // 应该保留
    });
    
    test('都有 key - 备份时间戳更新', () async {
      // 设置当前数据
      await store.setWithTimestamp('key1', 'current_value', 1000);
      
      final backupData = <String, Object?>{
        'key1': 'backup_value',
        store.lastUpdateTsKey: {
          'key1': 2000,
        },
      };
      
      await Mergeable.mergeStore(
        backupData: backupData,
        store: store,
        force: false,
      );
      
      expect(store.get('key1'), 'backup_value');
      expect(store.lastUpdateTs?['key1'], 2000);
    });
    
    test('都有 key - 当前时间戳更新', () async {
      // 设置当前数据
      await store.setWithTimestamp('key1', 'current_value', 3000);
      
      final backupData = <String, Object?>{
        'key1': 'backup_value',
        store.lastUpdateTsKey: {
          'key1': 1000,
        },
      };
      
      await Mergeable.mergeStore(
        backupData: backupData,
        store: store,
        force: false,
      );
      
      expect(store.get('key1'), 'current_value');
      expect(store.lastUpdateTs?['key1'], 3000);
    });
    
    test('force = true 时优先使用备份数据', () async {
      // 设置当前数据
      await store.setWithTimestamp('key1', 'current_value', 3000);
      await store.setWithTimestamp('key2', 'current_value2', 3000);
      
      final backupData = <String, Object?>{
        'key1': 'backup_value',
        'key3': 'backup_value3',
        store.lastUpdateTsKey: {
          'key1': 1000, // 即使备份时间戳旧
          'key2': 1000,
          'key3': 1000,
        },
      };
      
      await Mergeable.mergeStore(
        backupData: backupData,
        store: store,
        force: true,
      );
      
      expect(store.get('key1'), 'backup_value'); // 使用备份值
      expect(store.get('key2'), null); // 备份中没有，被删除
      expect(store.get('key3'), 'backup_value3'); // 新增
    });
    
    test('时间戳格式 - JSON 字符串', () async {
      final backupData = <String, Object?>{
        'key1': 'value1',
        store.lastUpdateTsKey: '{"key1": 2000}',
      };
      
      await Mergeable.mergeStore(
        backupData: backupData,
        store: store,
        force: false,
      );
      
      expect(store.get('key1'), 'value1');
      expect(store.lastUpdateTs?['key1'], 2000);
    });
    
    test('时间戳格式 - 单个整数', () async {
      final backupData = <String, Object?>{
        'key1': 'value1',
        'key2': 'value2',
        store.lastUpdateTsKey: 2000,
      };
      
      await Mergeable.mergeStore(
        backupData: backupData,
        store: store,
        force: false,
      );
      
      expect(store.get('key1'), 'value1');
      expect(store.get('key2'), 'value2');
      expect(store.lastUpdateTs?['key1'], 2000);
      expect(store.lastUpdateTs?['key2'], 2000);
    });
    
    test('时间戳格式 - Map', () async {
      final backupData = <String, Object?>{
        'key1': 'value1',
        store.lastUpdateTsKey: {'key1': 2000},
      };
      
      await Mergeable.mergeStore(
        backupData: backupData,
        store: store,
        force: false,
      );
      
      expect(store.get('key1'), 'value1');
      expect(store.lastUpdateTs?['key1'], 2000);
    });
    
    test('复杂场景 - 多个 key 混合操作', () async {
      // 设置当前数据
      await store.setWithTimestamp('keep1', 'current_keep1', 3000);
      await store.setWithTimestamp('update1', 'current_update1', 1000);
      await store.setWithTimestamp('delete1', 'current_delete1', 1000);
      
      final backupData = <String, Object?>{
        'keep1': 'backup_keep1',
        'update1': 'backup_update1',
        'new1': 'backup_new1',
        store.lastUpdateTsKey: {
          'keep1': 1000,    // 备份旧，保留当前
          'update1': 2000,  // 备份新，更新
          'delete1': 2000,  // 备份新但无数据，删除
          'new1': 2000,     // 新增
        },
      };
      
      await Mergeable.mergeStore(
        backupData: backupData,
        store: store,
        force: false,
      );
      
      expect(store.get('keep1'), 'current_keep1');
      expect(store.get('update1'), 'backup_update1');
      expect(store.get('delete1'), null);
      expect(store.get('new1'), 'backup_new1');
      
      expect(store.lastUpdateTs?['keep1'], 3000);
      expect(store.lastUpdateTs?['update1'], 2000);
      expect(store.lastUpdateTs?['new1'], 2000);
    });
    
    test('null 值处理', () async {
      await store.setWithTimestamp('key1', 'value1', 1000);
      
      final backupData = <String, Object?>{
        'key1': null,
        store.lastUpdateTsKey: {
          'key1': 2000,
        },
      };
      
      await Mergeable.mergeStore(
        backupData: backupData,
        store: store,
        force: false,
      );
      
      expect(store.get('key1'), null); // 应该删除
    });
    
    test('内部 key 处理', () async {
      const internalKey = '${StoreDefaults.prefixKey}internal';
      await store.setWithTimestamp(internalKey, 'internal_value', 1000);
      
      final backupData = <String, Object?>{
        internalKey: 'backup_internal',
        'normal_key': 'normal_value',
        store.lastUpdateTsKey: {
          internalKey: 2000,
          'normal_key': 2000,
        },
      };
      
      await Mergeable.mergeStore(
        backupData: backupData,
        store: store,
        force: false,
      );
      
      expect(store.get(internalKey), 'backup_internal');
      expect(store.get('normal_key'), 'normal_value');
    });
  });
}