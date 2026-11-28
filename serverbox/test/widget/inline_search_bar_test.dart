import 'package:fl_lib/fl_lib.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';

void main() {
  late InlineSearchController controller;

  setUp(() => controller = InlineSearchController());
  tearDown(() => controller.dispose());

  Future<void> pumpBar(
    WidgetTester tester, {
    ValueChanged<String>? onSubmitted,
    FocusOnKeyEventCallback? onKeyEvent,
    FocusNode? focusNode,
    Widget? trailing,
  }) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: InlineSearchBar(
            controller: controller,
            onSubmitted: onSubmitted,
            onKeyEvent: onKeyEvent,
            focusNode: focusNode,
            trailing: trailing,
            child: const Text('Files'),
          ),
        ),
      ),
    );
    controller.start();
    await tester.pumpAndSettle();
  }

  testWidgets('default submission dismisses focus and retains the query', (
    tester,
  ) async {
    await pumpBar(tester);
    final field = find.byType(TextField);
    final editable = tester.widget<EditableText>(find.byType(EditableText));
    expect(editable.focusNode.hasFocus, isTrue);

    await tester.enterText(field, 'report.txt');
    await tester.testTextInput.receiveAction(TextInputAction.search);
    await tester.pumpAndSettle();

    expect(editable.focusNode.hasFocus, isFalse);
    expect(controller.needle, 'report.txt');
    expect(field, findsOneWidget);
  });

  testWidgets('submission and navigation use the caller’s handlers', (
    tester,
  ) async {
    final focus = FocusNode();
    addTearDown(focus.dispose);
    final submitted = <String>[];
    final navigation = <LogicalKeyboardKey>[];
    await pumpBar(
      tester,
      focusNode: focus,
      onSubmitted: submitted.add,
      onKeyEvent: (_, event) {
        if (event is KeyDownEvent &&
            event.logicalKey == LogicalKeyboardKey.arrowDown) {
          navigation.add(event.logicalKey);
          return KeyEventResult.handled;
        }
        return KeyEventResult.ignored;
      },
    );
    expect(tester.widget<TextField>(find.byType(TextField)).focusNode, focus);
    expect(focus.hasFocus, isTrue);

    await tester.enterText(find.byType(TextField), 'example');
    await tester.sendKeyEvent(LogicalKeyboardKey.arrowDown);
    await tester.sendKeyEvent(LogicalKeyboardKey.arrowLeft);
    expect(controller.text.selection, const TextSelection.collapsed(offset: 6));
    await tester.testTextInput.receiveAction(TextInputAction.search);
    await tester.pumpAndSettle();

    expect(navigation, [LogicalKeyboardKey.arrowDown]);
    expect(submitted, ['example']);
    expect(focus.hasFocus, isTrue);
  });

  testWidgets('a trailing action pre-fills the query and places the caret', (
    tester,
  ) async {
    const query = ' /Example/Report.txt ';
    await pumpBar(
      tester,
      trailing: IconButton(
        tooltip: 'Paste path',
        onPressed: () => controller.setQuery(query),
        icon: const Icon(Icons.paste),
      ),
    );
    final action = find.byTooltip('Paste path');
    final close = find.byTooltip(libL10n.close);
    expect(tester.getCenter(action).dx, lessThan(tester.getCenter(close).dx));

    await tester.tap(action);
    await tester.pumpAndSettle();

    final text = tester.widget<TextField>(find.byType(TextField)).controller!;
    expect(text.text, query);
    expect(text.selection, TextSelection.collapsed(offset: query.length));
    expect(controller.value, query);
    expect(controller.needle, '/example/report.txt');
  });
}
