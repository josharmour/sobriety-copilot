import 'package:flutter/material.dart';

/// Lighthouse brand constants — deep navy, bright cyan, warm gold (Play Store
/// assets). These are *brand* values for canvases and illustrations (graph
/// painter, mood ramp); UI chrome should read the active [ColorScheme]
/// instead, which adapts each role for contrast in light and dark mode
/// (e.g. the cyan beam is too light for text on white, so light-mode
/// `primary` is a deeper cyan).
abstract class AppColors {
  static const Color brand = Color(0xFF0D1B2A); // deep navy
  static const Color accent = Color(0xFF48B8D0); // bright cyan (lighthouse beam)
  static const Color accentSoft = Color(0xFFE0F2F7); // tinted
  static const Color gold = Color(0xFFF4A261); // warm gold (accent callout)
  static const Color error = Color(0xFFE76F51);
  static const Color lightBg = Color(0xFFF4F7FA); // cool light gray-blue
  static const Color lightSurface = Color(0xFFFFFFFF);
  static const Color lightText = Color(0xFF1A1A2E);
  static const Color lightTextSecondary = Color(0xFF52606D);
  static const Color darkBg = Color(0xFF0A0F1A); // deeper navy
  static const Color darkSurface = Color(0xFF121B2A); // navy surface
  static const Color darkText = Color(0xFFE8EAED);
  static const Color darkTextSecondary = Color(0xFFA2ACB8);

  /// Highlight background for literature reader blocks. Always readable.
  static Color highlightBg(bool isDark) =>
      isDark ? const Color(0xFF1A3345) : const Color(0xFFD0E8F2);
}

abstract class AppSpacing {
  static const double xs = 4;
  static const double sm = 8;
  static const double md = 12;
  static const double lg = 16;
  static const double xl = 24;
  static const double xxl = 32;

  /// Tags and small badges.
  static const double radiusSm = 8;

  /// Cards, tiles, inputs, menus.
  static const double radius = 12;

  /// Composer field and large pills.
  static const double radiusLg = 20;

  /// Bottom sheets and dialogs.
  static const double radiusXl = 24;
}

abstract class AppTypography {
  static const String fontFamily = 'Roboto'; // default; serif used only in render view
  static const double body = 15;
  static const double small = 13;
  static const double title = 20;
}

/// One icon per feature, shared by the overflow menu, the composer shortcuts
/// and each sheet's header so a feature looks the same wherever it appears.
abstract class AppIcons {
  static const IconData today = Icons.wb_twilight_outlined;
  static const IconData meditation = Icons.self_improvement_outlined;
  static const IconData saved = Icons.bookmark_outline;
  static const IconData graph = Icons.hub_outlined;
  static const IconData meetings = Icons.groups_outlined;
  static const IconData crisis = Icons.health_and_safety_outlined;
  static const IconData altPaths = Icons.alt_route_outlined;
  static const IconData settings = Icons.settings_outlined;
  static const IconData about = Icons.info_outline;
  static const IconData conversations = Icons.forum_outlined;
  static const IconData memory = Icons.psychology_outlined;
  static const IconData tracker = Icons.emoji_events_outlined;
  static const IconData mood = Icons.emoji_emotions_outlined;
  static const IconData evening = Icons.nightlight_outlined;
  static const IconData privateMode = Icons.shield_outlined;
  static const IconData helpline = Icons.support_agent;
  static const IconData source = Icons.menu_book_outlined;
  static const IconData attach = Icons.add_photo_alternate_outlined;
  static const IconData help = Icons.help_outline;
}

/// Semantic colors Material's [ColorScheme] has no slot for. Gold callouts use
/// the scheme's `tertiary` roles.
extension AppSchemeColors on ColorScheme {
  bool get _dark => brightness == Brightness.dark;

  Color get success =>
      _dark ? const Color(0xFF6FCF97) : const Color(0xFF2E7D4F);
  Color get successContainer =>
      _dark ? const Color(0xFF16382A) : const Color(0xFFDDF3E6);
  Color get onSuccessContainer =>
      _dark ? const Color(0xFFC6F0D6) : const Color(0xFF0B3520);
}

/// Semantic tone for notices, tags and status rows.
enum AppTone { neutral, info, success, warning, danger }

/// Colors for an [AppTone]: [accent] for icons and subtle tints (notices),
/// [container] / [onContainer] for solid fills (tags, icon badges).
({Color accent, Color container, Color onContainer}) toneColors(
  ColorScheme cs,
  AppTone tone,
) {
  switch (tone) {
    case AppTone.neutral:
      return (
        accent: cs.onSurfaceVariant,
        container: cs.surfaceContainerHigh,
        onContainer: cs.onSurfaceVariant,
      );
    case AppTone.info:
      return (
        accent: cs.primary,
        container: cs.primaryContainer,
        onContainer: cs.onPrimaryContainer,
      );
    case AppTone.success:
      return (
        accent: cs.success,
        container: cs.successContainer,
        onContainer: cs.onSuccessContainer,
      );
    case AppTone.warning:
      return (
        accent: cs.tertiary,
        container: cs.tertiaryContainer,
        onContainer: cs.onTertiaryContainer,
      );
    case AppTone.danger:
      return (
        accent: cs.error,
        container: cs.errorContainer,
        onContainer: cs.onErrorContainer,
      );
  }
}

// Every role is spelled out (no `fromSeed`) so no generated purple/teal
// tints leak into containers, chips or dialogs. All foreground/background
// pairs meet WCAG AA (≥ 4.5:1).
const ColorScheme _lightScheme = ColorScheme(
  brightness: Brightness.light,
  primary: Color(0xFF17778D),
  onPrimary: Color(0xFFFFFFFF),
  primaryContainer: Color(0xFFD4EEF5),
  onPrimaryContainer: Color(0xFF073642),
  secondary: Color(0xFF3D5568),
  onSecondary: Color(0xFFFFFFFF),
  secondaryContainer: Color(0xFFDDEBF0),
  onSecondaryContainer: Color(0xFF0D2A35),
  tertiary: Color(0xFF96551A),
  onTertiary: Color(0xFFFFFFFF),
  tertiaryContainer: Color(0xFFFDE6D2),
  onTertiaryContainer: Color(0xFF4A2605),
  error: Color(0xFFBA3F22),
  onError: Color(0xFFFFFFFF),
  errorContainer: Color(0xFFFBE2DA),
  onErrorContainer: Color(0xFF5A1706),
  surface: AppColors.lightSurface,
  onSurface: AppColors.lightText,
  onSurfaceVariant: AppColors.lightTextSecondary,
  surfaceDim: Color(0xFFE3E8EE),
  surfaceBright: Color(0xFFFFFFFF),
  surfaceContainerLowest: Color(0xFFFFFFFF),
  surfaceContainerLow: Color(0xFFF7F9FB),
  surfaceContainer: Color(0xFFF1F4F7),
  surfaceContainerHigh: Color(0xFFEBEFF3),
  surfaceContainerHighest: Color(0xFFE3E8EE),
  outline: Color(0xFF7E8A96),
  outlineVariant: Color(0xFFD6DDE4),
  inverseSurface: Color(0xFF1C2533),
  onInverseSurface: Color(0xFFEEF1F4),
  inversePrimary: AppColors.accent,
  shadow: Color(0xFF000000),
  scrim: Color(0xFF000000),
  surfaceTint: Colors.transparent,
);

const ColorScheme _darkScheme = ColorScheme(
  brightness: Brightness.dark,
  primary: AppColors.accent,
  onPrimary: Color(0xFF032530),
  primaryContainer: Color(0xFF11404D),
  onPrimaryContainer: Color(0xFFC2EDF7),
  secondary: Color(0xFFA9BCCB),
  onSecondary: Color(0xFF102030),
  secondaryContainer: Color(0xFF1D3442),
  onSecondaryContainer: Color(0xFFCDE6EF),
  tertiary: AppColors.gold,
  onTertiary: Color(0xFF3D2106),
  tertiaryContainer: Color(0xFF53361A),
  onTertiaryContainer: Color(0xFFFFDCC0),
  error: Color(0xFFF28B6E),
  onError: Color(0xFF3E0E03),
  errorContainer: Color(0xFF5A2215),
  onErrorContainer: Color(0xFFFFD9CE),
  surface: AppColors.darkSurface,
  onSurface: AppColors.darkText,
  onSurfaceVariant: AppColors.darkTextSecondary,
  surfaceDim: AppColors.darkBg,
  surfaceBright: Color(0xFF2A374B),
  surfaceContainerLowest: AppColors.darkBg,
  surfaceContainerLow: Color(0xFF0F1724),
  surfaceContainer: Color(0xFF162131),
  surfaceContainerHigh: Color(0xFF1C283A),
  surfaceContainerHighest: Color(0xFF243245),
  outline: Color(0xFF6B7888),
  outlineVariant: Color(0xFF2B384A),
  inverseSurface: AppColors.darkText,
  onInverseSurface: Color(0xFF1A2332),
  inversePrimary: Color(0xFF17778D),
  shadow: Color(0xFF000000),
  scrim: Color(0xFF000000),
  surfaceTint: Colors.transparent,
);

/// Builds the Material 3 light theme using the lighthouse navy/cyan palette.
ThemeData buildLightTheme() =>
    _baseTheme(_lightScheme, scaffoldBackground: AppColors.lightBg);

/// Builds the Material 3 dark theme using the lighthouse navy/cyan palette.
ThemeData buildDarkTheme() =>
    _baseTheme(_darkScheme, scaffoldBackground: AppColors.darkBg);

/// Shared theme construction for both brightness modes. Component themes
/// only set shape, spacing and type — colors come from [cs] so every
/// variant (filled / tonal / outlined …) keeps its correct on-color.
ThemeData _baseTheme(ColorScheme cs, {required Color scaffoldBackground}) {
  final isDark = cs.brightness == Brightness.dark;
  // Surfaces that float above a sheet (dialogs, menus, cards in dark mode)
  // step one tone lighter so layering reads without heavy shadows.
  final raised = isDark ? cs.surfaceContainerHigh : cs.surface;
  final cardColor = isDark ? cs.surfaceContainer : cs.surface;

  final base = ThemeData(
    useMaterial3: true,
    colorScheme: cs,
    brightness: cs.brightness,
    fontFamily: AppTypography.fontFamily,
    scaffoldBackgroundColor: scaffoldBackground,
    canvasColor: cs.surface,
    visualDensity: VisualDensity.standard,
  );

  final t = base.textTheme.apply(
    bodyColor: cs.onSurface,
    displayColor: cs.onSurface,
  );
  final textTheme = t.copyWith(
    titleLarge: t.titleLarge?.copyWith(
      fontSize: AppTypography.title,
      fontWeight: FontWeight.w600,
      height: 1.25,
    ),
    titleMedium: t.titleMedium?.copyWith(
      fontSize: 16,
      fontWeight: FontWeight.w600,
    ),
    titleSmall: t.titleSmall?.copyWith(
      fontSize: 14,
      fontWeight: FontWeight.w600,
    ),
    bodyLarge: t.bodyLarge?.copyWith(fontSize: 16, height: 1.45),
    bodyMedium: t.bodyMedium?.copyWith(
      fontSize: AppTypography.body,
      height: 1.45,
    ),
    bodySmall: t.bodySmall?.copyWith(
      fontSize: AppTypography.small,
      height: 1.35,
      color: cs.onSurfaceVariant,
    ),
    labelLarge: t.labelLarge?.copyWith(
      fontSize: 14,
      fontWeight: FontWeight.w600,
    ),
    labelMedium: t.labelMedium?.copyWith(
      fontSize: 12,
      fontWeight: FontWeight.w600,
    ),
    labelSmall: t.labelSmall?.copyWith(
      fontSize: 11,
      fontWeight: FontWeight.w600,
      letterSpacing: 0.3,
    ),
  );

  const pill = StadiumBorder();
  final rounded = RoundedRectangleBorder(
    borderRadius: BorderRadius.circular(AppSpacing.radius),
  );
  const buttonPadding = EdgeInsets.symmetric(
    horizontal: AppSpacing.xl,
    vertical: AppSpacing.md,
  );
  const buttonMinSize = Size(64, 44);

  OutlineInputBorder field(Color color, [double width = 1]) =>
      OutlineInputBorder(
        borderRadius: BorderRadius.circular(AppSpacing.radius),
        borderSide: BorderSide(color: color, width: width),
      );

  return base.copyWith(
    textTheme: textTheme,
    appBarTheme: AppBarTheme(
      backgroundColor: scaffoldBackground,
      foregroundColor: cs.onSurface,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      scrolledUnderElevation: 0,
      centerTitle: false,
      iconTheme: IconThemeData(color: cs.onSurface),
      actionsIconTheme: IconThemeData(color: cs.onSurface),
      titleTextStyle: textTheme.titleLarge,
    ),
    cardTheme: CardThemeData(
      color: cardColor,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      margin: EdgeInsets.zero,
      clipBehavior: Clip.antiAlias,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppSpacing.radius),
        side: BorderSide(color: cs.outlineVariant),
      ),
    ),
    bottomSheetTheme: BottomSheetThemeData(
      backgroundColor: cs.surface,
      modalBackgroundColor: cs.surface,
      surfaceTintColor: Colors.transparent,
      elevation: 1,
      modalElevation: 1,
      showDragHandle: true,
      dragHandleColor: cs.onSurfaceVariant.withValues(alpha: 0.45),
      dragHandleSize: const Size(36, 4),
      clipBehavior: Clip.antiAlias,
      constraints: const BoxConstraints(maxWidth: 640),
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(
          top: Radius.circular(AppSpacing.radiusXl),
        ),
      ),
    ),
    dialogTheme: DialogThemeData(
      backgroundColor: raised,
      surfaceTintColor: Colors.transparent,
      elevation: 2,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppSpacing.radiusXl),
      ),
      titleTextStyle: textTheme.titleLarge,
      contentTextStyle: textTheme.bodyMedium?.copyWith(
        color: cs.onSurfaceVariant,
      ),
      actionsPadding: const EdgeInsets.fromLTRB(
        AppSpacing.xl,
        0,
        AppSpacing.xl,
        AppSpacing.lg,
      ),
    ),
    popupMenuTheme: PopupMenuThemeData(
      color: raised,
      surfaceTintColor: Colors.transparent,
      elevation: 3,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppSpacing.radius),
        side: BorderSide(color: cs.outlineVariant),
      ),
      textStyle: textTheme.bodyLarge,
      labelTextStyle: WidgetStatePropertyAll(textTheme.bodyLarge),
    ),
    menuTheme: MenuThemeData(
      style: MenuStyle(
        backgroundColor: WidgetStatePropertyAll(raised),
        surfaceTintColor: const WidgetStatePropertyAll(Colors.transparent),
        shape: WidgetStatePropertyAll(
          RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppSpacing.radius),
            side: BorderSide(color: cs.outlineVariant),
          ),
        ),
      ),
    ),
    // No `textColor`: it would also recolor subtitles, flattening the
    // title / subtitle hierarchy.
    listTileTheme: ListTileThemeData(
      iconColor: cs.onSurfaceVariant,
      selectedColor: cs.onPrimaryContainer,
      selectedTileColor: cs.primaryContainer,
      titleTextStyle: textTheme.bodyLarge?.copyWith(
        fontWeight: FontWeight.w500,
      ),
      subtitleTextStyle: textTheme.bodySmall,
      shape: rounded,
    ),
    expansionTileTheme: ExpansionTileThemeData(
      iconColor: cs.onSurfaceVariant,
      collapsedIconColor: cs.onSurfaceVariant,
      textColor: cs.onSurface,
      collapsedTextColor: cs.onSurface,
      shape: const Border(),
      collapsedShape: const Border(),
    ),
    chipTheme: ChipThemeData(
      backgroundColor: cs.surfaceContainerHigh,
      selectedColor: cs.primaryContainer,
      disabledColor: cs.surfaceContainer,
      checkmarkColor: cs.onPrimaryContainer,
      deleteIconColor: cs.onSurfaceVariant,
      labelStyle: textTheme.labelLarge?.copyWith(
        fontWeight: FontWeight.w500,
        color: cs.onSurface,
      ),
      secondaryLabelStyle: textTheme.labelLarge?.copyWith(
        color: cs.onPrimaryContainer,
      ),
      iconTheme: IconThemeData(color: cs.onSurfaceVariant, size: 16),
      side: BorderSide(color: cs.outlineVariant),
      shape: pill,
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.sm,
        vertical: AppSpacing.xs,
      ),
    ),
    segmentedButtonTheme: SegmentedButtonThemeData(
      style: ButtonStyle(
        textStyle: WidgetStatePropertyAll(textTheme.labelLarge),
        backgroundColor: WidgetStateProperty.resolveWith(
          (s) => s.contains(WidgetState.selected)
              ? cs.primaryContainer
              : Colors.transparent,
        ),
        foregroundColor: WidgetStateProperty.resolveWith(
          (s) => s.contains(WidgetState.selected)
              ? cs.onPrimaryContainer
              : cs.onSurfaceVariant,
        ),
        side: WidgetStatePropertyAll(BorderSide(color: cs.outlineVariant)),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: isDark ? cs.surfaceContainerLow : cs.surface,
      contentPadding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.lg,
        vertical: AppSpacing.md,
      ),
      hintStyle: textTheme.bodyMedium?.copyWith(color: cs.onSurfaceVariant),
      helperStyle: textTheme.bodySmall,
      border: field(cs.outlineVariant),
      enabledBorder: field(cs.outlineVariant),
      focusedBorder: field(cs.primary, 1.5),
      errorBorder: field(cs.error),
      focusedErrorBorder: field(cs.error, 1.5),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        shape: pill,
        padding: buttonPadding,
        minimumSize: buttonMinSize,
        textStyle: textTheme.labelLarge,
      ),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        elevation: 0,
        shape: pill,
        padding: buttonPadding,
        minimumSize: buttonMinSize,
        textStyle: textTheme.labelLarge,
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: cs.primary,
        side: BorderSide(color: cs.outline),
        shape: pill,
        padding: buttonPadding,
        minimumSize: buttonMinSize,
        textStyle: textTheme.labelLarge,
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: cs.primary,
        shape: pill,
        textStyle: textTheme.labelLarge,
      ),
    ),
    floatingActionButtonTheme: FloatingActionButtonThemeData(
      backgroundColor: cs.primaryContainer,
      foregroundColor: cs.onPrimaryContainer,
      elevation: 1,
    ),
    checkboxTheme: CheckboxThemeData(
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppSpacing.xs),
      ),
    ),
    dividerTheme: DividerThemeData(
      color: cs.outlineVariant,
      thickness: 1,
      space: AppSpacing.lg,
    ),
    snackBarTheme: SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      backgroundColor: isDark ? cs.surfaceBright : cs.inverseSurface,
      contentTextStyle: textTheme.bodyMedium?.copyWith(
        color: isDark ? cs.onSurface : cs.onInverseSurface,
      ),
      actionTextColor: AppColors.accent,
      elevation: 2,
      shape: rounded,
    ),
    tooltipTheme: TooltipThemeData(
      decoration: BoxDecoration(
        color: isDark ? cs.surfaceBright : cs.inverseSurface,
        borderRadius: BorderRadius.circular(AppSpacing.radiusSm),
      ),
      textStyle: textTheme.bodySmall?.copyWith(
        color: isDark ? cs.onSurface : cs.onInverseSurface,
      ),
    ),
    progressIndicatorTheme: ProgressIndicatorThemeData(
      color: cs.primary,
      linearTrackColor: cs.surfaceContainerHighest,
      circularTrackColor: Colors.transparent,
    ),
    textSelectionTheme: TextSelectionThemeData(
      cursorColor: cs.primary,
      selectionColor: cs.primary.withValues(alpha: 0.3),
      selectionHandleColor: cs.primary,
    ),
    datePickerTheme: DatePickerThemeData(
      backgroundColor: raised,
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppSpacing.radiusXl),
      ),
    ),
    timePickerTheme: TimePickerThemeData(
      backgroundColor: raised,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppSpacing.radiusXl),
      ),
    ),
  );
}
