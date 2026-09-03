require 'xcodeproj'

project_path = 'Runner.xcodeproj'
project = Xcodeproj::Project.open(project_path)

runner_target = project.targets.find { |t| t.name == 'Runner' }
raise "Runner target not found" unless runner_target

# Add Framework Info.plist fixer script phase if not present
plist_script_phase = runner_target.shell_script_build_phases.find { |p| p.name == 'Fix Native Framework Plists' }
if plist_script_phase.nil?
  plist_script_phase = runner_target.new_shell_script_build_phase('Fix Native Framework Plists')
  plist_script_phase.shell_script = <<~'SH'
    for f in "${TARGET_BUILD_DIR}/${FRAMEWORKS_FOLDER_PATH}"/*.framework "${BUILT_PRODUCTS_DIR}/${FRAMEWORKS_FOLDER_PATH}"/*.framework; do
      if [ -d "$f" ] && [ ! -f "$f/Info.plist" ]; then
        NAME=$(basename "$f" .framework)
        cat <<EOF > "$f/Info.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleDevelopmentRegion</key>
	<string>en</string>
	<key>CFBundleExecutable</key>
	<string>$NAME</string>
	<key>CFBundleIdentifier</key>
	<string>com.sobrietycopilot.app.$NAME</string>
	<key>CFBundleInfoDictionaryVersion</key>
	<string>6.0</string>
	<key>CFBundleName</key>
	<string>$NAME</string>
	<key>CFBundlePackageType</key>
	<string>FMWK</string>
	<key>CFBundleShortVersionString</key>
	<string>1.0</string>
	<key>CFBundleVersion</key>
	<string>1</string>
</dict>
</plist>
EOF
      fi
    done
  SH
  puts "Added Fix Native Framework Plists build phase"
end

project.save
puts "Saved Xcode project"
