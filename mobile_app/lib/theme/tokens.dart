import 'package:flutter/material.dart';

/// Calming recovery palette (teal/sage). Same names for light & dark usage.
abstract class AppColors {
  static const Color brand = Color(0xFF264653); // deep teal
  static const Color accent = Color(0xFF2A9D8F); // calming green-teal
  static const Color accentSoft = Color(0xFFE6F4F1);
  static const Color error = Color(0xFFE76F51);
  static const Color lightBg = Color(0xFFF7FAF9);
  static const Color lightSurface = Color(0xFFFFFFFF);
  static const Color lightText = Color(0xFF1A1A2E);
  static const Color lightTextSecondary = Color(0xFF52606D);
  static const Color darkBg = Color(0xFF0D1117);
  static const Color darkSurface = Color(0xFF161B22);
  static const Color darkText = Color(0xFFE8EAED);
  static const Color darkTextSecondary = Color(0xFF9DA7B3);
}

abstract class AppSpacing {
  static const double xs = 4;
  static const double sm = 8;
  static const double md = 12;
  static const double lg = 16;
  static const double xl = 24;
  static const double xxl = 32;
  static const double radius = 12;
  static const double radiusLg = 20;
}

abstract class AppTypography {
  static const String fontFamily = 'Roboto'; // default; serif used only in render view
  static const double body = 15;
  static const double small = 13;
  static const double title = 20;
}

/// Builds the Material 3 light theme using the calming teal/sage palette.
ThemeData buildLightTheme() {
  final colorScheme =
      ColorScheme.fromSeed(
        seedColor: AppColors.accent,
        brightness: Brightness.light,
      ).copyWith(
        primary: AppColors.accent,
        secondary: AppColors.brand,
        error: AppColors.error,
        surface: AppColors.lightSurface,
        onSurface: AppColors.lightText,
      );

  return _baseTheme(
    colorScheme: colorScheme,
    scaffoldBackground: AppColors.lightBg,
    surface: AppColors.lightSurface,
    textColor: AppColors.lightText,
    textSecondary: AppColors.lightTextSecondary,
  );
}

/// Builds the Material 3 dark theme using the calming teal/sage palette.
ThemeData buildDarkTheme() {
  final colorScheme =
      ColorScheme.fromSeed(
        seedColor: AppColors.accent,
        brightness: Brightness.dark,
      ).copyWith(
        primary: AppColors.accent,
        secondary: AppColors.accent,
        error: AppColors.error,
        surface: AppColors.darkSurface,
        onSurface: AppColors.darkText,
      );

  return _baseTheme(
    colorScheme: colorScheme,
    scaffoldBackground: AppColors.darkBg,
    surface: AppColors.darkSurface,
    textColor: AppColors.darkText,
    textSecondary: AppColors.darkTextSecondary,
  );
}

/// Shared theme construction for both brightness modes.
ThemeData _baseTheme({
  required ColorScheme colorScheme,
  required Color scaffoldBackground,
  required Color surface,
  required Color textColor,
  required Color textSecondary,
}) {
  final base = ThemeData(
    useMaterial3: true,
    colorScheme: colorScheme,
    brightness: colorScheme.brightness,
    fontFamily: AppTypography.fontFamily,
    scaffoldBackgroundColor: scaffoldBackground,
  );

  final textTheme = base.textTheme.apply(
    bodyColor: textColor,
    displayColor: textColor,
  );

  return base.copyWith(
    textTheme: textTheme.copyWith(
      titleLarge: textTheme.titleLarge?.copyWith(
        fontSize: AppTypography.title,
        fontWeight: FontWeight.w600,
        color: textColor,
      ),
      bodyMedium: textTheme.bodyMedium?.copyWith(
        fontSize: AppTypography.body,
        color: textColor,
        height: 1.45,
      ),
      bodySmall: textTheme.bodySmall?.copyWith(
        fontSize: AppTypography.small,
        color: textSecondary,
      ),
    ),
    appBarTheme: AppBarTheme(
      backgroundColor: scaffoldBackground,
      foregroundColor: textColor,
      elevation: 0,
      scrolledUnderElevation: 1,
      centerTitle: false,
      titleTextStyle: TextStyle(
        fontFamily: AppTypography.fontFamily,
        fontSize: AppTypography.title,
        fontWeight: FontWeight.w600,
        color: textColor,
      ),
    ),
    cardTheme: CardThemeData(
      color: surface,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppSpacing.radius),
        side: BorderSide(color: colorScheme.outlineVariant),
      ),
    ),
    chipTheme: base.chipTheme.copyWith(
      backgroundColor: colorScheme.surfaceContainerHighest,
      selectedColor: AppColors.accent,
      labelStyle: TextStyle(
        fontSize: AppTypography.small,
        color: textColor,
      ),
      secondaryLabelStyle: const TextStyle(
        fontSize: AppTypography.small,
        color: Colors.white,
      ),
      side: BorderSide(color: colorScheme.outlineVariant),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppSpacing.radiusLg),
      ),
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.sm,
        vertical: AppSpacing.xs,
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: surface,
      contentPadding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.lg,
        vertical: AppSpacing.md,
      ),
      hintStyle: TextStyle(color: textSecondary, fontSize: AppTypography.body),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(AppSpacing.radiusLg),
        borderSide: BorderSide(color: colorScheme.outlineVariant),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(AppSpacing.radiusLg),
        borderSide: BorderSide(color: colorScheme.outlineVariant),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(AppSpacing.radiusLg),
        borderSide: const BorderSide(color: AppColors.accent, width: 1.5),
      ),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        backgroundColor: AppColors.accent,
        foregroundColor: Colors.white,
        elevation: 0,
        padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.xl,
          vertical: AppSpacing.md,
        ),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppSpacing.radius),
        ),
        textStyle: const TextStyle(
          fontSize: AppTypography.body,
          fontWeight: FontWeight.w600,
        ),
      ),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: AppColors.accent,
        foregroundColor: Colors.white,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppSpacing.radius),
        ),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(foregroundColor: AppColors.accent),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: AppColors.accent,
        side: const BorderSide(color: AppColors.accent),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppSpacing.radius),
        ),
      ),
    ),
    iconButtonTheme: IconButtonThemeData(
      style: IconButton.styleFrom(foregroundColor: textColor),
    ),
    floatingActionButtonTheme: const FloatingActionButtonThemeData(
      backgroundColor: AppColors.accent,
      foregroundColor: Colors.white,
    ),
    switchTheme: SwitchThemeData(
      thumbColor: WidgetStateProperty.resolveWith(
        (states) => states.contains(WidgetState.selected)
            ? AppColors.accent
            : null,
      ),
      trackColor: WidgetStateProperty.resolveWith(
        (states) => states.contains(WidgetState.selected)
            ? AppColors.accent.withValues(alpha: 0.5)
            : null,
      ),
    ),
    checkboxTheme: CheckboxThemeData(
      fillColor: WidgetStateProperty.resolveWith(
        (states) => states.contains(WidgetState.selected)
            ? AppColors.accent
            : null,
      ),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppSpacing.xs),
      ),
    ),
    radioTheme: RadioThemeData(
      fillColor: WidgetStateProperty.resolveWith(
        (states) => states.contains(WidgetState.selected)
            ? AppColors.accent
            : null,
      ),
    ),
    dividerTheme: DividerThemeData(
      color: colorScheme.outlineVariant,
      thickness: 1,
      space: AppSpacing.lg,
    ),
    bottomSheetTheme: BottomSheetThemeData(
      backgroundColor: surface,
      surfaceTintColor: Colors.transparent,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(
          top: Radius.circular(AppSpacing.radiusLg),
        ),
      ),
    ),
    snackBarTheme: SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      backgroundColor: AppColors.brand,
      contentTextStyle: const TextStyle(color: Colors.white),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppSpacing.radius),
      ),
    ),
    progressIndicatorTheme: const ProgressIndicatorThemeData(
      color: AppColors.accent,
    ),
    listTileTheme: ListTileThemeData(
      iconColor: textSecondary,
      textColor: textColor,
    ),
  );
}
