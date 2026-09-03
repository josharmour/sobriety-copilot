require 'xcodeproj'

project_path = 'Runner.xcodeproj'
project = Xcodeproj::Project.open(project_path)

runner_target = project.targets.find { |t| t.name == 'Runner' }
raise "Runner target not found" unless runner_target

thin_binary = runner_target.build_phases.find { |p| p.display_name == 'Thin Binary' }
raise "Thin Binary phase not found" unless thin_binary

thin_binary.shell_script = <<~'SH'
  /bin/sh "$FLUTTER_ROOT/packages/flutter_tools/bin/xcode_backend.sh" embed_and_thin

  for dir in "${TARGET_BUILD_DIR}/${FRAMEWORKS_FOLDER_PATH}" "${BUILT_PRODUCTS_DIR}/${FRAMEWORKS_FOLDER_PATH}"; do
    if [ -d "$dir" ]; then
      for f in "$dir"/*.framework; do
        if [ -d "$f" ]; then
          NAME=$(basename "$f" .framework)
          if [ ! -f "$f/$NAME" ]; then
            echo "Pruning non-binary framework stub: $f"
            rm -rf "$f"
          fi
        fi
      done
    fi
  done
SH

project.save
puts "Successfully updated Thin Binary script to prune empty framework stubs"
